#!/usr/bin/env python3
"""
ThetaData historical options backfill CLI.

Requires Theta Terminal running on the host (Java 21+).
See: https://docs.thetadata.us/Articles/Getting-Started/Getting-Started.html

Usage:
    python scripts/backfill_thetadata.py SPY --start 2024-06-01 --end 2024-06-30
    python scripts/backfill_thetadata.py SPY,QQQ,IWM --start 2020-01-01 --end 2025-12-31
    python scripts/backfill_thetadata.py SPY --dry-run
    python scripts/backfill_thetadata.py --status
    python scripts/backfill_thetadata.py --check-terminal
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

ALL_TICKERS = "SPY,QQQ,IWM,AAPL,AMZN,GOOG,NFLX,META,MSFT,TSLA,AMD"
PROGRESS_FILE = "data/thetadata_progress.json"


def show_status():
    """Show backfill progress and DB stats for ThetaData label."""
    import sqlite3
    import os

    db_path = os.getenv("CHAIN_SNAPSHOTS_DB", "data/chain_snapshots.db")
    if not os.path.exists(db_path):
        print("Database not found:", db_path)
        return

    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT COUNT(*) as snapshots,
               SUM(contracts_count) as contracts,
               COUNT(DISTINCT ticker) as tickers,
               MIN(snapshot_date) as first_date,
               MAX(snapshot_date) as last_date
        FROM chain_snapshots WHERE label = 'thetadata'
    """).fetchone()

    greeks_row = conn.execute("""
        SELECT COUNT(*) as with_greeks
        FROM chain_contracts cc
        JOIN chain_snapshots cs ON cc.snapshot_id = cs.id
        WHERE cs.label = 'thetadata' AND cc.delta IS NOT NULL
    """).fetchone()
    conn.close()

    print(f"\nThetaData Backfill Status")
    print(f"{'='*40}")
    print(f"  Snapshots:  {row[0]:,}")
    print(f"  Contracts:  {row[1] or 0:,}")
    print(f"  Tickers:    {row[2]}")
    print(f"  Date range: {row[3]} → {row[4]}")
    print(f"  With greeks: {greeks_row[0]:,}")

    try:
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
        completed = progress.get("completed", [])
        print(f"\n  Progress file: {len(completed)} ticker-dates completed")
        if completed:
            print(f"  First: {completed[0]}")
            print(f"  Last:  {completed[-1]}")
    except FileNotFoundError:
        print(f"\n  No progress file found ({PROGRESS_FILE})")


def check_terminal():
    """Verify Theta Terminal is reachable."""
    from data.thetadata_client import ThetaDataClient

    client = ThetaDataClient()
    print(f"Checking Theta Terminal at {client.base_url}...")

    if client.health_check():
        print("  OK — Theta Terminal is running")
        return True
    else:
        print("  FAILED — Cannot reach Theta Terminal")
        print(f"  Make sure it's running on the host: java -jar ThetaTerminal.jar")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical option chains from ThetaData",
    )
    parser.add_argument(
        "tickers", nargs="?", default=ALL_TICKERS,
        help=f"Comma-separated tickers (default: {ALL_TICKERS})",
    )
    parser.add_argument(
        "--start", default="2020-01-01",
        help="Start date YYYY-MM-DD (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end", default="2025-12-31",
        help="End date YYYY-MM-DD (default: 2025-12-31)",
    )
    parser.add_argument(
        "--max-dte", type=int, default=14,
        help="Max DTE for contract filter (default: 14)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch one date per ticker only (for testing)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show backfill progress and DB stats",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Start fresh, ignore progress file",
    )
    parser.add_argument(
        "--check-terminal", action="store_true",
        help="Test Theta Terminal connectivity and exit",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.check_terminal:
        ok = check_terminal()
        sys.exit(0 if ok else 1)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("No tickers specified", file=sys.stderr)
        sys.exit(1)

    progress_file = None if args.no_resume else PROGRESS_FILE

    print(f"\n{'='*60}")
    print(f"ThetaData Historical Options Backfill")
    print(f"{'='*60}")
    print(f"  Tickers:  {', '.join(tickers)}")
    print(f"  Range:    {args.start} → {args.end}")
    print(f"  Max DTE:  {args.max_dte}")
    print(f"  Resume:   {'no' if args.no_resume else 'yes'}")

    if args.dry_run:
        print(f"\n  DRY RUN: testing with first date only\n")
        from data.thetadata_client import ThetaDataClient
        from data.thetadata_backfill import backfill_date, _business_days

        client = ThetaDataClient()
        if not client.health_check():
            print("ERROR: Theta Terminal not reachable")
            sys.exit(1)

        dates = _business_days(args.start, args.end)
        if not dates:
            print("No business days in range")
            return

        test_date = dates[0]
        for ticker in tickers:
            print(f"\nBackfilling {ticker} on {test_date}...")
            t0 = time.time()
            result = backfill_date(client, ticker, test_date, max_dte=args.max_dte)
            elapsed = time.time() - t0
            print(f"  Spot:      ${result.get('spot', 0):.2f}")
            print(f"  Contracts: {result.get('contracts', 0)}")
            print(f"  Greeks:    {result.get('greeks_stored', 0)}")
            print(f"  Stored:    {result.get('stored', False)}")
            print(f"  Time:      {elapsed:.1f}s")
            if result.get("error"):
                print(f"  Error:     {result['error']}")
        return

    from data.thetadata_backfill import backfill_range

    print(f"\nStarting backfill...\n")
    t0 = time.time()
    summary = backfill_range(
        tickers=tickers,
        start=args.start,
        end=args.end,
        max_dte=args.max_dte,
        progress_file=progress_file,
    )
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"Backfill Complete — {elapsed:.0f}s")
    print(f"{'='*60}")
    print(f"  Dates processed: {summary.get('dates_processed', 0)}")
    print(f"  Dates skipped:   {summary.get('dates_skipped', 0)}")
    print(f"  Total contracts: {summary.get('total_contracts', 0):,}")
    print(f"  Total greeks:    {summary.get('total_greeks', 0):,}")

    errors = summary.get("errors", [])
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"    - {e}")
        if len(errors) > 20:
            print(f"    ... and {len(errors) - 20} more")


if __name__ == "__main__":
    main()
