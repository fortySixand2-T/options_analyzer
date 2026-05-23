"""
Per-strategy OLS regression for confluence weight calibration.

Pooled regression gave R²=0.0147 — signals explain almost nothing when
strategies are mixed. This script runs separate regressions per strategy
to see if signals matter within each strategy independently.

Features:
  - regime_match: 1 if regime matches strategy's preferred regime
  - bias_aligned: 1 if bias direction matches strategy direction
  - edge_pct: IV-RV edge percentage at entry
  - iv_at_entry: realized vol at entry (control)

Target: per-trade P&L ($)
"""

import sys
import json
import numpy as np
from datetime import date

sys.path.insert(0, "/app/src")

from backtest.local_backtest import run_local_backtest
from backtest.models import BacktestRequest


def get_trades(strategy: str):
    """Run unfiltered backtest and return trades with signal snapshots."""
    req = BacktestRequest(
        strategy=strategy,
        symbol="SPY",
        start_date=date(2022, 1, 1),
        end_date=date(2026, 4, 25),
        slippage_pct=3.0,
        exit_rule="strategy",
    )
    result = run_local_backtest(req)
    return result.trades


def regime_matches(regime: str, strategy: str) -> int:
    """Does the regime match the strategy's preferred regime?"""
    prefs = {
        "short_put_spread": {"HIGH_IV", "MODERATE_IV"},
        "long_call_spread": {"LOW_IV", "MODERATE_IV"},
        "long_put_spread": {"LOW_IV", "MODERATE_IV"},
        "butterfly": {"LOW_IV", "MODERATE_IV"},
    }
    return 1 if regime in prefs.get(strategy, set()) else 0


def bias_aligned(bias_score, strategy: str) -> int:
    """Does the bias direction match the strategy's direction?"""
    if bias_score is None:
        return 0
    bullish = {"short_put_spread", "long_call_spread"}
    bearish = {"long_put_spread"}
    if strategy in bullish:
        return 1 if bias_score >= 2 else 0
    if strategy in bearish:
        return 1 if bias_score <= -2 else 0
    # butterfly: neutral
    return 1 if abs(bias_score) <= 3 else 0


def run_regression(strategy: str, trades):
    """Run OLS regression for a single strategy."""
    X_rows = []
    y = []

    for t in trades:
        regime_m = regime_matches(t.regime or "", strategy)
        bias_a = bias_aligned(t.bias_score, strategy)
        edge = t.edge_pct if t.edge_pct is not None else 0.0
        iv = t.iv_at_entry if t.iv_at_entry is not None else 0.20

        X_rows.append([regime_m, bias_a, edge, iv])
        y.append(t.pnl)

    if len(X_rows) < 10:
        print(f"\n{strategy}: only {len(X_rows)} trades — skipping regression")
        return None

    X = np.array(X_rows)
    y = np.array(y)

    # Add intercept
    ones = np.ones((X.shape[0], 1))
    X_full = np.hstack([ones, X])

    # OLS: beta = (X'X)^-1 X'y
    try:
        beta = np.linalg.lstsq(X_full, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        print(f"\n{strategy}: singular matrix — skipping")
        return None

    y_hat = X_full @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Standard errors
    n, k = X_full.shape
    if n > k:
        mse = ss_res / (n - k)
        try:
            var_beta = mse * np.linalg.inv(X_full.T @ X_full)
            se = np.sqrt(np.diag(var_beta))
        except np.linalg.LinAlgError:
            se = np.full(k, np.nan)
        t_stats = beta / se
    else:
        se = np.full(k, np.nan)
        t_stats = np.full(k, np.nan)

    labels = ["intercept", "regime_match", "bias_aligned", "edge_pct", "iv_at_entry"]

    print(f"\n{'='*60}")
    print(f"  {strategy.upper()}  ({len(trades)} trades)")
    print(f"{'='*60}")
    print(f"  R² = {r2:.4f}   (n={n})")
    print(f"  Mean P&L: ${np.mean(y):.1f}   Std: ${np.std(y):.1f}")
    print(f"\n  {'Feature':<16} {'Coeff':>10} {'SE':>10} {'t-stat':>8} {'Sig':>5}")
    print(f"  {'-'*50}")
    for j, label in enumerate(labels):
        sig = ""
        if not np.isnan(t_stats[j]):
            if abs(t_stats[j]) > 2.58:
                sig = "***"
            elif abs(t_stats[j]) > 1.96:
                sig = "**"
            elif abs(t_stats[j]) > 1.65:
                sig = "*"
        print(f"  {label:<16} {beta[j]:>10.2f} {se[j]:>10.2f} {t_stats[j]:>8.2f} {sig:>5}")

    # Practical signal importance: only count positive, significant coefficients
    signal_names = ["regime_match", "bias_aligned", "edge_pct"]
    pos_coeffs = {}
    for j, name in enumerate(signal_names, 1):
        if beta[j] > 0 and not np.isnan(t_stats[j]) and abs(t_stats[j]) > 1.65:
            pos_coeffs[name] = beta[j]

    if pos_coeffs:
        total = sum(pos_coeffs.values())
        print(f"\n  Significant positive signals → implied weights:")
        for name, coeff in pos_coeffs.items():
            print(f"    {name}: {coeff/total*100:.1f}%")
    else:
        print(f"\n  No signals statistically significant at p<0.10")

    return {"strategy": strategy, "r2": r2, "n": n, "beta": beta.tolist(), "labels": labels}


if __name__ == "__main__":
    strategies = ["short_put_spread", "long_call_spread", "long_put_spread", "butterfly"]

    print("Per-strategy OLS regression for confluence weight calibration")
    print("=" * 60)
    print("Target: per-trade P&L ($)")
    print("Features: regime_match, bias_aligned, edge_pct, iv_at_entry")
    print("Data: SPY 2022-01-01 to 2026-04-25, 3% slippage, strategy exits")

    results = []
    for strat in strategies:
        print(f"\nFetching trades for {strat}...")
        trades = get_trades(strat)
        print(f"  Got {len(trades)} trades")
        r = run_regression(strat, trades)
        if r:
            results.append(r)

    # Summary
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Strategy':<22} {'R²':>8} {'n':>5}  Notes")
    print(f"{'-'*60}")
    for r in results:
        notes = "low explanatory power" if r["r2"] < 0.05 else ("moderate" if r["r2"] < 0.15 else "meaningful")
        print(f"{r['strategy']:<22} {r['r2']:>8.4f} {r['n']:>5}  {notes}")
