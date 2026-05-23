"""
Day-type classifier for 0 DTE options.

The most important 0 DTE signal. Classifies the trading day as:
- RANGE_DAY: mean-reverting, sell premium (iron condors, butterflies)
- TREND_DAY: momentum, avoid selling premium or trade directional
- UNCERTAIN: no clear classification, stand aside

Uses three inputs measured after the first 30 minutes (10:00 AM ET):
1. First 30-min range / ATM 0DTE straddle price (expected move proxy)
2. VIX change from prior close
3. Overnight gap size

Options Analytics Team — 2026-04
"""

import logging
from typing import Optional

import pandas as pd

from data.intraday_models import DayClassification, DayType

logger = logging.getLogger(__name__)

# ── Classification thresholds ────────────────────────────────────────────────
# These are first-principles defaults. Calibrate with Phase 3 backtester.

# Range ratio = first_30min_range / expected_daily_move
RANGE_RATIO_LOW = 0.30    # Below → range day signal
RANGE_RATIO_HIGH = 0.60   # Above → trend day signal

# VIX intraday change from prior close
VIX_CHANGE_LOW = 5.0      # Below → calm (range day)
VIX_CHANGE_HIGH = 10.0    # Above → fear (trend day)

# Overnight gap (open vs prior close)
GAP_LOW = 0.3             # Below → no gap (range day)
GAP_HIGH = 0.5            # Above → gap (trend day)


def classify_day(
    bars: pd.DataFrame,
    expected_daily_move: float,
    prior_close: Optional[float] = None,
    vix_current: Optional[float] = None,
    vix_prior_close: Optional[float] = None,
) -> DayClassification:
    """Classify the current day as range, trend, or uncertain.

    Parameters
    ----------
    bars : pd.DataFrame
        Intraday bars with DatetimeIndex and OHLCV columns.
        Must include at least the first 30 min of trading (9:30-10:00 ET).
    expected_daily_move : float
        ATM 0DTE straddle mid price — proxy for the market's expected move.
        Must be > 0.
    prior_close : float, optional
        Previous day's closing price for gap calculation.
        If None, uses the first bar's Open.
    vix_current : float, optional
        Current VIX level.
    vix_prior_close : float, optional
        Previous day's VIX close for change calculation.

    Returns
    -------
    DayClassification
    """
    if bars.empty or expected_daily_move <= 0:
        return DayClassification(
            day_type=DayType.UNCERTAIN,
            confidence=0.0,
            first_30min_range=0.0,
            expected_daily_move=expected_daily_move,
            range_vs_expected=0.0,
            overnight_gap_pct=0.0,
            vix_change_pct=0.0,
            detail="Insufficient data for classification",
        )

    # ── Compute first 30-min range ───────────────────────────────────────
    first_30min_bars = _get_first_30min(bars)

    if first_30min_bars.empty:
        first_30min_range = 0.0
    else:
        first_30min_range = first_30min_bars["High"].max() - first_30min_bars["Low"].min()

    range_vs_expected = first_30min_range / expected_daily_move if expected_daily_move > 0 else 0.0

    # ── Overnight gap ────────────────────────────────────────────────────
    open_price = bars["Open"].iloc[0]
    if prior_close is not None and prior_close > 0:
        overnight_gap_pct = abs(open_price - prior_close) / prior_close * 100
    else:
        overnight_gap_pct = 0.0

    # ── VIX change ───────────────────────────────────────────────────────
    if vix_current is not None and vix_prior_close is not None and vix_prior_close > 0:
        vix_change_pct = (vix_current - vix_prior_close) / vix_prior_close * 100
    else:
        vix_change_pct = 0.0

    # ── Classify ─────────────────────────────────────────────────────────
    range_signals = 0
    trend_signals = 0
    reasons = []

    # Signal 1: Range ratio (most important)
    if range_vs_expected < RANGE_RATIO_LOW:
        range_signals += 2
        reasons.append(f"30min range {range_vs_expected:.0%} of expected move (< {RANGE_RATIO_LOW:.0%})")
    elif range_vs_expected > RANGE_RATIO_HIGH:
        trend_signals += 2
        reasons.append(f"30min range {range_vs_expected:.0%} of expected move (> {RANGE_RATIO_HIGH:.0%})")
    else:
        reasons.append(f"30min range {range_vs_expected:.0%} of expected move (ambiguous)")

    # Signal 2: VIX change
    abs_vix_change = abs(vix_change_pct)
    if abs_vix_change < VIX_CHANGE_LOW:
        range_signals += 1
        reasons.append(f"VIX change {vix_change_pct:+.1f}% (calm)")
    elif abs_vix_change > VIX_CHANGE_HIGH:
        trend_signals += 1
        reasons.append(f"VIX change {vix_change_pct:+.1f}% (fear)")
    else:
        reasons.append(f"VIX change {vix_change_pct:+.1f}% (moderate)")

    # Signal 3: Overnight gap
    if overnight_gap_pct < GAP_LOW:
        range_signals += 1
        reasons.append(f"Gap {overnight_gap_pct:.2f}% (flat open)")
    elif overnight_gap_pct > GAP_HIGH:
        trend_signals += 1
        reasons.append(f"Gap {overnight_gap_pct:.2f}% (gap open)")
    else:
        reasons.append(f"Gap {overnight_gap_pct:.2f}% (small)")

    # ── Decision ─────────────────────────────────────────────────────────
    total = range_signals + trend_signals
    if total == 0:
        day_type = DayType.UNCERTAIN
        confidence = 0.3
    elif range_signals > trend_signals:
        day_type = DayType.RANGE_DAY
        confidence = min(range_signals / max(total, 1), 1.0)
    elif trend_signals > range_signals:
        day_type = DayType.TREND_DAY
        confidence = min(trend_signals / max(total, 1), 1.0)
    else:
        day_type = DayType.UNCERTAIN
        confidence = 0.4

    detail = f"{day_type.value} ({confidence:.0%}): " + "; ".join(reasons)
    logger.info("Day classification: %s", detail)

    return DayClassification(
        day_type=day_type,
        confidence=round(confidence, 2),
        first_30min_range=round(first_30min_range, 4),
        expected_daily_move=round(expected_daily_move, 4),
        range_vs_expected=round(range_vs_expected, 4),
        overnight_gap_pct=round(overnight_gap_pct, 4),
        vix_change_pct=round(vix_change_pct, 2),
        detail=detail,
    )


