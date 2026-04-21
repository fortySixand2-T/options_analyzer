"""Long Straddle — buy ATM call + ATM put for vol expansion."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


class LongStraddle(StrategyDefinition):
    @property
    def name(self) -> str:
        return "long_straddle"

    @property
    def label(self) -> str:
        return "Long Straddle"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING, MarketRegime.SPIKE_EVENT]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (14, 60)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 35.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank < 35%", signal.iv_rank < 35,
                        f"{signal.iv_rank:.0f}%", weight=2.5),
            SignalCheck("VIX < 18 or event pending", vix.vix < 18 or regime_result.event_active,
                        f"VIX={vix.vix:.1f}", weight=2.0),
            SignalCheck("|Delta| < 0.25", abs(signal.delta) < 0.25,
                        f"{signal.delta:+.3f}", weight=1.5),
            SignalCheck("DTE 21-50", 21 <= signal.dte <= 50,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("Direction BUY", signal.direction == "BUY",
                        signal.direction, weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        return [
            {"action": "buy", "option_type": "call", "strike": atm},
            {"action": "buy", "option_type": "put", "strike": atm},
        ]
