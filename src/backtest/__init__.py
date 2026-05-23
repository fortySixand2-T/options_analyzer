"""
Backtesting engine for options strategies.

Two backends:
- local_backtest: BS-simulated pricing from OHLCV (fast, full date range)
- chain_replay: real bid/ask/mid from chain_snapshots.db (accurate, data-limited)
"""

from .models import BacktestRequest, BacktestTrade, BacktestResult
from .analyzer import analyze_results

__all__ = ['BacktestRequest', 'BacktestTrade', 'BacktestResult', 'analyze_results']
