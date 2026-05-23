"""
Intraday state builder for 0 DTE options.

build_intraday_state() is the main entry point — analogous to
build_market_state() for daily signals. It combines:
1. Intraday price bars from intraday_store
2. Latest intraday chain snapshot
3. Day-type classification
4. Move exhaustion
5. VIX intraday context
6. Recomputed GEX from intraday chain

Options Analytics Team — 2026-04
"""

import logging
from datetime import datetime
from typing import Optional

from data.intraday_models import DayType, IntradayState

logger = logging.getLogger(__name__)


def build_intraday_state(
    symbol: str,
    date: Optional[str] = None,
) -> IntradayState:
    """Build complete intraday state for 0 DTE decision-making.

    Parameters
    ----------
    symbol : str
        Ticker (e.g., "SPY", "^SPX").
    date : str, optional
        Date to build state for (YYYY-MM-DD). Defaults to today.

    Returns
    -------
    IntradayState
    """
    from data.intraday_store import get_bars
    from data.chain_store import get_intraday_snapshots, get_snapshot
    from signals.day_classifier import classify_day, get_expected_daily_move_from_chain
    from signals.move_exhaustion import compute_move_exhaustion
    from signals.intraday_gex import compute_intraday_gex

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    now = datetime.now()

    # ── 1. Load intraday bars ────────────────────────────────────────────
    bars = get_bars(symbol, date, interval="5m")
    bars_count = len(bars)

    if bars.empty:
        logger.warning("No intraday bars for %s on %s", symbol, date)
        return _empty_state(symbol, date, now, "No intraday bars available")

    open_price = bars["Open"].iloc[0]
    current_price = bars["Close"].iloc[-1]

    # ── 2. Get prior close for gap calculation ───────────────────────────
    prior_close = _get_prior_close(symbol, date)

    # ── 3. Load VIX data ─────────────────────────────────────────────────
    vix_current, vix_open, vix_prior_close = _get_vix_context(date)

    vix_change_pct = None
    if vix_current is not None and vix_prior_close is not None and vix_prior_close > 0:
        vix_change_pct = (vix_current - vix_prior_close) / vix_prior_close * 100

    # ── 4. Get expected daily move from chain ────────────────────────────
    expected_daily_move = 0.0
    chain_label = None

    # Try intraday chain first, then EOD
    intraday_snapshots = get_intraday_snapshots(symbol, date)
    if intraday_snapshots:
        chain_label, chain = intraday_snapshots[-1]  # latest
        expected_daily_move = get_expected_daily_move_from_chain(chain, date)
    else:
        # Fall back to short-DTE or EOD chain
        for label in ["shortdte", "eod"]:
            chain = get_snapshot(symbol, date, label=label)
            if chain:
                chain_label = label
                expected_daily_move = get_expected_daily_move_from_chain(chain, date)
                if expected_daily_move > 0:
                    break

    # If no chain data at all, estimate from VIX + spot
    if expected_daily_move <= 0:
        expected_daily_move = _estimate_expected_move(current_price, vix_current)
        logger.info("Using VIX-based expected move estimate: $%.2f", expected_daily_move)

    # ── 5. Classify day type ─────────────────────────────────────────────
    classification = classify_day(
        bars=bars,
        expected_daily_move=expected_daily_move,
        prior_close=prior_close,
        vix_current=vix_current,
        vix_prior_close=vix_prior_close,
    )

    # ── 6. Compute move exhaustion ───────────────────────────────────────
    exhaustion = compute_move_exhaustion(
        current_price=current_price,
        open_price=open_price,
        expected_daily_move=expected_daily_move,
    )

    # ── 7. Recompute GEX from intraday chain ────────────────────────────
    gamma_flip = None
    gamma_flip_distance_pct = None
    dealer_regime = None
    net_gex = None
    call_wall = None
    put_wall = None
    max_pain = None
    is_pinned = False

    dealer_chain = None
    if intraday_snapshots:
        _, dealer_chain = intraday_snapshots[-1]
    else:
        for label in ["shortdte", "eod"]:
            dealer_chain = get_snapshot(symbol, date, label=label)
            if dealer_chain:
                break

    if dealer_chain:
        dealer = compute_intraday_gex(dealer_chain)
        if dealer:
            gamma_flip = dealer.gamma_flip
            net_gex = dealer.net_gex
            dealer_regime = dealer.dealer_regime
            call_wall = dealer.call_wall
            put_wall = dealer.put_wall
            max_pain = dealer.max_pain

            if current_price > 0 and gamma_flip > 0:
                gamma_flip_distance_pct = round(
                    (current_price - gamma_flip) / current_price * 100, 2
                )

            # Pinned = spot within 0.3% of gamma flip AND LONG_GAMMA
            if gamma_flip_distance_pct is not None:
                is_pinned = (
                    abs(gamma_flip_distance_pct) < 0.3
                    and dealer_regime == "LONG_GAMMA"
                )

    # ── 8. Build state ───────────────────────────────────────────────────
    state = IntradayState(
        symbol=symbol,
        timestamp=now,
        spot=round(current_price, 4),
        open_price=round(open_price, 4),
        overnight_gap_pct=round(classification.overnight_gap_pct, 4),
        first_30min_range=round(classification.first_30min_range, 4),
        expected_daily_move=round(expected_daily_move, 4),
        range_vs_expected=round(classification.range_vs_expected, 4),
        day_type=classification.day_type,
        day_type_confidence=classification.confidence,
        intraday_move=round(exhaustion.intraday_move, 4),
        move_exhaustion_pct=round(exhaustion.exhaustion_pct, 2),
        exhaustion_signal=exhaustion.signal,
        vix_current=round(vix_current, 2) if vix_current else None,
        vix_open=round(vix_open, 2) if vix_open else None,
        vix_change_pct=round(vix_change_pct, 2) if vix_change_pct is not None else None,
        gamma_flip=gamma_flip,
        gamma_flip_distance_pct=gamma_flip_distance_pct,
        dealer_regime=dealer_regime,
        net_gex=net_gex,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        is_pinned=is_pinned,
        bars_count=bars_count,
        chain_label=chain_label,
    )

    logger.info(
        "IntradayState for %s: day_type=%s (%.0f%%), exhaustion=%s (%.0f%%), "
        "dealer=%s, pinned=%s",
        symbol, state.day_type.value, state.day_type_confidence * 100,
        state.exhaustion_signal, state.move_exhaustion_pct,
        state.dealer_regime or "N/A", state.is_pinned,
    )

    return state


