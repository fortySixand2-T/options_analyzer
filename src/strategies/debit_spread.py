"""Debit spread strategies — long call spread and long put spread.

Decision matrix: MODERATE_IV/LOW_IV + directional bias, DTE 3-14.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


def _strike_inc(spot: float) -> float:
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


class LongCallSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "long_call_spread"

    @property
    def label(self) -> str:
        return "Long Call Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.MODERATE_IV, MarketRegime.LOW_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (3, 14)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 50.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        return [
            SignalCheck("IV rank < 50%", signal.iv_rank < 50,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("Call option", signal.option_type == "call",
                        signal.option_type, weight=2.0),
            SignalCheck("Direction BUY", signal.direction == "BUY",
                        signal.direction, weight=1.5),
            SignalCheck("Edge > 5%", signal.edge_pct > 5,
                        f"{signal.edge_pct:+.1f}%", weight=1.5),
            SignalCheck("Delta 0.30-0.50", 0.30 <= abs(signal.delta) <= 0.50,
                        f"{signal.delta:+.3f}", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        return [
            {"action": "buy", "option_type": "call", "strike": signal.strike},
            {"action": "sell", "option_type": "call", "strike": signal.strike + w},
        ]


class LongPutSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "long_put_spread"

    @property
    def label(self) -> str:
        return "Long Put Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.MODERATE_IV, MarketRegime.LOW_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (3, 14)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 50.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        return [
            SignalCheck("IV rank < 50%", signal.iv_rank < 50,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("Put option", signal.option_type == "put",
                        signal.option_type, weight=2.0),
            SignalCheck("Direction BUY", signal.direction == "BUY",
                        signal.direction, weight=1.5),
            SignalCheck("Edge > 5%", signal.edge_pct > 5,
                        f"{signal.edge_pct:+.1f}%", weight=1.5),
            SignalCheck("Delta 0.30-0.50", 0.30 <= abs(signal.delta) <= 0.50,
                        f"{signal.delta:+.3f}", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        return [
            {"action": "buy", "option_type": "put", "strike": signal.strike},
            {"action": "sell", "option_type": "put", "strike": signal.strike - w},
        ]
