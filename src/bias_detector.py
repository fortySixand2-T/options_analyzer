"""
Determines directional bias from TA signals.
Returns one of four labels used by strategy_selector.

Unchanged from standalone options_scanner — no external dependencies.
"""
from typing import Any, Dict, Tuple

BULLISH          = "bullish"
BEARISH          = "bearish"
NEUTRAL_HIGH_IV  = "neutral_high_iv"
NEUTRAL_LOW_IV   = "neutral_low_iv"


def detect_bias(signals: Dict[str, Any]) -> Tuple[str, int, Dict[str, Any]]:
    """
    Returns (bias_label, net_score, detail).

    Scoring:
      Each bullish condition adds +1; each bearish condition adds -1.
      |score| >= BIAS_THRESHOLD  → directional
      |score| <  BIAS_THRESHOLD  → neutral; IV regime decides sub-label
    """
    trend    = signals["trend"]
    momentum = signals["momentum"]
    vol      = signals["volatility"]

    score  = 0
    detail: Dict[str, Any] = {}

    # ── Trend (5 signals) ──────────────────────────────────────────────────
    score += 1 if trend["above_sma20"]        else -1
    score += 1 if trend["above_sma50"]        else -1
    score += 1 if trend["above_sma200"]       else -1
    score += 1 if trend["sma20_above_sma50"]  else -1
    score += 1 if trend["sma50_above_sma200"] else -1

    if trend["golden_cross"]: score += 2   # strong confirmation
    if trend["death_cross"]:  score -= 2

    # ── Momentum (RSI, MACD, Stochastic) ─────────────────────────────────
    rsi = momentum["rsi"]
    if   rsi > 60:  score += 1
    elif rsi < 40:  score -= 1
    if   rsi > 70:  score -= 1   # overbought penalty
    if   rsi < 30:  score += 1   # oversold bounce potential

    score += 1 if momentum["macd_bullish"]  else -1
    if momentum["macd_crossover"]:  score += 2
    if momentum["macd_crossunder"]: score -= 2

    if momentum["stoch_oversold"]:   score += 1
    if momentum["stoch_overbought"]: score -= 1

    detail.update({
        "rsi":          rsi,
        "macd_bullish": momentum["macd_bullish"],
        "score":        score,
    })

    # ── Classify ──────────────────────────────────────────────────────────
    THRESHOLD = 3

    if score >= THRESHOLD:
        return BULLISH, score, detail

    if score <= -THRESHOLD:
        return BEARISH, score, detail

    # Neutral: choose sub-label based on IV regime
    high_iv = vol["atr_percentile"] >= 50 or vol["bb_squeeze"]
    label   = NEUTRAL_HIGH_IV if high_iv else NEUTRAL_LOW_IV
    return label, score, detail
