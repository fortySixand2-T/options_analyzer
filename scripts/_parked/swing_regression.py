#!/usr/bin/env python3
"""
Swing strategy OLS regression for confluence weight calibration (Phase 5b).

Same pattern as per_strategy_regression.py but with swing-specific features:
  - regime_match: 1 if regime matches strategy's preferred regime
  - swing_bias_aligned: 1 if SMA 20/50/200 bias aligns with strategy direction
  - vrp_at_entry: VRP percentage at entry
  - edge_pct: IV-RV edge percentage at entry
  - iv_at_entry: realized vol at entry (control)

Target: per-trade P&L ($)

Usage:
    python scripts/swing_regression.py
"""

import sys
import os
import numpy as np
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from backtest.local_backtest import run_local_backtest
from backtest.models import BacktestRequest


def get_swing_trades(strategy: str):
    """Run unfiltered swing backtest and return trades with signal snapshots."""
    req = BacktestRequest(
        strategy=strategy,
        symbol="SPY",
        start_date=date(2022, 1, 1),
        end_date=date.today(),
        entry_dte_min=14,
        entry_dte_max=45,
        slippage_pct=3.0,
        exit_rule="strategy",
    )
    result = run_local_backtest(req)
    return result.trades


def regime_matches(regime: str, strategy: str) -> int:
    prefs = {
        "calendar_spread": {"HIGH_IV", "MODERATE_IV"},
        "diagonal_spread": {"HIGH_IV", "MODERATE_IV"},
        "iron_butterfly": {"HIGH_IV"},
        "long_straddle": {"LOW_IV"},
    }
    return 1 if regime in prefs.get(strategy, set()) else 0


def swing_bias_aligned(swing_bias_score, strategy: str) -> int:
    if swing_bias_score is None:
        return 0
    directional = {"diagonal_spread"}
    if strategy in directional:
        return 1 if abs(swing_bias_score) >= 3 else 0
    neutral = {"calendar_spread", "iron_butterfly"}
    if strategy in neutral:
        return 1 if abs(swing_bias_score) <= 3 else 0
    # long_straddle: any bias is fine (buying vol)
    return 1


def run_regression(strategy: str, trades):
    """Run OLS regression for a single swing strategy."""
    X_rows = []
    y = []

    for t in trades:
        regime_m = regime_matches(t.regime or "", strategy)
        bias_a = swing_bias_aligned(t.swing_bias_score, strategy)
        vrp = t.vrp_at_entry if t.vrp_at_entry is not None else 0.0
        edge = t.edge_pct if t.edge_pct is not None else 0.0
        iv = t.iv_at_entry if t.iv_at_entry is not None else 0.20

        X_rows.append([regime_m, bias_a, vrp, edge, iv])
        y.append(t.pnl)

    if len(X_rows) < 10:
        print(f"\n{strategy}: only {len(X_rows)} trades — skipping regression")
        return None

    X = np.array(X_rows)
    y = np.array(y)

    ones = np.ones((X.shape[0], 1))
    X_full = np.hstack([ones, X])

    try:
        beta = np.linalg.lstsq(X_full, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        print(f"\n{strategy}: singular matrix — skipping")
        return None

    y_hat = X_full @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

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

    labels = ["intercept", "regime_match", "swing_bias", "vrp", "edge_pct", "iv_at_entry"]

    print(f"\n{'='*65}")
    print(f"  {strategy.upper()}  ({len(trades)} trades)")
    print(f"{'='*65}")
    print(f"  R² = {r2:.4f}   (n={n})")
    print(f"  Mean P&L: ${np.mean(y):.1f}   Std: ${np.std(y):.1f}")
    print(f"\n  {'Feature':<16} {'Coeff':>10} {'SE':>10} {'t-stat':>8} {'Sig':>5}")
    print(f"  {'-'*55}")
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

    signal_names = ["regime_match", "swing_bias", "vrp", "edge_pct"]
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
    strategies = ["calendar_spread", "diagonal_spread", "iron_butterfly", "long_straddle"]

    print("Swing strategy OLS regression for confluence weight calibration")
    print("=" * 65)
    print("Target: per-trade P&L ($)")
    print("Features: regime_match, swing_bias, vrp, edge_pct, iv_at_entry")
    print(f"Data: SPY 2022-01-01 to {date.today()}, 3% slippage, strategy exits")
    print(f"DTE: 14-45")

    results = []
    for strat in strategies:
        print(f"\nFetching trades for {strat}...")
        trades = get_swing_trades(strat)
        print(f"  Got {len(trades)} trades")
        r = run_regression(strat, trades)
        if r:
            results.append(r)

    print(f"\n\n{'='*65}")
    print("SUMMARY")
    print(f"{'='*65}")
    print(f"{'Strategy':<22} {'R²':>8} {'n':>5}  Notes")
    print(f"{'-'*55}")
    for r in results:
        notes = "low explanatory power" if r["r2"] < 0.05 else (
            "moderate" if r["r2"] < 0.15 else "meaningful"
        )
        print(f"{r['strategy']:<22} {r['r2']:>8.4f} {r['n']:>5}  {notes}")

    print(f"\nCurrent swing weights (src/config.py SWING_SCANNER_CONFIG):")
    print(f"  vrp=25%, term_structure=20%, vol_regime=15%, garch_edge=15%,")
    print(f"  directional=10%, dealer_regime=10%, liquidity=5%")
    print(f"\nUpdate weights based on significant coefficients above.")
