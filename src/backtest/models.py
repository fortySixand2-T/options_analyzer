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
    # F-018/F-019: gate entries on the IC-validated conditioned_reversal signal
    # (calm-regime medium-horizon reversal). For directional debit spreads only:
    # enter long_call_spread only when the signal is bullish (recent laggard in a
    # calm tape), long_put_spread only when bearish. signal_gate selects the calm
    # gate ("vix_pct" — VIX below trailing median — or "contango").
    signal_filter: bool = False
    signal_gate: str = "vix_pct"
    dealer_filter: bool = False             # only enter when dealer regime matches
    edge_threshold: float = 0.0             # min GARCH edge % to enter
    slippage_pct: float = 0.0               # % of premium lost to slippage (e.g., 3.0 = 3%)
    # Fill realism (chain-replay only): "bid_ask" crosses the spread (buys pay
    # ask, sells receive bid) for realistic fills; "mid" is the legacy optimistic
    # behavior that overstates edge — see docs/pricing_validation_report.md.
    fill_mode: str = "bid_ask"
    # Swing-specific filters
    vrp_filter: bool = False                # only enter when VRP > vrp_threshold
    vrp_threshold: float = 3.0             # min VRP % for swing credit strategies
    swing_bias_filter: bool = False         # use swing bias (SMA 20/50/200) instead of short-term
    option_style: str = "european"         # "european" (BS) or "american" (LSMC MC)
    # Phase 2 (F-023) vehicle knobs — match a validated DIRECTIONAL signal to a
    # more cost-efficient option structure. Defaults reproduce the legacy
    # narrow-ATM debit spread exactly (itm=0 → ATM long leg; width=0 → adjacent
    # short strike), so existing results are unchanged.
    entry_interval: int = 5                 # snapshots between entries (sample-size knob)
    debit_itm_pct: float = 0.0              # long leg this far ITM (frac of spot): more delta, less theta
    debit_width_pct: float = 0.0            # debit-spread width as frac of spot (0 = adjacent strike)


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
    # Signal snapshots at entry — for regression-based weight calibration
    bias_score: Optional[int] = None        # directional bias score at entry
    bias_label: Optional[str] = None        # e.g. "LEAN_BULLISH"
    edge_pct: Optional[float] = None        # IV-RV edge % at entry
    iv_at_entry: Optional[float] = None     # rolling vol at entry
    swing_bias_score: Optional[int] = None  # SMA 20/50/200 bias score
    swing_bias_label: Optional[str] = None
    vrp_at_entry: Optional[float] = None    # VRP % at entry
    dealer_regime: Optional[str] = None     # LONG_GAMMA / SHORT_GAMMA at entry
    # Fill transparency — how this trade's legs were priced and the spread cost
    fill_mode: Optional[str] = None         # "bid_ask" (realistic) or "mid" (legacy)
    avg_spread_pct: Optional[float] = None  # avg bid/ask spread % across legs at entry


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
    # Skew-aware metrics — Sharpe alone is misleading for convex, positively-
    # skewed, defined-risk payoffs (e.g. butterflies): it penalizes variance
    # symmetrically and assumes ~normal returns. See FINDINGS.md F-013.
    sortino_ratio: float = 0.0              # annualized, downside-deviation only
    pnl_skew: float = 0.0                   # skew of per-trade P&L (>0 = positive/convex)
    return_on_risk: float = 0.0             # avg P&L / avg premium at risk (expectancy per $ risked)
    # Tail-risk metrics — the correct primary lens for NEGATIVE-skew premium-
    # selling strategies (credit spreads, iron condors), where a high win rate
    # and Sharpe hide a fat left tail. See STRATEGY_LITERATURE_REVIEW.md / F-015.
    cvar_95: float = 0.0                    # expected shortfall: mean of the worst 5% of trade P&Ls
    max_single_loss: float = 0.0            # worst single-trade P&L ($)
    calmar_ratio: float = 0.0               # annualized P&L / max drawdown
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
    source: str = "local"                   # "local", "chain_replay", or "tastytrade"
    data_issues: List[str] = Field(default_factory=list)
