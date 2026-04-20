"""Calendar spread — sell front-month, buy back-month at same strike."""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from .base import SignalCheck, StrategyDefinition


class CalendarSpread(StrategyDefinition):
    @property
    def name(self) -> str:
        return "calendar_spread"

    @property
    def label(self) -> str:
        return "Calendar Spread"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.LOW_VOL_RANGING, MarketRegime.HIGH_VOL_TRENDING]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (21, 60)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (40.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        return [
            SignalCheck("IV rank > 40%", signal.iv_rank > 40,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("VIX contango (term structure)", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("|Delta| < 0.35", abs(signal.delta) < 0.35,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE > 25", signal.dte > 25,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("Spread < 10%", signal.bid_ask_spread_pct < 10,
                        f"{signal.bid_ask_spread_pct:.1f}%", weight=1.0),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        opt_type = signal.option_type
        return [
            {"action": "sell", "option_type": opt_type, "strike": atm},
            {"action": "buy", "option_type": opt_type, "strike": atm},
        ]