def _empty_state(symbol: str, date: str, now: datetime, reason: str) -> IntradayState:
    """Return a minimal IntradayState when data is insufficient."""
    return IntradayState(
        symbol=symbol,
        timestamp=now,
        spot=0.0,
        open_price=0.0,
        overnight_gap_pct=0.0,
        first_30min_range=0.0,
        expected_daily_move=0.0,
        range_vs_expected=0.0,
        day_type=DayType.UNCERTAIN,
        day_type_confidence=0.0,
        intraday_move=0.0,
        move_exhaustion_pct=0.0,
        exhaustion_signal="caution",
    )


def _get_prior_close(symbol: str, date: str) -> Optional[float]:
    """Get prior trading day's close from intraday bars."""
    from data.intraday_store import get_available_dates

    dates = get_available_dates(symbol, interval="5m")
    if not dates:
        return None

    # Find the date before the requested date
    prior_dates = [d for d in dates if d < date]
    if not prior_dates:
        return None

    prior_date = prior_dates[-1]
    from data.intraday_store import get_bars
    prior_bars = get_bars(symbol, prior_date, interval="5m")
    if prior_bars.empty:
        return None

    return prior_bars["Close"].iloc[-1]


def _get_vix_context(date: str) -> tuple:
    """Get VIX current, open, and prior close.

    Returns (vix_current, vix_open, vix_prior_close) — any may be None.
    """
    from data.intraday_store import get_bars, get_available_dates

    vix_ticker = "^VIX"

    # Current VIX from today's bars
    vix_bars = get_bars(vix_ticker, date, interval="5m")
    vix_current = None
    vix_open = None
    if not vix_bars.empty:
        vix_current = vix_bars["Close"].iloc[-1]
        vix_open = vix_bars["Open"].iloc[0]

    # Prior close
    vix_prior_close = None
    vix_dates = get_available_dates(vix_ticker, interval="5m")
    prior_vix_dates = [d for d in vix_dates if d < date]
    if prior_vix_dates:
        prior_vix_bars = get_bars(vix_ticker, prior_vix_dates[-1], interval="5m")
        if not prior_vix_bars.empty:
            vix_prior_close = prior_vix_bars["Close"].iloc[-1]

    return vix_current, vix_open, vix_prior_close


def _estimate_expected_move(spot: float, vix: Optional[float]) -> float:
    """Estimate expected daily move from VIX when no chain data available.

    VIX represents annualized expected vol. Daily move ≈ VIX / sqrt(252) * spot / 100.
    """
    if vix is None or vix <= 0 or spot <= 0:
        # Last resort: assume 1% daily move
        return spot * 0.01 if spot > 0 else 1.0

    import math
    daily_vol = vix / math.sqrt(252) / 100
    return spot * daily_vol
