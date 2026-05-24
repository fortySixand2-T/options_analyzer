"""SQLite database operations for user management."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from src.auth.config import AUTH_DB_PATH


def _get_db_path() -> str:
    path = os.path.abspath(AUTH_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_auth_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            tier          TEXT NOT NULL DEFAULT 'free',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
    """)
    conn.commit()
    conn.close()


def create_user(email: str, password_hash: str, display_name: str) -> dict:
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, display_name, now),
        )
        conn.commit()
        user_id = cursor.lastrowid
    finally:
        conn.close()
    return {"id": user_id, "email": email, "display_name": display_name, "tier": "free", "is_active": True}


def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def store_refresh_token(user_id: int, token_hash: str, expires_at: str) -> None:
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token_hash, expires_at, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_refresh_token(token_hash: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ? AND revoked = 0",
            (token_hash,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def revoke_refresh_token(token_hash: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?", (token_hash,))
        conn.commit()
    finally:
        conn.close()


def revoke_all_user_tokens(user_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
