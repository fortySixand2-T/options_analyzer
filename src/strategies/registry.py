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
from .butterfly import Butterfly
from ._deferred.calendar_spread import CalendarSpread
from ._deferred.diagonal_spread import DiagonalSpread
from ._deferred.short_strangle import IronButterfly
from ._deferred.long_straddle import LongStraddle

# Five defined-risk strategies for 0-14 DTE
# Deferred strategies (calendar, diagonal, strangle, straddle, naked put)
# are in _deferred/ for a future swing-trade tab.
STRATEGY_REGISTRY: List[StrategyDefinition] = [
    IronCondor(),
    ShortPutSpread(),
    ShortCallSpread(),
    LongCallSpread(),
    LongPutSpread(),
    Butterfly(),
]

# Four defined-risk strategies for 14-60 DTE swing trades
SWING_REGISTRY: List[StrategyDefinition] = [
    CalendarSpread(),
    DiagonalSpread(),
    IronButterfly(),
    LongStraddle(),
]


def for_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return strategies appropriate for the given regime."""
    return [s for s in STRATEGY_REGISTRY if regime in s.ideal_regimes]


def for_swing_regime(regime: MarketRegime) -> List[StrategyDefinition]:
    """Return swing strategies appropriate for the given regime."""
    return [s for s in SWING_REGISTRY if regime in s.ideal_regimes]


def get_strategy(name: str) -> StrategyDefinition:
    """Look up a strategy by machine name (both registries)."""
    for s in STRATEGY_REGISTRY + SWING_REGISTRY:
        if s.name == name:
            return s
    raise KeyError(f"Unknown strategy: {name!r}")
