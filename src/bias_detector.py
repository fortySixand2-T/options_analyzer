"""
Directional bias detector — Layer 2 of the signal architecture.

Computes a weighted directional score from 0-14 DTE signals:
    D1: EMA 9 vs EMA 21 (weight 2)
    D2: EMA 9 slope (3-bar) (weight 1)
    D3: RSI(14) 50-65 / 35-50 (weight 1)
    D4: RSI(14) extreme <30 bounce / >70 fade (weight 1)
    D5: MACD histogram positive+rising / negative+falling (weight 2)
    D6: MACD zero cross (weight 1)
    D7: Prior day candle close near high/low (weight 1)
    D8: 2-day momentum higher/lower close (weight 1)

ATR percentile modifies strategy selection (not directional).

Input:  pandas DataFrame of daily OHLCV
Output: BiasResult(label, score, detail)

See SIGNALS.md Layer 2 for full specification.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd


# ── Bias labels ──────────────────────────────────────────────────────────────

STRONG_BULLISH = "STRONG_BULLISH"
LEAN_BULLISH   = "LEAN_BULLISH"
NEUTRAL        = "NEUTRAL"
LEAN_BEARISH   = "LEAN_BEARISH"
STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class BiasResult:
    """Directional bias output."""
    label: str              # one of the 5 labels above
    score: int              # raw weighted score
    atr_percentile: float   # 0-100, used to modify strategy (trending vs ranging)
    detail: Dict[str, object] = field(default_factory=dict)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _macd(close: pd.Series):
    """Returns (macd_line, signal_line, histogram) as Series."""
    fast = _ema(close, 12)
    slow = _ema(close, 26)
    macd_line = fast - slow
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"] if "High" in df.columns else df["high"]
    low = df["Low"] if "Low" in df.columns else df["low"]
    close = df["Close"] if "Close" in df.columns else df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def detect_bias(df: pd.DataFrame) -> BiasResult:
    """Detect directional bias from daily OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        Daily OHLCV data with columns: Open, High, Low, Close, Volume.
        At least 30 rows recommended. Accepts either Title or lowercase column names.

    Returns
    -------
    BiasResult
    """
    # Normalize column names
    col_map = {}
    for col in df.columns:
        col_map[col.lower()] = col
    close_col = col_map.get("close", "Close")
    high_col = col_map.get("high", "High")
    low_col = col_map.get("low", "Low")

    close = df[close_col]
    high = df[high_col]
    low = df[low_col]

    if len(close) < 26:
        return BiasResult(label=NEUTRAL, score=0, atr_percentile=50.0,
                          detail={"error": "insufficient data"})

    score = 0
    detail: Dict[str, object] = {}

    # D1: EMA 9 vs EMA 21 (weight 2)
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema9_above = ema9.iloc[-1] > ema21.iloc[-1]
    detail["ema9_vs_ema21"] = "above" if ema9_above else "below"
    score += 2 if ema9_above else -2

    # D2: EMA 9 slope (3-bar) (weight 1)
    if len(ema9) >= 4:
        ema9_slope = ema9.iloc[-1] - ema9.iloc[-4]
        detail["ema9_slope"] = round(float(ema9_slope), 4)
        if ema9_slope > 0:
            score += 1
        elif ema9_slope < 0:
            score -= 1

    # D3: RSI(14) directional (weight 1)
    rsi_val = _rsi(close, 14)
    detail["rsi"] = round(rsi_val, 1)
    if 50 <= rsi_val <= 65:
        score += 1
    elif 35 <= rsi_val <= 50:
        score -= 1

    # D4: RSI(14) extreme (weight 1)
    if rsi_val < 30:
        score += 1   # oversold bounce
        detail["rsi_extreme"] = "oversold_bounce"
    elif rsi_val > 70:
        score -= 1   # overbought fade
        detail["rsi_extreme"] = "overbought_fade"

    # D5: MACD histogram (weight 2)
    macd_line, signal_line, histogram = _macd(close)
    hist_val = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2] if len(histogram) >= 2 else 0
    detail["macd_histogram"] = round(float(hist_val), 4)
    if hist_val > 0 and hist_val > hist_prev:
        score += 2   # positive and rising
    elif hist_val < 0 and hist_val < hist_prev:
        score -= 2   # negative and falling

    # D6: MACD zero cross (weight 1)
    if len(macd_line) >= 2:
        macd_now = macd_line.iloc[-1]
        macd_prev = macd_line.iloc[-2]
        sig_now = signal_line.iloc[-1]
        sig_prev = signal_line.iloc[-2]
        if macd_prev <= sig_prev and macd_now > sig_now:
            score += 1
            detail["macd_cross"] = "bullish"
        elif macd_prev >= sig_prev and macd_now < sig_now:
            score -= 1
            detail["macd_cross"] = "bearish"

    # D7: Prior day candle (weight 1)
    last_close = close.iloc[-1]
    last_high = high.iloc[-1]
    last_low = low.iloc[-1]
    candle_range = last_high - last_low
    if candle_range > 0:
        close_position = (last_close - last_low) / candle_range
        detail["candle_close_pct"] = round(float(close_position), 2)
        if close_position > 0.7:
            score += 1   # close near high
        elif close_position < 0.3:
            score -= 1   # close near low

    # D8: 2-day momentum (weight 1)
    if len(close) >= 3:
        if close.iloc[-1] > close.iloc[-3]:
            score += 1
            detail["two_day_momentum"] = "higher"
        elif close.iloc[-1] < close.iloc[-3]:
            score -= 1
            detail["two_day_momentum"] = "lower"

    # ATR percentile (not directional — modifies strategy choice)
    atr_series = _atr(df, 14)
    atr_vals = atr_series.dropna()
    if len(atr_vals) > 0:
        current_atr = atr_vals.iloc[-1]
        atr_pctl = float(np.sum(atr_vals < current_atr) / len(atr_vals) * 100)
    else:
        atr_pctl = 50.0
    detail["atr_percentile"] = round(atr_pctl, 1)

    # Classify
    if score >= 4:
        label = STRONG_BULLISH
    elif score >= 2:
        label = LEAN_BULLISH
    elif score <= -4:
        label = STRONG_BEARISH
    elif score <= -2:
        label = LEAN_BEARISH
    else:
        label = NEUTRAL

    detail["score"] = score

    return BiasResult(label=label, score=score, atr_percentile=atr_pctl,
                      detail=detail)
