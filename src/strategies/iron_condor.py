"""Iron Condor strategy — sell OTM call spread + OTM put spread."""

from typing import Dict, List, Optional, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


def _strike_inc(spot: float) -> float:
    if spot >= 100:
        return 5.0
    if spot >= 50:
        return 2.5
    return 1.0


class IronCondor(StrategyDefinition):
    @property
    def name(self) -> str:
        return "iron_condor"

    @property
    def label(self) -> str:
        return "Iron Condor"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING, MarketRegime.HIGH_VOL_TRENDING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (21, 60)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (50.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank > 50%", signal.iv_rank > 50,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=1.5),
            SignalCheck("DTE 21-45", 21 <= signal.dte <= 45,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("|Delta| < 0.30", abs(signal.delta) < 0.30,
                        f"{signal.delta:+.3f}", weight=1.5),
            SignalCheck("Spread < 10%", signal.bid_ask_spread_pct < 10,
                        f"{signal.bid_ask_spread_pct:.1f}%", weight=1.0),
            SignalCheck("No event in 3d", not regime_result.event_active,
                        regime_result.event_type or "clear", weight=1.5),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        w = _strike_inc(spot)
        atm = round(spot / w) * w
        return [
            {"action": "sell", "option_type": "call", "strike": atm + w},
            {"action": "buy", "option_type": "call", "strike": atm + 2 * w},
            {"action": "sell", "option_type": "put", "strike": atm - w},
            {"action": "buy", "option_type": "put", "strike": atm - 2 * w},
        ]
