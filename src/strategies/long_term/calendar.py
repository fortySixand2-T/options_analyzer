"""Long-term calendar spread (90-180 DTE).

At this horizon VRP mean-reverts slowly — the edge is cross-asset
divergence and term-structure dislocations that take months to normalise.
Wider profit targets, earlier time exit than medium-term.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class LongTermCalendar(StrategyDefinition):
    @property
    def name(self) -> str:
        return "lt_calendar_spread"

    @property
    def label(self) -> str:
        return "Calendar Spread (90-180 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (90, 180)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (25.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        cross_signal = getattr(signal, "cross_asset_signal", None) or "ALIGNED"

        return [
            SignalCheck("Cross-asset not EQUITY_VOL_RICH",
                        cross_signal != "EQUITY_VOL_RICH",
                        cross_signal, weight=3.0),
            SignalCheck("VRP regime RICH", vrp_regime == "RICH",
                        vrp_regime, weight=2.5),
            SignalCheck("IV rank > 30%", signal.iv_rank > 30,
                        f"{signal.iv_rank:.0f}%", weight=1.5),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("|Delta| < 0.30", abs(signal.delta) < 0.30,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 90-165", 90 <= signal.dte <= 165,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("Spread < 8%", signal.bid_ask_spread_pct < 8,
                        f"{signal.bid_ask_spread_pct:.1f}%", weight=0.5),
        ]

    def build_legs(self, signal, spot: float) -> List[Dict]:
        inc = 5.0 if spot >= 100 else (2.5 if spot >= 50 else 1.0)
        atm = round(spot / inc) * inc
        opt_type = signal.option_type
        return [
            {"action": "sell", "option_type": opt_type, "strike": atm,
             "note": "front_month"},
            {"action": "buy", "option_type": opt_type, "strike": atm,
             "note": "back_month"},
        ]
