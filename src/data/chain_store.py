"""
SQLite storage for daily options chain snapshots.

Inspired by Trading-copilot's database pattern: idempotent schema init,
upsert-based writes, and per-ticker-per-day-per-label uniqueness.

Tables:
    chain_snapshots  — one row per ticker per day per label (header)
    chain_contracts  — every contract in that snapshot (detail)
    iv_snapshots     — daily ATM IV + realized vol summary

Labels allow multiple snapshots per day (e.g. "eod" full chain + "shortdte"
for focused 1-7 DTE collection on index options).

Options Analytics Team — 2026-04
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from scanner.providers.base import ChainSnapshot, OptionContract

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "chain_snapshots.db",
)


def _get_db_path() -> str:
    path = os.getenv("CHAIN_SNAPSHOTS_DB", _DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    """Idempotent schema creation — safe to call on every connection."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chain_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT 'eod',
            spot REAL,
            fetched_at TEXT,
            contracts_count INTEGER DEFAULT 0,
            expiries_json TEXT,
            UNIQUE(ticker, snapshot_date, label)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_date
            ON chain_snapshots(ticker, snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_snapshots_label
            ON chain_snapshots(label);

        CREATE TABLE IF NOT EXISTS chain_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL REFERENCES chain_snapshots(id),
            ticker TEXT NOT NULL,
            strike REAL NOT NULL,
            expiry TEXT NOT NULL,
            option_type TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER DEFAULT 0,
            open_interest INTEGER DEFAULT 0,
            implied_volatility REAL,
            spread_pct REAL,
            UNIQUE(snapshot_id, strike, expiry, option_type)
        );

        CREATE INDEX IF NOT EXISTS idx_contracts_snapshot
            ON chain_contracts(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_contracts_lookup
            ON chain_contracts(ticker, expiry, strike, option_type);

        CREATE TABLE IF NOT EXISTS iv_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT 'eod',
            atm_iv_call REAL,
            atm_iv_put REAL,
            atm_iv_avg REAL,
            realized_vol_30d REAL,
            realized_vol_60d REAL,
            spot REAL,
            UNIQUE(ticker, snapshot_date, label)
        );

        CREATE INDEX IF NOT EXISTS idx_iv_ticker_date
            ON iv_snapshots(ticker, snapshot_date);
    """)


# ── Write operations ─────────────────────────────────────────────────────────


def store_snapshot(chain: ChainSnapshot, label: str = "eod") -> int:
    """Store a full chain snapshot. Returns the snapshot_id.

    Args:
        chain: The chain snapshot to store.
        label: Snapshot label — "eod" for full daily, "shortdte" for 1-7 DTE, etc.
               Multiple labels can coexist for the same ticker/date.
    """
    import json

    conn = _get_conn()
    snapshot_date = chain.fetched_at.strftime("%Y-%m-%d")

    try:
        # Upsert snapshot header
        conn.execute("""
            INSERT INTO chain_snapshots
                (ticker, snapshot_date, label, spot, fetched_at, contracts_count, expiries_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, snapshot_date, label) DO UPDATE SET
                spot = excluded.spot,
                fetched_at = excluded.fetched_at,
                contracts_count = excluded.contracts_count,
                expiries_json = excluded.expiries_json
        """, (
            chain.ticker,
            snapshot_date,
            label,
            chain.spot,
            chain.fetched_at.isoformat(),
            len(chain.contracts),
            json.dumps(chain.expiries),
        ))

        # Get the snapshot_id
        row = conn.execute(
            "SELECT id FROM chain_snapshots WHERE ticker = ? AND snapshot_date = ? AND label = ?",
            (chain.ticker, snapshot_date, label),
        ).fetchone()
        snapshot_id = row["id"]

        # Delete old contracts for this snapshot (simpler than per-row upsert)
        conn.execute(
            "DELETE FROM chain_contracts WHERE snapshot_id = ?",
            (snapshot_id,),
        )

        # Insert all contracts
        for c in chain.contracts:
            spread_pct = ((c.ask - c.bid) / c.mid * 100) if c.mid > 0 else None
            conn.execute("""
                INSERT INTO chain_contracts
                    (snapshot_id, ticker, strike, expiry, option_type,
                     bid, ask, mid, last, volume, open_interest,
                     implied_volatility, spread_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, chain.ticker, c.strike, c.expiry, c.option_type,
                c.bid, c.ask, c.mid, c.last, c.volume, c.open_interest,
                c.implied_volatility, spread_pct,
            ))

        conn.commit()
        logger.info(
            "Stored snapshot [%s]: %s %s — %d contracts, spot=%.2f",
            label, chain.ticker, snapshot_date, len(chain.contracts), chain.spot,
        )
        return snapshot_id

    except Exception as e:
        conn.rollback()
        logger.error("Failed to store snapshot for %s: %s", chain.ticker, e)
        raise
    finally:
        conn.close()


