"""
Pydantic models for the backtesting engine.

Options Analytics Team — 2026-04
"""

from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    """Parameters for a backtest run."""
    strategy: str                           # e.g. "iron_condor"
    symbol: str                             # e.g. "SPY"
    start_date: date
    end_date: date
    entry_delta: float = 0.20               # target |delta| for short strikes
    entry_dte_min: int = 3
    entry_dte_max: int = 14
    exit_profit_pct: float = 50.0           # close at 50% max profit
    exit_loss_pct: float = 200.0            # close at 200% max profit (2x loss)
    exit_dte: int = 1                       # close at 1 DTE remaining
    exit_rule: str = "50pct"                # "50pct" or "hold"
    quantity: int = 1
    min_score: float = 0.0                  # minimum strategy score to enter
    # Signal layer filters
    regime_filter: bool = False             # only enter when regime matches strategy
    bias_filter: bool = False               # only enter when directional bias aligns
    dealer_filter: bool = False             # only enter when dealer regime matches
    edge_threshold: float = 0.0             # min GARCH edge % to enter
    slippage_pct: float = 0.0               # % of premium lost to slippage (e.g., 3.0 = 3%)


class BacktestTrade(BaseModel):
    """Single trade in a backtest."""
    entry_date: date
    exit_date: date
    entry_price: float                      # net premium collected/paid
    exit_price: float                       # net premium to close
    pnl: float                              # per-contract P&L
    pnl_pct: float                          # P&L as % of max risk
    dte_at_entry: int
    dte_at_exit: int
    regime: Optional[str] = None            # regime at entry
    score: Optional[float] = None           # strategy score at entry
    win: bool = False
    exit_reason: str = ""                   # "profit_target", "stop_loss", "expiry", "dte_exit"


class BacktestStats(BaseModel):
    """Aggregate statistics for a backtest."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0                   # %
    avg_win: float = 0.0                    # $ per contract
    avg_loss: float = 0.0                   # $ per contract
    avg_pnl: float = 0.0                    # $ per contract
    total_pnl: float = 0.0
    profit_factor: float = 0.0              # gross wins / gross losses
    max_drawdown: float = 0.0               # $ worst peak-to-trough
    max_drawdown_pct: float = 0.0           # %
    sharpe_ratio: float = 0.0               # annualized
    avg_dte_at_entry: float = 0.0
    avg_days_in_trade: float = 0.0


class BacktestResult(BaseModel):
    """Complete backtest result."""
    request: BacktestRequest
    stats: BacktestStats
    trades: List[BacktestTrade] = Field(default_factory=list)
    equity_curve: List[float] = Field(default_factory=list)
    regime_breakdown: Dict[str, Dict] = Field(default_factory=dict)
    dte_breakdown: Dict[str, Dict] = Field(default_factory=dict)
    pnl_distribution: List[Dict] = Field(default_factory=list)
    cached: bool = False
    source: str = "local"                   # "local" or "tastytrade"
