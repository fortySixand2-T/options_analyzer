"""
Migration: collapse fabricated bid/ask on Alpaca-backfilled chain snapshots.

Background
----------
Alpaca options history is delivered as OHLC *bars* (traded prices), not bid/ask
quotes. The original backfill (`src/data/backfill_pipeline._estimate_bid_ask`)
manufactured a spread from each bar's open/close range
(bid = min(open, close), ask = max(open, close)). That conflates intrabar price
*movement* with a quoted *spread* — it invented ~25% spreads on low-volume
strikes and made spread-sensitive structures (butterflies, 4-leg spreads) look
far worse than reality in the chain-replay backtester.

The real traded close was preserved in the `last` column, so we can repair the
existing rows in place: set bid == ask == mid == last (the close) and zero the
spread_pct. Real fill cost is now modeled by the backtester's slippage_pct
(see chain_replay._leg_fill_price), not by a fabricated spread.

Scope
-----
Only snapshots with label='backfill' are touched. Real-quote sources are left
untouched: 'dolt' (recorded DoltHub quotes) and the yfinance forward-collection
labels ('eod', 'midday', 'shortdte', 'intraday_*').

This migration is idempotent — re-running it sets the same values.

Usage
-----
    python scripts/migrate_backfill_fills.py            # apply
    python scripts/migrate_backfill_fills.py --dry-run  # report only
"""

import argparse
import os
import sqlite3
import sys

# DB path mirrors chain_replay / chain_store resolution.
DB_PATH = os.getenv("CHAIN_SNAPSHOTS_DB", "data/chain_snapshots.db")

# Rows to repair: Alpaca-backfilled contracts that still carry a fabricated
# spread (bid != ask) and have a usable close in `last`.
_BACKFILL_SUBQUERY = "SELECT id FROM chain_snapshots WHERE label = 'backfill'"


def _counts(conn: sqlite3.Connection) -> dict:
    """Return diagnostic counts over the backfill contract rows."""
    row = conn.execute(
        f"""
        SELECT COUNT(*)                                            AS total,
               SUM(CASE WHEN last > 0 THEN 1 ELSE 0 END)           AS last_pos,
               SUM(CASE WHEN bid <> ask THEN 1 ELSE 0 END)         AS fake_spread,
               ROUND(AVG(CASE WHEN mid > 0
                              THEN (ask - bid) / mid * 100 END), 2) AS avg_spread_pct
        FROM chain_contracts
        WHERE snapshot_id IN ({_BACKFILL_SUBQUERY})
        """
    ).fetchone()
    return dict(zip(("total", "last_pos", "fake_spread", "avg_spread_pct"), row))


def migrate(db_path: str, dry_run: bool = False) -> int:
    """Collapse fabricated bid/ask to the real close for backfill rows.

    Returns the number of contract rows updated (0 in dry-run).
    """
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return -1

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        before = _counts(conn)
        print(f"Before: {before}")

        if dry_run:
            print("Dry-run — no changes written.")
            return 0

        # Use the real traded close (`last`) as bid == ask == mid; zero spread.
        cur = conn.execute(
            f"""
            UPDATE chain_contracts
               SET bid = last, ask = last, mid = last, spread_pct = 0.0
             WHERE last > 0
               AND snapshot_id IN ({_BACKFILL_SUBQUERY})
            """
        )
        conn.commit()
        updated = cur.rowcount

        after = _counts(conn)
        print(f"Updated {updated} contract rows.")
        print(f"After:  {after}")
        return updated
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts without writing changes.")
    parser.add_argument("--db", default=DB_PATH,
                        help=f"Path to chain_snapshots.db (default: {DB_PATH})")
    args = parser.parse_args()

    result = migrate(args.db, dry_run=args.dry_run)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
