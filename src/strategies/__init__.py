"""
Strategy definitions and registry.

Each strategy defines ideal regime, DTE range, IV conditions,
signal checklist, and evaluation logic.
"""

from .base import StrategyDefinition, StrategyResult, SignalCheck
from .registry import STRATEGY_REGISTRY, for_regime

__all__ = [
    'StrategyDefinition', 'StrategyResult', 'SignalCheck',
    'STRATEGY_REGISTRY', 'for_regime',
]