def _get_first_30min(bars: pd.DataFrame) -> pd.DataFrame:
    """Extract bars from 9:30 to 10:00 ET.

    Handles both timezone-aware and naive timestamps.
    Falls back to first 6 bars (6 x 5min = 30min) if timezone detection fails.
    """
    if bars.empty:
        return bars

    try:
        idx = bars.index
        # Try to work with timezone-aware timestamps
        if hasattr(idx, 'tz') and idx.tz is not None:
            # Convert to US/Eastern for market hours comparison
            import pytz
            eastern = pytz.timezone("US/Eastern")
            local_idx = idx.tz_convert(eastern)
            mask = local_idx.time <= pd.Timestamp("10:00").time()
            return bars[mask]

        # Naive timestamps — check if times look like market hours
        first_time = idx[0]
        if hasattr(first_time, 'hour'):
            # Assume Eastern time if hours are in 9-16 range
            if 9 <= first_time.hour <= 10:
                mask = idx.time <= pd.Timestamp("10:00").time()
                return bars[mask]

    except Exception as e:
        logger.debug("Timezone handling failed, using first 6 bars: %s", e)

    # Fallback: first 6 bars (5-min interval × 6 = 30 min)
    return bars.iloc[:6]


def get_expected_daily_move_from_chain(chain_snapshot, today: str) -> float:
    """Compute expected daily move from ATM 0DTE straddle mid price.

    The ATM straddle price is the market's best estimate of the
    expected absolute move for the day.

    Parameters
    ----------
    chain_snapshot : ChainSnapshot
        Must include 0 DTE contracts.
    today : str
        Today's date (YYYY-MM-DD) to identify 0 DTE expiry.

    Returns
    -------
    float : Expected move in dollar terms. Returns 0 if no 0 DTE contracts found.
    """
    spot = chain_snapshot.spot
    contracts = chain_snapshot.contracts

    # Find 0 DTE contracts (expiring today)
    zero_dte = [c for c in contracts if c.expiry == today]
    if not zero_dte:
        logger.warning("No 0 DTE contracts found for %s expiring %s", chain_snapshot.ticker, today)
        return 0.0

    # Find ATM strike (closest to spot)
    strikes = sorted(set(c.strike for c in zero_dte))
    if not strikes:
        return 0.0

    atm_strike = min(strikes, key=lambda s: abs(s - spot))

    # Get ATM call and put mid prices
    atm_call_mid = 0.0
    atm_put_mid = 0.0
    for c in zero_dte:
        if c.strike == atm_strike:
            if c.option_type == "call" and c.mid > 0:
                atm_call_mid = c.mid
            elif c.option_type == "put" and c.mid > 0:
                atm_put_mid = c.mid

    straddle_price = atm_call_mid + atm_put_mid

    if straddle_price <= 0:
        logger.warning("ATM straddle price is zero for %s at strike %.1f", chain_snapshot.ticker, atm_strike)
        return 0.0

    logger.info(
        "Expected daily move for %s: $%.2f (ATM strike=%.1f, call=$%.2f, put=$%.2f)",
        chain_snapshot.ticker, straddle_price, atm_strike, atm_call_mid, atm_put_mid,
    )
    return straddle_price
