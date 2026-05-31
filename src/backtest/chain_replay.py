"""
Chain-replay backtester using real option chain snapshots.

Instead of BS-simulated pricing, this backtester:
1. Walks through historical chain snapshots from SQLite
2. Selects strikes based on real bid/ask/mid from the snapshot
3. Finds the nearest future snapshot for exit pricing
4. Computes P&L from actual market quotes

Same interface as local_backtest.run_local_backtest — returns BacktestResult.

DATA ISSUES (documented for transparency):
- Snapshot frequency is ~every-other-day (not daily), so entry/exit dates
  snap to nearest available snapshot. Trades may enter/exit 1 day off.
- Older data (2020-2024) has ~60 contracts per snapshot vs 2000+ in 2025+.
  Fewer strikes means coarser delta targeting.
- OI data only exists for May 2026 snapshots. Dealer filter is a no-op
  on historical data before that.
- Spread percentage is sometimes wide on far-OTM strikes. Fills are priced
  at real bid/ask by default (buys pay the ask, sells receive the bid); set
  request.fill_mode="mid" for legacy optimistic mid pricing. Spread width is
  logged per trade as avg_spread_pct. See docs/pricing_validation_report.md
  for why mid pricing overstates edge.
- No intraday data — all prices are EOD snapshots. Intraday profit targets
  or stop losses can only be checked at next snapshot.
- Some symbols (QQQ, IWM) only have data from May 2025 onward.
"""

import logging
import os
import sqlite3
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import RISK_FREE_RATE
from .models import BacktestRequest, BacktestResult, BacktestTrade
from .analyzer import (
    analyze_results, compute_regime_breakdown,
    compute_dte_breakdown, compute_pnl_distribution,
)
from .cache import get_cached, store_cached

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("CHAIN_SNAPSHOTS_DB", "data/chain_snapshots.db")


def run_chain_replay(request: BacktestRequest) -> BacktestResult:
    """Run backtest by replaying real chain snapshots.

    Same interface as run_local_backtest — accepts BacktestRequest,
    returns BacktestResult. Uses real bid/ask/mid prices from
    chain_snapshots.db instead of BS-computed prices.
    """
    cache_key_suffix = "_chain"
    cached = get_cached(request, key_suffix=cache_key_suffix)
    if cached:
        return cached

    logger.info("Running chain-replay backtest: %s on %s (%s to %s)",
                request.strategy, request.symbol,
                request.start_date, request.end_date)

    db_path = os.getenv("CHAIN_SNAPSHOTS_DB", _DB_PATH)
    if not os.path.exists(db_path):
        logger.error("Chain snapshots DB not found: %s", db_path)
        return BacktestResult(
            request=request,
            stats=analyze_results([]),
            source="chain_replay",
            data_issues=["Chain snapshots DB not found"],
        )

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row

    snapshots = _load_snapshots(conn, request.symbol, request.start_date, request.end_date)
    if len(snapshots) < 10:
        conn.close()
        return BacktestResult(
            request=request,
            stats=analyze_results([]),
            source="chain_replay",
            data_issues=[f"Only {len(snapshots)} snapshots found — need at least 10"],
        )

    rolling_vol = _compute_rolling_vol_from_snapshots(snapshots)

    trades, issues, equity = _simulate_chain_trades(
        conn=conn,
        snapshots=snapshots,
        rolling_vol=rolling_vol,
        request=request,
    )
    conn.close()

    # Annualization for the mark-to-market Sharpe: number of snapshot/return
    # periods per calendar year over the actual span.
    span_days = (date.fromisoformat(snapshots[-1]["date"])
                 - date.fromisoformat(snapshots[0]["date"])).days
    years = max(span_days / 365.25, 1e-9)
    periods_per_year = len(snapshots) / years

    # Risk metrics use the time-indexed mark-to-market curve (F-006); per-trade
    # descriptive stats (win rate, PF, avg win/loss) come from the trade list.
    stats = analyze_results(trades, equity_curve=equity, periods_per_year=periods_per_year)

    result = BacktestResult(
        request=request,
        stats=stats,
        trades=trades,
        equity_curve=equity,
        regime_breakdown=compute_regime_breakdown(trades),
        dte_breakdown=compute_dte_breakdown(trades),
        pnl_distribution=compute_pnl_distribution(trades),
        source="chain_replay",
        data_issues=issues,
    )

    store_cached(request, result, key_suffix=cache_key_suffix)
    return result


