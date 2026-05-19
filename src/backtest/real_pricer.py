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

    elif strategy == "calendar_spread":
        back_expiry = _pick_expiry(contracts, dte_min, dte_max, date_str)
        front_expiry = _pick_expiry(contracts, max(dte_min // 3, 3), dte_min, date_str)
        if not back_expiry or not front_expiry or front_expiry >= back_expiry:
            return None

        sell_c = find_contracts_near(contracts, atm, "call", front_expiry)
        buy_c = find_contracts_near(contracts, atm, "call", back_expiry)
        if not sell_c or not buy_c:
            return None

        legs = [
            SpreadLeg(sell_c.strike, front_expiry, "call", "sell",
                      sell_c.bid, sell_c.ask, sell_c.mid, sell_c.implied_volatility or 0),
            SpreadLeg(buy_c.strike, back_expiry, "call", "buy",
                      buy_c.bid, buy_c.ask, buy_c.mid, buy_c.implied_volatility or 0),
        ]
        entry_net = legs[0].fill_price - legs[1].fill_price  # typically negative (debit)
        max_risk = abs(entry_net) if entry_net < 0 else legs[1].fill_price
        return SpreadPosition(strategy, legs, entry_net,
                              entry_net > 0, back_expiry, max_risk)

    elif strategy == "diagonal_spread":
        back_expiry = _pick_expiry(contracts, dte_min, dte_max, date_str)
        front_expiry = _pick_expiry(contracts, max(dte_min // 3, 3), dte_min, date_str)
        if not back_expiry or not front_expiry or front_expiry >= back_expiry:
            return None

        sell_c = find_contracts_near(contracts, atm + inc, "call", front_expiry)
        buy_c = find_contracts_near(contracts, atm, "call", back_expiry)
        if not sell_c or not buy_c:
            return None

        legs = [
            SpreadLeg(sell_c.strike, front_expiry, "call", "sell",
                      sell_c.bid, sell_c.ask, sell_c.mid, sell_c.implied_volatility or 0),
            SpreadLeg(buy_c.strike, back_expiry, "call", "buy",
                      buy_c.bid, buy_c.ask, buy_c.mid, buy_c.implied_volatility or 0),
        ]
        entry_net = legs[0].fill_price - legs[1].fill_price
        max_risk = abs(entry_net) if entry_net < 0 else legs[1].fill_price
        return SpreadPosition(strategy, legs, entry_net,
                              entry_net > 0, back_expiry, max_risk)

    elif strategy == "iron_butterfly":
        sc = find_contracts_near(contracts, atm, "call", expiry)
        sp = find_contracts_near(contracts, atm, "put", expiry)
        if not sc or not sp:
            return None
        bc = find_contracts_near(contracts, atm + 2 * inc, "call", expiry,
                                 exclude_strikes=[sc.strike])
        bp = find_contracts_near(contracts, atm - 2 * inc, "put", expiry,
                                 exclude_strikes=[sp.strike])
        if not bc or not bp:
            return None

        legs = [
            SpreadLeg(sc.strike, expiry, "call", "sell", sc.bid, sc.ask, sc.mid, sc.implied_volatility or 0),
            SpreadLeg(sp.strike, expiry, "put", "sell", sp.bid, sp.ask, sp.mid, sp.implied_volatility or 0),
            SpreadLeg(bc.strike, expiry, "call", "buy", bc.bid, bc.ask, bc.mid, bc.implied_volatility or 0),
            SpreadLeg(bp.strike, expiry, "put", "buy", bp.bid, bp.ask, bp.mid, bp.implied_volatility or 0),
        ]
        credit = (legs[0].fill_price + legs[1].fill_price
                  - legs[2].fill_price - legs[3].fill_price)
        width = max(bc.strike - sc.strike, sp.strike - bp.strike)
        max_risk = width - credit
        return SpreadPosition(strategy, legs, credit, True, expiry, max_risk)

    elif strategy == "long_straddle":
        buy_c = find_contracts_near(contracts, atm, "call", expiry)
        buy_p = find_contracts_near(contracts, atm, "put", expiry)
        if not buy_c or not buy_p:
            return None

        legs = [
            SpreadLeg(buy_c.strike, expiry, "call", "buy",
                      buy_c.bid, buy_c.ask, buy_c.mid, buy_c.implied_volatility or 0),
            SpreadLeg(buy_p.strike, expiry, "put", "buy",
                      buy_p.bid, buy_p.ask, buy_p.mid, buy_p.implied_volatility or 0),
        ]
        debit = legs[0].fill_price + legs[1].fill_price
        return SpreadPosition(strategy, legs, -debit, False, expiry, debit)

    return None


def _leg_expired_value(leg: SpreadLeg, spot: float) -> float:
    """Intrinsic value of an expired leg. OTM = 0."""
    if leg.option_type == "call":
        return max(spot - leg.strike, 0)
    else:
        return max(leg.strike - spot, 0)


def reprice_spread(position: SpreadPosition, contracts,
                   current_date: str = "", spot: float = 0.0) -> Optional[float]:
    """Reprice an open spread using real bid/ask from a new snapshot.

    Handles expired legs: if a leg's expiry has passed, values it at
    intrinsic (OTM = 0). This is critical for calendar/diagonal spreads
    where the front month expires before the back month.

    Returns the net value to CLOSE the position (cost to close for credits,
    proceeds for debits). Returns None only if a live leg can't be found.
    """
    close_value = 0.0

    for leg in position.legs:
        leg_expired = False
        if current_date and leg.expiry:
            try:
                exp_dt = datetime.strptime(leg.expiry, "%Y-%m-%d")
                cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
                leg_expired = cur_dt > exp_dt
            except (ValueError, TypeError):
                pass

        if leg_expired:
            intrinsic = _leg_expired_value(leg, spot)
            if leg.side == "sell":
                close_value -= intrinsic
            else:
                close_value += intrinsic
            continue

        match = find_contracts_near(contracts, leg.strike, leg.option_type, leg.expiry)
        if not match:
            match = _find_closest_expiry_match(contracts, leg, current_date)
        if not match:
            return None
        if match.bid is None or match.ask is None:
            return None
        if leg.side == "sell":
            close_value -= match.ask  # buy back at ask
        else:
            close_value += match.bid  # sell at bid

    return close_value


def _find_closest_expiry_match(contracts, leg: SpreadLeg,
                                current_date: str = ""):
    """Find a contract at the same strike/type but nearest available expiry.

    Used when the exact expiry isn't in the current snapshot but hasn't
    technically expired yet (e.g., snapshot is from a few days before expiry
    and the contract is no longer listed).
    """
    matches = [
        c for c in contracts
        if c.option_type == leg.option_type
        and abs(c.strike - leg.strike) < 0.01
        and c.bid is not None and c.bid > 0
        and c.ask is not None and c.ask > 0
    ]
    if not matches:
        return None

    if current_date:
        try:
            cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
            future = [
                m for m in matches
                if datetime.strptime(m.expiry, "%Y-%m-%d") >= cur_dt
            ]
            if future:
                return min(future, key=lambda m: abs(
                    (datetime.strptime(m.expiry, "%Y-%m-%d")
                     - datetime.strptime(leg.expiry, "%Y-%m-%d")).days
                ))
        except (ValueError, TypeError):
            pass

    return min(matches, key=lambda m: abs(
        hash(m.expiry) - hash(leg.expiry)
    )) if matches else None


def compute_pnl(position: SpreadPosition, close_value: float) -> float:
    """Compute P&L from entry net and close value.

    For credit spreads: P&L = entry_net + close_value (close_value is negative)
    For debit spreads: P&L = close_value + entry_net (entry_net is negative)
    """
    return position.entry_net + close_value
