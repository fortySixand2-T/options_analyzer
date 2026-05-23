"""Medium-term calendar spread (30-90 DTE).

VRP is the primary edge at this horizon (Sharpe 0.5-0.6). Skew regime
gates the checklist — avoid selling into inverted skew.
"""

from typing import Dict, List, Tuple

from regime.detector import MarketRegime
from ..base import SignalCheck, StrategyDefinition


class MediumTermCalendar(StrategyDefinition):
    @property
    def name(self) -> str:
        return "mt_calendar_spread"

    @property
    def label(self) -> str:
        return "Calendar Spread (30-90 DTE)"

    @property
    def ideal_regimes(self) -> List[MarketRegime]:
        return [MarketRegime.HIGH_IV, MarketRegime.MODERATE_IV]

    @property
    def dte_range(self) -> Tuple[int, int]:
        return (30, 90)

    @property
    def iv_range(self) -> Tuple[float, float]:
        return (30.0, 100.0)

    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        vix = regime_result.vix
        vrp_regime = getattr(signal, "vrp_regime", None) or "NEUTRAL"
        skew_regime = getattr(signal, "skew_regime", None) or "NORMAL"

        return [
            SignalCheck("VRP regime RICH", vrp_regime == "RICH",
                        vrp_regime, weight=3.0),
            SignalCheck("IV rank > 35%", signal.iv_rank > 35,
                        f"{signal.iv_rank:.0f}%", weight=2.0),
            SignalCheck("VIX contango", vix.contango,
                        f"slope {vix.term_structure_slope:+.1f}%", weight=2.0),
            SignalCheck("Skew not INVERTED", skew_regime != "INVERTED",
                        skew_regime, weight=1.5),
            SignalCheck("|Delta| < 0.35", abs(signal.delta) < 0.35,
                        f"{signal.delta:+.3f}", weight=1.0),
            SignalCheck("DTE 30-80", 30 <= signal.dte <= 80,
                        f"{signal.dte}d", weight=1.0),
            SignalCheck("Spread < 10%", signal.bid_ask_spread_pct < 10,
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
