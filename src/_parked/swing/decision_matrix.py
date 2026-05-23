"""Decision matrix — maps multi-signal state to strategy recommendation.

Swing (14-60 DTE): 5-input lookup — regime, bias, dealer, VRP, term structure.
Medium-term (30-90 DTE): adds skew, cross-asset, flow signals.
Long-term (90-180 DTE): cross-asset and correlation premium dominate.

The medium/long-term matrix uses VRP regime (RICH/NEUTRAL/CHEAP) from the
upgraded VRP module with Yang-Zhang realized vol.
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


@dataclass
class MediumTermRecommendation:
    strategy: str
    strategy_label: str
    rationale: str
    suggested_dte: tuple
    risk_profile: str = "defined"
    edge_source: str = ""
    position_size_factor: float = 1.0


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


# ── Medium-term matrix (30-90 DTE) ────────────────────────────────────


def map_medium_term_strategy(
    regime: str,
    swing_bias: str,
    dealer_regime: Optional[str],
    vrp_regime: str,
    vrp_pct: float,
    calendar_signal: float,
    skew_regime: str,
    cross_asset_signal: str,
    flow_signal: str,
    vvix_size_factor: float,
    in_earnings_window: bool,
    earnings_iv_inflation: float,
) -> Optional[MediumTermRecommendation]:
    """Select strategy for 30-90 DTE options.

    Parameters
    ----------
    regime : str
        HIGH_IV, MODERATE_IV, LOW_IV, SPIKE
    swing_bias : str
        STRONG_BULLISH..STRONG_BEARISH
    dealer_regime : str or None
        LONG_GAMMA, SHORT_GAMMA
    vrp_regime : str
        RICH, NEUTRAL, CHEAP (from VRPRegime)
    vrp_pct : float
        VRP as % of IV
    calendar_signal : float
        -1 to +1 from term structure
    skew_regime : str
        STEEP, NORMAL, FLAT, INVERTED (from SkewRegime)
    cross_asset_signal : str
        ALIGNED, EQUITY_VOL_CHEAP, EQUITY_VOL_RICH (from CrossAssetSignal)
    flow_signal : str
        BULLISH, BEARISH, NEUTRAL (from FlowSignal)
    vvix_size_factor : float
        0.25-1.0 position sizing from VVIX signal
    in_earnings_window : bool
        Earnings within 10 days
    earnings_iv_inflation : float
        0-1 inflation score
    """
    if regime == "SPIKE":
        return None

    # Earnings: sell inflated vol if VRP rich, else avoid
    if in_earnings_window:
        if vrp_regime == "RICH" and earnings_iv_inflation >= 0.5 and regime == "HIGH_IV":
            return MediumTermRecommendation(
                strategy="iron_butterfly",
                strategy_label="Iron Butterfly (earnings crush)",
                rationale=f"Earnings IV inflated ({earnings_iv_inflation:.0%}), VRP {vrp_regime}",
                suggested_dte=(30, 60),
                edge_source="vrp_earnings_crush",
                position_size_factor=vvix_size_factor * 0.75,
            )
        return None

    # EQUITY_VOL_CHEAP from cross-asset: buy premium at 60-90 DTE
    if cross_asset_signal == "EQUITY_VOL_CHEAP" and vrp_regime != "RICH":
        return MediumTermRecommendation(
            strategy="long_straddle",
            strategy_label="Long Straddle (cross-asset divergence)",
            rationale=f"MOVE/VIX divergence — equity vol underpriced, skew {skew_regime}",
            suggested_dte=(60, 90),
            edge_source="cross_asset_divergence",
            position_size_factor=vvix_size_factor,
        )

    # HIGH_IV + RICH VRP: premium selling
    if regime == "HIGH_IV" and vrp_regime == "RICH":
        # Steep skew → avoid naked short puts, favor spreads or calendars
        if skew_regime == "STEEP":
            if calendar_signal > 0.2:
                return MediumTermRecommendation(
                    strategy="calendar_spread",
                    strategy_label="Calendar Spread (steep skew)",
                    rationale=f"HIGH_IV, VRP {vrp_pct:.1f}%, steep skew, calendar {calendar_signal:+.2f}",
                    suggested_dte=(30, 60),
                    edge_source="vrp_term_structure_skew",
                    position_size_factor=vvix_size_factor,
                )
            return MediumTermRecommendation(
                strategy="iron_butterfly",
                strategy_label="Iron Butterfly (defined risk, steep skew)",
                rationale=f"HIGH_IV, VRP {vrp_pct:.1f}%, steep skew limits put credit strategy",
                suggested_dte=(30, 60),
                edge_source="vrp",
                position_size_factor=vvix_size_factor * 0.75,
            )

        # Flow bullish + directional bias: diagonal
        if flow_signal == "BULLISH" and swing_bias in ("LEAN_BULLISH", "STRONG_BULLISH"):
            return MediumTermRecommendation(
                strategy="diagonal_spread",
                strategy_label="Bull Diagonal (flow-confirmed)",
                rationale=f"HIGH_IV VRP {vrp_pct:.1f}%, bullish flow + bias",
                suggested_dte=(30, 60),
                edge_source="vrp_flow_directional",
                position_size_factor=vvix_size_factor,
            )

        if flow_signal == "BEARISH" and swing_bias in ("LEAN_BEARISH", "STRONG_BEARISH"):
            return MediumTermRecommendation(
                strategy="diagonal_spread",
                strategy_label="Bear Diagonal (flow-confirmed)",
                rationale=f"HIGH_IV VRP {vrp_pct:.1f}%, bearish flow + bias",
                suggested_dte=(30, 60),
                edge_source="vrp_flow_directional",
                position_size_factor=vvix_size_factor,
            )

        # Calendar if term structure favorable
        if calendar_signal > 0.2:
            return MediumTermRecommendation(
                strategy="calendar_spread",
                strategy_label="Calendar Spread",
                rationale=f"HIGH_IV, VRP {vrp_pct:.1f}%, calendar {calendar_signal:+.2f}",
                suggested_dte=(30, 60),
                edge_source="vrp_term_structure",
                position_size_factor=vvix_size_factor,
            )

        # Default HIGH_IV RICH: iron butterfly
        return MediumTermRecommendation(
            strategy="iron_butterfly",
            strategy_label="Iron Butterfly",
            rationale=f"HIGH_IV, VRP {vrp_pct:.1f}% — harvest premium",
            suggested_dte=(30, 60),
            edge_source="vrp",
            position_size_factor=vvix_size_factor,
        )

    # MODERATE_IV: need supporting signals
    if regime == "MODERATE_IV":
        if vrp_regime == "RICH" and calendar_signal > 0.3:
            return MediumTermRecommendation(
                strategy="calendar_spread",
                strategy_label="Calendar Spread",
                rationale=f"MODERATE_IV, VRP {vrp_pct:.1f}%, calendar {calendar_signal:+.2f}",
                suggested_dte=(30, 60),
                edge_source="term_structure",
                position_size_factor=vvix_size_factor,
            )

        if vrp_regime == "RICH" and swing_bias in ("LEAN_BULLISH", "LEAN_BEARISH"):
            return MediumTermRecommendation(
                strategy="diagonal_spread",
                strategy_label="Diagonal Spread",
                rationale=f"MODERATE_IV directional ({swing_bias}), VRP {vrp_pct:.1f}%",
                suggested_dte=(30, 60),
                edge_source="vrp_directional",
                position_size_factor=vvix_size_factor,
            )

        # Flat skew at moderate IV: potential vol expansion
        if skew_regime in ("FLAT", "INVERTED") and vrp_regime == "CHEAP":
            return MediumTermRecommendation(
                strategy="long_straddle",
                strategy_label="Long Straddle (flat skew, cheap vol)",
                rationale=f"MODERATE_IV, flat skew, VRP cheap — vol expansion play",
                suggested_dte=(45, 75),
                edge_source="skew_vrp_cheap",
                position_size_factor=vvix_size_factor,
            )

        return None

    # LOW_IV: buy premium
    if regime == "LOW_IV":
        if vrp_regime == "CHEAP":
            return MediumTermRecommendation(
                strategy="long_straddle",
                strategy_label="Long Straddle",
                rationale="LOW_IV + CHEAP VRP — buy vol for expansion",
                suggested_dte=(45, 90),
                edge_source="iv_underpriced",
                position_size_factor=vvix_size_factor,
            )

        if skew_regime == "FLAT" and flow_signal == "BULLISH":
            return MediumTermRecommendation(
                strategy="long_straddle",
                strategy_label="Long Straddle (flow-supported)",
                rationale="LOW_IV, flat skew, bullish flow",
                suggested_dte=(45, 90),
                edge_source="skew_flow",
                position_size_factor=vvix_size_factor,
            )

        return None

    return None


# ── Long-term matrix (90-180 DTE) ─────────────────────────────────────


def map_long_term_strategy(
    regime: str,
    swing_bias: str,
    vrp_regime: str,
    vrp_pct: float,
    skew_regime: str,
    cross_asset_signal: str,
    flow_signal: str,
    vvix_size_factor: float,
    correlation_premium: Optional[float] = None,
) -> Optional[MediumTermRecommendation]:
    """Select strategy for 90-180 DTE options.

    At this horizon, cross-asset signals and correlation premium dominate.
    VRP is still relevant but slower-moving.
    """
    if regime == "SPIKE":
        return None

    # Correlation premium: dispersion trade (sell index vol, buy singles)
    if correlation_premium is not None and correlation_premium > 0.05:
        return MediumTermRecommendation(
            strategy="iron_butterfly",
            strategy_label="Iron Butterfly (correlation premium)",
            rationale=f"Corr premium {correlation_premium:.1%} — sell index vol at 90+ DTE",
            suggested_dte=(90, 120),
            edge_source="correlation_premium",
            position_size_factor=vvix_size_factor,
        )

    # Cross-asset divergence: buy cheap equity vol
    if cross_asset_signal == "EQUITY_VOL_CHEAP" and vrp_regime != "RICH":
        return MediumTermRecommendation(
            strategy="long_straddle",
            strategy_label="Long Straddle (MOVE/VIX divergence)",
            rationale="Equity vol cheap vs bond vol — buy at 90-180 DTE",
            suggested_dte=(90, 150),
            edge_source="cross_asset",
            position_size_factor=vvix_size_factor,
        )

    # RICH VRP at long horizon: calendar or diagonal
    if vrp_regime == "RICH" and regime == "HIGH_IV":
        if swing_bias in ("LEAN_BULLISH", "LEAN_BEARISH", "STRONG_BULLISH", "STRONG_BEARISH"):
            return MediumTermRecommendation(
                strategy="diagonal_spread",
                strategy_label="LEAPS Diagonal",
                rationale=f"HIGH_IV, VRP {vrp_pct:.1f}%, directional ({swing_bias})",
                suggested_dte=(90, 180),
                edge_source="vrp_directional_leaps",
                position_size_factor=vvix_size_factor,
            )
        return MediumTermRecommendation(
            strategy="calendar_spread",
            strategy_label="Calendar Spread (long-dated)",
            rationale=f"HIGH_IV, VRP {vrp_pct:.1f}% — sell near, buy far",
            suggested_dte=(90, 150),
            edge_source="vrp_long",
            position_size_factor=vvix_size_factor,
        )

    # CHEAP VRP at long horizon: vol is underpriced
    if vrp_regime == "CHEAP" and skew_regime in ("FLAT", "INVERTED"):
        return MediumTermRecommendation(
            strategy="long_straddle",
            strategy_label="Long Straddle (LEAPS)",
            rationale="Cheap VRP + flat skew — vol expansion at 90+ DTE",
            suggested_dte=(90, 180),
            edge_source="vrp_cheap_leaps",
            position_size_factor=vvix_size_factor,
        )

    # Flow-driven at long horizon
    if flow_signal == "BULLISH" and swing_bias in ("LEAN_BULLISH", "STRONG_BULLISH"):
        return MediumTermRecommendation(
            strategy="diagonal_spread",
            strategy_label="Bull Diagonal (LEAPS)",
            rationale="Bullish flow + bias confirmed at long horizon",
            suggested_dte=(90, 180),
            edge_source="flow_directional_leaps",
            position_size_factor=vvix_size_factor * 0.75,
        )

    return None
