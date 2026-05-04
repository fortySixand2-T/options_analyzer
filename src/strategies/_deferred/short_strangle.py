"""Iron butterfly — sell ATM straddle, buy OTM wings for defined risk.

Replaces the original short strangle (undefined risk) with an iron butterfly
that captures the same VRP edge with capped downside.

Edge: variance risk premium harvest at 30-45 DTE.
Best in HIGH_IV + LONG_GAMMA (range-bound, premium rich).
DTE: 21-50 (sweet spot for VRP collection with manageable gamma).
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class IronButterfly(StrategyDefinition):
    @property
    def name(self) -> str:
        return "iron_butterfly"

    @property
    def label(self) -> str:
        return "Iron Butterfly"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (21, 50)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (50.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank > 50%", signal.iv_rank > 50,
                        f"{signal.iv_rank:.0f}%", weight=2.5),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("Direction SELL", signal.direction == "SELL",
                        signal.direction, weight=2.0),
            SignalCheck("|Delta| < 0.15", abs(signal.delta) < 0.15,
                        f"{signal.delta:+.3f}", weight=1.5),
            SignalCheck("No event in 5d", not regime_result.event_active,
                        regime_result.event_type or "clear", weight=2.0),
            SignalCheck("DTE 30-50", 30 <= signal.dte <= 50,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        wing_width = inc * 5
        return [
            {"action": "buy", "option_type": "put", "strike": atm - wing_width},
            {"action": "sell", "option_type": "put", "strike": atm},
            {"action": "sell", "option_type": "call", "strike": atm},
            {"action": "buy", "option_type": "call", "strike": atm + wing_width},
        ]