def _load_snapshots(conn, symbol: str, start: date, end: date) -> List[dict]:
    """Load snapshot metadata (id, date, spot) for the date range."""
    rows = conn.execute("""
        SELECT id, snapshot_date, spot
        FROM chain_snapshots
        WHERE ticker = ? AND snapshot_date BETWEEN ? AND ?
        ORDER BY snapshot_date
    """, (symbol, str(start), str(end))).fetchall()

    return [{"id": r["id"], "date": r["snapshot_date"], "spot": r["spot"]} for r in rows]


def _load_contracts(conn, snapshot_id: int, dte_min: int, dte_max: int,
                    snapshot_date: str) -> List[dict]:
    """Load contracts from a snapshot within the DTE range, with valid bids."""
    rows = conn.execute("""
        SELECT strike, expiry, option_type, bid, ask, mid,
               implied_volatility, volume, open_interest, spread_pct
        FROM chain_contracts
        WHERE snapshot_id = ?
          AND bid > 0
          AND julianday(expiry) - julianday(?) BETWEEN ? AND ?
        ORDER BY expiry, strike
    """, (snapshot_id, snapshot_date, dte_min, dte_max)).fetchall()

    return [dict(r) for r in rows]


def _find_exit_contracts(conn, symbol: str, target_date: str,
                         expiry: str, strikes: List[float],
                         option_types: List[str]) -> Optional[Dict]:
    """Find contracts at exit time for the given strikes/types.

    Looks for the nearest snapshot on or after target_date (up to +3 days).
    If none found, tries the nearest before target_date.
    Returns {(strike, option_type): {bid, ask, mid, ...}} or None.
    """
    for offset in range(4):
        d = _date_add(target_date, offset)
        snap = conn.execute("""
            SELECT id, snapshot_date, spot
            FROM chain_snapshots
            WHERE ticker = ? AND snapshot_date = ?
        """, (symbol, d)).fetchone()
        if snap:
            break
    else:
        for offset in range(1, 4):
            d = _date_add(target_date, -offset)
            snap = conn.execute("""
                SELECT id, snapshot_date, spot
                FROM chain_snapshots
                WHERE ticker = ? AND snapshot_date = ?
            """, (symbol, d)).fetchone()
            if snap:
                break
        else:
            return None

    result = {}
    for strike, otype in zip(strikes, option_types):
        row = conn.execute("""
            SELECT strike, option_type, bid, ask, mid, implied_volatility
            FROM chain_contracts
            WHERE snapshot_id = ? AND strike = ? AND option_type = ?
              AND expiry = ?
        """, (snap["id"], strike, otype, expiry)).fetchone()
        if row:
            result[(strike, otype)] = dict(row)

    if result:
        result["_snap_date"] = snap["snapshot_date"]
        result["_snap_spot"] = snap["spot"]
    return result


def _date_add(date_str: str, days: int) -> str:
    d = date.fromisoformat(date_str) + timedelta(days=days)
    return str(d)


def _compute_rolling_vol_from_snapshots(snapshots: List[dict], window: int = 20) -> np.ndarray:
    """Compute rolling realized vol from snapshot spot prices."""
    spots = np.array([s["spot"] for s in snapshots])
    if len(spots) < 2:
        return np.full(len(spots), 0.20)
    returns = np.diff(np.log(spots))
    vol = np.full(len(spots), 0.20)
    for i in range(window, len(returns) + 1):
        vol[i] = float(np.std(returns[i - window:i]) * np.sqrt(252))
    return vol


def _classify_regime(iv: float, rolling_vol: np.ndarray, idx: int) -> str:
    """Same percentile-based regime classifier as local_backtest."""
    if iv > 0.30:
        return "SPIKE"
    if idx >= 252:
        window = rolling_vol[max(0, idx - 252):idx + 1]
        valid = window[window > 0]
        if len(valid) > 20:
            rank = float(np.sum(valid < iv) / len(valid) * 100)
            if rank > 50:
                return "HIGH_IV"
            elif rank > 30:
                return "MODERATE_IV"
            else:
                return "LOW_IV"
    if iv > 0.20:
        return "HIGH_IV"
    elif iv > 0.15:
        return "MODERATE_IV"
    else:
        return "LOW_IV"


