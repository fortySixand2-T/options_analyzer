"""Swing-timeframe directional bias detector.

Longer-horizon signals for 14-60 DTE strategies. Uses SMA 20/50/200
alignment, golden/death cross, weekly RSI, and 20-day momentum —
signals that are too slow for 0-14 DTE but appropriate for swing trades.

Input:  pandas DataFrame of daily OHLCV (needs >= 200 rows for SMA 200)
Output: SwingBiasResult(label, score, detail) — same interface as BiasResult
"""

import logging
from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

STRONG_BULLISH = "STRONG_BULLISH"
LEAN_BULLISH   = "LEAN_BULLISH"
NEUTRAL        = "NEUTRAL"
LEAN_BEARISH   = "LEAN_BEARISH"
STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class SwingBiasResult:
    """Swing-timeframe directional bias output."""
    label: str              # one of the 5 labels
    score: int              # raw weighted score (-10 to +10)
    atr_percentile: float   # 0-100, trending vs ranging
    detail: Dict[str, object] = field(default_factory=dict)


def detect_swing_bias(df: pd.DataFrame) -> SwingBiasResult:
    """Detect swing-timeframe directional bias from daily OHLCV.

    Signals:
        S1: SMA 20/50/200 alignment (weight 3)
        S2: SMA 50/200 cross — golden cross / death cross (weight 2)
        S3: Weekly RSI(14) (weight 2)
        S4: 20-day momentum — close vs 20-day-ago close (weight 1)
        S5: SMA 50 slope — 10-bar trend direction (weight 1)
        S6: Price vs SMA 200 distance — mean reversion (weight 1)

    Parameters
    ----------
    df : pd.DataFrame
        Daily OHLCV with columns: Open, High, Low, Close, Volume.
        Needs >= 200 rows for full signal set; degrades gracefully with less.

    Returns
    -------
    SwingBiasResult
    """
    if df is None or len(df) < 30:
        return SwingBiasResult(label=NEUTRAL, score=0, atr_percentile=50.0)

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values

    score = 0
    detail = {}

    # S1: SMA alignment (weight 3)
    s1_score, s1_detail = _sma_alignment(close)
    score += s1_score * 3
    detail["sma_alignment"] = s1_detail

    # S2: Golden cross / death cross (weight 2)
    s2_score, s2_detail = _sma_cross(close)
    score += s2_score * 2
    detail["sma_cross"] = s2_detail

    # S3: Weekly RSI (weight 2)
    s3_score, s3_detail = _weekly_rsi(close)
    score += s3_score * 2
    detail["weekly_rsi"] = s3_detail

    # S4: 20-day momentum (weight 1)
    s4_score, s4_detail = _momentum_20d(close)
    score += s4_score
    detail["momentum_20d"] = s4_detail

    # S5: SMA 50 slope (weight 1)
    s5_score, s5_detail = _sma50_slope(close)
    score += s5_score
    detail["sma50_slope"] = s5_detail

    # S6: Distance from SMA 200 (weight 1)
    s6_score, s6_detail = _sma200_distance(close)
    score += s6_score
    detail["sma200_distance"] = s6_detail

    # ATR percentile
    atr_pctl = _atr_percentile(high, low, close)

    # Map score to label
    label = _score_to_label(score)

    return SwingBiasResult(
        label=label,
        score=score,
        atr_percentile=atr_pctl,
        detail=detail,
    )


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    if len(values) < period:
        return np.full(len(values), np.nan)
    cumsum = np.cumsum(np.insert(values.astype(float), 0, 0))
    result = np.full(len(values), np.nan)
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def _sma_alignment(close: np.ndarray) -> tuple:
    """S1: SMA 20/50/200 alignment.

    +1 if close > SMA20 > SMA50 > SMA200 (fully bullish)
    -1 if close < SMA20 < SMA50 < SMA200 (fully bearish)
     0 otherwise (mixed)
    """
    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)

    current = close[-1]
    s20 = sma20[-1] if not np.isnan(sma20[-1]) else current
    s50 = sma50[-1] if not np.isnan(sma50[-1]) else current

    if np.isnan(sma200[-1]):
        # Not enough data for SMA200, use 20/50 only
        if current > s20 > s50:
            return 1, {"alignment": "bullish_partial", "close": round(current, 2),
                       "sma20": round(s20, 2), "sma50": round(s50, 2)}
        elif current < s20 < s50:
            return -1, {"alignment": "bearish_partial", "close": round(current, 2),
                        "sma20": round(s20, 2), "sma50": round(s50, 2)}
        return 0, {"alignment": "mixed", "close": round(current, 2),
                   "sma20": round(s20, 2), "sma50": round(s50, 2)}

    s200 = sma200[-1]

    if current > s20 > s50 > s200:
        return 1, {"alignment": "fully_bullish", "close": round(current, 2),
                   "sma20": round(s20, 2), "sma50": round(s50, 2), "sma200": round(s200, 2)}
    elif current < s20 < s50 < s200:
        return -1, {"alignment": "fully_bearish", "close": round(current, 2),
                    "sma20": round(s20, 2), "sma50": round(s50, 2), "sma200": round(s200, 2)}
    return 0, {"alignment": "mixed", "close": round(current, 2),
               "sma20": round(s20, 2), "sma50": round(s50, 2), "sma200": round(s200, 2)}


