#!/usr/bin/env python3
"""Cross-asset signal backtest: MOVE/VIX divergence + VVIX regime.

Tests two hypotheses:
    1. MOVE/VIX divergence: when bond vol (MOVE) rises and equity vol (VIX)
       stays flat, buying 60-90 DTE equity vol produces alpha (Choi et al 2017).
       MOVE leads VIX by 5-10 trading days.

    2. VVIX regime: VVIX/VIX ratio as position sizing signal.
       UNSTABLE regime should have higher realized vol → reduce size.
       STABLE regime should have lower realized vol → full size.

Usage:
    python scripts/backtest_cross_asset_signal.py --ticker SPY
    python scripts/backtest_cross_asset_signal.py --ticker SPY --forward 60
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.chain_store import get_swing_signals

logger = logging.getLogger(__name__)


def run_cross_asset_backtest(
    ticker: str,
    forward_days: int = 30,
    divergence_threshold: float = 1.0,
):
    """Backtest cross-asset signals: MOVE/VIX divergence + VVIX regime."""
    signals = get_swing_signals(ticker)
    if not signals:
        print(f"No swing signals found for {ticker}")
        return

    dates = [s["snapshot_date"] for s in signals]
    vrp_pcts = np.array([
        s.get("vrp_overall_pct") if s.get("vrp_overall_pct") is not None else np.nan
        for s in signals
    ])
    move_vix_signals = [s.get("move_vix_signal") for s in signals]
    move_vix_divs = np.array([
        s.get("move_vix_divergence") if s.get("move_vix_divergence") is not None else np.nan
        for s in signals
    ])
    vvix_regimes = [s.get("vvix_regime") for s in signals]
    vvix_ratios = np.array([
        s.get("vvix_ratio") if s.get("vvix_ratio") is not None else np.nan
        for s in signals
    ])
    vvix_size_factors = np.array([
        s.get("vvix_size_factor") if s.get("vvix_size_factor") is not None else np.nan
        for s in signals
    ])

    print(f"\n{'='*60}")
    print(f"CROSS-ASSET SIGNAL BACKTEST — {ticker}")
    print(f"{'='*60}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print(f"Total observations: {len(signals)}")

    move_valid = int(np.sum(~np.isnan(move_vix_divs)))
    vvix_valid = int(np.sum(~np.isnan(vvix_ratios)))
    print(f"MOVE/VIX divergence obs: {move_valid}")
    print(f"VVIX ratio obs: {vvix_valid}")
    print(f"Forward measurement: {forward_days} days")
    print(f"Divergence threshold: {divergence_threshold}")

    # Forward VRP (proxy for premium-selling/buying return)
    forward_vrp = np.full(len(vrp_pcts), np.nan)
    for i in range(len(vrp_pcts) - forward_days):
        fwd = vrp_pcts[i + 1:i + 1 + forward_days]
        clean = fwd[~np.isnan(fwd)]
        if len(clean) >= forward_days // 2:
            forward_vrp[i] = float(np.mean(clean))

    # ═══ MOVE/VIX Divergence ═══

    print(f"\n{'─'*60}")
    print("1. MOVE/VIX DIVERGENCE")
    print(f"{'─'*60}")

    # Signal distribution
    move_counts = {}
    for s in move_vix_signals:
        if s:
            move_counts[s] = move_counts.get(s, 0) + 1
    if move_counts:
        print("\n  Signal distribution:")
        for s, c in sorted(move_counts.items(), key=lambda x: -x[1]):
            print(f"    {s:>20}: {c:4d} ({c/len(signals)*100:.1f}%)")

    # EQUITY_VOL_CHEAP → buy vol (negative VRP = profit from buying)
    cheap_mask = np.array([s == "EQUITY_VOL_CHEAP" for s in move_vix_signals]) & ~np.isnan(forward_vrp)
    cheap_returns = -forward_vrp[cheap_mask]

    # EQUITY_VOL_RICH → sell vol (positive VRP = profit from selling)
    rich_mask = np.array([s == "EQUITY_VOL_RICH" for s in move_vix_signals]) & ~np.isnan(forward_vrp)
    rich_returns = forward_vrp[rich_mask]

    # Divergence z-score based: buy vol when divergence > threshold
    div_buy_mask = (move_vix_divs > divergence_threshold) & ~np.isnan(forward_vrp)
    div_buy_returns = -forward_vrp[div_buy_mask]

    # Baseline
    baseline_mask = ~np.isnan(forward_vrp) & ~np.isnan(vrp_pcts)
    baseline_returns = forward_vrp[baseline_mask]

    _print_stats("BASELINE (always sell premium)", baseline_returns)
    _print_stats("EQUITY_VOL_CHEAP → buy vol", cheap_returns)
    _print_stats("EQUITY_VOL_RICH → sell vol", rich_returns)
    _print_stats(f"Divergence > {divergence_threshold} → buy vol", div_buy_returns)

    # Divergence threshold sensitivity
    if move_valid >= 30:
        print(f"\n  Divergence threshold sensitivity:")
        print(f"  {'Threshold':>10} {'Entries':>8} {'Win%':>8} {'Avg Ret%':>10} {'Sharpe':>8}")
        for thresh in [0.5, 1.0, 1.5, 2.0]:
            mask = (move_vix_divs > thresh) & ~np.isnan(forward_vrp)
            rets = -forward_vrp[mask]  # buying vol
            if len(rets) >= 5:
                win_pct = np.mean(rets > 0) * 100
                avg = np.mean(rets)
                sharpe = avg / np.std(rets) if np.std(rets) > 0 else 0
                print(f"  div>{thresh:<9.1f} {len(rets):>8d} {win_pct:>7.1f}% {avg:>+9.2f}% {sharpe:>+7.2f}")
            else:
                print(f"  div>{thresh:<9.1f} {len(rets):>8d}     — insufficient data")

    # Lead-lag analysis: does MOVE divergence predict VRP changes 5-10 days later?
    if move_valid >= 30:
        print(f"\n  Lead-lag analysis (MOVE divergence → VRP):")
        print(f"  {'Lag (days)':>12} {'Corr':>8} {'N':>6}")
        for lag in [1, 3, 5, 7, 10, 15]:
            if lag + 20 >= len(move_vix_divs):
                continue
            x = move_vix_divs[:-lag]
            y = vrp_pcts[lag:]
            valid = ~np.isnan(x) & ~np.isnan(y)
            if np.sum(valid) >= 20:
                corr = float(np.corrcoef(x[valid], y[valid])[0, 1])
                print(f"  {lag:>12d} {corr:>+7.3f} {int(np.sum(valid)):>6d}")

    # ═══ VVIX Regime Sizing ═══

    print(f"\n{'─'*60}")
    print("2. VVIX REGIME AS SIZING SIGNAL")
    print(f"{'─'*60}")

    # Regime distribution
    vvix_counts = {}
    for r in vvix_regimes:
        if r:
            vvix_counts[r] = vvix_counts.get(r, 0) + 1
    if vvix_counts:
        print("\n  Regime distribution:")
        for r, c in sorted(vvix_counts.items(), key=lambda x: -x[1]):
            print(f"    {r:>12}: {c:4d} ({c/len(signals)*100:.1f}%)")

    # Returns by VVIX regime
    for regime in ["STABLE", "NORMAL", "UNSTABLE"]:
        mask = np.array([r == regime for r in vvix_regimes]) & ~np.isnan(forward_vrp)
        rets = forward_vrp[mask]
        _print_stats(f"VVIX {regime} → sell premium", rets)

    # VVIX-scaled returns: simulate using vvix_size_factor as a multiplier
    scaled_mask = ~np.isnan(vvix_size_factors) & ~np.isnan(forward_vrp)
    if np.sum(scaled_mask) >= 10:
        unscaled = forward_vrp[scaled_mask]
        scaled = forward_vrp[scaled_mask] * vvix_size_factors[scaled_mask]

        print(f"\n  VVIX-SCALED vs UNSCALED premium selling:")
        _print_stats("UNSCALED (full size always)", unscaled)
        _print_stats("VVIX-SCALED (regime-adjusted)", scaled)

        # Key metric: does VVIX scaling reduce drawdown?
        cum_unscaled = np.cumsum(unscaled)
        cum_scaled = np.cumsum(scaled)
        dd_unscaled = _max_drawdown(cum_unscaled)
        dd_scaled = _max_drawdown(cum_scaled)
        dd_improvement = (dd_unscaled - dd_scaled) / abs(dd_unscaled) * 100 if dd_unscaled != 0 else 0

        print(f"\n  Drawdown comparison:")
        print(f"    Unscaled max DD: {dd_unscaled:.2f}%")
        print(f"    VVIX-scaled DD:  {dd_scaled:.2f}%")
        print(f"    Improvement:     {dd_improvement:+.1f}%")

    # ═══ Statistical Significance ═══

    print(f"\n{'─'*60}")
    print("STATISTICAL SIGNIFICANCE")
    print(f"{'─'*60}")

    for label, rets in [
        ("MOVE divergence buy-vol", cheap_returns),
        ("VVIX STABLE sell-premium", forward_vrp[np.array([r == "STABLE" for r in vvix_regimes]) & ~np.isnan(forward_vrp)]),
    ]:
        if len(rets) >= 10:
            mean = np.mean(rets)
            se = np.std(rets, ddof=1) / np.sqrt(len(rets))
            t_stat = mean / se if se > 0 else 0
            print(f"  {label}:")
            print(f"    Mean: {mean:+.3f}%, SE: {se:.3f}%, t-stat: {t_stat:+.2f}")
            if abs(t_stat) >= 2.0:
                print(f"    → SIGNIFICANT at 5% level")
            else:
                print(f"    → NOT significant (t < 2.0), set weight to 0")
        else:
            print(f"  {label}: insufficient data (N={len(rets)})")


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


def _max_drawdown(cumulative: np.ndarray) -> float:
    if len(cumulative) == 0:
        return 0.0
    peak = np.maximum.accumulate(cumulative)
    dd = cumulative - peak
    return float(np.min(dd))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-asset signal backtest")
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol")
    parser.add_argument("--forward", type=int, default=30, help="Forward measurement days")
    parser.add_argument("--divergence", type=float, default=1.0, help="MOVE/VIX divergence threshold")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    run_cross_asset_backtest(args.ticker, args.forward, args.divergence)
