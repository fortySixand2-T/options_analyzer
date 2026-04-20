"""
Market regime detection module.

Classifies the current market environment based on VIX levels,
term structure, and macro calendar events.
"""

from .detector import detect_regime, MarketRegime
from .vix_analysis import get_vix_data, VixSnapshot

__all__ = ['detect_regime', 'MarketRegime', 'get_vix_data', 'VixSnapshot']
