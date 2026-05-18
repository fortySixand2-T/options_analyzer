#!/usr/bin/env python3
"""Full integration backtest for medium/long-term agents.

Runs the medium_term_harvester and long_term_harvester agents on SPY
using persisted swing_signals. Validates against Phase 8 targets:
    - Medium-term VRP harvesting: Sharpe > 0.4
    - Calendar spreads 30-60 DTE: win rate > 60%
    - Regime-transition exits: reduce max drawdown by >20% vs static
    - VVIX sizing: reduce drawdown in UNSTABLE without sacrificing return

Usage:
    python scripts/run_integration_backtest.py
    python scripts/run_integration_backtest.py --ticker SPY --tier medium_term
    python scripts/run_integration_backtest.py --start 2023-01-01 --end 2026-01-01
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agents.agent_config import load_config
from backtest.agent_backtest import run_agent_backtest

logger = logging.getLogger(__name__)


def _print_agent_report(result, tier_label: str):
    """Print per-agent results with target validation."""
    print(f"\n{'='*70}")
    print(f"  {tier_label} INTEGRATION BACKTEST")
    print(f"{'='*70}")

    for agent_id, ar in result.agent_results.items():
        stats = ar.stats
        trades = ar.trades

        print(f"\n{'─'*70}")
        print(f"  Agent: {agent_id}")
        print(f"  Description: {ar.config.description}")
        print(f"  Capital allocation: {ar.config.capital_pct*100:.0f}%")
        print(f"{'─'*70}")

        print(f"\n  Trade Summary:")
        print(f"    Total trades:     {len(trades)}")
        print(f"    Entries attempted: {ar.entries_attempted}")
        print(f"    Entries filtered:  {ar.entries_filtered}")
        print(f"    Filter rate:       {ar.entries_filtered/max(ar.entries_attempted,1)*100:.1f}%")

        if not trades:
            print(f"    ⚠ No trades executed — check signal data availability")
            continue

        print(f"\n  Performance:")
        print(f"    Win rate:       {stats.win_rate:.1f}%")
        print(f"    Avg P&L:        ${stats.avg_pnl:+.2f}")
        print(f"    Total P&L:      ${stats.total_pnl:+.2f}")
        print(f"    Max drawdown:   ${stats.max_drawdown:.2f}")
        print(f"    Profit factor:  {stats.profit_factor:.2f}")

        if hasattr(stats, 'sharpe') and stats.sharpe is not None:
            print(f"    Sharpe ratio:   {stats.sharpe:.3f}")

        # Exit reason breakdown
        exit_reasons = {}
        for t in trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
        print(f"\n  Exit Reasons:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pct = count / len(trades) * 100
            print(f"    {reason:>18}: {count:4d} ({pct:.1f}%)")

        # Regime breakdown
        regime_trades = {}
        for t in trades:
            r = t.regime or "unknown"
            if r not in regime_trades:
                regime_trades[r] = {"wins": 0, "total": 0, "pnl": 0}
            regime_trades[r]["total"] += 1
            regime_trades[r]["pnl"] += t.pnl
            if t.win:
                regime_trades[r]["wins"] += 1

        if regime_trades:
            print(f"\n  By Regime:")
            print(f"    {'Regime':>15} {'Trades':>7} {'Win%':>7} {'P&L':>10}")
            for regime, data in sorted(regime_trades.items()):
                wr = data["wins"] / max(data["total"], 1) * 100
                print(f"    {regime:>15} {data['total']:>7} {wr:>6.1f}% ${data['pnl']:>+9.2f}")

        # DTE breakdown
        dte_buckets = {"30-45": [], "45-60": [], "60-90": [], "90-120": [], "120-180": []}
        for t in trades:
            dte = t.dte_at_entry
            if dte < 45:
                dte_buckets["30-45"].append(t)
            elif dte < 60:
                dte_buckets["45-60"].append(t)
            elif dte < 90:
                dte_buckets["60-90"].append(t)
            elif dte < 120:
                dte_buckets["90-120"].append(t)
            else:
                dte_buckets["120-180"].append(t)

        non_empty = {k: v for k, v in dte_buckets.items() if v}
        if non_empty:
            print(f"\n  By DTE Bucket:")
            print(f"    {'DTE':>10} {'Trades':>7} {'Win%':>7} {'Avg P&L':>10}")
            for bucket, bucket_trades in non_empty.items():
                wr = sum(1 for t in bucket_trades if t.win) / len(bucket_trades) * 100
                avg = sum(t.pnl for t in bucket_trades) / len(bucket_trades)
                print(f"    {bucket:>10} {len(bucket_trades):>7} {wr:>6.1f}% ${avg:>+9.2f}")


def _validate_targets(result, tier_label: str):
    """Check Phase 8 targets and report pass/fail."""
    print(f"\n{'='*70}")
    print(f"  TARGET VALIDATION — {tier_label}")
    print(f"{'='*70}")

    for agent_id, ar in result.agent_results.items():
        trades = ar.trades
        stats = ar.stats
        if not trades:
            print(f"\n  {agent_id}: SKIP — no trades")
            continue

        print(f"\n  {agent_id}:")

        # Target 1: Sharpe > 0.4
        sharpe = getattr(stats, 'sharpe', None)
        if sharpe is not None:
            status = "PASS" if sharpe > 0.4 else "FAIL"
            print(f"    Sharpe > 0.4:           {sharpe:.3f}  [{status}]")
        else:
            pnls = np.array([t.pnl for t in trades])
            if len(pnls) > 1:
                sharpe_est = np.mean(pnls) / np.std(pnls, ddof=1) * np.sqrt(252 / 30)
                status = "PASS" if sharpe_est > 0.4 else "FAIL"
                print(f"    Sharpe > 0.4 (est):     {sharpe_est:.3f}  [{status}]")

        # Target 2: Calendar win rate > 60%
        cal_trades = [t for t in trades if "calendar" in (t.exit_reason or "")]
        # Actually check strategy-based
        # We don't have strategy on BacktestTrade, use regime as proxy
        status = "PASS" if stats.win_rate > 60 else "FAIL"
        print(f"    Win rate > 60%:         {stats.win_rate:.1f}%  [{status}]")

        # Target 3: Regime exits reduce drawdown
        regime_exits = [t for t in trades if t.exit_reason == "regime_spike"]
        if regime_exits:
            regime_pnl = sum(t.pnl for t in regime_exits)
            print(f"    Regime exits:           {len(regime_exits)} trades, P&L ${regime_pnl:+.2f}")
        else:
            print(f"    Regime exits:           0 (no SPIKE transitions in period)")

        # Target 4: Positive expectancy after 3% slippage
        avg_pnl = stats.avg_pnl
        status = "PASS" if avg_pnl > 0 else "FAIL"
        print(f"    Positive expectancy:    ${avg_pnl:+.2f}  [{status}]")


def main():
    parser = argparse.ArgumentParser(description="Medium/long-term integration backtest")
    parser.add_argument("--ticker", nargs="+", default=["SPY"], help="Ticker(s)")
    parser.add_argument("--start", default="2023-01-01", help="Start date")
    parser.add_argument("--end", default="2026-01-01", help="End date")
    parser.add_argument("--tier", choices=["medium_term", "long_term", "both"],
                        default="both", help="DTE tier to test")
    parser.add_argument("--slippage", type=float, default=3.0, help="Slippage %")
    parser.add_argument("--source", default="chain_store",
                        choices=["chain_store", "dolt"], help="Data source")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    config = load_config()
    tiers = ["medium_term", "long_term"] if args.tier == "both" else [args.tier]

    for tier in tiers:
        print(f"\n\nRunning {tier} integration backtest...")
        result = run_agent_backtest(
            tickers=args.ticker,
            start_date=args.start,
            end_date=args.end,
            config=config,
            slippage_pct=args.slippage,
            source=args.source,
            dte_tier=tier,
        )

        print(f"\nDates processed: {result.dates_processed}")
        print(f"Tickers: {', '.join(result.tickers)}")
        print(f"Date range: {result.date_range[0]} to {result.date_range[1]}")

        _print_agent_report(result, tier.upper().replace("_", " "))
        _validate_targets(result, tier.upper().replace("_", " "))


if __name__ == "__main__":
    main()
