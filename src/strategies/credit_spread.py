"""Credit spread strategies — short put spread and short call spread.

Decision matrix: HIGH_IV + directional bias, DTE 3-10.
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


class ShortPutSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "short_put_spread"

    @property
    def label(self) -> str:
        return "Short Put Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (3, 10)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (30.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        return [
            SignalCheck("IV rank > 30%", signal.iv_rank > 30,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("Put option", signal.option_type == "put",
                        signal.option_type, weight=2.0),
            SignalCheck("Direction SELL", signal.direction == "SELL",
                        signal.direction, weight=1.5),
            SignalCheck("DTE 3-10", 3 <= signal.dte <= 10,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("OI > 200", signal.open_interest > 200,
                        f"{signal.open_interest}", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        return [
            {"action": "sell", "option_type": "put", "strike": signal.strike},
            {"action": "buy", "option_type": "put", "strike": signal.strike - w},
        ]


class ShortCallSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "short_call_spread"

    @property
    def label(self) -> str:
        return "Short Call Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (3, 10)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (30.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        return [
            SignalCheck("IV rank > 30%", signal.iv_rank > 30,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("Call option", signal.option_type == "call",
                        signal.option_type, weight=2.0),
            SignalCheck("Direction SELL", signal.direction == "SELL",
                        signal.direction, weight=1.5),
            SignalCheck("DTE 3-10", 3 <= signal.dte <= 10,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("OI > 200", signal.open_interest > 200,
                        f"{signal.open_interest}", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        return [
            {"action": "sell", "option_type": "call", "strike": signal.strike},
            {"action": "buy", "option_type": "call", "strike": signal.strike + w},
        ]
