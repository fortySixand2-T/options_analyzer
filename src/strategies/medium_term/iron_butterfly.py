"""Medium-term iron butterfly (30-90 DTE).

Sell ATM straddle + buy OTM wings for max VRP harvest with defined risk.
VRP regime RICH + steep skew are the primary conditions.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class MediumTermIronButterfly(StrategyDefinition):
    @property
    def name(self) -> str:
        return "mt_iron_butterfly"

    @property
    def label(self) -> str:
        return "Iron Butterfly (30-90 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (30, 90)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (40.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        skew_regime = getattr(signal, "skew_regime", None) or "NORMAL"

        return [
            SignalCheck("VRP regime RICH", vrp_regime == "RICH",
                        vrp_regime, weight=3.0),
            SignalCheck("IV rank > 50%", signal.iv_rank > 50,
                        f"{signal.iv_rank:.0f}%", weight=2.5),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("Skew STEEP or NORMAL",
                        skew_regime in ("STEEP", "NORMAL"),
                        skew_regime, weight=1.5),
            SignalCheck("|Delta| < 0.20", abs(signal.delta) < 0.20,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 30-75", 30 <= signal.dte <= 75,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        wing_width = inc * 3
        return [
            {"action": "sell", "option_type": "call", "strike": atm},
            {"action": "sell", "option_type": "put", "strike": atm},
            {"action": "buy", "option_type": "call", "strike": atm + wing_width},
            {"action": "buy", "option_type": "put", "strike": atm - wing_width},
        ]
