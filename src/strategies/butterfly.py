"""Butterfly spread — buy/sell/buy at three strikes for pinning plays."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


def _strike_inc(spot: float) -> float:
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


class Butterfly(StrategyDefinition):
    @property
    def name(self) -> str:
        return "butterfly"

    @property
    def label(self) -> str:
        return "Butterfly Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (7, 30)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (30.0, 80.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("Low vol regime", regime_result.regime == MarketRegime.LOW_VOL_RANGING,
                        regime_result.regime.value, weight=2.0),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=1.5),
            SignalCheck("IV rank 30-80%", 30 <= signal.iv_rank <= 80,
                        f"{signal.iv_rank:.0f}%", weight=1.5),
            SignalCheck("|Delta| < 0.30", abs(signal.delta) < 0.30,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 7-21", 7 <= signal.dte <= 21,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        atm = round(spot / w) * w
        opt_type = signal.option_type
        return [
            {"action": "buy", "option_type": opt_type, "strike": atm - w},
            {"action": "sell", "option_type": opt_type, "strike": atm},
            {"action": "sell", "option_type": opt_type, "strike": atm},
            {"action": "buy", "option_type": opt_type, "strike": atm + w},
        ]
