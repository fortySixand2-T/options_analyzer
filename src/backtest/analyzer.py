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


def analyze_results(trades: List[BacktestTrade],
                    equity_curve: List[float] = None,
                    periods_per_year: float = 52.0) -> BacktestStats:
    """Compute aggregate statistics from a list of trades.

    Parameters
    ----------
    trades : List[BacktestTrade]
        Completed trades with P&L data.
    equity_curve : List[float], optional
        A TIME-INDEXED mark-to-market portfolio curve (one value per snapshot/
        period, realized + unrealized $). When provided, Sharpe and max drawdown
        are computed from this curve's periodic returns rather than from the
        per-trade P&L series. This is the correct basis when positions overlap:
        simultaneous correlated moves register as a single high-variance period
        instead of N independent "wins" (which inflated Sharpe — see FINDINGS.md
        F-006). When omitted, falls back to the legacy per-trade computation
        (used by local_backtest and unit tests).
    periods_per_year : float
        Annualization factor for the equity-curve Sharpe — the number of
        snapshot/return periods per year (≈ snapshots ÷ years spanned). For the
        per-trade fallback this is the assumed trades/year.

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

    # Profit factor. Cap at a large finite value when there are no losses —
    # raw float('inf') is not JSON-serializable and broke the result cache
    # round-trip (it round-tripped to None). 999.0 reads clearly as "no losses".
    gross_wins = sum(t.pnl for t in wins)
    gross_losses = abs(sum(t.pnl for t in losses))
    if gross_losses > 0:
        profit_factor = gross_wins / gross_losses
    else:
        profit_factor = 999.0 if gross_wins > 0 else 0.0

    # Equity curve, drawdown, and Sharpe.
    # Prefer a supplied TIME-INDEXED mark-to-market curve (correct when trades
    # overlap — F-006). Fall back to the per-trade cumsum for callers that don't
    # supply one (local_backtest, unit tests).
    if equity_curve is not None and len(equity_curve) >= 2:
        max_dd, max_dd_pct = _compute_max_drawdown(equity_curve)
        sharpe = _compute_sharpe_from_curve(equity_curve, periods_per_year)
        sortino = _compute_sortino_from_curve(equity_curve, periods_per_year)
    else:
        equity = _compute_equity_curve(pnls)
        max_dd, max_dd_pct = _compute_max_drawdown(equity)
        sharpe = _compute_sharpe(pnls)
        sortino = _compute_sortino(pnls)

    # Skew-aware metrics (F-013): payoff skew and expectancy-per-$-risked. For
    # convex/defined-risk payoffs these say more than Sharpe.
    pnl_skew = _compute_skew(pnls)
    # Premium at risk ≈ |entry premium| × 100 (a proxy for capital at risk).
    risks = [abs(t.entry_price) * 100 for t in trades if t.entry_price]
    avg_risk = float(np.mean(risks)) if risks else 0.0
    return_on_risk = (avg_pnl / avg_risk) if avg_risk > 0 else 0.0

    # Tail-risk metrics (F-015): the correct lens for negative-skew premium
    # selling — a high win rate and Sharpe hide the fat left tail.
    cvar_95 = _compute_cvar(pnls, 0.05)
    max_single_loss = round(min(pnls), 2) if pnls else 0.0
    # Calmar = annualized P&L / max drawdown. Annualize over the calendar span.
    span_days = max((max(t.exit_date for t in trades) - min(t.entry_date for t in trades)).days, 1)
    years = span_days / 365.25
    calmar_ratio = ((total_pnl / years) / max_dd) if max_dd > 0 else 0.0

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
        sortino_ratio=round(sortino, 2),
        pnl_skew=round(pnl_skew, 2),
        return_on_risk=round(return_on_risk, 3),
        cvar_95=round(cvar_95, 2),
        max_single_loss=round(max_single_loss, 2),
        calmar_ratio=round(calmar_ratio, 2),
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


def compute_dte_breakdown(trades: List[BacktestTrade]) -> Dict[str, Dict]:
    """Break down trade stats by DTE bucket at entry.

    Buckets: 0-3, 3-5, 5-7, 7-10, 10-14.
    """
    buckets = [
        ("0-3", 0, 3),
        ("3-5", 3, 5),
        ("5-7", 5, 7),
        ("7-10", 7, 10),
        ("10-14", 10, 14),
    ]

    result = {}
    for label, lo, hi in buckets:
        bucket_trades = [t for t in trades if lo <= t.dte_at_entry < hi]
        if not bucket_trades:
            continue
        pnls = [t.pnl for t in bucket_trades]
        wins = sum(1 for t in bucket_trades if t.win)
        result[label] = {
            "count": len(bucket_trades),
            "win_rate": round(wins / len(bucket_trades) * 100, 1),
            "avg_pnl": round(float(np.mean(pnls)), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def compute_pnl_distribution(trades: List[BacktestTrade], n_bins: int = 20) -> List[Dict]:
    """Compute P&L histogram buckets for distribution chart.

    Returns list of {bin_start, bin_end, count, pct}.
    """
    if not trades:
        return []

    pnls = np.array([t.pnl for t in trades])
    min_pnl = float(np.min(pnls))
    max_pnl = float(np.max(pnls))

    if max_pnl - min_pnl < 1e-6:
        return [{"bin_start": min_pnl, "bin_end": max_pnl, "count": len(trades), "pct": 100.0}]

    edges = np.linspace(min_pnl, max_pnl, n_bins + 1)
    counts, _ = np.histogram(pnls, bins=edges)
    total = len(trades)

    result = []
    for i in range(len(counts)):
        if counts[i] > 0:
            result.append({
                "bin_start": round(float(edges[i]), 0),
                "bin_end": round(float(edges[i + 1]), 0),
                "count": int(counts[i]),
                "pct": round(int(counts[i]) / total * 100, 1),
            })
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
    """Annualized Sharpe ratio from a per-trade P&L series (legacy fallback).

    Treats each trade as an independent period — only valid when trades do not
    overlap. For overlapping positions use _compute_sharpe_from_curve.
    """
    if len(pnls) < 2:
        return 0.0
    arr = np.array(pnls)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if std < 1e-10:
        return 0.0
    return mean / std * np.sqrt(trades_per_year)


def _compute_sharpe_from_curve(equity_curve: List[float],
                               periods_per_year: float) -> float:
    """Annualized Sharpe from a time-indexed mark-to-market equity curve.

    Returns are the per-period $ changes of the portfolio's realized+unrealized
    value. Because every open position is marked on the SAME timeline, a day
    when the market moves shows up as one large-variance period (correlated
    positions move together), correctly penalizing Sharpe — unlike the
    per-trade series, which counts correlated overlapping winners as many
    independent samples (F-006).
    """
    arr = np.asarray(equity_curve, dtype=float)
    if arr.size < 3:
        return 0.0
    returns = np.diff(arr)
    if returns.size < 2:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std < 1e-10:
        return 0.0
    return mean / std * np.sqrt(max(periods_per_year, 1e-9))


def _downside_dev(arr: np.ndarray) -> float:
    """Downside deviation: RMS of negative values only (target = 0)."""
    downside = arr[arr < 0]
    if downside.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(downside ** 2)))


def _compute_sortino_from_curve(equity_curve: List[float], periods_per_year: float) -> float:
    """Annualized Sortino from the time-indexed equity curve's periodic returns.

    Like Sharpe but divides by DOWNSIDE deviation only — it does not penalize
    upside variance, so it does not punish positively-skewed payoffs (F-013).
    """
    arr = np.asarray(equity_curve, dtype=float)
    if arr.size < 3:
        return 0.0
    returns = np.diff(arr)
    dd = _downside_dev(returns)
    if dd < 1e-10:
        return 0.0
    return float(np.mean(returns)) / dd * np.sqrt(max(periods_per_year, 1e-9))


def _compute_sortino(pnls: List[float], trades_per_year: float = 52.0) -> float:
    """Per-trade Sortino fallback (no equity curve)."""
    if len(pnls) < 2:
        return 0.0
    arr = np.array(pnls, dtype=float)
    dd = _downside_dev(arr)
    if dd < 1e-10:
        return 0.0
    return float(np.mean(arr)) / dd * np.sqrt(trades_per_year)


def _compute_cvar(pnls: List[float], alpha: float = 0.05) -> float:
    """Conditional VaR / expected shortfall: mean of the worst `alpha` fraction
    of trade P&Ls (at least one trade). The tail-loss number that matters most
    for negative-skew premium selling — Sharpe/win-rate hide it. Negative = a
    loss. Returns 0.0 with no trades."""
    if not pnls:
        return 0.0
    arr = np.sort(np.array(pnls, dtype=float))
    k = max(1, int(np.ceil(len(arr) * alpha)))
    return float(np.mean(arr[:k]))


def _compute_skew(pnls: List[float]) -> float:
    """Skew of the per-trade P&L distribution (Fisher). >0 = positive/convex
    (small frequent losses, rare large gains — the butterfly profile)."""
    if len(pnls) < 3:
        return 0.0
    try:
        from scipy.stats import skew
        return float(skew(np.array(pnls, dtype=float)))
    except Exception:
        return 0.0