def store_iv_snapshot(
    ticker: str,
    snapshot_date: str,
    atm_iv_call: Optional[float],
    atm_iv_put: Optional[float],
    atm_iv_avg: Optional[float],
    realized_vol_30d: Optional[float],
    realized_vol_60d: Optional[float],
    spot: Optional[float],
    label: str = "eod",
):
    """Store daily IV summary (inspired by Trading-copilot's iv_history)."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO iv_snapshots
                (ticker, snapshot_date, label, atm_iv_call, atm_iv_put, atm_iv_avg,
                 realized_vol_30d, realized_vol_60d, spot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, snapshot_date, label) DO UPDATE SET
                atm_iv_call = excluded.atm_iv_call,
                atm_iv_put = excluded.atm_iv_put,
                atm_iv_avg = excluded.atm_iv_avg,
                realized_vol_30d = excluded.realized_vol_30d,
                realized_vol_60d = excluded.realized_vol_60d,
                spot = excluded.spot
        """, (
            ticker, snapshot_date, label, atm_iv_call, atm_iv_put, atm_iv_avg,
            realized_vol_30d, realized_vol_60d, spot,
        ))
        conn.commit()
    except Exception as e:
        logger.error("Failed to store IV snapshot for %s: %s", ticker, e)
    finally:
        conn.close()


# ── Read operations ──────────────────────────────────────────────────────────


