"""
Real-price spread construction and pricing from chain snapshots.

Instead of Black-Scholes theoretical prices, this module finds actual
contracts from stored chain data and prices entries/exits using real
bid/ask quotes. Sells at bid, buys at ask (worst-case fills).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SpreadLeg:
    """A single leg of a spread, priced from real market data."""
    strike: float
    expiry: str
    option_type: str  # "call" or "put"
    side: str  # "buy" or "sell"
    bid: float
    ask: float
    mid: float
    iv: float

    @property
    def fill_price(self) -> float:
        """Worst-case fill: sell at bid, buy at ask."""
        return self.bid if self.side == "sell" else self.ask

    @property
    def close_price(self) -> float:
        """Worst-case close: buy back at ask (if sold), sell at bid (if bought)."""
        return self.ask if self.side == "sell" else self.bid


@dataclass
class SpreadPosition:
    """A complete spread with real-priced legs."""
    strategy: str
    legs: List[SpreadLeg]
    entry_net: float  # net credit (positive) or debit (negative)
    is_credit: bool
    expiry: str
    max_risk: float

    @property
    def dte(self) -> int:
        try:
            exp = datetime.strptime(self.expiry, "%Y-%m-%d")
            return max((exp - datetime.now()).days, 0)
        except (ValueError, TypeError):
            return 7


def find_contracts_near(contracts, strike_target: float, option_type: str,
                        expiry: str, exclude_strikes: Optional[List[float]] = None) -> Optional[Dict]:
    """Find the contract closest to target strike with given type and expiry."""
    excl = set(exclude_strikes or [])
    matches = [
        c for c in contracts
        if c.option_type == option_type
        and c.expiry == expiry
        and c.bid is not None and c.bid > 0
        and c.ask is not None and c.ask > 0
        and c.strike not in excl
    ]
    if not matches:
        return None
    return min(matches, key=lambda c: abs(c.strike - strike_target))


def _pick_expiry(contracts, dte_min: int, dte_max: int,
                 ref_date: str) -> Optional[str]:
    """Pick the best expiry within the DTE range."""
    ref = datetime.strptime(ref_date, "%Y-%m-%d")
    expiries = set()
    for c in contracts:
        if c.expiry and c.bid is not None and c.bid > 0:
            expiries.add(c.expiry)

    valid = []
    for exp_str in sorted(expiries):
        try:
            exp_dt = datetime.strptime(exp_str, "%Y-%m-%d")
            dte = (exp_dt - ref).days
            if dte_min <= dte <= dte_max:
                valid.append((exp_str, dte))
        except (ValueError, TypeError):
            continue

    if not valid:
        return None
    # Prefer middle of range
    target_dte = (dte_min + dte_max) / 2
    return min(valid, key=lambda x: abs(x[1] - target_dte))[0]


def _get_strike_increment(spot: float) -> float:
    if spot >= 200:
        return 5.0
    elif spot >= 50:
        return 2.5
    else:
        return 1.0


def build_spread(contracts, spot: float, strategy: str, date_str: str,
                 dte_min: int = 3, dte_max: int = 14) -> Optional[SpreadPosition]:
    """Build a spread position from real chain contracts.

    Finds actual contracts, prices at bid/ask, returns None if no valid
    spread can be constructed.
    """
    expiry = _pick_expiry(contracts, dte_min, dte_max, date_str)
    if not expiry:
        return None

    inc = _get_strike_increment(spot)
    atm = round(spot / inc) * inc

    if strategy == "short_put_spread":
        short_k = atm - inc
        long_k = atm - 2 * inc
        short_c = find_contracts_near(contracts, short_k, "put", expiry)
        if not short_c:
            return None
        long_c = find_contracts_near(contracts, long_k, "put", expiry,
                                     exclude_strikes=[short_c.strike])
        if not long_c:
            return None
        if short_c.strike <= long_c.strike:
            return None

        legs = [
            SpreadLeg(short_c.strike, expiry, "put", "sell",
                      short_c.bid, short_c.ask, short_c.mid, short_c.implied_volatility or 0),
            SpreadLeg(long_c.strike, expiry, "put", "buy",
                      long_c.bid, long_c.ask, long_c.mid, long_c.implied_volatility or 0),
        ]
        entry_net = legs[0].fill_price - legs[1].fill_price
        width = short_c.strike - long_c.strike
        max_risk = width - entry_net
        return SpreadPosition(strategy, legs, entry_net, True, expiry, max_risk)

    elif strategy == "short_call_spread":
        short_k = atm + inc
        long_k = atm + 2 * inc
        short_c = find_contracts_near(contracts, short_k, "call", expiry)
        if not short_c:
            return None
        long_c = find_contracts_near(contracts, long_k, "call", expiry,
                                     exclude_strikes=[short_c.strike])
        if not long_c:
            return None
        if long_c.strike <= short_c.strike:
            return None

        legs = [
            SpreadLeg(short_c.strike, expiry, "call", "sell",
                      short_c.bid, short_c.ask, short_c.mid, short_c.implied_volatility or 0),
            SpreadLeg(long_c.strike, expiry, "call", "buy",
                      long_c.bid, long_c.ask, long_c.mid, long_c.implied_volatility or 0),
        ]
        entry_net = legs[0].fill_price - legs[1].fill_price
        width = long_c.strike - short_c.strike
        max_risk = width - entry_net
        return SpreadPosition(strategy, legs, entry_net, True, expiry, max_risk)

    elif strategy == "iron_condor":
        sp = find_contracts_near(contracts, atm - inc, "put", expiry)
        if not sp:
            return None
        bp = find_contracts_near(contracts, atm - 2 * inc, "put", expiry,
                                 exclude_strikes=[sp.strike])
        sc = find_contracts_near(contracts, atm + inc, "call", expiry)
        if not sc:
            return None
        bc = find_contracts_near(contracts, atm + 2 * inc, "call", expiry,
                                 exclude_strikes=[sc.strike])

        if not all([sp, bp, sc, bc]):
            return None
        if sp.strike <= bp.strike or bc.strike <= sc.strike:
            return None

        legs = [
            SpreadLeg(sp.strike, expiry, "put", "sell", sp.bid, sp.ask, sp.mid, sp.implied_volatility or 0),
            SpreadLeg(bp.strike, expiry, "put", "buy", bp.bid, bp.ask, bp.mid, bp.implied_volatility or 0),
            SpreadLeg(sc.strike, expiry, "call", "sell", sc.bid, sc.ask, sc.mid, sc.implied_volatility or 0),
            SpreadLeg(bc.strike, expiry, "call", "buy", bc.bid, bc.ask, bc.mid, bc.implied_volatility or 0),
        ]
        put_credit = legs[0].fill_price - legs[1].fill_price
        call_credit = legs[2].fill_price - legs[3].fill_price
        entry_net = put_credit + call_credit
        width = max(sp.strike - bp.strike, bc.strike - sc.strike)
        max_risk = width - entry_net
        return SpreadPosition(strategy, legs, entry_net, True, expiry, max_risk)

    elif strategy == "long_call_spread":
        long_c = find_contracts_near(contracts, atm, "call", expiry)
        if not long_c:
            return None
        short_c = find_contracts_near(contracts, atm + inc, "call", expiry,
                                      exclude_strikes=[long_c.strike])
        if not short_c:
            return None
        if short_c.strike <= long_c.strike:
            return None

        legs = [
            SpreadLeg(long_c.strike, expiry, "call", "buy",
                      long_c.bid, long_c.ask, long_c.mid, long_c.implied_volatility or 0),
            SpreadLeg(short_c.strike, expiry, "call", "sell",
                      short_c.bid, short_c.ask, short_c.mid, short_c.implied_volatility or 0),
        ]
        entry_net = legs[1].fill_price - legs[0].fill_price  # negative = debit
        max_risk = abs(entry_net)
        return SpreadPosition(strategy, legs, entry_net, False, expiry, max_risk)

    elif strategy == "long_put_spread":
        long_c = find_contracts_near(contracts, atm, "put", expiry)
        if not long_c:
            return None
        short_c = find_contracts_near(contracts, atm - inc, "put", expiry,
                                      exclude_strikes=[long_c.strike])
        if not short_c:
            return None
        if long_c.strike <= short_c.strike:
            return None

        legs = [
            SpreadLeg(long_c.strike, expiry, "put", "buy",
                      long_c.bid, long_c.ask, long_c.mid, long_c.implied_volatility or 0),
            SpreadLeg(short_c.strike, expiry, "put", "sell",
                      short_c.bid, short_c.ask, short_c.mid, short_c.implied_volatility or 0),
        ]
        entry_net = legs[1].fill_price - legs[0].fill_price  # negative = debit
        max_risk = abs(entry_net)
        return SpreadPosition(strategy, legs, entry_net, False, expiry, max_risk)

    elif strategy == "butterfly":
        lo = find_contracts_near(contracts, atm - inc, "call", expiry)
        if not lo:
            return None
        mid_c = find_contracts_near(contracts, atm, "call", expiry,
                                    exclude_strikes=[lo.strike])
        if not mid_c:
            return None
        hi = find_contracts_near(contracts, atm + inc, "call", expiry,
                                 exclude_strikes=[lo.strike, mid_c.strike])
        if not hi:
            return None

        legs = [
            SpreadLeg(lo.strike, expiry, "call", "buy", lo.bid, lo.ask, lo.mid, lo.implied_volatility or 0),
            SpreadLeg(mid_c.strike, expiry, "call", "sell", mid_c.bid, mid_c.ask, mid_c.mid, mid_c.implied_volatility or 0),
            SpreadLeg(mid_c.strike, expiry, "call", "sell", mid_c.bid, mid_c.ask, mid_c.mid, mid_c.implied_volatility or 0),
            SpreadLeg(hi.strike, expiry, "call", "buy", hi.bid, hi.ask, hi.mid, hi.implied_volatility or 0),
        ]
        debit = legs[0].fill_price + legs[3].fill_price - 2 * legs[1].fill_price
        entry_net = -debit
        max_risk = abs(debit)
        return SpreadPosition(strategy, legs, entry_net, False, expiry, max_risk)

    return None


def reprice_spread(position: SpreadPosition, contracts) -> Optional[float]:
    """Reprice an open spread using real bid/ask from a new snapshot.

    Returns the net value to CLOSE the position (cost to close for credits,
    proceeds for debits). Returns None if contracts can't be found.
    """
    close_value = 0.0
    for leg in position.legs:
        match = find_contracts_near(contracts, leg.strike, leg.option_type, leg.expiry)
        if not match:
            return None
        if match.bid is None or match.ask is None:
            return None
        if leg.side == "sell":
            close_value -= match.ask  # buy back at ask
        else:
            close_value += match.bid  # sell at bid

    return close_value


def compute_pnl(position: SpreadPosition, close_value: float) -> float:
    """Compute P&L from entry net and close value.

    For credit spreads: P&L = entry_net + close_value (close_value is negative)
    For debit spreads: P&L = close_value + entry_net (entry_net is negative)
    """
    return position.entry_net + close_value
