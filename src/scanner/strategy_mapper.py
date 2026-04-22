"""
Strategy decision matrix — 3-input lookup from SIGNALS.md.

Maps (regime, bias, dealer_regime) → StrategyRecommendation.

Inputs:
    regime       — HIGH_IV, MODERATE_IV, LOW_IV, SPIKE
    bias         — STRONG_BULLISH, LEAN_BULLISH, NEUTRAL, LEAN_BEARISH, STRONG_BEARISH
    dealer_regime — LONG_GAMMA, SHORT_GAMMA, or None

Options Analytics Team — 2026-04
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyRecommendation:
    """Recommended trade structure from the decision matrix."""
    strategy: str           # e.g. "iron_condor", "short_put_spread"
    strategy_label: str
    rationale: str
    suggested_dte: tuple    # (min_dte, max_dte)
    risk_profile: str = "defined"
    edge_source: str = ""


# ── Decision matrix from SIGNALS.md ──────────────────────────────────────────

_MATRIX = {
    # (regime, bias, dealer_regime) → (strategy, label, dte_range, edge_source)
    # HIGH_IV regime — sell premium
    ("HIGH_IV", "NEUTRAL", "LONG_GAMMA"):
        ("iron_condor", "Iron Condor", (7, 14), "iv_overpriced"),
    ("HIGH_IV", "LEAN_BULLISH", None):
        ("short_put_spread", "Short Put Spread", (5, 10), "iv_overpriced"),
    ("HIGH_IV", "LEAN_BEARISH", None):
        ("short_call_spread", "Short Call Spread", (5, 10), "iv_overpriced"),
    ("HIGH_IV", "STRONG_BULLISH", None):
        ("short_put_spread", "Short Put Spread (tight)", (3, 7), "iv_overpriced"),
    ("HIGH_IV", "STRONG_BEARISH", None):
        ("short_call_spread", "Short Call Spread (tight)", (3, 7), "iv_overpriced"),

    # MODERATE_IV regime — either side
    ("MODERATE_IV", "NEUTRAL", "LONG_GAMMA"):
        ("butterfly", "Butterfly (max pain)", (3, 7), "pinning"),
    ("MODERATE_IV", "LEAN_BULLISH", None):
        ("long_call_spread", "Long Call Spread", (5, 14), "directional"),
    ("MODERATE_IV", "LEAN_BEARISH", None):
        ("long_put_spread", "Long Put Spread", (5, 14), "directional"),

    # LOW_IV regime — buy premium
    ("LOW_IV", "NEUTRAL", None):
        ("butterfly", "Butterfly (max pain)", (3, 7), "pinning"),
    ("LOW_IV", "LEAN_BULLISH", None):
        ("long_call_spread", "Long Call Spread", (5, 10), "iv_underpriced"),
    ("LOW_IV", "LEAN_BEARISH", None):
        ("long_put_spread", "Long Put Spread", (5, 10), "iv_underpriced"),
    ("LOW_IV", "STRONG_BULLISH", None):
        ("long_call_spread", "Long Call Spread (tight)", (3, 5), "iv_underpriced"),
    ("LOW_IV", "STRONG_BEARISH", None):
        ("long_put_spread", "Long Put Spread (tight)", (3, 5), "iv_underpriced"),

    # SPIKE — small debit only
    ("SPIKE", None, None):
        ("long_call_spread", "Small Debit Spread", (3, 5), "spike_debit"),
}


def map_strategy(
    regime: str,
    bias: str,
    dealer_regime: Optional[str] = None,
) -> Optional[StrategyRecommendation]:
    """Look up strategy from the 3-input decision matrix.

    Parameters
    ----------
    regime : str
        One of HIGH_IV, MODERATE_IV, LOW_IV, SPIKE.
    bias : str
        One of STRONG_BULLISH, LEAN_BULLISH, NEUTRAL, LEAN_BEARISH, STRONG_BEARISH.
    dealer_regime : str, optional
        LONG_GAMMA or SHORT_GAMMA (None if unavailable).

    Returns
    -------
    StrategyRecommendation or None if no match.
    """
    # Override rules from SIGNALS.md
    if dealer_regime == "SHORT_GAMMA" and regime == "HIGH_IV" and bias == "NEUTRAL":
        # SHORT_GAMMA → never sell iron condor. Switch to directional or stand aside.
        return None

    # SPIKE: small debit or stand aside regardless of bias
    if regime == "SPIKE":
        entry = _MATRIX.get(("SPIKE", None, None))
        if entry:
            strategy, label, dte, edge = entry
            return StrategyRecommendation(
                strategy=strategy,
                strategy_label=label,
                rationale=f"SPIKE regime — small debit only or stand aside",
                suggested_dte=dte,
                edge_source=edge,
            )
        return None

    # Try exact match with dealer regime
    key = (regime, bias, dealer_regime)
    entry = _MATRIX.get(key)

    # Fall back to None dealer (matches any)
    if entry is None:
        key = (regime, bias, None)
        entry = _MATRIX.get(key)

    # Collapse STRONG → LEAN for lookup
    if entry is None and "STRONG" in bias:
        lean_bias = bias.replace("STRONG", "LEAN")
        key = (regime, lean_bias, dealer_regime)
        entry = _MATRIX.get(key)
        if entry is None:
            key = (regime, lean_bias, None)
            entry = _MATRIX.get(key)

    if entry is None:
        return None

    strategy, label, dte, edge = entry
    return StrategyRecommendation(
        strategy=strategy,
        strategy_label=label,
        rationale=_build_rationale(regime, bias, dealer_regime, label),
        suggested_dte=dte,
        edge_source=edge,
    )


def _build_rationale(regime: str, bias: str, dealer: Optional[str], label: str) -> str:
    parts = [f"Regime: {regime}", f"Bias: {bias}"]
    if dealer:
        parts.append(f"Dealer: {dealer}")
    parts.append(f"→ {label}")
    return " | ".join(parts)


# Backward compat: old map_signal interface
def map_signal(signal) -> Optional[StrategyRecommendation]:
    """Legacy mapper — maps from OptionSignal using iv_regime as regime.

    For full 3-input lookup, use map_strategy() directly.
    """
    if signal.conviction < 30:
        return None

    regime = signal.iv_regime
    # Infer bias from direction
    if signal.direction == "SELL":
        bias = "NEUTRAL"
    elif signal.option_type == "call":
        bias = "LEAN_BULLISH"
    else:
        bias = "LEAN_BEARISH"

    return map_strategy(regime, bias)
