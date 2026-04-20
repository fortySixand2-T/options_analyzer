"""
Backtest results analyzer.

Computes aggregate stats, equity curve, regime breakdown,
and Sharpe ratio from a list of BacktestTrade objects.

Options Analytics Team — 2026-04
"""

import logging
from collections import defaultdict
from typing import Dict, List

import numpy as np

from .models import BacktestStats, BacktestTrade

logger = logging.getLogger(__name__)


def analyze_results(trades: List[BacktestTrade]) -> BacktestStats:
    """Compute aggregate statistics from a list of trades.

    Parameters
    ----------
    trades : List[BacktestTrade]
        Completed trades with P&L data.

    Returns
    -------
    BacktestStats
    """
    if not trades:
        return BacktestStats()

    pnls = [t.pnl for t in trades]
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]

    total = len(trades)
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / total * 100 if total > 0 else 0.0

    avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
    avg_pnl = float(np.mean(pnls))
    total_pnl = sum(pnls)

    # Profit factor
    gross_wins = sum(t.pnl for t in wins)
    gross_losses = abs(sum(t.pnl for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    # Equity curve and drawdown
    equity = _compute_equity_curve(pnls)
    max_dd, max_dd_pct = _compute_max_drawdown(equity)

    # Sharpe ratio (annualized, assuming ~52 trades/year for weeklies)
    sharpe = _compute_sharpe(pnls)

    # Average DTE and hold time
    avg_dte = float(np.mean([t.dte_at_entry for t in trades]))
    avg_days = float(np.mean([
        (t.exit_date - t.entry_date).days for t in trades
    ]))

    return BacktestStats(
        total_trades=total,
        wins=n_wins,
        losses=n_losses,
        win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        avg_pnl=round(avg_pnl, 2),
        total_pnl=round(total_pnl, 2),
        profit_factor=round(profit_factor, 2),
        max_drawdown=round(max_dd, 2),
        max_drawdown_pct=round(max_dd_pct, 1),
        sharpe_ratio=round(sharpe, 2),
        avg_dte_at_entry=round(avg_dte, 1),
        avg_days_in_trade=round(avg_days, 1),
    )


def compute_regime_breakdown(trades: List[BacktestTrade]) -> Dict[str, Dict]:
    """Break down trade stats by regime at entry.

    Returns dict of regime -> {win_rate, avg_pnl, count}.
    """
    by_regime = defaultdict(list)
    for t in trades:
        regime = t.regime or "UNKNOWN"
        by_regime[regime].append(t)

    result = {}
    for regime, regime_trades in by_regime.items():
        pnls = [t.pnl for t in regime_trades]
        wins = sum(1 for t in regime_trades if t.win)
        result[regime] = {
            "count": len(regime_trades),
            "win_rate": round(wins / len(regime_trades) * 100, 1),
            "avg_pnl": round(float(np.mean(pnls)), 2),
            "total_pnl": round(sum(pnls), 2),
        }

    return result


def _compute_equity_curve(pnls: List[float]) -> List[float]:
    """Cumulative equity curve from trade P&Ls."""
    curve = [0.0]
    for pnl in pnls:
        curve.append(curve[-1] + pnl)
    return curve


def _compute_max_drawdown(equity: List[float]):
    """Max drawdown (absolute and percentage) from equity curve."""
    if len(equity) < 2:
        return 0.0, 0.0

    peak = equity[0]
    max_dd = 0.0

    for val in equity[1:]:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd

    # Percentage relative to peak (avoid div by zero)
    peak_at_max_dd = max(abs(p) for p in equity) if equity else 1.0
    max_dd_pct = (max_dd / peak_at_max_dd * 100) if peak_at_max_dd > 0 else 0.0

    return max_dd, max_dd_pct


def _compute_sharpe(pnls: List[float], trades_per_year: float = 52.0) -> float:
    """Annualized Sharpe ratio from trade P&Ls."""
    if len(pnls) < 2:
        return 0.0
    arr = np.array(pnls)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if std < 1e-10:
        return 0.0
    return mean / std * np.sqrt(trades_per_year)
