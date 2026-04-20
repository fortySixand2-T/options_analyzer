"""Diagonal spread — sell front-month, buy back-month at different strike."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


def _strike_inc(spot: float) -> float:
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


class DiagonalSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "diagonal_spread"

    @property
    def label(self) -> str:
        return "Diagonal Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING, MarketRegime.HIGH_VOL_TRENDING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (21, 60)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (35.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank > 35%", signal.iv_rank > 35,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=1.5),
            SignalCheck("Direction SELL", signal.direction == "SELL",
                        signal.direction, weight=1.5),
            SignalCheck("Delta 0.20-0.45", 0.20 <= abs(signal.delta) <= 0.45,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE > 25", signal.dte > 25,
                        f"{signal.dte}d", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        opt_type = signal.option_type
        # Sell near-term at signal strike, buy longer-term one strike further OTM
        if opt_type == "call":
            return [
                {"action": "sell", "option_type": "call", "strike": signal.strike},
                {"action": "buy", "option_type": "call", "strike": signal.strike + w},
            ]
        return [
            {"action": "sell", "option_type": "put", "strike": signal.strike},
            {"action": "buy", "option_type": "put", "strike": signal.strike - w},
        ]
