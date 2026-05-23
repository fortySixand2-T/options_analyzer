"""Long-term LEAPS straddle (90-180 DTE).

Buy vol at quarterly+ horizon when cross-asset divergence signals equity
vol is cheap relative to bond vol. The primary edge is structural mispricing,
not event-driven.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class LongTermStraddle(StrategyDefinition):
    @property
    def name(self) -> str:
        return "lt_long_straddle"

    @property
    def label(self) -> str:
        return "LEAPS Straddle (90-180 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (90, 180)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 40.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        cross_signal = getattr(signal, "cross_asset_signal", None) or "ALIGNED"
        skew_regime = getattr(signal, "skew_regime", None) or "NORMAL"

        return [
            SignalCheck("Cross-asset EQUITY_VOL_CHEAP",
                        cross_signal == "EQUITY_VOL_CHEAP",
                        cross_signal, weight=3.5),
            SignalCheck("VRP regime CHEAP", vrp_regime == "CHEAP",
                        vrp_regime, weight=2.5),
            SignalCheck("Skew flat or inverted",
                        skew_regime in ("FLAT", "INVERTED"),
                        skew_regime, weight=2.0),
            SignalCheck("IV rank < 35%", signal.iv_rank < 35,
                        f"{signal.iv_rank:.0f}%", weight=1.5),
            SignalCheck("|Delta| < 0.25", abs(signal.delta) < 0.25,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 90-170", 90 <= signal.dte <= 170,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        return [
            {"action": "buy", "option_type": "call", "strike": atm},
            {"action": "buy", "option_type": "put", "strike": atm},
        ]
