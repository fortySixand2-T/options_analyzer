#!/usr/bin/env python3
"""
Alpaca historical options backfill CLI.

Usage:
    python scripts/backfill_chains.py SPY --start 2025-04-01 --end 2025-05-01
    python scripts/backfill_chains.py SPY,QQQ --start 2024-06-01 --end 2025-05-01
    python scripts/backfill_chains.py SPY --start 2025-04-01 --end 2025-04-03 --dry-run
    python scripts/backfill_chains.py --status

Options Analytics Team — 2026-05
"""

import argparse
import json
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def show_status():
    """Show backfill progress and DB stats."""
    from data.chain_store import get_db_stats

    stats = get_db_stats()
    print(json.dumps(stats, indent=2, default=str))

    progress_file = "data/backfill_progress.json"
    try:
        with open(progress_file) as f:
            progress = json.load(f)
        completed = progress.get("completed", [])
        print(f"\nBackfill progress: {len(completed)} ticker-dates completed")
        if completed:
            print(f"  First: {completed[0]}")
            print(f"  Last:  {completed[-1]}")
    except FileNotFoundError:
        print("\nNo backfill progress file found.")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical option chains from Alpaca",
    )
    parser.add_argument(
        "tickers", nargs="?", default="SPY",
        help="Comma-separated tickers (default: SPY)",
    )
    parser.add_argument(
        "--start", default="2025-04-01",
        help="Start date YYYY-MM-DD (default: 2025-04-01)",
    )
    parser.add_argument(
        "--end", default="2025-05-01",
        help="End date YYYY-MM-DD (default: 2025-05-01)",
    )
    parser.add_argument(
        "--max-dte", type=int, default=60,
        help="Max DTE for contract discovery (default: 60)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch one date only to test pipeline",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show backfill progress and DB stats",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Start fresh, ignore progress file",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("No tickers specified", file=sys.stderr)
        sys.exit(1)

    progress_file = None if args.no_resume else "data/backfill_progress.json"

    print(f"\n{'='*60}")
    print(f"Alpaca Historical Options Backfill")
    print(f"{'='*60}")
    print(f"  Tickers:  {', '.join(tickers)}")
    print(f"  Range:    {args.start} → {args.end}")
    print(f"  Max DTE:  {args.max_dte}")
    print(f"  Resume:   {'no' if args.no_resume else 'yes'}")

    if args.dry_run:
        print(f"\n  DRY RUN: testing with first date only\n")
        from data.backfill_pipeline import backfill_date
        from data.alpaca_client import AlpacaOptionsClient
        from data.backfill_pipeline import _business_days

        client = AlpacaOptionsClient()
        dates = _business_days(args.start, args.end)
        if not dates:
            print("No business days in range")
            return

        date = dates[0]
        for ticker in tickers:
            print(f"\nBackfilling {ticker} on {date}...")
            t0 = time.time()
            result = backfill_date(client, ticker, date, max_dte=args.max_dte)
            elapsed = time.time() - t0

            print(f"\n  Results for {ticker} {date}:")
            print(f"    Spot:             ${result['spot'] or 'N/A'}")
            print(f"    Contracts fetched: {result['contracts_fetched']}")
            print(f"    Contracts priced:  {result['contracts_priced']}")
            print(f"    IV solved:         {result['iv_solved']}")
            print(f"    Stored:            {result['stored']}")
            print(f"    Time:              {elapsed:.1f}s")
            if result.get("error"):
                print(f"    Error:             {result['error']}")

        return

    # Full backfill
    from data.backfill_pipeline import backfill_range

    print(f"\nStarting backfill...\n")
    t0 = time.time()
    result = backfill_range(
        tickers=tickers,
        start=args.start,
        end=args.end,
        max_dte=args.max_dte,
        progress_file=progress_file,
    )
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"Backfill Complete")
    print(f"{'='*60}")
    print(f"  Dates total:       {result['dates_total']}")
    print(f"  Dates processed:   {result['dates_processed']}")
    print(f"  Dates skipped:     {result['dates_skipped']}")
    print(f"  Total contracts:   {result['total_contracts']}")
    print(f"  Total IV solved:   {result['total_iv_solved']}")
    print(f"  Duration:          {elapsed:.1f}s")

    if result["errors"]:
        print(f"\n  Errors ({len(result['errors'])}):")
        for e in result["errors"][:20]:
            print(f"    - {e}")
        if len(result["errors"]) > 20:
            print(f"    ... and {len(result['errors']) - 20} more")


if __name__ == "__main__":
    main()
