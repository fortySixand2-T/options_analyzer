"""
Strategy template mapper for chain scanner signals.

Maps (iv_regime, direction, option_type, delta) → StrategyRecommendation.
Does NOT price legs — just recommends the structure, strikes, and DTE.
Pricing happens downstream if the user clicks through.

Options Analytics Team — 2026-04
"""

from dataclasses import dataclass
from typing import Optional

from . import OptionSignal


@dataclass
class StrategyRecommendation:
    """Recommended trade structure for a scanned signal."""
    strategy: str           # e.g. "short_put_spread", "long_straddle"
    strategy_label: str     # Human-readable: "Short Put Spread"
    rationale: str          # Why this structure fits the signal
    legs: list[dict]        # [{"action": "buy"|"sell", "option_type": ..., "strike_method": ...}]
    suggested_dte: int      # Recommended DTE for this structure
    risk_profile: str       # "defined" or "undefined"
    max_risk_method: str    # How to compute max risk: "spread_width", "premium_paid", "unlimited"
    edge_source: str        # "iv_overpriced", "iv_underpriced", "directional"


def map_signal(signal: OptionSignal) -> Optional[StrategyRecommendation]:
    """Map a chain scanner signal to a strategy recommendation.

    Returns None if no high-conviction mapping exists (e.g. NORMAL regime
    + SELL direction has no edge).
    """
    if signal.conviction < 30:
        return None

    regime = signal.iv_regime
    direction = signal.direction
    opt_type = signal.option_type
    delta = signal.delta

    if regime == "HIGH":
        return _map_high(signal, direction, opt_type, delta)
    if regime == "ELEVATED":
        return _map_elevated(signal, direction, opt_type, delta)
    if regime == "NORMAL":
        return _map_normal(signal, direction, opt_type, delta)
    if regime == "LOW":
        return _map_low(signal, direction, opt_type, delta)

    return None


def _map_high(signal, direction, opt_type, delta):
    if direction == "BUY":
        return None  # don't buy expensive vol

    # SELL in HIGH regime
    if abs(delta) < 0.20:
        return StrategyRecommendation(
            strategy="iron_condor",
            strategy_label="Iron Condor",
            rationale=f"IV rank {signal.iv_rank:.0f}% — vol is elevated across the chain. "
                      f"Near-neutral delta ({delta:+.2f}) suggests range-bound. "
                      f"Sell premium on both sides with defined risk.",
            legs=[
                {"action": "sell", "option_type": "call", "strike_method": "otm_1"},
                {"action": "buy", "option_type": "call", "strike_method": "otm_2"},
                {"action": "sell", "option_type": "put", "strike_method": "otm_1"},
                {"action": "buy", "option_type": "put", "strike_method": "otm_2"},
            ],
            suggested_dte=35,
            risk_profile="defined",
            max_risk_method="spread_width",
            edge_source="iv_overpriced",
        )

    if opt_type == "put":
        return StrategyRecommendation(
            strategy="short_put_spread",
            strategy_label="Short Put Spread",
            rationale=f"IV rank {signal.iv_rank:.0f}% — premium is rich. "
                      f"Sell the flagged put, buy protection one strike below.",
            legs=[
                {"action": "sell", "option_type": "put", "strike_method": "signal_strike"},
                {"action": "buy", "option_type": "put", "strike_method": "signal_strike - width"},
            ],
            suggested_dte=35,
            risk_profile="defined",
            max_risk_method="spread_width",
            edge_source="iv_overpriced",
        )

    # call
    return StrategyRecommendation(
        strategy="short_call_spread",
        strategy_label="Short Call Spread",
        rationale=f"IV rank {signal.iv_rank:.0f}% — premium is rich. "
                  f"Sell the flagged call, buy protection one strike above.",
        legs=[
            {"action": "sell", "option_type": "call", "strike_method": "signal_strike"},
            {"action": "buy", "option_type": "call", "strike_method": "signal_strike + width"},
        ],
        suggested_dte=35,
        risk_profile="defined",
        max_risk_method="spread_width",
        edge_source="iv_overpriced",
    )