def _select_strikes(contracts: List[dict], spot: float, strategy: str,
                    target_delta: float) -> Optional[dict]:
    """Select strikes for the strategy from real chain contracts.

    Uses IV-implied delta approximation: for OTM options, lower IV and
    further-from-spot = lower delta. We pick the strike closest to the
    target delta on each side.

    Returns dict with strategy legs or None if insufficient strikes.
    """
    puts = sorted([c for c in contracts if c["option_type"] == "put"], key=lambda c: c["strike"])
    calls = sorted([c for c in contracts if c["option_type"] == "call"], key=lambda c: c["strike"])

    if not puts or not calls:
        return None

    expiry = contracts[0]["expiry"]
    dte = max((date.fromisoformat(expiry) - date.fromisoformat(contracts[0].get("_snap_date", expiry))).days, 1)

    otm_puts = [p for p in puts if p["strike"] < spot]
    otm_calls = [c for c in calls if c["strike"] > spot]

    if strategy == "iron_condor":
        short_put = _find_delta_strike(otm_puts, spot, target_delta, "put", dte, side="high")
        short_call = _find_delta_strike(otm_calls, spot, target_delta, "call", dte, side="low")
        if not short_put or not short_call:
            return None
        long_put = _find_wing(puts, short_put["strike"], "below")
        long_call = _find_wing(calls, short_call["strike"], "above")
        if not long_put or not long_call:
            return None
        return {
            "legs": [
                {"contract": short_put, "side": "sell"},
                {"contract": long_put, "side": "buy"},
                {"contract": short_call, "side": "sell"},
                {"contract": long_call, "side": "buy"},
            ],
            "expiry": expiry,
            "is_credit": True,
        }

    elif strategy == "short_put_spread":
        short_put = _find_delta_strike(otm_puts, spot, target_delta, "put", dte, side="high")
        if not short_put:
            return None
        long_put = _find_wing(puts, short_put["strike"], "below")
        if not long_put:
            return None
        return {
            "legs": [
                {"contract": short_put, "side": "sell"},
                {"contract": long_put, "side": "buy"},
            ],
            "expiry": expiry,
            "is_credit": True,
        }

    elif strategy == "short_call_spread":
        short_call = _find_delta_strike(otm_calls, spot, target_delta, "call", dte, side="low")
        if not short_call:
            return None
        long_call = _find_wing(calls, short_call["strike"], "above")
        if not long_call:
            return None
        return {
            "legs": [
                {"contract": short_call, "side": "sell"},
                {"contract": long_call, "side": "buy"},
            ],
            "expiry": expiry,
            "is_credit": True,
        }

    elif strategy == "long_call_spread":
        atm_calls = sorted(calls, key=lambda c: abs(c["strike"] - spot))
        if len(atm_calls) < 2:
            return None
        buy_call = atm_calls[0]
        otm_above = [c for c in calls if c["strike"] > buy_call["strike"]]
        if not otm_above:
            return None
        sell_call = otm_above[0]
        return {
            "legs": [
                {"contract": buy_call, "side": "buy"},
                {"contract": sell_call, "side": "sell"},
            ],
            "expiry": expiry,
            "is_credit": False,
        }

    elif strategy == "long_put_spread":
        atm_puts = sorted(puts, key=lambda c: abs(c["strike"] - spot))
        if len(atm_puts) < 2:
            return None
        buy_put = atm_puts[0]
        otm_below = [p for p in puts if p["strike"] < buy_put["strike"]]
        if not otm_below:
            return None
        sell_put = otm_below[-1]
        return {
            "legs": [
                {"contract": buy_put, "side": "buy"},
                {"contract": sell_put, "side": "sell"},
            ],
            "expiry": expiry,
            "is_credit": False,
        }

    elif strategy == "butterfly":
        atm_calls = sorted(calls, key=lambda c: abs(c["strike"] - spot))
        if len(atm_calls) < 1:
            return None
        center = atm_calls[0]
        wings_above = [c for c in calls if c["strike"] > center["strike"]]
        wings_below = [c for c in calls if c["strike"] < center["strike"]]
        if not wings_above or not wings_below:
            atm_puts = sorted(puts, key=lambda c: abs(c["strike"] - spot))
            if len(atm_puts) < 1:
                return None
            center_put = atm_puts[0]
            wings_above_p = [p for p in puts if p["strike"] > center_put["strike"]]
            wings_below_p = [p for p in puts if p["strike"] < center_put["strike"]]
            if not wings_above_p or not wings_below_p:
                return None
            return {
                "legs": [
                    {"contract": wings_below_p[-1], "side": "buy"},
                    {"contract": center_put, "side": "sell"},
                    {"contract": center_put, "side": "sell"},
                    {"contract": wings_above_p[0], "side": "buy"},
                ],
                "expiry": expiry,
                "is_credit": False,
            }
        return {
            "legs": [
                {"contract": wings_below[-1], "side": "buy"},
                {"contract": center, "side": "sell"},
                {"contract": center, "side": "sell"},
                {"contract": wings_above[0], "side": "buy"},
            ],
            "expiry": expiry,
            "is_credit": False,
        }

    return None