def get_snapshot(
    ticker: str, date: str, label: Optional[str] = None,
) -> Optional[ChainSnapshot]:
    """Retrieve a stored chain snapshot for a given ticker and date.

    If label is None, returns the "eod" snapshot (or first available).
    """
    import json

    conn = _get_conn()
    try:
        if label:
            row = conn.execute(
                "SELECT * FROM chain_snapshots WHERE ticker = ? AND snapshot_date = ? AND label = ?",
                (ticker, date, label),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM chain_snapshots WHERE ticker = ? AND snapshot_date = ? ORDER BY label",
                (ticker, date),
            ).fetchone()

        if not row:
            return None

        contracts_rows = conn.execute(
            "SELECT * FROM chain_contracts WHERE snapshot_id = ?",
            (row["id"],),
        ).fetchall()

        contracts = [
            OptionContract(
                ticker=r["ticker"],
                strike=r["strike"],
                expiry=r["expiry"],
                option_type=r["option_type"],
                bid=r["bid"],
                ask=r["ask"],
                mid=r["mid"],
                last=r["last"],
                volume=r["volume"],
                open_interest=r["open_interest"],
                implied_volatility=r["implied_volatility"],
            )
            for r in contracts_rows
        ]

        return ChainSnapshot(
            ticker=row["ticker"],
            spot=row["spot"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            contracts=contracts,
            expiries=json.loads(row["expiries_json"]) if row["expiries_json"] else [],
        )
    finally:
        conn.close()


def get_available_dates(ticker: str, label: Optional[str] = None) -> List[str]:
    """List all dates with stored snapshots for a ticker."""
    conn = _get_conn()
    try:
        if label:
            rows = conn.execute(
                "SELECT DISTINCT snapshot_date FROM chain_snapshots WHERE ticker = ? AND label = ? ORDER BY snapshot_date",
                (ticker, label),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT snapshot_date FROM chain_snapshots WHERE ticker = ? ORDER BY snapshot_date",
                (ticker,),
            ).fetchall()
        return [r["snapshot_date"] for r in rows]
    finally:
        conn.close()


def get_iv_history(
    ticker: str, start_date: str = "", end_date: str = "", label: Optional[str] = None,
) -> List[dict]:
    """Retrieve IV history for a ticker, optionally filtered by date range and label."""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM iv_snapshots WHERE ticker = ?"
        params: list = [ticker]

        if label:
            sql += " AND label = ?"
            params.append(label)
        if start_date:
            sql += " AND snapshot_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND snapshot_date <= ?"
            params.append(end_date)

        sql += " ORDER BY snapshot_date, label"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_intraday_snapshots(
    ticker: str, date: str,
) -> List[tuple]:
    """Return all intraday-labeled snapshots for a date, ordered by time.

    Returns list of (label, ChainSnapshot) tuples where label starts with 'intraday_'.
    """
    import json

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM chain_snapshots "
            "WHERE ticker = ? AND snapshot_date = ? AND label LIKE 'intraday_%' "
            "ORDER BY label",
            (ticker, date),
        ).fetchall()

        results = []
        for row in rows:
            contracts_rows = conn.execute(
                "SELECT * FROM chain_contracts WHERE snapshot_id = ?",
                (row["id"],),
            ).fetchall()

            contracts = [
                OptionContract(
                    ticker=r["ticker"],
                    strike=r["strike"],
                    expiry=r["expiry"],
                    option_type=r["option_type"],
                    bid=r["bid"],
                    ask=r["ask"],
                    mid=r["mid"],
                    last=r["last"],
                    volume=r["volume"],
                    open_interest=r["open_interest"],
                    implied_volatility=r["implied_volatility"],
                )
                for r in contracts_rows
            ]

            snap = ChainSnapshot(
                ticker=row["ticker"],
                spot=row["spot"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                contracts=contracts,
                expiries=json.loads(row["expiries_json"]) if row["expiries_json"] else [],
            )
            results.append((row["label"], snap))

        return results
    finally:
        conn.close()


def get_intraday_snapshot_times(ticker: str, date: str) -> List[str]:
    """Return available intraday snapshot labels for a date."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT label FROM chain_snapshots "
            "WHERE ticker = ? AND snapshot_date = ? AND label LIKE 'intraday_%' "
            "ORDER BY label",
            (ticker, date),
        ).fetchall()
        return [r["label"] for r in rows]
    finally:
        conn.close()


def get_db_stats() -> dict:
    """Summary stats for the chain snapshot database."""
    conn = _get_conn()
    try:
        snap_count = conn.execute("SELECT COUNT(*) FROM chain_snapshots").fetchone()[0]
        contract_count = conn.execute("SELECT COUNT(*) FROM chain_contracts").fetchone()[0]
        iv_count = conn.execute("SELECT COUNT(*) FROM iv_snapshots").fetchone()[0]

        tickers = conn.execute(
            "SELECT DISTINCT ticker FROM chain_snapshots ORDER BY ticker"
        ).fetchall()
        ticker_list = [r["ticker"] for r in tickers]

        labels = conn.execute(
            "SELECT DISTINCT label FROM chain_snapshots ORDER BY label"
        ).fetchall()
        label_list = [r["label"] for r in labels]

        # Per-label breakdown
        label_stats = {}
        for lbl in label_list:
            row = conn.execute(
                "SELECT COUNT(*) as snaps, SUM(contracts_count) as contracts "
                "FROM chain_snapshots WHERE label = ?",
                (lbl,),
            ).fetchone()
            label_stats[lbl] = {
                "snapshots": row["snaps"],
                "contracts": row["contracts"] or 0,
            }

        date_range = conn.execute(
            "SELECT MIN(snapshot_date), MAX(snapshot_date) FROM chain_snapshots"
        ).fetchone()

        db_path = _get_db_path()
        db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

        return {
            "snapshots": snap_count,
            "contracts": contract_count,
            "iv_snapshots": iv_count,
            "tickers": ticker_list,
            "labels": label_stats,
            "date_range": {
                "start": date_range[0],
                "end": date_range[1],
            } if date_range[0] else None,
            "db_size_mb": round(db_size_mb, 2),
            "db_path": db_path,
        }
    finally:
        conn.close()
