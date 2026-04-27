#!/usr/bin/env python3
"""
CLI entry point for daily chain snapshot collection.

Usage:
    python scripts/collect_chains.py                    # Default: SPY,QQQ,IWM
    python scripts/collect_chains.py SPY                # Single ticker
    python scripts/collect_chains.py SPY,QQQ --max-dte 30
    python scripts/collect_chains.py --stats            # Show database stats

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
        description="Collect and store daily option chain snapshots",
    )
    parser.add_argument(
        "tickers",
        nargs="?",
        default="SPY,QQQ,IWM",
        help="Comma-separated ticker symbols (default: SPY,QQQ,IWM)",
    )
    parser.add_argument(
        "--min-dte", type=int, default=0,
        help="Minimum DTE to collect (default: 0)",
    )
    parser.add_argument(
        "--max-dte", type=int, default=60,
        help="Maximum DTE to collect (default: 60)",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds between API calls (default: 2.0)",
    )
    parser.add_argument(
        "--label", default="eod",
        help="Snapshot label: 'eod' (default) or 'shortdte' for 1-7 DTE",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show database statistics and exit",
    )
    parser.add_argument(
        "--dates", metavar="TICKER",
        help="Show available dates for a ticker and exit",
    )

    args = parser.parse_args()

    # Stats mode
    if args.stats:
        from data.chain_store import get_db_stats
        stats = get_db_stats()
        print(json.dumps(stats, indent=2))
        return

    # Dates mode
    if args.dates:
        from data.chain_store import get_available_dates
        dates = get_available_dates(args.dates.upper())
        if dates:
            print(f"{args.dates.upper()}: {len(dates)} snapshots")
            for d in dates:
                print(f"  {d}")
        else:
            print(f"No snapshots found for {args.dates.upper()}")
        return

    # Collection mode
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("No tickers specified", file=sys.stderr)
        sys.exit(1)

    from data.chain_collector import collect_daily_snapshots

    print(f"Collecting chain snapshots for: {', '.join(tickers)}")
    print(f"DTE range: {args.min_dte}-{args.max_dte}, label: {args.label}")
    print()

    result = collect_daily_snapshots(
        tickers=tickers,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        delay=args.delay,
        label=args.label,
    )

    # Print summary
    print()
    print("=" * 50)
    print(f"Collection Summary — {result['date']}")
    print("=" * 50)
    print(f"  Tickers:   {result['tickers_success']}/{result['tickers_requested']} succeeded")
    print(f"  Contracts: {result['total_contracts']} stored")
    print(f"  Duration:  {result['duration_sec']}s")

    if result["details"]:
        print()
        for d in result["details"]:
            print(f"  {d['ticker']}: {d['contracts']} contracts, "
                  f"{d['expiries']} expiries, spot=${d['spot']:.2f}")

    if result["errors"]:
        print()
        print("  Errors:")
        for e in result["errors"]:
            print(f"    - {e}")

    # Show cumulative DB stats
    from data.chain_store import get_db_stats
    stats = get_db_stats()
    print()
    print(f"  Database: {stats['db_size_mb']} MB, "
          f"{stats['snapshots']} snapshots, "
          f"{stats['contracts']} contracts total")
    if stats["date_range"]:
        print(f"  Range: {stats['date_range']['start']} → {stats['date_range']['end']}")


if __name__ == "__main__":
    main()
