"""
Strategy registry — 0-14 DTE defined-risk strategies only.

Deferred strategies (swing, medium-term, long-term) live in _parked/
and will be re-introduced after the core scanner is validated.
"""

from typing import List

from regime.detector import MarketRegime
from .base import StrategyDefinition
from .iron_condor import IronCondor
from .credit_spread import ShortPutSpread, ShortCallSpread
from .debit_spread import LongCallSpread, LongPutSpread
from .butterfly import Butterfly

STRATEGY_REGISTRY: List[StrategyDefinition] = [
    IronCondor(),
    ShortPutSpread(),
    ShortCallSpread(),
    LongCallSpread(),
    LongPutSpread(),
    Butterfly(),
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
