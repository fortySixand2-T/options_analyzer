"""
SQLite storage for sentiment data.

Three tables: headlines, scored_headlines, sentiment_snapshots.
Idempotent schema init, WAL mode, upsert-based writes.

Mirrors the chain_store.py pattern from src/data/.
Zero imports from other src/ packages.
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    Headline,
    ScoredHeadline,
    SentimentLabel,
    SentimentSnapshot,
    SignalLabel,
)

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    from .config import SENTIMENT_DB_PATH
    os.makedirs(os.path.dirname(SENTIMENT_DB_PATH), exist_ok=True)
    return SENTIMENT_DB_PATH


def _get_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    """Idempotent schema creation."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS headlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            text TEXT NOT NULL,
            published_at TEXT NOT NULL,
            source TEXT NOT NULL,
            url TEXT,
            collected_at TEXT NOT NULL,
            UNIQUE(ticker, text, published_at)
        );

        CREATE INDEX IF NOT EXISTS idx_headlines_ticker_date
            ON headlines(ticker, published_at);

        CREATE TABLE IF NOT EXISTS scored_headlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headline_id INTEGER NOT NULL REFERENCES headlines(id),
            positive REAL NOT NULL,
            negative REAL NOT NULL,
            neutral REAL NOT NULL,
            confidence REAL NOT NULL,
            label TEXT NOT NULL,
            model_version TEXT NOT NULL,
            scored_at TEXT NOT NULL,
            UNIQUE(headline_id, model_version)
        );

        CREATE INDEX IF NOT EXISTS idx_scored_headline_id
            ON scored_headlines(headline_id);

        CREATE TABLE IF NOT EXISTS sentiment_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            window TEXT NOT NULL,
            composite_score REAL NOT NULL,
            velocity REAL,
            breadth REAL,
            headline_count INTEGER NOT NULL,
            signal_label TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            UNIQUE(ticker, window, computed_at)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_window
            ON sentiment_snapshots(ticker, window);
    """)


class SentimentStore:
    """Read/write interface for the sentiment SQLite database."""

    def __init__(self, db_path: str = None):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _get_conn(self._db_path)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Headlines ──────────────────────────────────────────────────────────

    def save_headlines(self, headlines: List[Headline]) -> int:
        """Save raw headlines. Returns count of new inserts (duplicates skipped)."""
        conn = self._ensure_conn()
        inserted = 0
        for h in headlines:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO headlines
                       (ticker, text, published_at, source, url, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        h.ticker,
                        h.text,
                        h.published_at.isoformat(),
                        h.source,
                        h.url,
                        h.collected_at.isoformat() if h.collected_at else datetime.utcnow().isoformat(),
                    ),
                )
                inserted += conn.total_changes  # approximate
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return inserted

    def get_headline_id(self, headline: Headline) -> Optional[int]:
        """Get the database ID for a headline, or None if not found."""
        conn = self._ensure_conn()
        row = conn.execute(
            """SELECT id FROM headlines
               WHERE ticker = ? AND text = ? AND published_at = ?""",
            (headline.ticker, headline.text, headline.published_at.isoformat()),
        ).fetchone()
        return row["id"] if row else None

    # ── Scored headlines ───────────────────────────────────────────────────

    def save_scored(self, scored: List[ScoredHeadline]) -> int:
        """Save scored headlines. Requires headlines to be saved first."""
        conn = self._ensure_conn()
        inserted = 0
        for s in scored:
            h_id = self.get_headline_id(s.headline)
            if h_id is None:
                # Auto-save the headline
                self.save_headlines([s.headline])
                h_id = self.get_headline_id(s.headline)
                if h_id is None:
                    logger.warning("Could not save headline: %s", s.headline.text[:60])
                    continue
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO scored_headlines
                       (headline_id, positive, negative, neutral, confidence,
                        label, model_version, scored_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        h_id,
                        s.positive,
                        s.negative,
                        s.neutral,
                        s.confidence,
                        s.label.value,
                        s.model_version,
                        s.scored_at.isoformat() if s.scored_at else datetime.utcnow().isoformat(),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return inserted

    def get_scored_headlines(
        self,
        ticker: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        model_version: str = "ProsusAI/finbert",
    ) -> List[Dict]:
        """Fetch scored headlines for aggregation.

        Returns list of dicts with keys:
            text, published_at, positive, negative, neutral, confidence, label
        """
        conn = self._ensure_conn()
        query = """
            SELECT h.text, h.published_at, h.source,
                   s.positive, s.negative, s.neutral, s.confidence, s.label
            FROM scored_headlines s
            JOIN headlines h ON h.id = s.headline_id
            WHERE h.ticker = ?
              AND s.model_version = ?
        """
        params: list = [ticker, model_version]

        if since:
            query += " AND h.published_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND h.published_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY h.published_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_unscored_headline_ids(
        self,
        model_version: str = "ProsusAI/finbert",
        limit: int = 500,
    ) -> List[Dict]:
        """Find headlines not yet scored by a given model."""
        conn = self._ensure_conn()
        rows = conn.execute(
            """SELECT h.id, h.ticker, h.text, h.published_at, h.source
               FROM headlines h
               LEFT JOIN scored_headlines s
                   ON s.headline_id = h.id AND s.model_version = ?
               WHERE s.id IS NULL
               ORDER BY h.published_at DESC
               LIMIT ?""",
            (model_version, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Sentiment snapshots ────────────────────────────────────────────────

    def save_snapshot(self, snapshot: SentimentSnapshot) -> None:
        """Save an aggregated sentiment snapshot."""
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO sentiment_snapshots
               (ticker, window, composite_score, velocity, breadth,
                headline_count, signal_label, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.ticker,
                snapshot.window,
                snapshot.composite_score,
                snapshot.velocity,
                snapshot.breadth,
                snapshot.headline_count,
                snapshot.signal_label.value,
                snapshot.computed_at.isoformat(),
            ),
        )
        conn.commit()

    def get_latest_snapshot(
        self,
        ticker: str,
        window: str,
    ) -> Optional[SentimentSnapshot]:
        """Get the most recent snapshot for a ticker/window."""
        conn = self._ensure_conn()
        row = conn.execute(
            """SELECT * FROM sentiment_snapshots
               WHERE ticker = ? AND window = ?
               ORDER BY computed_at DESC LIMIT 1""",
            (ticker, window),
        ).fetchone()
        if not row:
            return None
        return SentimentSnapshot(
            ticker=row["ticker"],
            window=row["window"],
            composite_score=row["composite_score"],
            velocity=row["velocity"],
            breadth=row["breadth"],
            headline_count=row["headline_count"],
            computed_at=datetime.fromisoformat(row["computed_at"]),
            signal_label=SignalLabel(row["signal_label"]),
        )

    def get_snapshot_history(
        self,
        ticker: str,
        window: str,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[SentimentSnapshot]:
        """Get historical snapshots for backtesting."""
        conn = self._ensure_conn()
        query = """SELECT * FROM sentiment_snapshots
                   WHERE ticker = ? AND window = ?"""
        params: list = [ticker, window]
        if since:
            query += " AND computed_at >= ?"
            params.append(since.isoformat())
        query += " ORDER BY computed_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [
            SentimentSnapshot(
                ticker=r["ticker"],
                window=r["window"],
                composite_score=r["composite_score"],
                velocity=r["velocity"],
                breadth=r["breadth"],
                headline_count=r["headline_count"],
                computed_at=datetime.fromisoformat(r["computed_at"]),
                signal_label=SignalLabel(r["signal_label"]),
            )
            for r in rows
        ]

    # ── Stats ──────────────────────────────────────────────────────────────

    def headline_count(self, ticker: str = None) -> int:
        conn = self._ensure_conn()
        if ticker:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM headlines WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM headlines").fetchone()
        return row["cnt"]

    def scored_count(self, ticker: str = None) -> int:
        conn = self._ensure_conn()
        if ticker:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM scored_headlines s
                   JOIN headlines h ON h.id = s.headline_id
                   WHERE h.ticker = ?""",
                (ticker,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM scored_headlines"
            ).fetchone()
        return row["cnt"]
