"""
Strategy registry — catalog of all available strategies.

Four registries by DTE tier — each tier is its own trading system with
separate signals, weights, strategies, and risk parameters:
  - STRATEGY_REGISTRY: 0-14 DTE (short-term, 6 strategies)
  - SWING_REGISTRY: 14-60 DTE (swing, 4 strategies)
  - MEDIUM_TERM_REGISTRY: 30-90 DTE (VRP-driven, 4 strategies)
  - LONG_TERM_REGISTRY: 90-180 DTE (cross-asset-driven, 3 strategies)
"""

from typing import List

from regime.detector import MarketRegime
from .base import StrategyDefinition
from .iron_condor import IronCondor
from .credit_spread import ShortPutSpread, ShortCallSpread
from .debit_spread import LongCallSpread, LongPutSpread
from .butterfly import Butterfly
from ._deferred.calendar_spread import CalendarSpread
from ._deferred.diagonal_spread import DiagonalSpread
from ._deferred.short_strangle import IronButterfly
from ._deferred.long_straddle import LongStraddle
from .medium_term.calendar import MediumTermCalendar
from .medium_term.diagonal import MediumTermDiagonal
from .medium_term.straddle import MediumTermStraddle
from .medium_term.iron_butterfly import MediumTermIronButterfly
from .long_term.calendar import LongTermCalendar
from .long_term.diagonal import LongTermDiagonal
from .long_term.straddle import LongTermStraddle

# 0-14 DTE — short-term
STRATEGY_REGISTRY: List[StrategyDefinition] = [
    IronCondor(),
    ShortPutSpread(),
    ShortCallSpread(),
    LongCallSpread(),
    LongPutSpread(),
    Butterfly(),
]

# 14-60 DTE — swing
SWING_REGISTRY: List[StrategyDefinition] = [
    CalendarSpread(),
    DiagonalSpread(),
    IronButterfly(),
    LongStraddle(),
]

# 30-90 DTE — medium-term (VRP + skew dominant)
MEDIUM_TERM_REGISTRY: List[StrategyDefinition] = [
    MediumTermCalendar(),
    MediumTermDiagonal(),
    MediumTermStraddle(),
    MediumTermIronButterfly(),
]

# 90-180 DTE — long-term (cross-asset + correlation dominant)
LONG_TERM_REGISTRY: List[StrategyDefinition] = [
    LongTermCalendar(),
    LongTermDiagonal(),
    LongTermStraddle(),
]


def for_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return strategies appropriate for the given regime."""
    return [s for s in STRATEGY_REGISTRY if regime in s.ideal_regimes]


def for_swing_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return swing strategies appropriate for the given regime."""
    return [s for s in SWING_REGISTRY if regime in s.ideal_regimes]


def for_medium_term_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return medium-term (30-90 DTE) strategies for the given regime."""
    return [s for s in MEDIUM_TERM_REGISTRY if regime in s.ideal_regimes]


def for_long_term_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return long-term (90-180 DTE) strategies for the given regime."""
    return [s for s in LONG_TERM_REGISTRY if regime in s.ideal_regimes]


_ALL_REGISTRIES = (
    STRATEGY_REGISTRY + SWING_REGISTRY
    + MEDIUM_TERM_REGISTRY + LONG_TERM_REGISTRY
)


def get_strategy(name: str) -> StrategyDefinition:
    """Look up a strategy by machine name (all registries)."""
    for s in _ALL_REGISTRIES:
        if s.name == name:
            return s
    raise KeyError(f"Unknown strategy: {name!r}")
