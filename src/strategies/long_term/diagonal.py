"""Long-term LEAPS diagonal (90-180 DTE).

Directional + time-decay edge over quarters. Flow signal and cross-asset
alignment are weighted higher than VRP at this horizon.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


def _strike_inc(spot: float) -> float:
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


class LongTermDiagonal(StrategyDefinition):
    @property
    def name(self) -> str:
        return "lt_diagonal_spread"

    @property
    def label(self) -> str:
        return "LEAPS Diagonal (90-180 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (90, 180)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (20.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        flow_signal = getattr(signal, "flow_signal", None) or "NEUTRAL"
        cross_signal = getattr(signal, "cross_asset_signal", None) or "ALIGNED"

        return [
            SignalCheck("Flow aligns with direction",
                        flow_signal != "NEUTRAL",
                        flow_signal, weight=2.5),
            SignalCheck("Cross-asset not adverse",
                        cross_signal != "EQUITY_VOL_RICH",
                        cross_signal, weight=2.0),
            SignalCheck("VRP regime RICH or NEUTRAL",
                        vrp_regime in ("RICH", "NEUTRAL"),
                        vrp_regime, weight=2.0),
            SignalCheck("IV rank > 25%", signal.iv_rank > 25,
                        f"{signal.iv_rank:.0f}%", weight=1.5),
            SignalCheck("Directional SELL", signal.direction == "SELL",
                        signal.direction, weight=1.5),
            SignalCheck("Delta 0.15-0.40", 0.15 <= abs(signal.delta) <= 0.40,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 90-165", 90 <= signal.dte <= 165,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        opt_type = signal.option_type
        if opt_type == "call":
            return [
                {"action": "sell", "option_type": "call", "strike": signal.strike,
                 "note": "front_month"},
                {"action": "buy", "option_type": "call", "strike": signal.strike + w,
                 "note": "back_month_leaps"},
            ]
        return [
            {"action": "sell", "option_type": "put", "strike": signal.strike,
             "note": "front_month"},
            {"action": "buy", "option_type": "put", "strike": signal.strike - w,
             "note": "back_month_leaps"},
        ]
