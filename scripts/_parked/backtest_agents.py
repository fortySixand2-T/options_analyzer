#!/usr/bin/env python3
"""
Agent backtest CLI — replay historical chain snapshots through agent filters.

Usage:
    python scripts/backtest_agents.py --tickers SPY,QQQ,IWM
    python scripts/backtest_agents.py --tickers SPY --start 2025-06-01 --end 2025-12-31
    python scripts/backtest_agents.py --tickers SPY,QQQ,IWM --agent momentum
    python scripts/backtest_agents.py --status
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


logger = logging.getLogger(__name__)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Agent Backtest — replay chains through agent filters")
    p.add_argument("--tickers", type=str, default="SPY,QQQ,IWM",
                   help="Comma-separated tickers (default: SPY,QQQ,IWM)")
    p.add_argument("--start", type=str, default=None,
                   help="Start date YYYY-MM-DD (default: earliest available)")
    p.add_argument("--end", type=str, default=None,
                   help="End date YYYY-MM-DD (default: latest available)")
    p.add_argument("--agent", type=str, default=None,
                   help="Run only this agent (default: all enabled)")
    p.add_argument("--source", type=str, default="chain_store",
                   choices=["chain_store", "dolt"],
                   help="Data source: chain_store (local snapshots) or dolt (DoltHub options DB)")
    p.add_argument("--label", type=str, default="backfill",
                   help="Chain store snapshot label (default: backfill)")
    p.add_argument("--slippage", type=float, default=3.0,
                   help="Slippage as %% of premium (default: 3.0)")
    p.add_argument("--status", action="store_true",
                   help="Show available backfill data and exit")
    p.add_argument("--json", action="store_true",
                   help="Output results as JSON")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Verbose logging")
    return p.parse_args(argv)


def show_status(tickers, label, source="chain_store"):
    if source == "dolt":
        from data.dolt_provider import get_available_dates
        print("\n=== Dolt Options Data Status ===\n")
        for ticker in tickers:
            dates = get_available_dates(ticker)
            if dates:
                print(f"  {ticker}: {len(dates)} dates ({dates[0]} to {dates[-1]})")
            else:
                print(f"  {ticker}: no data")
    else:
        from data.chain_store import get_available_dates
        print("\n=== Backfill Data Status ===\n")
        for ticker in tickers:
            dates = get_available_dates(ticker, label=label)
            if dates:
                print(f"  {ticker}: {len(dates)} dates ({dates[0]} to {dates[-1]})")
            else:
                print(f"  {ticker}: no data")
    print()


def print_agent_result(agent_id, result):
    stats = result.stats
    trades = result.trades

    print(f"\n{'=' * 60}")
    print(f"  Agent: {agent_id}")
    print(f"  Description: {result.config.description}")
    print(f"  Capital allocation: {result.config.capital_pct * 100:.0f}%")
    print(f"{'=' * 60}")

    print(f"\n  Trades: {len(trades)}")
    print(f"  Entries attempted: {result.entries_attempted}")
    print(f"  Entries filtered: {result.entries_filtered}")

    if len(trades) == 0:
        print("  No trades to analyze.\n")
        return

    print(f"\n  Win rate:       {stats.win_rate:.1f}%")
    print(f"  Total P&L:      ${stats.total_pnl:,.2f}")
    print(f"  Avg P&L:        ${stats.avg_pnl:,.2f}")
    print(f"  Profit factor:  {stats.profit_factor:.2f}")
    print(f"  Sharpe ratio:   {stats.sharpe_ratio:.2f}")
    print(f"  Max drawdown:   ${stats.max_drawdown:,.2f}")
    print(f"  Avg DTE entry:  {stats.avg_dte_at_entry:.1f}")

    # Win rate by regime from trade data
    regime_trades = {}
    for t in trades:
        regime_trades.setdefault(t.regime, []).append(t)
    if regime_trades:
        print(f"\n  Win rate by regime:")
        for regime in sorted(regime_trades):
            rt = regime_trades[regime]
            wr = sum(1 for t in rt if t.win) / len(rt) * 100
            print(f"    {regime}: {wr:.1f}% ({len(rt)} trades)")

    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]
    if wins:
        print(f"\n  Avg win:  ${sum(t.pnl for t in wins) / len(wins):,.2f}")
    if losses:
        print(f"  Avg loss: ${sum(t.pnl for t in losses) / len(losses):,.2f}")

    print(f"\n  Equity curve: start=$0.00 → end=${result.equity_curve[-1]:,.2f}")
    print()


def main(argv=None):
    args = parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    if args.status:
        show_status(tickers, args.label, source=args.source)
        return

    if not args.start or not args.end:
        all_dates = set()
        if args.source == "dolt":
            from data.dolt_provider import get_available_dates as dolt_dates
            for ticker in tickers:
                dates = dolt_dates(ticker)
                all_dates.update(dates)
        else:
            from data.chain_store import get_available_dates
            for ticker in tickers:
                dates = get_available_dates(ticker, label=args.label)
                all_dates.update(dates)

        if not all_dates:
            if args.source == "dolt":
                print(f"\nNo Dolt data found for {tickers}.")
                print("Clone the DB: cd data && dolt clone post-no-preference/options dolt_options")
            else:
                print(f"\nNo backfill data found for {tickers} with label '{args.label}'.")
                print("Run: ./start.sh backfill SPY,QQQ,IWM --start 2025-05-01 --end 2026-05-01")
            return

        sorted_dates = sorted(all_dates)
        start_date = args.start or sorted_dates[0]
        end_date = args.end or sorted_dates[-1]
    else:
        start_date = args.start
        end_date = args.end

    from agents.agent_config import load_config
    config = load_config()

    if args.agent:
        if args.agent not in config.agents:
            print(f"\nUnknown agent '{args.agent}'. Available: {list(config.agents.keys())}")
            return
        for name in list(config.agents.keys()):
            if name != args.agent:
                config.agents[name].enabled = False

    print(f"\n{'=' * 60}")
    print(f"  Agent Backtest")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Slippage: {args.slippage}%")
    print(f"  Source: {args.source}")
    if args.source != "dolt":
        print(f"  Label: {args.label}")
    enabled = [n for n, c in config.agents.items() if c.enabled]
    print(f"  Agents: {', '.join(enabled)}")
    print(f"{'=' * 60}")

    from backtest.agent_backtest import run_agent_backtest

    summary = run_agent_backtest(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        config=config,
        label=args.label,
        slippage_pct=args.slippage,
        source=args.source,
    )

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
        return

    print(f"\n  Dates processed: {summary.dates_processed}")
    print(f"  Date range: {summary.date_range[0]} to {summary.date_range[1]}")

    for agent_id, result in summary.agent_results.items():
        print_agent_result(agent_id, result)

    # Summary comparison table
    if len(summary.agent_results) > 1:
        print(f"\n{'=' * 60}")
        print("  Agent Comparison")
        print(f"{'=' * 60}")
        header = f"  {'Agent':<16} {'Trades':>6} {'Win%':>6} {'P&L':>10} {'Sharpe':>7} {'PF':>6}"
        print(header)
        print(f"  {'-' * 54}")
        for agent_id, result in summary.agent_results.items():
            s = result.stats
            print(
                f"  {agent_id:<16} {len(result.trades):>6} "
                f"{s.win_rate:>5.1f}% ${s.total_pnl:>9,.2f} "
                f"{s.sharpe_ratio:>7.2f} {s.profit_factor:>5.2f}"
            )
        print()


if __name__ == "__main__":
    main()
