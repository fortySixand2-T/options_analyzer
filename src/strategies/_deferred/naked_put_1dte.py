"""Naked Put 0-1 DTE — sell OTM put for theta decay on expiration day."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


class NakedPut1DTE(StrategyDefinition):
    @property
    def name(self) -> str:
        return "naked_put_1dte"

    @property
    def label(self) -> str:
        return "Naked Put 0-1 DTE"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (0, 3)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (0.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("DTE 0-1", signal.dte <= 1,
                        f"{signal.dte}d", weight=3.0),
            SignalCheck("Put option", signal.option_type == "put",
                        signal.option_type, weight=2.0),
            SignalCheck("VIX < 22", vix.vix < 22,
                        f"VIX={vix.vix:.1f}", weight=2.0),
            SignalCheck("|Delta| < 0.15", abs(signal.delta) < 0.15,
                        f"{signal.delta:+.3f}", weight=2.0),
            SignalCheck("No event today", not regime_result.event_active,
                        regime_result.event_type or "clear", weight=2.5),
            SignalCheck("OI > 500", signal.open_interest > 500,
                        f"{signal.open_interest}", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        return [
            {"action": "sell", "option_type": "put", "strike": signal.strike},
        ]
