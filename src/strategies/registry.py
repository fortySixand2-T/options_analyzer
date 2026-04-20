"""
Strategy registry — catalog of all available strategies.

Options Analytics Team — 2026-04
"""

from typing import List

from regime.detector import MarketRegime
from .base import StrategyDefinition
from .iron_condor import IronCondor
from .credit_spread import ShortPutSpread, ShortCallSpread
from .debit_spread import LongCallSpread, LongPutSpread
from .long_straddle import LongStraddle
from .butterfly import Butterfly
from .calendar_spread import CalendarSpread
from .diagonal_spread import DiagonalSpread
from .short_strangle import ShortStrangle
from .naked_put_1dte import NakedPut1DTE

# All registered strategies
STRATEGY_REGISTRY: List[StrategyDefinition] = [
    IronCondor(),
    ShortPutSpread(),
    ShortCallSpread(),
    LongCallSpread(),
    LongPutSpread(),
    LongStraddle(),
    Butterfly(),
    CalendarSpread(),
    DiagonalSpread(),
    ShortStrangle(),
    NakedPut1DTE(),
]


def for_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return strategies appropriate for the given regime."""
    return [s for s in STRATEGY_REGISTRY if regime in s.ideal_regimes]


def get_strategy(name: str) -> StrategyDefinition:
    """Look up a strategy by machine name."""
    for s in STRATEGY_REGISTRY:
        if s.name == name:
            return s
    raise KeyError(f"Unknown strategy: {name!r}")
