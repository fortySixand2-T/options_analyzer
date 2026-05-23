#!/usr/bin/env python3
"""
Import DoltHub options data into chain_snapshots.db for backtesting.

Reads from a local Dolt clone of post-no-preference/options and writes
ChainSnapshot records into the same SQLite format used by chain_store.py.

Usage:
    python scripts/import_dolt.py --tickers SPY,QQQ,IWM --start 2020-01-01 --end 2024-12-31
    python scripts/import_dolt.py --tickers SPY --start 2022-01-01 --end 2022-06-30 --label dolt
    python scripts/import_dolt.py --status
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

logger = logging.getLogger(__name__)

DEFAULT_DOLT_PATH = os.path.join(_ROOT, "data", "dolt_options")
DEFAULT_LABEL = "dolt"


def dolt_query(sql: str, dolt_path: str) -> list:
    result = subprocess.run(
        ["dolt", "sql", "-q", sql, "-r", "json"],
        cwd=dolt_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error("Dolt query failed: %s", result.stderr.strip())
        return []
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def get_dolt_dates(ticker: str, start: str, end: str, dolt_path: str) -> list:
    sql = (
        f"SELECT DISTINCT date FROM option_chain "
        f"WHERE act_symbol = '{ticker}' AND date >= '{start}' AND date <= '{end}' "
        f"ORDER BY date"
    )
    rows = dolt_query(sql, dolt_path)
    return [str(r["date"]) for r in rows]


def estimate_spot(contracts: list) -> float:
    best_delta = 0.0
    best_call = None
    for c in contracts:
        if c.get("call_put", "").lower() != "call":
            continue
        delta = abs(float(c.get("delta") or 0))
        if delta > best_delta:
            best_delta = delta
            best_call = c

    if best_call and best_delta > 0.95:
        strike = float(best_call["strike"])
        mid = (float(best_call.get("bid") or 0) + float(best_call.get("ask") or 0)) / 2
        return strike + mid

    calls = [c for c in contracts if c.get("call_put", "").lower() == "call"]
    if calls:
        atm = sorted(calls, key=lambda c: abs(float(c.get("delta") or 0) - 0.5))
        if atm:
            return float(atm[0]["strike"])

    strikes = sorted(set(float(c["strike"]) for c in contracts if c.get("strike")))
    if strikes:
        return strikes[len(strikes) // 2]
    return 0.0


def import_date(ticker: str, date: str, label: str, dolt_path: str, chain_db_path: str) -> bool:
    """Import one date of option chain data from Dolt to chain_snapshots.db."""
    import sqlite3

    sql = (
        f"SELECT date, act_symbol, expiration, strike, call_put, "
        f"bid, ask, vol, delta, gamma, theta, vega, rho "
        f"FROM option_chain "
        f"WHERE act_symbol = '{ticker}' AND date = '{date}' "
        f"ORDER BY expiration, strike, call_put"
    )
    rows = dolt_query(sql, dolt_path)
    if not rows:
        return False

    spot = estimate_spot(rows)
    if spot <= 0:
        logger.warning("Cannot estimate spot for %s on %s", ticker, date)
        return False

    expiries = sorted(set(str(r["expiration"]) for r in rows))

    conn = sqlite3.connect(chain_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT id FROM chain_snapshots WHERE ticker = ? AND snapshot_date = ? AND label = ?",
            (ticker, date, label),
        ).fetchone()
        if existing:
            return False

        conn.execute(
            """INSERT INTO chain_snapshots
               (ticker, snapshot_date, label, spot, fetched_at, contracts_count, expiries_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ticker, date, label, spot, datetime.now().isoformat(),
             len(rows), json.dumps(expiries)),
        )
        snapshot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for r in rows:
            bid = float(r.get("bid") or 0)
            ask = float(r.get("ask") or 0)
            mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
            iv = float(r.get("vol") or 0)

            conn.execute(
                """INSERT INTO chain_contracts
                   (snapshot_id, ticker, strike, expiry, option_type,
                    bid, ask, mid, last, volume, open_interest, implied_volatility)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_id, ticker, float(r["strike"]), str(r["expiration"]),
                 str(r["call_put"]).lower(), bid, ask, mid, mid, 0, 0, iv),
            )

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error("Failed to import %s %s: %s", ticker, date, e)
        return False
    finally:
        conn.close()


def show_status(dolt_path: str, chain_db_path: str):
    import sqlite3

    print("\n=== Dolt Options Database ===")
    print(f"  Path: {dolt_path}")
    exists = os.path.exists(os.path.join(dolt_path, ".dolt"))
    print(f"  Status: {'found' if exists else 'NOT FOUND'}")

    if exists:
        for ticker in ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "META", "AMZN", "GOOG", "NFLX", "TSLA"]:
            sql = (
                f"SELECT MIN(date) as min_d, MAX(date) as max_d, COUNT(DISTINCT date) as cnt "
                f"FROM option_chain WHERE act_symbol = '{ticker}'"
            )
            rows = dolt_query(sql, dolt_path)
            if rows and rows[0].get("cnt"):
                r = rows[0]
                print(f"  {ticker}: {r['cnt']} dates ({r['min_d']} to {r['max_d']})")

    print(f"\n=== Imported Data (label='dolt') ===")
    if os.path.exists(chain_db_path):
        conn = sqlite3.connect(chain_db_path)
        rows = conn.execute(
            "SELECT ticker, COUNT(*) as cnt, MIN(snapshot_date) as min_d, MAX(snapshot_date) as max_d "
            "FROM chain_snapshots WHERE label = 'dolt' GROUP BY ticker ORDER BY ticker"
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r[0]}: {r[1]} dates ({r[2]} to {r[3]})")
        else:
            print("  No data imported yet.")
        conn.close()
    else:
        print("  No chain_snapshots.db found.")
    print()


def main():
    parser = argparse.ArgumentParser(description="Import DoltHub options data into chain_snapshots.db")
    parser.add_argument("--tickers", type=str, default="SPY,QQQ,IWM",
                        help="Comma-separated tickers")
    parser.add_argument("--start", type=str, required=False,
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=False,
                        help="End date YYYY-MM-DD")
    parser.add_argument("--label", type=str, default=DEFAULT_LABEL,
                        help=f"Snapshot label (default: {DEFAULT_LABEL})")
    parser.add_argument("--dolt-path", type=str, default=DEFAULT_DOLT_PATH,
                        help="Path to local Dolt clone")
    parser.add_argument("--status", action="store_true",
                        help="Show Dolt data status and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    chain_db_path = os.path.join(_ROOT, "data", "chain_snapshots.db")

    if args.status:
        show_status(args.dolt_path, chain_db_path)
        return

    if not args.start or not args.end:
        print("Error: --start and --end are required for import.")
        print("Example: python scripts/import_dolt.py --tickers SPY --start 2023-01-01 --end 2023-12-31")
        return

    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    if not os.path.exists(os.path.join(args.dolt_path, ".dolt")):
        print(f"Error: Dolt database not found at {args.dolt_path}")
        print("Clone it: cd data && dolt clone post-no-preference/options dolt_options")
        return

    print(f"\n{'=' * 60}")
    print(f"  Dolt Options Import")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Range: {args.start} to {args.end}")
    print(f"  Label: {args.label}")
    print(f"  Target: {chain_db_path}")
    print(f"{'=' * 60}\n")

    total_imported = 0
    total_skipped = 0

    for ticker in tickers:
        dates = get_dolt_dates(ticker, args.start, args.end, args.dolt_path)
        print(f"  {ticker}: {len(dates)} dates available")

        imported = 0
        for i, date in enumerate(dates):
            ok = import_date(ticker, date, args.label, args.dolt_path, chain_db_path)
            if ok:
                imported += 1
                total_imported += 1
            else:
                total_skipped += 1

            if (i + 1) % 50 == 0 or i == len(dates) - 1:
                print(f"    {ticker}: {i + 1}/{len(dates)} processed, {imported} imported")

        print(f"  {ticker}: {imported} dates imported\n")

    print(f"{'=' * 60}")
    print(f"  Import complete: {total_imported} imported, {total_skipped} skipped")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