def _find_delta_strike(options: List[dict], spot: float, target_delta: float,
                       option_type: str, dte: int, side: str = "high") -> Optional[dict]:
    """Find the strike closest to the target delta using IV from the chain.

    For puts: delta ~ -N(d1), we want |delta| ~ target_delta.
    Uses a rough BS delta approximation with the chain's own IV.
    """
    from models.black_scholes import black_scholes_price

    best = None
    best_diff = float("inf")
    T = dte / 365.0

    for opt in options:
        iv = opt.get("implied_volatility", 0.20)
        if iv <= 0 or iv > 3.0:
            continue
        try:
            d1 = (np.log(spot / opt["strike"]) + (RISK_FREE_RATE + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
            from scipy.stats import norm
            if option_type == "put":
                delta = abs(norm.cdf(d1) - 1)
            else:
                delta = norm.cdf(d1)
        except (ValueError, ZeroDivisionError):
            continue

        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best = opt

    return best


def _find_wing(options: List[dict], anchor_strike: float, direction: str) -> Optional[dict]:
    """Find the next available strike in the given direction for a wing."""
    if direction == "below":
        candidates = [o for o in options if o["strike"] < anchor_strike]
        return candidates[-1] if candidates else None
    else:
        candidates = [o for o in options if o["strike"] > anchor_strike]
        return candidates[0] if candidates else None


def _leg_fill_price(quote: dict, side: str, action: str, fill_mode: str) -> float:
    """Realistic fill price for a single leg.

    Models crossing the bid/ask spread: a buy lifts the ask, a sell hits the
    bid. On exit the action reverses — a short leg is bought back at the ask,
    a long leg is sold at the bid — which charges the spread on both entry and
    exit (the honest cost a real trader pays).

    `fill_mode="mid"` reproduces the legacy optimistic behavior (mid for every
    leg, ignoring the spread). Any other value ("bid_ask") uses real fills.

    Falls back to mid when the needed bid/ask is missing or non-positive — this
    happens on far-OTM/illiquid strikes (see DATA_ISSUES.md §4) — and to 0.0
    when no usable quote exists at all (e.g. an expired/worthless leg). Note
    that Alpaca-backfilled rows now carry bid == ask == close (a single traded
    price; see backfill_pipeline._estimate_bid_ask), so bid_ask mode prices
    them at the close and the spread cost is modeled by net slippage instead
    (see _apply_slippage usage in _check_exit / the entry loop).
    """
    mid = quote.get("mid") or 0.0
    if fill_mode != "bid_ask":
        return mid if mid > 0 else 0.0
    # Is this leg being bought in this action? Buying on open = a "buy" leg;
    # buying on close = covering a "sell" leg.
    buying = (side == "buy") if action == "open" else (side == "sell")
    if buying:
        ask = quote.get("ask") or 0.0
        return ask if ask > 0 else (mid if mid > 0 else 0.0)
    bid = quote.get("bid") or 0.0
    return bid if bid > 0 else (mid if mid > 0 else 0.0)


def _compute_entry_price(position: dict, fill_mode: str = "bid_ask") -> float:
    """Net entry premium. Positive = credit received, negative = debit paid.

    With fill_mode="bid_ask" buys pay the ask and sells receive the bid; with
    "mid" every leg is priced at mid (legacy, optimistic).
    """
    net = 0.0
    for leg in position["legs"]:
        price = _leg_fill_price(leg["contract"], leg["side"], "open", fill_mode)
        if leg["side"] == "sell":
            net += price
        else:
            net -= price
    return net


def _compute_exit_price(position: dict, exit_contracts: Dict,
                        fill_mode: str = "bid_ask") -> Optional[float]:
    """Net premium to close the position, valued at the exit snapshot.

    Uses the same leg orientation as entry (short legs positive, long legs
    negative) so P&L = entry_net - current_value (credit) holds. Closing
    reverses each leg: a short leg is bought back at the ask, a long leg is
    sold at the bid. Returns None if any leg is absent from the exit snapshot.
    """
    net = 0.0
    for leg in position["legs"]:
        strike = leg["contract"]["strike"]
        otype = leg["contract"]["option_type"]
        key = (strike, otype)
        exit_data = exit_contracts.get(key)
        if exit_data is None:
            return None
        price = _leg_fill_price(exit_data, leg["side"], "close", fill_mode)
        if leg["side"] == "sell":
            net += price
        else:
            net -= price
    return net


def _apply_slippage(net_price: float, slippage_pct: float, is_exit: bool) -> float:
    """Adverse slippage on a NET premium, for the unified P&L convention.

    P&L here is `entry_net - current_value` for both credit and debit (the
    legs are oriented sell:+, buy:-). To make slippage a strict cost under that
    convention it must ALWAYS lower P&L: reduce entry_net on entry, and raise
    current_value on exit. Then pnl' = (entry_net - s_e) - (current_value + s_x)
    = pnl - s_e - s_x, so slippage can never improve a trade regardless of
    credit/debit. (This is why the credit/debit-branched form used by
    local_backtest — which has a *branched* P&L formula — is wrong here: under
    the unified formula it flipped debit-exit slippage into a benefit and
    produced spurious 98% win rates.)

    Applied at the net-premium level — NOT per leg — so the cost is a fraction
    of the small spread net, consistent with the BS backtester. Per-leg
    slippage on the large individual legs is ~10x harsher and destabilizes the
    sequential single-position exit loop.
    """
    slip = abs(net_price) * (slippage_pct / 100.0)
    return net_price + slip if is_exit else net_price - slip


def _compute_intrinsic_exit(position: dict, spot: float) -> float:
    """Compute exit P&L using intrinsic value at expiry (spot vs strike)."""
    net = 0.0
    for leg in position["legs"]:
        strike = leg["contract"]["strike"]
        otype = leg["contract"]["option_type"]
        if otype == "call":
            intrinsic = max(spot - strike, 0.0)
        else:
            intrinsic = max(strike - spot, 0.0)
        if leg["side"] == "sell":
            net += intrinsic
        else:
            net -= intrinsic
    return net


def _check_entry_filters(request, regime: str, bias_score=None, bias_label=None,
                         dealer_regime=None) -> bool:
    """Same filter logic as local_backtest for consistency."""
    if request.regime_filter:
        strategy_regimes = {
            "iron_condor": {"HIGH_IV", "SPIKE"},
            "short_put_spread": {"HIGH_IV", "MODERATE_IV", "SPIKE"},
            "short_call_spread": {"HIGH_IV", "SPIKE"},
            "long_call_spread": {"LOW_IV", "MODERATE_IV"},
            "long_put_spread": {"LOW_IV", "MODERATE_IV"},
            "butterfly": {"LOW_IV", "MODERATE_IV"},
        }
        allowed = strategy_regimes.get(request.strategy, set())
        if regime not in allowed:
            return False

    if request.dealer_filter and dealer_regime is not None:
        strategy_dealer = {
            "iron_condor": "LONG_GAMMA",
            "butterfly": "LONG_GAMMA",
            "long_call_spread": "SHORT_GAMMA",
            "long_put_spread": "SHORT_GAMMA",
        }
        required = strategy_dealer.get(request.strategy)
        if required and dealer_regime != required:
            return False

    if request.bias_filter and bias_score is not None:
        bullish = {"short_put_spread", "long_call_spread"}
        bearish = {"short_call_spread", "long_put_spread"}
        neutral = {"iron_condor", "butterfly"}
        if request.strategy in bullish and bias_score < 2:
            return False
        if request.strategy in bearish and bias_score > -2:
            return False
        if request.strategy in neutral and abs(bias_score) > 3:
            return False

    return True


def _simulate_chain_trades(conn, snapshots: List[dict], rolling_vol: np.ndarray,
                           request: BacktestRequest) -> Tuple[List[BacktestTrade], List[str]]:
    """Walk through snapshots, enter trades from real chains, exit at real prices."""
    trades = []
    issues = []
    skipped_no_strikes = 0
    skipped_no_exit = 0
    skipped_filter = 0
    skipped_bad_premium = 0
    exit_used_intrinsic = 0
    entry_interval = 5

    exit_rules = _get_exit_rules(request.strategy)

    dealer_map = {}
    if request.dealer_filter:
        dealer_map = _load_dealer_data(conn, request.symbol, request.start_date, request.end_date)
        if not dealer_map:
            issues.append("Dealer filter ON but no OI data found — filter skipped")

    ohlcv_df = _fetch_ohlcv_for_bias(request.symbol, request.start_date, request.end_date)

    # Path-stable design: entries fire on a FIXED snapshot cadence, independent
    # of any prior trade's outcome, and each position's exit is found by an
    # independent forward scan. This decouples the trade SET from P&L, so
    # perturbing fills / slippage / exit thresholds changes each trade's
    # OUTCOME but not WHICH trades exist — the prerequisite for meaningful
    # perturbation and robustness analysis.
    #
    # The previous design held one position at a time and set the next entry to
    # `exit_idx + 3`, so the entry calendar depended on prior exit timing. A
    # sub-1% P&L perturbation then shifted an exit by one snapshot and
    # reshuffled the entire downstream trade sequence (observed: long_put_spread
    # QQQ flipping 51% -> 100% win rate between 0% and 1% slippage). See
    # FINDINGS.md (F-004) and ARCHITECTURE_EVOLUTION.md.
    #
    # Positions may now overlap (concurrency is allowed); per-trade P&L is
    # summed, which is the correct basis for measuring per-trade edge.
    n = len(snapshots)
    # Time-indexed mark-to-market portfolio curve (one entry per snapshot).
    # Each position adds its unrealized mark while open and its realized P&L
    # thereafter, so overlapping positions are aggregated on one timeline —
    # the correct basis for Sharpe/drawdown when trades overlap (F-006).
    portfolio_mtm = [0.0] * n
    for idx in range(0, n, entry_interval):
        snap = snapshots[idx]

        iv = rolling_vol[idx] if idx < len(rolling_vol) else 0.20
        regime = _classify_regime(iv, rolling_vol, idx)

        bias_score, bias_label = None, None
        if ohlcv_df is not None and request.bias_filter:
            bias_score, bias_label = _compute_bias(ohlcv_df, snap["date"])

        dealer_regime = dealer_map.get(snap["date"])

        if not _check_entry_filters(request, regime, bias_score, bias_label, dealer_regime):
            skipped_filter += 1
            continue

        contracts = _load_contracts(
            conn, snap["id"], request.entry_dte_min, request.entry_dte_max, snap["date"],
        )
        if len(contracts) < 4:
            skipped_no_strikes += 1
            continue

        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(
            contracts, snap["spot"], request.strategy, request.entry_delta,
        )
        if not position:
            skipped_no_strikes += 1
            continue

        entry_net = _compute_entry_price(position, request.fill_mode)
        if abs(entry_net) < 0.01:
            skipped_no_strikes += 1
            continue

        # Sanity gate (F-008): a defined-risk position cannot be worth more than
        # its strike span. Close-based marks are non-synchronous last trades —
        # an illiquid leg's stale print (from a different intraday spot) yields
        # a phantom credit/debit that violates this bound and, if booked,
        # "decays to zero" into fake profit (it inflated QQQ long_put to 100% WR;
        # 40-96% of entries were impossible). Reject those entries. The real fix
        # is synchronized NBBO quotes (gated, OPRA) — see FINDINGS.md F-008.
        strikes_all = [leg["contract"]["strike"] for leg in position["legs"]]
        strike_span = max(strikes_all) - min(strikes_all)
        if strike_span > 0 and abs(entry_net) > strike_span * 1.10:
            skipped_bad_premium += 1
            continue

        # Net slippage on entry — always reduces entry_net (adverse cost).
        if request.slippage_pct:
            entry_net = _apply_slippage(entry_net, request.slippage_pct, is_exit=False)

        if request.edge_threshold > 0:
            avg_iv = np.mean([
                leg["contract"].get("implied_volatility", 0.20)
                for leg in position["legs"]
                if leg["contract"].get("implied_volatility", 0) > 0
            ])
            edge_pct = ((avg_iv - iv) / avg_iv * 100) if avg_iv > 0 else 0
            is_credit = position["is_credit"]
            if is_credit and edge_pct < request.edge_threshold:
                skipped_filter += 1
                continue
            if not is_credit and edge_pct > -request.edge_threshold:
                skipped_filter += 1
                continue
        else:
            avg_iv = None
            edge_pct = None

        dte = (date.fromisoformat(position["expiry"]) - date.fromisoformat(snap["date"])).days
        spread_pcts = [
            leg["contract"].get("spread_pct", 0) or 0
            for leg in position["legs"]
        ]

        open_position = {
            "position": position,
            "entry_net": entry_net,
            "entry_date": snap["date"],
            "entry_spot": snap["spot"],
            "entry_idx": idx,
            "dte": dte,
            "regime": regime,
            "bias_score": bias_score,
            "bias_label": bias_label,
            "edge_pct": edge_pct,
            "iv_at_entry": iv,
            "avg_spread_pct": np.mean(spread_pcts) if spread_pcts else 0,
        }

        # Independent forward scan for this position's exit, recording the
        # mark-to-market P&L at every snapshot so overlapping positions can be
        # aggregated onto one timeline (F-006). Does not touch any other
        # position, so the trade set stays fixed under P&L perturbation (F-004).
        last_mark = 0.0
        exit_j = None
        realized = None
        for j in range(idx + 1, n):
            res = _check_exit(
                conn, request.symbol, snapshots[j], open_position,
                exit_rules, request, rolling_vol, j,
            )
            if res is None:
                # Can't reprice here (no contracts, not expiry) — carry the
                # last known mark forward.
                portfolio_mtm[j] += last_mark
                continue
            last_mark = res["pnl"]
            portfolio_mtm[j] += last_mark
            if res["trade"] is not None:
                if res.get("_used_intrinsic"):
                    exit_used_intrinsic += 1
                trades.append(res["trade"])
                exit_j = j
                realized = res["pnl"]
                break
        else:
            # Ran off the end of the data without an exit trigger — position
            # left open; its unrealized marks are already in portfolio_mtm.
            skipped_no_exit += 1

        # A closed position's realized P&L persists in the account for every
        # later snapshot.
        if exit_j is not None and realized is not None:
            for j in range(exit_j + 1, n):
                portfolio_mtm[j] += realized

    if skipped_no_strikes > 0:
        issues.append(f"{skipped_no_strikes} entries skipped — insufficient strikes in chain")
    if skipped_no_exit > 0:
        issues.append(f"{skipped_no_exit} trades dropped — no exit snapshot found")
    if skipped_filter > 0:
        issues.append(f"{skipped_filter} entries skipped by signal filters")
    if skipped_bad_premium > 0:
        issues.append(f"{skipped_bad_premium} entries skipped — premium exceeded strike span (non-synchronous close marks, F-008). Real fix needs synchronized NBBO quotes.")
    if exit_used_intrinsic > 0:
        issues.append(f"{exit_used_intrinsic} exits used intrinsic value (no matching contracts in exit snapshot)")
    if request.fill_mode == "bid_ask":
        issues.append("Fills priced at real bid/ask (buys pay ask, sells receive bid) — spread charged on entry and exit")
    else:
        issues.append("Fills priced at mid (optimistic — overstates edge; see docs/pricing_validation_report.md)")
    if request.slippage_pct:
        issues.append(f"Explicit net slippage of {request.slippage_pct}% applied (adverse) on entry and snapshot exits — models fill cost for close-priced Alpaca-backfilled data (bid==ask==close).")

    return trades, issues, portfolio_mtm


def _check_exit(conn, symbol: str, current_snap: dict, position_info: dict,
                exit_rules: dict, request: BacktestRequest,
                rolling_vol: np.ndarray, idx: int) -> Optional[dict]:
    """Value the position at this snapshot and decide whether to exit.

    Returns None if the position cannot be valued here (no matching contracts
    and not yet at expiry). Otherwise returns:
        {"pnl":  mark-to-market P&L (×100) at this snapshot,
         "trade": BacktestTrade if an exit triggered this snapshot, else None,
         "_used_intrinsic": bool}
    The caller records `pnl` every snapshot to build the mark-to-market
    portfolio curve and closes the position when `trade` is not None.
    """
    position = position_info["position"]
    entry_net = position_info["entry_net"]
    expiry = position["expiry"]
    entry_date = position_info["entry_date"]
    dte_remaining = (date.fromisoformat(expiry) - date.fromisoformat(current_snap["date"])).days

    strikes = [leg["contract"]["strike"] for leg in position["legs"]]
    otypes = [leg["contract"]["option_type"] for leg in position["legs"]]

    exit_contracts = _find_exit_contracts(conn, symbol, current_snap["date"], expiry, strikes, otypes)
    used_intrinsic = False

    if exit_contracts:
        current_value = _compute_exit_price(position, exit_contracts, request.fill_mode)
        if current_value is None:
            if dte_remaining <= 1:
                current_value = _compute_intrinsic_exit(position, current_snap["spot"])
                used_intrinsic = True
            else:
                return None
    elif dte_remaining <= 1:
        current_value = _compute_intrinsic_exit(position, current_snap["spot"])
        used_intrinsic = True
    else:
        return None

    # Net slippage on exit — always raises current_value (adverse cost under
    # pnl = entry_net - current_value). Skip intrinsic settlement at expiry —
    # there is no spread to cross at exercise.
    if request.slippage_pct and not used_intrinsic:
        current_value = _apply_slippage(current_value, request.slippage_pct, is_exit=True)

    # P&L is entry_net - current_value for BOTH credit and debit. entry_net and
    # current_value are computed in the same leg orientation (sell legs add,
    # buy legs subtract), so this single formula holds regardless of sign:
    #   credit: collect entry_net (+), buy back at current_value → entry - current
    #   debit:  pay |entry_net| (entry_net < 0); the same difference yields the
    #           correct signed gain (verified: a debit spread that appreciates
    #           shows a positive P&L). The previous `current - entry` branch for
    #           debits inverted the sign of every long-spread/butterfly trade.
    pnl = entry_net - current_value

    use_strategy_rules = (request.exit_rule == "strategy")
    if use_strategy_rules:
        profit_pct = exit_rules["profit_pct"]
        loss_pct = exit_rules["loss_pct"]
        time_exit_dte = exit_rules["exit_dte"]
        hold = exit_rules["hold"]
    else:
        profit_pct = request.exit_profit_pct
        loss_pct = request.exit_loss_pct
        time_exit_dte = request.exit_dte
        hold = (request.exit_rule == "hold")

    exit_reason = None
    ref_price = abs(entry_net)

    if not hold:
        if ref_price > 0:
            if pnl >= ref_price * (profit_pct / 100):
                exit_reason = "profit_target"
            elif pnl <= -ref_price * (loss_pct / 100):
                exit_reason = "stop_loss"
    else:
        if ref_price > 0 and pnl <= -ref_price * (loss_pct / 100):
            exit_reason = "stop_loss"

    if dte_remaining <= time_exit_dte:
        exit_reason = exit_reason or "dte_exit"

    final_pnl = pnl * 100

    # Always report the mark-to-market P&L; attach a closed trade only when an
    # exit actually triggered at this snapshot.
    trade = None
    if exit_reason:
        dte_at_entry = position_info["dte"]
        trade = BacktestTrade(
            entry_date=date.fromisoformat(position_info["entry_date"]),
            exit_date=date.fromisoformat(current_snap["date"]),
            entry_price=round(entry_net, 4),
            exit_price=round(current_value, 4),
            pnl=round(final_pnl, 2),
            pnl_pct=round(pnl / max(abs(entry_net), 0.01) * 100, 1),
            dte_at_entry=dte_at_entry,
            dte_at_exit=max(dte_remaining, 0),
            regime=position_info["regime"],
            win=pnl > 0,
            exit_reason=exit_reason,
            bias_score=position_info.get("bias_score"),
            bias_label=position_info.get("bias_label"),
            edge_pct=round(position_info["edge_pct"], 2) if position_info.get("edge_pct") is not None else None,
            iv_at_entry=round(position_info["iv_at_entry"], 4),
            fill_mode=request.fill_mode,
            avg_spread_pct=round(position_info.get("avg_spread_pct", 0) or 0, 2),
        )

    return {"pnl": round(final_pnl, 2), "trade": trade, "_used_intrinsic": used_intrinsic}


def _get_exit_rules(strategy: str) -> dict:
    rules = {
        "iron_condor":       {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1, "hold": False},
        "short_put_spread":  {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1, "hold": False},
        "short_call_spread": {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1, "hold": False},
        "long_call_spread":  {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2, "hold": False},
        "long_put_spread":   {"profit_pct": 75, "loss_pct": 100, "exit_dte": 2, "hold": False},
        "butterfly":         {"profit_pct": 100, "loss_pct": 100, "exit_dte": 0, "hold": True},
    }
    return rules.get(strategy, {"profit_pct": 50, "loss_pct": 200, "exit_dte": 1, "hold": False})


def _load_dealer_data(conn, symbol: str, start_date, end_date) -> dict:
    """Load P/C OI ratio as dealer proxy — same logic as local_backtest."""
    try:
        cursor = conn.execute("""
            SELECT cs.snapshot_date, cc.option_type, SUM(cc.open_interest)
            FROM chain_contracts cc
            JOIN chain_snapshots cs ON cc.snapshot_id = cs.id
            WHERE cs.ticker = ? AND cs.snapshot_date BETWEEN ? AND ?
              AND cc.open_interest > 0
            GROUP BY cs.snapshot_date, cc.option_type
        """, (symbol, str(start_date), str(end_date)))

        oi_by_date = {}
        for row in cursor.fetchall():
            snap_date, opt_type, total_oi = row
            if snap_date not in oi_by_date:
                oi_by_date[snap_date] = {"call": 0, "put": 0}
            oi_by_date[snap_date][opt_type] = total_oi

        dealer_map = {}
        for d, oi in oi_by_date.items():
            if oi["call"] > 0:
                pc_ratio = oi["put"] / oi["call"]
                dealer_map[d] = "SHORT_GAMMA" if pc_ratio > 1.0 else "LONG_GAMMA"
        return dealer_map
    except Exception:
        return {}


def _fetch_ohlcv_for_bias(symbol: str, start: date, end: date):
    """Fetch OHLCV for bias detection. Returns DataFrame or None."""
    try:
        import yfinance as yf
        lookback_start = start - timedelta(days=60)
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=lookback_start.isoformat(), end=end.isoformat())
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


def _compute_bias(ohlcv_df, snap_date: str, lookback: int = 30):
    """Compute bias at a snapshot date."""
    try:
        from bias_detector import detect_bias
        target = date.fromisoformat(snap_date)
        mask = ohlcv_df.index.date <= target
        window = ohlcv_df[mask].tail(lookback + 1)
        if len(window) < lookback:
            return None, None
        result = detect_bias(window)
        return result.score, result.label
    except Exception:
        return None, None
