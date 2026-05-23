#!/usr/bin/env python3
"""Skew mean-reversion backtest.

Replays historical skew from swing_signals, computes rolling z-scores,
and tests whether extreme skew predicts future returns.

Hypothesis (Xing, Zhang & Zhao 2010):
    - STEEP skew (z > 1.5): puts expensive → sell puts over next 30-60 days
    - FLAT/INVERTED skew (z < -1.0): puts cheap → buy vol

Usage:
    python scripts/backtest_skew_signal.py --ticker SPY --lookback 60
    python scripts/backtest_skew_signal.py --ticker SPY --z-threshold 1.5
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.chain_store import get_swing_signals

logger = logging.getLogger(__name__)


def run_skew_backtest(
    ticker: str,
    z_lookback: int = 60,
    z_threshold_steep: float = 1.5,
    z_threshold_flat: float = -1.0,
    forward_days: int = 30,
):
    """Backtest skew mean-reversion signal."""
    signals = get_swing_signals(ticker)
    if not signals:
        print(f"No swing signals found for {ticker}")
        return

    dates = [s["snapshot_date"] for s in signals]
    skew_vals = np.array([
        s.get("skew_25d") if s.get("skew_25d") is not None else np.nan
        for s in signals
    ])
    vrp_pcts = np.array([
        s.get("vrp_overall_pct") if s.get("vrp_overall_pct") is not None else np.nan
        for s in signals
    ])
    skew_regimes = [s.get("skew_regime", "NORMAL") for s in signals]

    valid_mask = ~np.isnan(skew_vals)
    valid_count = int(valid_mask.sum())

    print(f"\n{'='*60}")
    print(f"SKEW MEAN-REVERSION BACKTEST — {ticker}")
    print(f"{'='*60}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print(f"Total observations: {len(signals)}")
    print(f"Valid skew observations: {valid_count}")
    print(f"Z-score lookback: {z_lookback} days")
    print(f"Steep threshold: z > {z_threshold_steep}")
    print(f"Flat threshold: z < {z_threshold_flat}")
    print(f"Forward measurement: {forward_days} days")

    if valid_count < z_lookback + forward_days + 10:
        print(f"\nInsufficient data (need {z_lookback + forward_days + 10}+)")
        return

    # Compute rolling z-scores of normalized skew
    z_scores = np.full(len(skew_vals), np.nan)
    for i in range(z_lookback, len(skew_vals)):
        window = skew_vals[i - z_lookback:i]
        clean = window[~np.isnan(window)]
        if len(clean) < 20:
            continue
        mean = np.mean(clean)
        std = np.std(clean, ddof=1)
        if std < 1e-8:
            continue
        if not np.isnan(skew_vals[i]):
            z_scores[i] = (skew_vals[i] - mean) / std

    # Forward returns: use VRP% as proxy for premium-selling return
    # When skew is steep and mean-reverts, selling puts captures positive VRP
    forward_vrp = np.full(len(vrp_pcts), np.nan)
    for i in range(len(vrp_pcts) - forward_days):
        fwd = vrp_pcts[i + 1:i + 1 + forward_days]
        clean = fwd[~np.isnan(fwd)]
        if len(clean) >= forward_days // 2:
            forward_vrp[i] = float(np.mean(clean))

    # Forward skew change: does extreme skew mean-revert?
    forward_skew_change = np.full(len(skew_vals), np.nan)
    for i in range(len(skew_vals) - forward_days):
        if np.isnan(skew_vals[i]):
            continue
        fwd = skew_vals[i + 1:i + 1 + forward_days]
        clean = fwd[~np.isnan(fwd)]
        if len(clean) >= forward_days // 2:
            forward_skew_change[i] = float(np.mean(clean)) - skew_vals[i]

    # ── Strategy 1: STEEP skew → sell puts (skew mean-reverts, VRP captured) ──
    steep_mask = (z_scores > z_threshold_steep) & ~np.isnan(forward_vrp)
    steep_returns = forward_vrp[steep_mask]
    steep_skew_chg = forward_skew_change[steep_mask & ~np.isnan(forward_skew_change)]

    # ── Strategy 2: FLAT/INVERTED skew → buy vol (cheap puts, vol expansion) ──
    flat_mask = (z_scores < z_threshold_flat) & ~np.isnan(forward_vrp)
    flat_returns = -forward_vrp[flat_mask]  # buying vol profits when VRP < 0
    flat_skew_chg = forward_skew_change[flat_mask & ~np.isnan(forward_skew_change)]

    # ── Strategy 3: Regime-based (use skew_regime field directly) ──
    regime_steep_mask = np.array([r == "STEEP" for r in skew_regimes]) & ~np.isnan(forward_vrp)
    regime_steep_returns = forward_vrp[regime_steep_mask]

    # ── Baseline: always-on premium selling ──
    baseline_mask = ~np.isnan(forward_vrp) & ~np.isnan(skew_vals)
    baseline_returns = forward_vrp[baseline_mask]

    print(f"\n{'─'*60}")
    print("STRATEGY COMPARISON")
    print(f"{'─'*60}")

    _print_stats("BASELINE (always sell)", baseline_returns)
    _print_stats(f"STEEP SKEW SELL (z>{z_threshold_steep})", steep_returns)
    _print_stats(f"FLAT SKEW BUY (z<{z_threshold_flat})", flat_returns)
    _print_stats("REGIME=STEEP (sell puts)", regime_steep_returns)

    # Mean-reversion check
    print(f"\n{'─'*60}")
    print("SKEW MEAN-REVERSION CHECK")
    print(f"{'─'*60}")
    if len(steep_skew_chg) >= 5:
        print(f"  After STEEP skew (z>{z_threshold_steep}):")
        print(f"    Avg skew change: {np.mean(steep_skew_chg):+.4f}")
        print(f"    % that reverted: {np.mean(steep_skew_chg < 0)*100:.1f}%")
        print(f"    N: {len(steep_skew_chg)}")
    else:
        print(f"  STEEP skew: insufficient data (N={len(steep_skew_chg)})")

    if len(flat_skew_chg) >= 5:
        print(f"  After FLAT skew (z<{z_threshold_flat}):")
        print(f"    Avg skew change: {np.mean(flat_skew_chg):+.4f}")
        print(f"    % that steepened: {np.mean(flat_skew_chg > 0)*100:.1f}%")
        print(f"    N: {len(flat_skew_chg)}")
    else:
        print(f"  FLAT skew: insufficient data (N={len(flat_skew_chg)})")

    # Z-score distribution
    valid_z = z_scores[~np.isnan(z_scores)]
    if len(valid_z) > 0:
        print(f"\n{'─'*60}")
        print("SKEW Z-SCORE DISTRIBUTION")
        print(f"{'─'*60}")
        print(f"  Mean:   {np.mean(valid_z):+.2f}")
        print(f"  Std:    {np.std(valid_z):.2f}")
        print(f"  >1.5:   {np.sum(valid_z > 1.5):d} ({np.mean(valid_z > 1.5)*100:.1f}%)")
        print(f"  >2.0:   {np.sum(valid_z > 2.0):d} ({np.mean(valid_z > 2.0)*100:.1f}%)")
        print(f"  <-1.0:  {np.sum(valid_z < -1.0):d} ({np.mean(valid_z < -1.0)*100:.1f}%)")

    # Regime distribution
    regime_counts = {}
    for r in skew_regimes:
        if r:
            regime_counts[r] = regime_counts.get(r, 0) + 1
    if regime_counts:
        print(f"\n{'─'*60}")
        print("SKEW REGIME DISTRIBUTION")
        print(f"{'─'*60}")
        for r, c in sorted(regime_counts.items(), key=lambda x: -x[1]):
            print(f"  {r:>12}: {c:4d} ({c/len(skew_regimes)*100:.1f}%)")

    # Threshold sensitivity
    print(f"\n{'─'*60}")
    print("THRESHOLD SENSITIVITY (steep skew → sell puts)")
    print(f"{'─'*60}")
    print(f"  {'Threshold':>10} {'Entries':>8} {'Win%':>8} {'Avg VRP%':>10} {'Sharpe':>8}")
    for thresh in [0.5, 1.0, 1.5, 2.0, 2.5]:
        mask = (z_scores > thresh) & ~np.isnan(forward_vrp)
        rets = forward_vrp[mask]
        if len(rets) >= 5:
            win_pct = np.mean(rets > 0) * 100
            avg = np.mean(rets)
            sharpe = np.mean(rets) / np.std(rets) if np.std(rets) > 0 else 0
            print(f"  z>{thresh:<9.1f} {len(rets):>8d} {win_pct:>7.1f}% {avg:>+9.2f}% {sharpe:>+7.2f}")
        else:
            print(f"  z>{thresh:<9.1f} {len(rets):>8d}     — insufficient data")

    # Alpha estimation
    if len(steep_returns) >= 10 and len(baseline_returns) >= 10:
        alpha = float(np.mean(steep_returns) - np.mean(baseline_returns))
        annualized = alpha * (252 / forward_days)
        print(f"\n{'─'*60}")
        print("ALPHA ESTIMATE")
        print(f"{'─'*60}")
        print(f"  Skew-timed vs baseline: {alpha:+.2f}% per {forward_days}-day period")
        print(f"  Annualized alpha:       {annualized:+.1f}%")
        print(f"  Target (Xing 2010):     >3% annualized")
        if annualized >= 3.0:
            print(f"  → PASS: skew signal validated, keep 15% weight")
        else:
            print(f"  → FAIL: reduce skew weight from 15% to 5%")


def _print_stats(label: str, returns: np.ndarray):
    print(f"\n  {label}")
    if len(returns) < 5:
        print(f"    Entries: {len(returns)} — insufficient data")
        return

    win_pct = np.mean(returns > 0) * 100
    avg = np.mean(returns)
    std = np.std(returns, ddof=1)
    sharpe = avg / std if std > 0 else 0
    cumulative = np.cumsum(returns)
    max_dd = _max_drawdown(cumulative)

    print(f"    Entries:    {len(returns)}")
    print(f"    Win rate:   {win_pct:.1f}%")
    print(f"    Avg return: {avg:+.2f}%")
    print(f"    Std dev:    {std:.2f}%")
    print(f"    Sharpe:     {sharpe:+.3f}")
    print(f"    Max DD:     {max_dd:.2f}%")
    print(f"    Total:      {np.sum(returns):+.1f}%")


def _max_drawdown(cumulative: np.ndarray) -> float:
    if len(cumulative) == 0:
        return 0.0
    peak = np.maximum.accumulate(cumulative)
    dd = cumulative - peak
    return float(np.min(dd))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skew mean-reversion backtest")
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol")
    parser.add_argument("--lookback", type=int, default=60, help="Z-score lookback days")
    parser.add_argument("--z-steep", type=float, default=1.5, help="Steep skew z threshold")
    parser.add_argument("--z-flat", type=float, default=-1.0, help="Flat skew z threshold")
    parser.add_argument("--forward", type=int, default=30, help="Forward measurement days")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    run_skew_backtest(args.ticker, args.lookback, args.z_steep, args.z_flat, args.forward)
