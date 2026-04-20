"""
Backtesting engine for options strategies.

Supports both Tastytrade API backtesting (13 years of data)
and local offline backtesting using historical OHLCV + BS pricer.
"""

from .models import BacktestRequest, BacktestTrade, BacktestResult
from .analyzer import analyze_results

__all__ = ['BacktestRequest', 'BacktestTrade', 'BacktestResult', 'analyze_results']
