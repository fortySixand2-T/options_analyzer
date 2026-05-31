"""
Robustness / out-of-sample harness for chain-replay backtests.

The whole point of the bug hunt + invariant tests (FINDINGS F-001…F-013) was to
make the backtester trustworthy enough that THIS can run on it. A single
backtest number is not evidence — a real edge survives being sliced by time and
perturbed by execution assumptions. This module runs a strategy across:

  1. time folds        — contiguous sub-windows: is the edge sign-consistent
                          over time, or driven by one lucky period?
  2. in/out-of-sample  — a held-out recent tail vs the rest: does it generalize?
  3. perturbations     — fill-mode × slippage grid: is the metric stable, and
                          does it degrade *monotonically* (not chaotically — a
                          regression of the F-004 path-stability guarantee)?

It does NOT fit parameters (our strategies are rule-based), so "OOS" here tests
whether a fixed rule's edge persists outside the period it was calibrated on,
and folds test temporal stability. All slices report skew-aware metrics
(Sharpe, Sortino, profit factor, P&L skew, return-on-risk) — Sharpe alone is
misleading for convex/defined-risk payoffs (F-013).
"""

import logging
import statistics
from datetime import timedelta
from typing import Dict, List

from .models import BacktestRequest
from .chain_replay import run_chain_replay

logger = logging.getLogger(__name__)

# A slice needs at least this many trades for its metrics to be worth trusting.
_MIN_TRADES = 10
# In-sample Sharpe below this isn't a real edge — don't dignify OOS as "holding".
_MIN_IS_SHARPE = 0.3


def _metrics(result) -> dict:
    """Compact skew-aware metric snapshot from a BacktestResult."""
    s = result.stats
    return {
        "trades": s.total_trades,
        "win_rate": s.win_rate,
        "pnl": round(s.total_pnl, 0),
        "sharpe": s.sharpe_ratio,
        "sortino": s.sortino_ratio,
        "profit_factor": s.profit_factor,
        "skew": s.pnl_skew,
        "return_on_risk": s.return_on_risk,
    }


def _run_window(req: BacktestRequest, start, end) -> dict:
    """Run the backtest over a sub-window and return its metric snapshot."""
    sub = req.model_copy(update={"start_date": start, "end_date": end})
    m = _metrics(run_chain_replay(sub))
    m["window"] = f"{start}..{end}"
    return m


def time_fold_analysis(req: BacktestRequest, n_folds: int = 4) -> dict:
    """Split the window into contiguous folds and check temporal consistency.

    A robust edge is sign-consistent across folds with bounded dispersion; an
    edge that lives in one fold and dies in the others is regime-fit.
    """
    span = (req.end_date - req.start_date).days
    if span < n_folds * 14:           # need a meaningful span per fold
        n_folds = max(1, span // 14)
    step = max(span // n_folds, 1)

    folds: List[dict] = []
    for i in range(n_folds):
        start = req.start_date + timedelta(days=i * step)
        end = req.end_date if i == n_folds - 1 else req.start_date + timedelta(days=(i + 1) * step)
        folds.append(_run_window(req, start, end))

    valid = [f for f in folds if f["trades"] >= _MIN_TRADES]
    sharpes = [f["sharpe"] for f in valid]
    pnls = [f["pnl"] for f in valid]
    return {
        "folds": folds,
        "aggregate": {
            "folds_total": len(folds),
            "folds_evaluated": len(valid),
            "sharpe_mean": round(statistics.mean(sharpes), 2) if sharpes else 0.0,
            "sharpe_min": round(min(sharpes), 2) if sharpes else 0.0,
            "sharpe_std": round(statistics.pstdev(sharpes), 2) if len(sharpes) > 1 else 0.0,
            "pnl_positive_folds": sum(1 for p in pnls if p > 0),
            "sign_consistent": bool(valid) and (all(p > 0 for p in pnls) or all(p <= 0 for p in pnls)),
        },
    }


def oos_split_analysis(req: BacktestRequest, oos_fraction: float = 0.3) -> dict:
    """In-sample (older) vs out-of-sample (recent tail) comparison.

    `oos_holds` = both slices have enough trades AND the OOS edge keeps the
    in-sample sign without collapsing (OOS Sharpe ≥ half the IS Sharpe when IS
    is positive). Insufficient sample is reported honestly rather than guessed.
    """
    span = (req.end_date - req.start_date).days
    split = req.start_date + timedelta(days=int(span * (1 - oos_fraction)))
    is_m = _run_window(req, req.start_date, split)
    oos_m = _run_window(req, split, req.end_date)

    if is_m["trades"] < _MIN_TRADES or oos_m["trades"] < _MIN_TRADES:
        verdict = "insufficient_sample"
    elif is_m["sharpe"] < _MIN_IS_SHARPE:
        verdict = "no_in_sample_edge"
    elif oos_m["sharpe"] >= 0.5 * is_m["sharpe"]:
        verdict = "holds"
    else:
        verdict = "degrades_oos"

    return {"in_sample": is_m, "out_of_sample": oos_m, "oos_verdict": verdict}


def perturbation_analysis(req: BacktestRequest,
                          fill_modes=("mid", "bid_ask"),
                          slippages=(0.0, 1.0, 2.0, 3.0)) -> dict:
    """Fill-mode × slippage grid. A trustworthy result has a STABLE trade count
    across perturbations (F-004) and P&L that worsens monotonically with
    slippage (F-006) — not chaotic swings."""
    grid: List[dict] = []
    for fm in fill_modes:
        for sl in slippages:
            sub = req.model_copy(update={"fill_mode": fm, "slippage_pct": sl})
            m = _metrics(run_chain_replay(sub))
            m["fill_mode"], m["slippage_pct"] = fm, sl
            grid.append(m)

    trade_counts = {g["trades"] for g in grid}
    # Within a fill mode, P&L should be non-increasing in slippage.
    monotonic = True
    for fm in fill_modes:
        seq = [g["pnl"] for g in grid if g["fill_mode"] == fm]
        if any(seq[i] < seq[i + 1] - 1e-6 for i in range(len(seq) - 1)):
            monotonic = False
    return {
        "grid": grid,
        "trade_count_stable": len(trade_counts) == 1,
        "slippage_monotonic": monotonic,
        "pnl_min": min(g["pnl"] for g in grid),
        "pnl_max": max(g["pnl"] for g in grid),
    }


def run_robustness(req: BacktestRequest, n_folds: int = 4,
                   oos_fraction: float = 0.3) -> dict:
    """Full robustness report + a consolidated verdict.

    `verdict` is intentionally conservative: 'robust' only when the OOS edge
    holds, folds are sign-consistent, and perturbations are stable/monotonic.
    """
    folds = time_fold_analysis(req, n_folds=n_folds)
    oos = oos_split_analysis(req, oos_fraction=oos_fraction)
    pert = perturbation_analysis(req)

    robust = (
        oos["oos_verdict"] == "holds"
        and folds["aggregate"]["sign_consistent"]
        and folds["aggregate"]["pnl_positive_folds"] == folds["aggregate"]["folds_evaluated"]
        and pert["trade_count_stable"]
        and pert["slippage_monotonic"]
    )
    if oos["oos_verdict"] == "insufficient_sample":
        verdict = "insufficient_sample"
    elif robust:
        verdict = "robust"
    else:
        verdict = "fragile_or_no_edge"

    return {
        "strategy": req.strategy,
        "symbol": req.symbol,
        "window": f"{req.start_date}..{req.end_date}",
        "verdict": verdict,
        "time_folds": folds,
        "oos_split": oos,
        "perturbation": pert,
    }
