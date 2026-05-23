"""Medium-term long straddle (30-90 DTE).

Buy cheap vol for expansion. VRP CHEAP regime is the primary entry.
Cross-asset divergence supports but doesn't dominate at this horizon
(that's the long-term tier's job).
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class MediumTermStraddle(StrategyDefinition):
    @property
    def name(self) -> str:
        return "mt_long_straddle"

    @property
    def label(self) -> str:
        return "Long Straddle (30-90 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (30, 90)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 45.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        cross_signal = getattr(signal, "cross_asset_signal", None) or "ALIGNED"
        skew_regime = getattr(signal, "skew_regime", None) or "NORMAL"

        return [
            SignalCheck("VRP regime CHEAP", vrp_regime == "CHEAP",
                        vrp_regime, weight=3.0),
            SignalCheck("IV rank < 40%", signal.iv_rank < 40,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("Cross-asset vol cheap",
                        cross_signal == "EQUITY_VOL_CHEAP",
                        cross_signal, weight=2.5),
            SignalCheck("Skew flat or inverted",
                        skew_regime in ("FLAT", "INVERTED"),
                        skew_regime, weight=1.5),
            SignalCheck("Direction BUY", signal.direction == "BUY",
                        signal.direction, weight=1.0),
            SignalCheck("|Delta| < 0.30", abs(signal.delta) < 0.30,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 30-80", 30 <= signal.dte <= 80,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        return [
            {"action": "buy", "option_type": "call", "strike": atm},
            {"action": "buy", "option_type": "put", "strike": atm},
        ]
