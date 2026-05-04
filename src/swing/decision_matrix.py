"""Swing decision matrix — maps multi-signal state to swing strategy.

5-input lookup: (regime, swing_bias, dealer, vrp_signal, term_structure_signal)
→ SwingStrategyRecommendation.

Unlike the short-DTE matrix (3 inputs), swing adds VRP and term structure
because those edges dominate at 14-60 DTE.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SwingRecommendation:
    strategy: str
    strategy_label: str
    rationale: str
    suggested_dte: tuple
    risk_profile: str = "defined"
    edge_source: str = ""


def map_swing_strategy(
    regime: str,
    swing_bias: str,
    dealer_regime: Optional[str],
    vrp_rich: bool,
    vrp_pct: float,
    calendar_signal: float,
    in_earnings_window: bool,
    earnings_iv_inflation: float,
) -> Optional[SwingRecommendation]:
    """Select a swing strategy from the multi-signal state.

    Parameters
    ----------
    regime : str
        HIGH_IV, MODERATE_IV, LOW_IV, SPIKE
    swing_bias : str
        STRONG_BULLISH, LEAN_BULLISH, NEUTRAL, LEAN_BEARISH, STRONG_BEARISH
    dealer_regime : str or None
        LONG_GAMMA, SHORT_GAMMA, or None
    vrp_rich : bool
        True if VRP > 0 (options overpriced vs realized vol)
    vrp_pct : float
        VRP as % of IV (higher = richer premium)
    calendar_signal : float
        -1 to +1 from term structure analysis (positive = sell front, buy back)
    in_earnings_window : bool
        True if earnings within 10 days
    earnings_iv_inflation : float
        0-1 score of how inflated IV is pre-earnings
    """
    # SPIKE: stand aside for swing — short-DTE debit only
    if regime == "SPIKE":
        return None

    # Earnings window: long straddle if IV is cheap relative to expected move
    if in_earnings_window and earnings_iv_inflation < 0.5:
        return SwingRecommendation(
            strategy="long_straddle",
            strategy_label="Long Straddle (pre-earnings)",
            rationale=f"Earnings pending, IV inflation low ({earnings_iv_inflation:.0%})",
            suggested_dte=(14, 45),
            edge_source="earnings_vol",
        )

    # Earnings window but IV already inflated: avoid vol-buying strategies
    if in_earnings_window and earnings_iv_inflation >= 0.5:
        # If VRP is rich, sell the inflated vol via iron butterfly
        if vrp_rich and vrp_pct > 5.0 and regime == "HIGH_IV":
            return SwingRecommendation(
                strategy="iron_butterfly",
                strategy_label="Iron Butterfly (earnings crush)",
                rationale=f"Earnings IV inflated ({earnings_iv_inflation:.0%}), VRP rich ({vrp_pct:.1f}%)",
                suggested_dte=(21, 45),
                edge_source="vrp_earnings_crush",
            )
        return None

    # HIGH_IV + VRP rich: premium selling strategies
    if regime == "HIGH_IV" and vrp_rich and vrp_pct > 3.0:
        # Calendar if term structure is favorable
        if calendar_signal > 0.2:
            return SwingRecommendation(
                strategy="calendar_spread",
                strategy_label="Calendar Spread",
                rationale=f"HIGH_IV, VRP {vrp_pct:.1f}%, calendar signal {calendar_signal:+.2f}",
                suggested_dte=(25, 50),
                edge_source="vrp_term_structure",
            )

        # Neutral + range-bound: iron butterfly for max VRP harvest
        if swing_bias == "NEUTRAL" and dealer_regime == "LONG_GAMMA":
            return SwingRecommendation(
                strategy="iron_butterfly",
                strategy_label="Iron Butterfly",
                rationale=f"HIGH_IV neutral, VRP {vrp_pct:.1f}%, LONG_GAMMA pinning",
                suggested_dte=(30, 45),
                edge_source="vrp_pinning",
            )

        # Directional lean: diagonal spread
        if swing_bias in ("LEAN_BULLISH", "LEAN_BEARISH", "STRONG_BULLISH", "STRONG_BEARISH"):
            return SwingRecommendation(
                strategy="diagonal_spread",
                strategy_label="Diagonal Spread",
                rationale=f"HIGH_IV directional ({swing_bias}), VRP {vrp_pct:.1f}%",
                suggested_dte=(25, 50),
                edge_source="vrp_directional",
            )

        # Fallback: iron butterfly (VRP is the primary edge)
        return SwingRecommendation(
            strategy="iron_butterfly",
            strategy_label="Iron Butterfly",
            rationale=f"HIGH_IV, VRP {vrp_pct:.1f}% — harvest premium",
            suggested_dte=(30, 45),
            edge_source="vrp",
        )

    # MODERATE_IV: calendar/diagonal if structure supports it
    if regime == "MODERATE_IV":
        if calendar_signal > 0.3 and vrp_rich:
            return SwingRecommendation(
                strategy="calendar_spread",
                strategy_label="Calendar Spread",
                rationale=f"MODERATE_IV, calendar signal {calendar_signal:+.2f}, VRP {vrp_pct:.1f}%",
                suggested_dte=(25, 50),
                edge_source="term_structure",
            )

        if swing_bias in ("LEAN_BULLISH", "LEAN_BEARISH") and vrp_rich:
            return SwingRecommendation(
                strategy="diagonal_spread",
                strategy_label="Diagonal Spread",
                rationale=f"MODERATE_IV directional ({swing_bias}), VRP {vrp_pct:.1f}%",
                suggested_dte=(25, 50),
                edge_source="vrp_directional",
            )

        # No strong edge at moderate IV without VRP or structure signal
        return None

    # LOW_IV: buy vol — straddle or nothing
    if regime == "LOW_IV":
        if swing_bias == "NEUTRAL":
            return SwingRecommendation(
                strategy="long_straddle",
                strategy_label="Long Straddle",
                rationale="LOW_IV neutral — buy cheap vol for expansion",
                suggested_dte=(21, 45),
                edge_source="iv_underpriced",
            )
        # Directional at low IV: no swing edge (short-DTE debit spreads are better)
        return None

    return None


def _build_rationale_parts(regime, bias, dealer, vrp_pct, calendar_signal):
    parts = [f"Regime: {regime}", f"Bias: {bias}"]
    if dealer:
        parts.append(f"Dealer: {dealer}")
    parts.append(f"VRP: {vrp_pct:.1f}%")
    if abs(calendar_signal) > 0.1:
        parts.append(f"Calendar: {calendar_signal:+.2f}")
    return " | ".join(parts)
