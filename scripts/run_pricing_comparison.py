#!/usr/bin/env python3
"""Compare Black-Scholes vs real bid/ask pricing in backtests.

Runs the same agents/tickers/dates through both pricing modes and
prints a side-by-side comparison. Real pricing uses actual chain
snapshot bid/ask (sell at bid, buy at ask), while BS uses theoretical
prices with a slippage estimate.

Usage:
    python scripts/run_pricing_comparison.py
    python scripts/run_pricing_comparison.py --ticker SPY --tier short_term
    python scripts/run_pricing_comparison.py --ticker SPY QQQ IWM --tier short_term
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agents.agent_config import load_config
from backtest.agent_backtest import run_agent_backtest

SEP = "=" * 80
LINE = "-" * 80


def _run_tier(tickers, tier, start, end, slippage, config, source="chain_store"):
    """Run both BS and real pricing for a tier, return (bs_result, real_result)."""
    print(f"  Running {tier} — Black-Scholes pricing ({source})...", flush=True)
    bs = run_agent_backtest(
        tickers=tickers, start_date=start, end_date=end,
        config=config, dte_tier=tier, slippage_pct=slippage,
        pricing_mode="bs", source=source,
    )

    print(f"  Running {tier} — Real bid/ask pricing ({source})...", flush=True)
    real = run_agent_backtest(
        tickers=tickers, start_date=start, end_date=end,
        config=config, dte_tier=tier, slippage_pct=slippage,
        pricing_mode="real", source=source,
    )

    return bs, real


def _agent_stats(result):
    """Extract aggregate stats from an AgentBacktestSummary."""
    all_trades = []
    for ar in result.agent_results.values():
        all_trades.extend(ar.trades)

    if not all_trades:
        return {"trades": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_dd": 0, "pf": 0, "sharpe": 0}

    pnls = np.array([t.pnl for t in all_trades])
    wins = sum(1 for t in all_trades if t.win)
    gross_p = sum(t.pnl for t in all_trades if t.pnl > 0)
    gross_l = abs(sum(t.pnl for t in all_trades if t.pnl < 0))

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd = abs(np.min(equity - peak)) if len(equity) > 0 else 0

    sharpe = (
        np.mean(pnls) / np.std(pnls, ddof=1) * np.sqrt(252 / 30)
        if len(pnls) > 1 and np.std(pnls) > 0 else 0
    )

    return {
        "trades": len(all_trades),
        "win_rate": wins / len(all_trades) * 100,
        "total_pnl": sum(t.pnl for t in all_trades),
        "avg_pnl": np.mean(pnls),
        "max_dd": max_dd,
        "pf": gross_p / gross_l if gross_l > 0 else float("inf"),
        "sharpe": sharpe,
    }


def _per_agent_stats(result):
    """Extract per-agent stats."""
    rows = {}
    for agent_id, ar in result.agent_results.items():
        trades = ar.trades
        if not trades:
            rows[agent_id] = {"trades": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}
            continue
        pnls = [t.pnl for t in trades]
        wins = sum(1 for t in trades if t.win)
        rows[agent_id] = {
            "trades": len(trades),
            "win_rate": wins / len(trades) * 100,
            "total_pnl": sum(pnls),
            "avg_pnl": np.mean(pnls),
        }
    return rows


def _print_comparison(tier, bs, real):
    """Print side-by-side comparison for one tier."""
    bs_s = _agent_stats(bs)
    real_s = _agent_stats(real)

    print(f"\n{LINE}")
    print(f"  {tier.upper().replace('_', ' ')} — BS vs REAL PRICING")
    print(LINE)

    headers = f"  {'Metric':>20} {'Black-Scholes':>15} {'Real Bid/Ask':>15} {'Delta':>12}"
    print(headers)
    print(f"  {'':>20} {'':>15} {'':>15} {'':>12}")

    metrics = [
        ("Trades", "trades", "d"),
        ("Win Rate", "win_rate", ".1f"),
        ("Total P&L", "total_pnl", "+,.2f"),
        ("Avg P&L", "avg_pnl", "+,.2f"),
        ("Max Drawdown", "max_dd", ",.2f"),
        ("Profit Factor", "pf", ".2f"),
        ("Sharpe", "sharpe", "+.3f"),
    ]

    for label, key, fmt in metrics:
        bv = bs_s[key]
        rv = real_s[key]
        delta = rv - bv

        if fmt == "d":
            print(f"  {label:>20} {bv:>15d} {rv:>15d} {delta:>+12d}")
        elif key == "win_rate":
            print(f"  {label:>20} {bv:>14.1f}% {rv:>14.1f}% {delta:>+11.1f}%")
        elif key in ("total_pnl", "avg_pnl", "max_dd"):
            print(f"  {label:>20} ${bv:>13,.2f} ${rv:>13,.2f} ${delta:>+10,.2f}")
        elif key == "pf":
            pf_bs = f"{bv:.2f}" if bv < 999 else "inf"
            pf_real = f"{rv:.2f}" if rv < 999 else "inf"
            print(f"  {label:>20} {pf_bs:>15} {pf_real:>15} {delta:>+12.2f}")
        else:
            print(f"  {label:>20} {bv:>+15.3f} {rv:>+15.3f} {delta:>+12.3f}")

    # Per-agent breakdown
    bs_agents = _per_agent_stats(bs)
    real_agents = _per_agent_stats(real)

    all_agents = sorted(set(list(bs_agents.keys()) + list(real_agents.keys())))
    if all_agents:
        print(f"\n  Per-Agent Breakdown:")
        print(f"  {'Agent':>25} {'BS Trades':>10} {'Real Trades':>12} "
              f"{'BS P&L':>12} {'Real P&L':>12} {'BS Win%':>8} {'Real Win%':>10}")
        for agent_id in all_agents:
            ba = bs_agents.get(agent_id, {"trades": 0, "win_rate": 0, "total_pnl": 0})
            ra = real_agents.get(agent_id, {"trades": 0, "win_rate": 0, "total_pnl": 0})
            print(f"  {agent_id:>25} {ba['trades']:>10} {ra['trades']:>12} "
                  f"${ba['total_pnl']:>10,.2f} ${ra['total_pnl']:>10,.2f} "
                  f"{ba['win_rate']:>7.1f}% {ra['win_rate']:>9.1f}%")

    # Exit reason comparison
    print(f"\n  Exit Reasons:")
    bs_exits = {}
    real_exits = {}
    for ar in bs.agent_results.values():
        for t in ar.trades:
            bs_exits[t.exit_reason] = bs_exits.get(t.exit_reason, 0) + 1
    for ar in real.agent_results.values():
        for t in ar.trades:
            real_exits[t.exit_reason] = real_exits.get(t.exit_reason, 0) + 1

    all_reasons = sorted(set(list(bs_exits.keys()) + list(real_exits.keys())))
    print(f"  {'Reason':>18} {'BS':>6} {'Real':>6}")
    for reason in all_reasons:
        print(f"  {reason:>18} {bs_exits.get(reason, 0):>6} {real_exits.get(reason, 0):>6}")


def main():
    parser = argparse.ArgumentParser(description="BS vs Real pricing comparison")
    parser.add_argument("--ticker", nargs="+", default=["SPY", "QQQ", "IWM"])
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument("--tier", default="short_term",
                        choices=["short_term", "swing", "medium_term", "long_term", "all"])
    parser.add_argument("--slippage", type=float, default=3.0)
    parser.add_argument("--source", default="chain_store",
                        choices=["chain_store", "dolt"],
                        help="Data source for chain snapshots")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    config = load_config()
    tickers = args.ticker

    if args.tier == "all":
        tiers = ["short_term", "swing", "medium_term", "long_term"]
    else:
        tiers = [args.tier]

    print(f"\n{SEP}")
    print(f"  PRICING MODE COMPARISON: BLACK-SCHOLES vs REAL BID/ASK")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Period:  {args.start} to {args.end}")
    print(f"  BS Slippage: {args.slippage}%  |  Real: bid/ask spread (no added slippage)")
    print(f"  Data source: {args.source}")
    print(SEP)

    all_bs = {}
    all_real = {}

    for tier in tiers:
        print(f"\n  Processing {tier}...")
        bs, real = _run_tier(tickers, tier, args.start, args.end, args.slippage, config, args.source)
        all_bs[tier] = bs
        all_real[tier] = real
        _print_comparison(tier, bs, real)

    if len(tiers) > 1:
        print(f"\n{SEP}")
        print(f"  PORTFOLIO SUMMARY")
        print(SEP)

        total_bs_pnl = 0
        total_real_pnl = 0
        total_bs_trades = 0
        total_real_trades = 0

        for tier in tiers:
            bs_s = _agent_stats(all_bs[tier])
            real_s = _agent_stats(all_real[tier])
            label = tier.upper().replace("_", " ")
            print(f"  {label:>15}  BS: {bs_s['trades']:>4} trades ${bs_s['total_pnl']:>+12,.2f}  |  "
                  f"Real: {real_s['trades']:>4} trades ${real_s['total_pnl']:>+12,.2f}")
            total_bs_pnl += bs_s["total_pnl"]
            total_real_pnl += real_s["total_pnl"]
            total_bs_trades += bs_s["trades"]
            total_real_trades += real_s["trades"]

        print(f"\n  {'TOTAL':>15}  BS: {total_bs_trades:>4} trades ${total_bs_pnl:>+12,.2f}  |  "
              f"Real: {total_real_trades:>4} trades ${total_real_pnl:>+12,.2f}")
        pnl_diff = total_real_pnl - total_bs_pnl
        pnl_pct = pnl_diff / abs(total_bs_pnl) * 100 if total_bs_pnl != 0 else 0
        print(f"  {'DELTA':>15}  P&L: ${pnl_diff:>+12,.2f} ({pnl_pct:>+.1f}%)")
        print(f"  {'TRADES':>15}  {total_real_trades - total_bs_trades:>+d} "
              f"({'fewer' if total_real_trades < total_bs_trades else 'more'} in real mode)")


if __name__ == "__main__":
    main()