def _map_elevated(signal, direction, opt_type, delta):
    if direction == "BUY":
        return StrategyRecommendation(
            strategy="calendar_spread",
            strategy_label="Calendar Spread",
            rationale=f"IV rank {signal.iv_rank:.0f}% — front-month vol is elevated relative to back. "
                      f"Buy the back-month {opt_type}, sell the front-month to capture term structure.",
            legs=[
                {"action": "sell", "option_type": opt_type, "strike_method": "atm"},
                {"action": "buy", "option_type": opt_type, "strike_method": "atm"},
            ],
            suggested_dte=45,
            risk_profile="defined",
            max_risk_method="premium_paid",
            edge_source="iv_overpriced",
        )

    # SELL in ELEVATED regime — narrower spreads than HIGH
    if opt_type == "put":
        return StrategyRecommendation(
            strategy="short_put_spread",
            strategy_label="Short Put Spread",
            rationale=f"IV rank {signal.iv_rank:.0f}% — moderately elevated premium. "
                      f"Sell the flagged put with a tighter spread for defined risk.",
            legs=[
                {"action": "sell", "option_type": "put", "strike_method": "signal_strike"},
                {"action": "buy", "option_type": "put", "strike_method": "signal_strike - width"},
            ],
            suggested_dte=35,
            risk_profile="defined",
            max_risk_method="spread_width",
            edge_source="iv_overpriced",
        )

    return StrategyRecommendation(
        strategy="short_call_spread",
        strategy_label="Short Call Spread",
        rationale=f"IV rank {signal.iv_rank:.0f}% — moderately elevated premium. "
                  f"Sell the flagged call with a tighter spread for defined risk.",
        legs=[
            {"action": "sell", "option_type": "call", "strike_method": "signal_strike"},
            {"action": "buy", "option_type": "call", "strike_method": "signal_strike + width"},
        ],
        suggested_dte=35,
        risk_profile="defined",
        max_risk_method="spread_width",
        edge_source="iv_overpriced",
    )


def _map_normal(signal, direction, opt_type, delta):
    if direction == "SELL":
        return None  # not enough premium to sell

    # BUY in NORMAL regime — directional play
    if opt_type == "call":
        return StrategyRecommendation(
            strategy="long_call",
            strategy_label="Long Call",
            rationale=f"IV is fairly priced (rank {signal.iv_rank:.0f}%). "
                      f"Edge is {signal.edge_pct:+.1f}% — ride the directional move with a long call.",
            legs=[
                {"action": "buy", "option_type": "call", "strike_method": "signal_strike"},
            ],
            suggested_dte=signal.dte,
            risk_profile="defined",
            max_risk_method="premium_paid",
            edge_source="directional",
        )

    return StrategyRecommendation(
        strategy="long_put",
        strategy_label="Long Put",
        rationale=f"IV is fairly priced (rank {signal.iv_rank:.0f}%). "
                  f"Edge is {signal.edge_pct:+.1f}% — ride the directional move with a long put.",
        legs=[
            {"action": "buy", "option_type": "put", "strike_method": "signal_strike"},
        ],
        suggested_dte=signal.dte,
        risk_profile="defined",
        max_risk_method="premium_paid",
        edge_source="directional",
    )


def _map_low(signal, direction, opt_type, delta):
    if direction == "SELL":
        return None  # selling cheap vol has no edge

    # BUY in LOW regime
    if abs(delta) < 0.25:
        return StrategyRecommendation(
            strategy="long_straddle",
            strategy_label="Long Straddle",
            rationale=f"IV rank {signal.iv_rank:.0f}% — vol is cheap. "
                      f"Near-neutral delta ({delta:+.2f}) suggests buy both sides for vol expansion.",
            legs=[
                {"action": "buy", "option_type": "call", "strike_method": "atm"},
                {"action": "buy", "option_type": "put", "strike_method": "atm"},
            ],
            suggested_dte=50,
            risk_profile="defined",
            max_risk_method="premium_paid",
            edge_source="iv_underpriced",
        )

    if opt_type == "call":
        return StrategyRecommendation(
            strategy="long_call",
            strategy_label="Long Call",
            rationale=f"IV rank {signal.iv_rank:.0f}% — options are cheap. "
                      f"Directional long call with capped risk.",
            legs=[
                {"action": "buy", "option_type": "call", "strike_method": "signal_strike"},
            ],
            suggested_dte=signal.dte,
            risk_profile="defined",
            max_risk_method="premium_paid",
            edge_source="iv_underpriced",
        )

    return StrategyRecommendation(
        strategy="long_put",
        strategy_label="Long Put",
        rationale=f"IV rank {signal.iv_rank:.0f}% — options are cheap. "
                  f"Directional long put with capped risk.",
        legs=[
            {"action": "buy", "option_type": "put", "strike_method": "signal_strike"},
        ],
        suggested_dte=signal.dte,
        risk_profile="defined",
        max_risk_method="premium_paid",
        edge_source="iv_underpriced",
    )
