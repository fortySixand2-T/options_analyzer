"""Medium-term diagonal spread (30-90 DTE).

Calendar edge + directional lean. VRP regime + flow signal in checklist.
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


class MediumTermDiagonal(StrategyDefinition):
    @property
    def name(self) -> str:
        return "mt_diagonal_spread"

    @property
    def label(self) -> str:
        return "Diagonal Spread (30-90 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (30, 90)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (25.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        flow_signal = getattr(signal, "flow_signal", None) or "NEUTRAL"

        return [
            SignalCheck("VRP regime RICH", vrp_regime == "RICH",
                        vrp_regime, weight=2.5),
            SignalCheck("IV rank > 30%", signal.iv_rank > 30,
                        f"{signal.iv_rank:.0f}%", weight=1.5),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=1.5),
            SignalCheck("Directional SELL", signal.direction == "SELL",
                        signal.direction, weight=2.0),
            SignalCheck("Flow aligns", flow_signal != "NEUTRAL",
                        flow_signal, weight=1.5),
            SignalCheck("Delta 0.15-0.45", 0.15 <= abs(signal.delta) <= 0.45,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 30-80", 30 <= signal.dte <= 80,
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
                 "note": "back_month"},
            ]
        return [
            {"action": "sell", "option_type": "put", "strike": signal.strike,
             "note": "front_month"},
            {"action": "buy", "option_type": "put", "strike": signal.strike - w,
             "note": "back_month"},
        ]
