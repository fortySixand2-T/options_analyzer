"""
SQLite storage for intraday price bars.

Separate DB (data/intraday.db) from chain_snapshots.db to keep
intraday volume from bloating the daily chain storage.

Stores 1-min and 5-min OHLCV bars for SPY, SPX, VIX for:
- 0 DTE backtesting (walk 5-min bars during session)
- Day-type classification (first 30-min range)
- Move exhaustion tracking (intraday realized movement)

Options Analytics Team — 2026-04
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "intraday.db",
)


def _get_db_path() -> str:
    path = os.getenv("INTRADAY_DB", _DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    """Idempotent schema creation."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intraday_bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            bar_date TEXT NOT NULL,
            interval TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER DEFAULT 0,
            UNIQUE(ticker, bar_time, interval)
        );

        CREATE INDEX IF NOT EXISTS idx_bars_ticker_date
            ON intraday_bars(ticker, bar_date, interval);
        CREATE INDEX IF NOT EXISTS idx_bars_time
            ON intraday_bars(ticker, bar_time);
    """)


# ── Write ────────────────────────────────────────────────────────────────────


def store_bars(ticker: str, bars_df: pd.DataFrame, interval: str = "5m") -> int:
    """Store intraday bars from a yfinance DataFrame.

    Args:
        ticker: Symbol (e.g., "SPY", "^SPX", "^VIX").
        bars_df: DataFrame with DatetimeIndex and columns: Open, High, Low, Close, Volume.
        interval: Bar interval string ('1m', '5m', '15m', '30m').

    Returns:
        Number of rows upserted.
    """
    if bars_df is None or bars_df.empty:
        return 0

    conn = _get_conn()
    count = 0

    try:
        for ts, row in bars_df.iterrows():
            bar_time = ts.isoformat()
            bar_date = ts.strftime("%Y-%m-%d")

            conn.execute("""
                INSERT INTO intraday_bars
                    (ticker, bar_time, bar_date, interval, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, bar_time, interval) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
            """, (
                ticker, bar_time, bar_date, interval,
                float(row.get("Open", 0)),
                float(row.get("High", 0)),
                float(row.get("Low", 0)),
                float(row.get("Close", 0)),
                int(row.get("Volume", 0)),
            ))
            count += 1

        conn.commit()
        logger.info("Stored %d %s bars for %s", count, interval, ticker)
    except Exception as e:
        conn.rollback()
        logger.error("Failed to store bars for %s: %s", ticker, e)
        raise
    finally:
        conn.close()

    return count


# ── Read ─────────────────────────────────────────────────────────────────────


def get_bars(ticker: str, date: str, interval: str = "5m") -> pd.DataFrame:
    """Retrieve intraday bars for a single date.

    Returns DataFrame with DatetimeIndex (timezone-aware) and OHLCV columns.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT bar_time, open, high, low, close, volume "
            "FROM intraday_bars "
            "WHERE ticker = ? AND bar_date = ? AND interval = ? "
            "ORDER BY bar_time",
            (ticker, date, interval),
        ).fetchall()

        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        data = []
        for r in rows:
            data.append({
                "time": pd.Timestamp(r["bar_time"]),
                "Open": r["open"],
                "High": r["high"],
                "Low": r["low"],
                "Close": r["close"],
                "Volume": r["volume"],
            })

        df = pd.DataFrame(data)
        df.set_index("time", inplace=True)
        df.index.name = None
        return df
    finally:
        conn.close()


def get_bars_range(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str = "5m",
) -> pd.DataFrame:
    """Retrieve intraday bars across multiple dates.

    Returns a single DataFrame spanning the date range.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT bar_time, open, high, low, close, volume "
            "FROM intraday_bars "
            "WHERE ticker = ? AND bar_date >= ? AND bar_date <= ? AND interval = ? "
            "ORDER BY bar_time",
            (ticker, start_date, end_date, interval),
        ).fetchall()

        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        data = []
        for r in rows:
            data.append({
                "time": pd.Timestamp(r["bar_time"]),
                "Open": r["open"],
                "High": r["high"],
                "Low": r["low"],
                "Close": r["close"],
                "Volume": r["volume"],
            })

        df = pd.DataFrame(data)
        df.set_index("time", inplace=True)
        df.index.name = None
        return df
    finally:
        conn.close()


def get_available_dates(ticker: str, interval: str = "5m") -> List[str]:
    """List all dates with stored bars for a ticker."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT bar_date FROM intraday_bars "
            "WHERE ticker = ? AND interval = ? ORDER BY bar_date",
            (ticker, interval),
        ).fetchall()
        return [r["bar_date"] for r in rows]
    finally:
        conn.close()


def get_intraday_stats() -> dict:
    """Summary stats for the intraday database."""
    conn = _get_conn()
    try:
        total_rows = conn.execute("SELECT COUNT(*) FROM intraday_bars").fetchone()[0]

        tickers = conn.execute(
            "SELECT DISTINCT ticker FROM intraday_bars ORDER BY ticker"
        ).fetchall()
        ticker_list = [r["ticker"] for r in tickers]

        intervals = conn.execute(
            "SELECT DISTINCT interval FROM intraday_bars ORDER BY interval"
        ).fetchall()
        interval_list = [r["interval"] for r in intervals]

        date_range = conn.execute(
            "SELECT MIN(bar_date), MAX(bar_date) FROM intraday_bars"
        ).fetchone()

        # Per-ticker breakdown
        ticker_stats = {}
        for t in ticker_list:
            row = conn.execute(
                "SELECT COUNT(*) as bars, COUNT(DISTINCT bar_date) as days "
                "FROM intraday_bars WHERE ticker = ?",
                (t,),
            ).fetchone()
            ticker_stats[t] = {"bars": row["bars"], "days": row["days"]}

        db_path = _get_db_path()
        db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

        return {
            "total_bars": total_rows,
            "tickers": ticker_stats,
            "intervals": interval_list,
            "date_range": {
                "start": date_range[0],
                "end": date_range[1],
            } if date_range[0] else None,
            "db_size_mb": round(db_size_mb, 2),
            "db_path": db_path,
        }
    finally:
        conn.close()
