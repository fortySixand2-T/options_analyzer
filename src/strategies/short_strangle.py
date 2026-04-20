"""Short Strangle — sell OTM call + OTM put (undefined risk)."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


class ShortStrangle(StrategyDefinition):
    @property
    def name(self) -> str:
        return "short_strangle"

    @property
    def label(self) -> str:
        return "Short Strangle"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING, MarketRegime.HIGH_VOL_TRENDING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (21, 60)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (60.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank > 60%", signal.iv_rank > 60,
                        f"{signal.iv_rank:.0f}%", weight=2.5),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("Direction SELL", signal.direction == "SELL",
                        signal.direction, weight=1.5),
            SignalCheck("|Delta| 0.15-0.30", 0.15 <= abs(signal.delta) <= 0.30,
                        f"{signal.delta:+.3f}", weight=1.5),
            SignalCheck("No event in 5d", not regime_result.event_active,
                        regime_result.event_type or "clear", weight=2.0),
            SignalCheck("DTE 30-50", 30 <= signal.dte <= 50,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        return [
            {"action": "sell", "option_type": "call", "strike": atm + inc},
            {"action": "sell", "option_type": "put", "strike": atm - inc},
        ]
