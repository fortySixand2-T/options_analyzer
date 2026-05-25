"""Shared SQLite helper for user-scoped tables in data/users.db.

All user-scoped feature tables (journal, watchlist, positions, alerts,
notifications, presets) live alongside auth tables in a single DB.
"""

import os
import sqlite3
from datetime import datetime, timezone

from src.auth.config import AUTH_DB_PATH


def get_user_db() -> sqlite3.Connection:
    path = os.path.abspath(AUTH_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_user_tables() -> None:
    conn = get_user_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS journal (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            strategy      TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            entry_date    TEXT NOT NULL,
            entry_price   REAL NOT NULL,
            exit_date     TEXT,
            exit_price    REAL,
            contracts     INTEGER DEFAULT 1,
            pnl           REAL,
            notes         TEXT DEFAULT '',
            regime_at_entry TEXT,
            bias_at_entry   TEXT,
            edge_at_entry   REAL,
            tags          TEXT DEFAULT '',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type       TEXT NOT NULL DEFAULT 'info',
            title      TEXT NOT NULL,
            body       TEXT DEFAULT '',
            read       INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol          TEXT NOT NULL,
            strategy        TEXT NOT NULL,
            legs_json       TEXT,
            entry_date      TEXT NOT NULL,
            entry_price     REAL NOT NULL,
            is_credit       INTEGER DEFAULT 1,
            contracts       INTEGER DEFAULT 1,
            max_loss        REAL,
            profit_target   REAL,
            stop_loss       REAL,
            exit_date       TEXT,
            exit_price      REAL,
            exit_reason     TEXT,
            pnl             REAL,
            status          TEXT NOT NULL DEFAULT 'open',
            regime_at_entry TEXT,
            bias_at_entry   TEXT,
            notes           TEXT DEFAULT '',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS watchlist_items (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol              TEXT NOT NULL,
            alert_iv_rank_above REAL,
            alert_iv_rank_below REAL,
            notes               TEXT DEFAULT '',
            sort_order          INTEGER DEFAULT 0,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS scanner_presets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            config_json TEXT NOT NULL,
            is_pinned   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_journal_user ON journal(user_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, read);
        CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id);
        CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist_items(user_id);
        CREATE INDEX IF NOT EXISTS idx_scanner_presets_user ON scanner_presets(user_id);
    """)
    conn.commit()
    conn.close()


def migrate_journal_from_legacy() -> None:
    """Migrate journal entries from the old data/journal.db into users.db."""
    legacy_path = os.path.join(os.path.dirname(os.path.abspath(AUTH_DB_PATH)), "journal.db")
    if not os.path.exists(legacy_path):
        return

    legacy = sqlite3.connect(legacy_path, timeout=10)
    legacy.row_factory = sqlite3.Row
    rows = legacy.execute("SELECT * FROM journal ORDER BY id").fetchall()
    legacy.close()

    if not rows:
        return

    conn = get_user_db()
    first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    default_user_id = first_user["id"] if first_user else 1

    existing = conn.execute("SELECT COUNT(*) as c FROM journal").fetchone()["c"]
    if existing > 0:
        conn.close()
        return

    for row in rows:
        conn.execute(
            """INSERT INTO journal (user_id, strategy, symbol, entry_date, entry_price,
               exit_date, exit_price, contracts, pnl, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (default_user_id, row["strategy"], row["symbol"], row["entry_date"],
             row["entry_price"], row["exit_date"], row["exit_price"],
             row["contracts"], row["pnl"], row["notes"], row["created_at"]),
        )
    conn.commit()
    conn.close()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
