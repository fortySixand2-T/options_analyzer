#!/usr/bin/env python3
"""
CLI for intraday data collection (0 DTE support).

Usage:
    python scripts/collect_intraday.py bars               # Fetch 5-min bars (last 5 days)
    python scripts/collect_intraday.py bars --period 60d   # Fetch 5-min bars (last 60 days)
    python scripts/collect_intraday.py chain               # One-shot intraday chain snapshot
    python scripts/collect_intraday.py loop                # 30-min collection loop (long-lived)
    python scripts/collect_intraday.py stats               # Show intraday DB stats

Options Analytics Team — 2026-04
"""

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="Intraday data collection for 0 DTE options",
    )
    parser.add_argument(
        "mode",
        choices=["bars", "chain", "loop", "stats"],
        help="Collection mode",
    )
    parser.add_argument(
        "--tickers", default=None,
        help="Comma-separated tickers (default: SPY,^SPX,^VIX for bars; SPY,^SPX for chain)",
    )
    parser.add_argument(
        "--interval", default="5m",
        help="Bar interval: 1m, 5m, 15m (default: 5m)",
    )
    parser.add_argument(
        "--period", default="5d",
        help="yfinance period for bars: 5d, 30d, 60d (default: 5d)",
    )
    parser.add_argument(
        "--loop-interval", type=int, default=30,
        help="Minutes between chain snapshots in loop mode (default: 30)",
    )
    parser.add_argument(
        "--label", default=None,
        help="Override chain snapshot label (default: auto from current time)",
    )

    args = parser.parse_args()

    if args.mode == "stats":
        from data.intraday_store import get_intraday_stats
        from data.chain_store import get_db_stats

        print("=== Intraday Bars (intraday.db) ===")
        bar_stats = get_intraday_stats()
        print(json.dumps(bar_stats, indent=2))

        print("\n=== Chain Snapshots (chain_snapshots.db) ===")
        chain_stats = get_db_stats()
        print(json.dumps(chain_stats, indent=2))
        return

    if args.mode == "bars":
        from data.intraday_collector import collect_intraday_bars

        tickers = None
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",")]

        print(f"Collecting {args.interval} bars (period={args.period})")
        result = collect_intraday_bars(
            tickers=tickers,
            interval=args.interval,
            period=args.period,
        )

        print()
        print("=" * 50)
        print(f"Bar Collection Summary")
        print("=" * 50)
        print(f"  Tickers: {result['tickers_success']}/{result['tickers_success'] + result['tickers_failed']}")
        print(f"  Bars:    {result['total_bars']} stored")
        print(f"  Duration: {result['duration_sec']}s")

        for d in result.get("details", []):
            print(f"  {d['ticker']}: {d['bars']} bars — {d['date_range']}")

        if result["errors"]:
            print("  Errors:")
            for e in result["errors"]:
                print(f"    - {e}")

        # Show cumulative stats
        from data.intraday_store import get_intraday_stats
        stats = get_intraday_stats()
        print(f"\n  Database: {stats['db_size_mb']} MB, {stats['total_bars']} total bars")
        return

    if args.mode == "chain":
        from data.intraday_collector import collect_intraday_chain_snapshot

        tickers = None
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",")]

        print("Collecting intraday chain snapshot")
        result = collect_intraday_chain_snapshot(
            tickers=tickers,
            label=args.label,
        )

        print()
        print("=" * 50)
        print(f"Chain Snapshot [{result['label']}]")
        print("=" * 50)
        print(f"  Tickers:   {result['tickers_success']}/{result['tickers_success'] + result['tickers_failed']}")
        print(f"  Contracts: {result['total_contracts']}")
        print(f"  Duration:  {result['duration_sec']}s")

        for d in result.get("details", []):
            print(f"  {d['ticker']}: {d['contracts']} contracts, spot=${d['spot']:.2f}")

        if result["errors"]:
            print("  Errors:")
            for e in result["errors"]:
                print(f"    - {e}")
        return

    if args.mode == "loop":
        from data.intraday_collector import run_intraday_collection_loop

        print(f"Starting intraday collection loop (every {args.loop_interval} min)")
        print("Press Ctrl+C to stop")
        try:
            run_intraday_collection_loop(
                interval_minutes=args.loop_interval,
                bar_interval=args.interval,
            )
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
