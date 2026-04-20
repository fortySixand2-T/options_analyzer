"""
Strategy definition base class and result structures.

Options Analytics Team — 2026-04
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from regime.detector import MarketRegime


@dataclass
class SignalCheck:
    """Single checklist item for a strategy."""
    name: str                       # e.g. "IV rank > 60%"
    passed: bool
    value: Optional[str] = None     # e.g. "72.3%"
    weight: float = 1.0             # importance weight for scoring


@dataclass
class StrategyResult:
    """Evaluated strategy result for one ticker."""
    strategy_name: str
    strategy_label: str
    ticker: str
    score: float                    # 0-100 composite
    regime: MarketRegime
    checklist: List[SignalCheck]
    checks_passed: int
    checks_total: int
    legs: List[Dict]                # concrete legs with strikes
    entry: float                    # net premium
    is_credit: bool
    max_profit: Optional[float]
    max_loss: Optional[float]
    risk_reward: str
    prob_profit: Optional[float]
    suggested_dte: int
    rationale: str


class StrategyDefinition(ABC):
    """Abstract base for strategy definitions."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Machine name, e.g. 'iron_condor'."""
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        """Human label, e.g. 'Iron Condor'."""
        ...

    @property
    @abstractmethod
    def ideal_regimes(self) -> List[MarketRegime]:
        """Regimes where this strategy has edge."""
        ...

    @property
    @abstractmethod
    def dte_range(self) -> Tuple[int, int]:
        """(min_dte, max_dte) for this strategy."""
        ...

    @property
    @abstractmethod
    def iv_range(self) -> Tuple[float, float]:
        """(min_iv_rank, max_iv_rank) — IV rank bounds where strategy works."""
        ...

    @abstractmethod
    def build_checklist(self, signal, regime_result) -> List[SignalCheck]:
        """Build signal checklist for this strategy.

        Parameters
        ----------
        signal : OptionSignal
            Scanner signal to evaluate.
        regime_result : RegimeResult
            Current regime classification.

        Returns
        -------
        List[SignalCheck]
        """
        ...

    @abstractmethod
    def build_legs(self, signal, spot: float) -> List[Dict]:
        """Construct concrete legs for this strategy.

        Returns list of dicts with keys: action, option_type, strike.
        """
        ...

    def evaluate(self, signal, regime_result) -> Optional[StrategyResult]:
        """Evaluate this strategy for a given signal and regime.

        Returns None if the strategy doesn't apply.
        """
        regime = regime_result.regime
        if regime not in self.ideal_regimes:
            return None

        min_dte, max_dte = self.dte_range
        if signal.dte < min_dte or signal.dte > max_dte:
            return None

        min_iv, max_iv = self.iv_range
        if signal.iv_rank < min_iv or signal.iv_rank > max_iv:
            return None

        checklist = self.build_checklist(signal, regime_result)
        passed = sum(1 for c in checklist if c.passed)
        total = len(checklist)

        if total == 0:
            return None

        # Weighted score from checklist
        weighted_sum = sum(c.weight for c in checklist if c.passed)
        weight_total = sum(c.weight for c in checklist)
        checklist_score = (weighted_sum / weight_total * 100) if weight_total > 0 else 0

        # Blend with conviction from scanner
        score = 0.6 * checklist_score + 0.4 * signal.conviction

        if score < 30:
            return None

        legs = self.build_legs(signal, signal.spot)

        return StrategyResult(
            strategy_name=self.name,
            strategy_label=self.label,
            ticker=signal.ticker,
            score=round(score, 1),
            regime=regime,
            checklist=checklist,
            checks_passed=passed,
            checks_total=total,
            legs=legs,
            entry=0.0,       # filled by pricer downstream
            is_credit=False,  # filled by pricer downstream
            max_profit=None,
            max_loss=None,
            risk_reward="N/A",
            prob_profit=None,
            suggested_dte=signal.dte,
            rationale=self._build_rationale(signal, regime_result, passed, total),
        )

    def _build_rationale(self, signal, regime_result, passed, total) -> str:
        return (
            f"{self.label}: {passed}/{total} signals met. "
            f"IV rank {signal.iv_rank:.0f}%, "
            f"edge {signal.edge_pct:+.1f}%, "
            f"regime {regime_result.regime.value}."
        )
