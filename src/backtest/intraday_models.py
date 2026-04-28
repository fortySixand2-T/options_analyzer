"""
Pydantic models for the 0 DTE intraday backtester.

Separate from daily backtest models because intraday operates on:
- 5-min bars (not daily OHLCV)
- Entry windows (specific times, not "next open")
- Intraday theta decay (minutes_to_close / (390 * 252))
- Day-type classification as primary filter

Options Analytics Team — 2026-04
"""

from datetime import date, time
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class IntradayBacktestRequest(BaseModel):
    """Parameters for an intraday (0 DTE) backtest run."""
    strategy: str = "0dte_iron_condor"
    symbol: str = "SPY"
    start_date: date
    end_date: date

    # Entry timing
    entry_windows: List[str] = Field(
        default=["10:00", "10:30", "11:00"],
        description="Times (ET) to evaluate entry. Format: HH:MM",
    )
    exit_time: str = Field(
        default="15:45",
        description="Force exit time (ET). Default 15:45 (15 min before close).",
    )

    # Strategy params
    wing_width: float = Field(
        default=5.0, description="Width between short and long strikes ($)",
    )
    entry_delta: float = Field(
        default=0.15, description="Target |delta| for short strikes",
    )

    # Filters
    day_type_filter: Optional[str] = Field(
        default="RANGE_DAY",
        description="Only enter on this day type. None = no filter.",
    )
    exhaustion_min: float = Field(
        default=0.0, description="Min exhaustion % to enter (0 = no filter)",
    )
    exhaustion_max: float = Field(
        default=80.0, description="Max exhaustion % to enter",
    )
    dealer_filter: Optional[str] = Field(
        default="LONG_GAMMA",
        description="Only enter in this dealer regime. None = no filter.",
    )
    min_expected_move: float = Field(
        default=0.0, description="Min expected daily move ($) to enter",
    )

    # Exit rules
    profit_target_pct: float = Field(
        default=50.0, description="Close at this % of max profit",
    )
    stop_loss_pct: float = Field(
        default=200.0, description="Close at this % of max profit lost (2x = 200%)",
    )

    # Sizing
    quantity: int = 1
    slippage_per_leg: float = Field(
        default=0.02, description="Slippage per leg in $ (e.g., 0.02 = 2 cents)",
    )


class IntradayBacktestTrade(BaseModel):
    """Single trade in an intraday backtest."""
    trade_date: date
    entry_time: str                          # HH:MM ET
    exit_time: str                           # HH:MM ET
    entry_price: float                       # net credit/debit per contract
    exit_price: float                        # net to close
    pnl: float                               # per-contract P&L ($)
    pnl_pct: float                           # P&L as % of max risk
    max_profit: float                        # max possible profit
    max_risk: float                          # max possible loss

    # Market context at entry
    spot_at_entry: float
    spot_at_exit: float
    expected_daily_move: float
    day_type: str
    day_type_confidence: float
    move_exhaustion_pct: float
    dealer_regime: Optional[str] = None

    # Exit info
    win: bool = False
    exit_reason: str = ""                    # profit_target, stop_loss, time_exit, eod

    # Strike info
    short_call: Optional[float] = None
    short_put: Optional[float] = None
    long_call: Optional[float] = None
    long_put: Optional[float] = None


class IntradayBacktestStats(BaseModel):
    """Aggregate stats for an intraday backtest."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0

    # 0 DTE specific
    avg_hold_minutes: float = 0.0
    range_day_win_rate: float = 0.0
    trend_day_win_rate: float = 0.0
    avg_entry_exhaustion: float = 0.0
    days_traded: int = 0
    days_skipped: int = 0
    skip_reasons: Dict[str, int] = Field(default_factory=dict)


class IntradayBacktestResult(BaseModel):
    """Complete result of an intraday backtest."""
    request: IntradayBacktestRequest
    stats: IntradayBacktestStats
    trades: List[IntradayBacktestTrade] = Field(default_factory=list)
    equity_curve: List[float] = Field(default_factory=list)
    day_type_breakdown: Dict[str, Dict] = Field(default_factory=dict)
    entry_time_breakdown: Dict[str, Dict] = Field(default_factory=dict)
    source: str = "intraday_local"