def _sma_cross(close: np.ndarray) -> tuple:
    """S2: SMA 50/200 cross (golden cross / death cross).

    +1 if SMA50 crossed above SMA200 in last 20 bars (golden cross)
    -1 if SMA50 crossed below SMA200 in last 20 bars (death cross)
     0 if no recent cross
    """
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)

    if np.isnan(sma200[-1]) or np.isnan(sma50[-1]):
        return 0, {"cross": "insufficient_data"}

    lookback = min(20, len(close) - 200)
    if lookback < 2:
        return 0, {"cross": "insufficient_data"}

    for i in range(-lookback, -1):
        prev_diff = sma50[i - 1] - sma200[i - 1]
        curr_diff = sma50[i] - sma200[i]

        if np.isnan(prev_diff) or np.isnan(curr_diff):
            continue

        if prev_diff <= 0 < curr_diff:
            return 1, {"cross": "golden_cross", "bars_ago": abs(i)}
        elif prev_diff >= 0 > curr_diff:
            return -1, {"cross": "death_cross", "bars_ago": abs(i)}

    # No cross, but report current relationship
    diff = sma50[-1] - sma200[-1]
    return 0, {"cross": "none", "sma50_above_200": diff > 0,
               "spread_pct": round(diff / sma200[-1] * 100, 2)}


def _weekly_rsi(close: np.ndarray, period: int = 14) -> tuple:
    """S3: Weekly RSI(14).

    Resample daily closes to weekly, compute RSI.
    +1 if RSI 50-65 (bullish momentum without overbought)
    -1 if RSI 35-50 (bearish momentum without oversold)
     0 if neutral or extreme (>70 overbought fade, <30 oversold bounce — handled by short-DTE)
    """
    # Approximate weekly by taking every 5th close
    weekly_close = close[::5]
    if len(weekly_close) < period + 1:
        return 0, {"rsi": None, "note": "insufficient_data"}

    rsi = _compute_rsi(weekly_close, period)
    if rsi is None:
        return 0, {"rsi": None}

    if 50 <= rsi <= 65:
        return 1, {"rsi": round(rsi, 1), "zone": "bullish_momentum"}
    elif 35 <= rsi < 50:
        return -1, {"rsi": round(rsi, 1), "zone": "bearish_momentum"}

    return 0, {"rsi": round(rsi, 1), "zone": "neutral_or_extreme"}


def _compute_rsi(values: np.ndarray, period: int = 14) -> float:
    """Compute RSI from a price series."""
    if len(values) < period + 1:
        return None

    deltas = np.diff(values.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _momentum_20d(close: np.ndarray) -> tuple:
    """S4: 20-day momentum.

    +1 if close > close[20 days ago]
    -1 if close < close[20 days ago]
    """
    if len(close) < 21:
        return 0, {"momentum": None}

    current = close[-1]
    past = close[-21]
    pct = (current - past) / past * 100

    if pct > 1.0:
        return 1, {"momentum_pct": round(pct, 2), "direction": "bullish"}
    elif pct < -1.0:
        return -1, {"momentum_pct": round(pct, 2), "direction": "bearish"}

    return 0, {"momentum_pct": round(pct, 2), "direction": "flat"}


def _sma50_slope(close: np.ndarray) -> tuple:
    """S5: SMA 50 slope over last 10 bars.

    +1 if rising (slope > 0.1% per bar)
    -1 if falling (slope < -0.1% per bar)
     0 if flat
    """
    sma50 = _sma(close, 50)
    if np.isnan(sma50[-1]) or np.isnan(sma50[-11]):
        return 0, {"slope": None}

    current = sma50[-1]
    past = sma50[-11]
    slope_pct = (current - past) / past * 100

    if slope_pct > 1.0:
        return 1, {"slope_pct": round(slope_pct, 2), "direction": "rising"}
    elif slope_pct < -1.0:
        return -1, {"slope_pct": round(slope_pct, 2), "direction": "falling"}

    return 0, {"slope_pct": round(slope_pct, 2), "direction": "flat"}


def _sma200_distance(close: np.ndarray) -> tuple:
    """S6: Price distance from SMA 200.

    Mean-reversion signal for swing timeframe.
    +1 if price 2-8% above SMA200 (healthy uptrend, not extended)
    -1 if price 2-8% below SMA200 (healthy downtrend)
     0 if within 2% (near SMA) or >8% away (over-extended)
    """
    sma200 = _sma(close, 200)
    if np.isnan(sma200[-1]):
        return 0, {"distance_pct": None}

    dist_pct = (close[-1] - sma200[-1]) / sma200[-1] * 100

    if 2.0 <= dist_pct <= 8.0:
        return 1, {"distance_pct": round(dist_pct, 2), "zone": "healthy_uptrend"}
    elif -8.0 <= dist_pct <= -2.0:
        return -1, {"distance_pct": round(dist_pct, 2), "zone": "healthy_downtrend"}

    return 0, {"distance_pct": round(dist_pct, 2),
               "zone": "near_sma" if abs(dist_pct) < 2 else "over_extended"}


def _atr_percentile(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                    period: int = 14, lookback: int = 60) -> float:
    """ATR percentile over lookback period."""
    if len(close) < period + lookback:
        return 50.0

    # True range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )

    if len(tr) < period + lookback:
        return 50.0

    # Rolling ATR
    atrs = []
    for i in range(lookback):
        idx = -(lookback - i)
        window = tr[idx - period:idx] if idx < 0 else tr[idx - period:]
        if len(window) >= period:
            atrs.append(float(np.mean(window)))

    if not atrs:
        return 50.0

    current_atr = atrs[-1]
    pctl = sum(1 for a in atrs if a < current_atr) / len(atrs) * 100
    return round(pctl, 1)


def _score_to_label(score: int) -> str:
    """Map weighted score to directional label."""
    if score >= 5:
        return STRONG_BULLISH
    elif score >= 2:
        return LEAN_BULLISH
    elif score <= -5:
        return STRONG_BEARISH
    elif score <= -2:
        return LEAN_BEARISH
    return NEUTRAL
