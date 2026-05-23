#!/usr/bin/env python3
"""VRP timing signal backtest.

Replays historical VRP from swing_signals table, computes rolling z-scores,
and measures whether VRP-timed entries outperform always-on premium selling.

Usage:
    python scripts/backtest_vrp_signal.py --ticker SPY --lookback 60
    python scripts/backtest_vrp_signal.py --ticker SPY --z-threshold 1.5

Methodology:
    1. Load VRP% history from swing_signals for given ticker
    2. Compute rolling z-scores (60-day default lookback)
    3. Compare two strategies:
       - ALWAYS-ON: sell premium every day VRP > 0 (VRP regime = RICH)
       - Z-TIMED: sell premium only when VRP z-score > threshold
    4. For each entry, measure 30-day forward return of selling premium
       (proxy: IV - RV over next 30 days = realized VRP)
    5. Report Sharpe, win rate, max drawdown for both strategies
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.chain_store import get_swing_signals, get_vrp_history

logger = logging.getLogger(__name__)


def run_vrp_backtest(
    ticker: str,
    z_lookback: int = 60,
    z_threshold: float = 1.5,
    forward_days: int = 30,
):
    """Backtest VRP timing signal."""
    signals = get_swing_signals(ticker)
    if not signals:
        print(f"No swing signals found for {ticker}")
        return

    dates = [s["snapshot_date"] for s in signals]
    vrp_pcts = np.array([
        s["vrp_overall_pct"] if s["vrp_overall_pct"] is not None else np.nan
        for s in signals
    ])

    valid_mask = ~np.isnan(vrp_pcts)
    valid_count = int(valid_mask.sum())
    print(f"\n{'='*60}")
    print(f"VRP TIMING SIGNAL BACKTEST — {ticker}")
    print(f"{'='*60}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print(f"Total observations: {len(signals)}")
    print(f"Valid VRP observations: {valid_count}")
    print(f"Z-score lookback: {z_lookback} days")
    print(f"Z-score threshold: {z_threshold}")
    print(f"Forward measurement: {forward_days} days")

    if valid_count < z_lookback + forward_days + 10:
        print(f"\nInsufficient data (need {z_lookback + forward_days + 10}+)")
        return

    # Compute rolling z-scores
    z_scores = np.full(len(vrp_pcts), np.nan)
    for i in range(z_lookback, len(vrp_pcts)):
        window = vrp_pcts[i - z_lookback:i]
        clean = window[~np.isnan(window)]
        if len(clean) < 20:
            continue
        mean = np.mean(clean)
        std = np.std(clean, ddof=1)
        if std < 0.01:
            continue
        if not np.isnan(vrp_pcts[i]):
            z_scores[i] = (vrp_pcts[i] - mean) / std

    # Forward returns: realized VRP over next N days
    # Proxy: if VRP is +10% today and stays rich, selling premium captures ~VRP%
    # We use the average VRP% over the next forward_days as the "return"
    forward_vrp = np.full(len(vrp_pcts), np.nan)
    for i in range(len(vrp_pcts) - forward_days):
        fwd = vrp_pcts[i + 1:i + 1 + forward_days]
        clean = fwd[~np.isnan(fwd)]
        if len(clean) >= forward_days // 2:
            forward_vrp[i] = float(np.mean(clean))

    # Strategy 1: ALWAYS-ON — sell whenever VRP > 0
    always_on_mask = (vrp_pcts > 0) & ~np.isnan(forward_vrp) & ~np.isnan(vrp_pcts)
    always_on_returns = forward_vrp[always_on_mask]

    # Strategy 2: Z-TIMED — sell only when z > threshold
    z_timed_mask = (z_scores > z_threshold) & ~np.isnan(forward_vrp)
    z_timed_returns = forward_vrp[z_timed_mask]

    # Strategy 3: Z-TIMED BUY — buy vol when z < -1.0
    z_buy_mask = (z_scores < -1.0) & ~np.isnan(forward_vrp)
    z_buy_returns = -forward_vrp[z_buy_mask]  # negative VRP = profit from buying vol

    print(f"\n{'─'*60}")
    print("STRATEGY COMPARISON")
    print(f"{'─'*60}")

    _print_stats("ALWAYS-ON (VRP>0)", always_on_returns)
    _print_stats(f"Z-TIMED SELL (z>{z_threshold})", z_timed_returns)
    _print_stats("Z-TIMED BUY (z<-1.0)", z_buy_returns)

    # Z-score distribution
    valid_z = z_scores[~np.isnan(z_scores)]
    if len(valid_z) > 0:
        print(f"\n{'─'*60}")
        print("Z-SCORE DISTRIBUTION")
        print(f"{'─'*60}")
        print(f"  Mean:   {np.mean(valid_z):+.2f}")
        print(f"  Std:    {np.std(valid_z):.2f}")
        print(f"  Min:    {np.min(valid_z):+.2f}")
        print(f"  Max:    {np.max(valid_z):+.2f}")
        print(f"  >1.5:   {np.sum(valid_z > 1.5):d} ({np.mean(valid_z > 1.5)*100:.1f}%)")
        print(f"  >2.0:   {np.sum(valid_z > 2.0):d} ({np.mean(valid_z > 2.0)*100:.1f}%)")
        print(f"  <-1.0:  {np.sum(valid_z < -1.0):d} ({np.mean(valid_z < -1.0)*100:.1f}%)")

    # Threshold sensitivity
    print(f"\n{'─'*60}")
    print("THRESHOLD SENSITIVITY (z-timed sell)")
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


def _print_stats(label: str, returns: np.ndarray):
    """Print strategy statistics."""
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
    print(f"    Avg return: {avg:+.2f}% (VRP captured)")
    print(f"    Std dev:    {std:.2f}%")
    print(f"    Sharpe:     {sharpe:+.3f}")
    print(f"    Max DD:     {max_dd:.2f}%")
    print(f"    Total:      {np.sum(returns):+.1f}%")


def _max_drawdown(cumulative: np.ndarray) -> float:
    """Compute max drawdown from cumulative returns."""
    if len(cumulative) == 0:
        return 0.0
    peak = np.maximum.accumulate(cumulative)
    dd = cumulative - peak
    return float(np.min(dd))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRP timing signal backtest")
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol")
    parser.add_argument("--lookback", type=int, default=60, help="Z-score lookback days")
    parser.add_argument("--z-threshold", type=float, default=1.5, help="Z-score entry threshold")
    parser.add_argument("--forward", type=int, default=30, help="Forward measurement days")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    run_vrp_backtest(args.ticker, args.lookback, args.z_threshold, args.forward)
