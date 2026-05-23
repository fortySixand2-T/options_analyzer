#!/usr/bin/env python3
"""Options flow signal backtest.

Tests whether flow signals (put-call parity deviations, OI changes, volume
ratios) predict forward returns at 30-90 DTE.

Hypotheses:
    1. PCP CALLS_EXPENSIVE: underlying outperforms 50bp/week (Cremers 2010)
    2. Large call OI increases: alpha at 30-90 DTE (Pan & Poteshman 2006)
    3. Extreme P/C ratio: contrarian — very high P/C → bullish reversal

Usage:
    python scripts/backtest_flow_signal.py --ticker SPY
    python scripts/backtest_flow_signal.py --ticker SPY --forward 60
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.chain_store import get_swing_signals

logger = logging.getLogger(__name__)


def run_flow_backtest(
    ticker: str,
    forward_days: int = 30,
):
    """Backtest options flow signals."""
    signals = get_swing_signals(ticker)
    if not signals:
        print(f"No swing signals found for {ticker}")
        return

    dates = [s["snapshot_date"] for s in signals]
    vrp_pcts = np.array([
        s.get("vrp_overall_pct") if s.get("vrp_overall_pct") is not None else np.nan
        for s in signals
    ])
    flow_composites = [s.get("flow_composite") for s in signals]

    flow_valid = sum(1 for f in flow_composites if f is not None)

    print(f"\n{'='*60}")
    print(f"OPTIONS FLOW SIGNAL BACKTEST — {ticker}")
    print(f"{'='*60}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print(f"Total observations: {len(signals)}")
    print(f"Flow composite obs: {flow_valid}")
    print(f"Forward measurement: {forward_days} days")

    # Forward VRP (proxy for premium return)
    forward_vrp = np.full(len(vrp_pcts), np.nan)
    for i in range(len(vrp_pcts) - forward_days):
        fwd = vrp_pcts[i + 1:i + 1 + forward_days]
        clean = fwd[~np.isnan(fwd)]
        if len(clean) >= forward_days // 2:
            forward_vrp[i] = float(np.mean(clean))

    # ═══ Flow Composite Signal ═══

    print(f"\n{'─'*60}")
    print("1. FLOW COMPOSITE SIGNAL")
    print(f"{'─'*60}")

    # Distribution
    flow_counts = {}
    for f in flow_composites:
        if f:
            flow_counts[f] = flow_counts.get(f, 0) + 1
    if flow_counts:
        print("\n  Signal distribution:")
        for f, c in sorted(flow_counts.items(), key=lambda x: -x[1]):
            print(f"    {f:>12}: {c:4d} ({c/len(signals)*100:.1f}%)")

    # Baseline
    baseline_mask = ~np.isnan(forward_vrp) & ~np.isnan(vrp_pcts)
    baseline_returns = forward_vrp[baseline_mask]
    _print_stats("BASELINE (always sell premium)", baseline_returns)

    # BULLISH flow → sell puts (collect premium, expect underlying up)
    bullish_mask = np.array([f == "BULLISH" for f in flow_composites]) & ~np.isnan(forward_vrp)
    bullish_sell_returns = forward_vrp[bullish_mask]
    _print_stats("BULLISH flow → sell puts", bullish_sell_returns)

    # BEARISH flow → sell calls or buy puts
    bearish_mask = np.array([f == "BEARISH" for f in flow_composites]) & ~np.isnan(forward_vrp)
    bearish_buy_returns = -forward_vrp[bearish_mask]
    _print_stats("BEARISH flow → buy vol", bearish_buy_returns)

    # NEUTRAL flow → standard premium selling
    neutral_mask = np.array([f == "NEUTRAL" for f in flow_composites]) & ~np.isnan(forward_vrp)
    neutral_returns = forward_vrp[neutral_mask]
    _print_stats("NEUTRAL flow → sell premium", neutral_returns)

    # ═══ Flow as Filter ═══

    print(f"\n{'─'*60}")
    print("2. FLOW AS PREMIUM-SELLING FILTER")
    print(f"{'─'*60}")
    print("  (Does filtering OUT bearish flow improve selling returns?)")

    # Sell premium only when flow != BEARISH
    no_bearish_mask = np.array([f != "BEARISH" for f in flow_composites]) & ~np.isnan(forward_vrp) & ~np.isnan(vrp_pcts)
    no_bearish_returns = forward_vrp[no_bearish_mask]
    _print_stats("Sell when flow != BEARISH", no_bearish_returns)

    # Sell premium only when flow == BULLISH
    _print_stats("Sell only when flow == BULLISH", bullish_sell_returns)

    # ═══ Flow + VRP Combo ═══

    print(f"\n{'─'*60}")
    print("3. FLOW + VRP COMBINATION")
    print(f"{'─'*60}")
    print("  (Does adding flow to VRP timing improve results?)")

    vrp_rich_mask = (vrp_pcts > 0) & ~np.isnan(forward_vrp)
    vrp_rich_returns = forward_vrp[vrp_rich_mask]
    _print_stats("VRP>0 only", vrp_rich_returns)

    vrp_and_bullish = vrp_rich_mask & np.array([f == "BULLISH" for f in flow_composites])
    vrp_bullish_returns = forward_vrp[vrp_and_bullish]
    _print_stats("VRP>0 + BULLISH flow", vrp_bullish_returns)

    vrp_not_bearish = vrp_rich_mask & np.array([f != "BEARISH" for f in flow_composites])
    vrp_nb_returns = forward_vrp[vrp_not_bearish]
    _print_stats("VRP>0 + flow != BEARISH", vrp_nb_returns)

    # ═══ Transition Analysis ═══

    print(f"\n{'─'*60}")
    print("4. FLOW REGIME TRANSITIONS")
    print(f"{'─'*60}")

    transitions = {}
    for i in range(1, len(flow_composites)):
        prev = flow_composites[i - 1]
        curr = flow_composites[i]
        if prev and curr and prev != curr:
            key = f"{prev} → {curr}"
            if key not in transitions:
                transitions[key] = {"count": 0, "returns": []}
            transitions[key]["count"] += 1
            if not np.isnan(forward_vrp[i]):
                transitions[key]["returns"].append(forward_vrp[i])

    if transitions:
        print(f"\n  {'Transition':>25} {'Count':>6} {'Avg VRP%':>10} {'Win%':>8}")
        for key, data in sorted(transitions.items(), key=lambda x: -x[1]["count"]):
            rets = np.array(data["returns"])
            if len(rets) >= 3:
                avg = np.mean(rets)
                win = np.mean(rets > 0) * 100
                print(f"  {key:>25} {data['count']:>6d} {avg:>+9.2f}% {win:>7.1f}%")
            else:
                print(f"  {key:>25} {data['count']:>6d}        — insufficient data")

    # ═══ Statistical Significance ═══

    print(f"\n{'─'*60}")
    print("STATISTICAL SIGNIFICANCE")
    print(f"{'─'*60}")

    test_cases = [
        ("BULLISH flow sell premium", bullish_sell_returns),
        ("BEARISH flow buy vol", bearish_buy_returns),
        ("Flow filter (no bearish)", no_bearish_returns),
    ]

    for label, rets in test_cases:
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

    # Alpha vs baseline
    if len(bullish_sell_returns) >= 10 and len(baseline_returns) >= 10:
        alpha = float(np.mean(bullish_sell_returns) - np.mean(baseline_returns))
        annualized = alpha * (252 / forward_days)
        print(f"\n  Flow-timed vs baseline:")
        print(f"    Alpha per period: {alpha:+.2f}%")
        print(f"    Annualized:       {annualized:+.1f}%")


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
    parser = argparse.ArgumentParser(description="Options flow signal backtest")
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol")
    parser.add_argument("--forward", type=int, default=30, help="Forward measurement days")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    run_flow_backtest(args.ticker, args.forward)
