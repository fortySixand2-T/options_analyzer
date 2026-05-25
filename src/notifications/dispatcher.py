"""Notification dispatcher — stores in-app notifications, extensible to email/webhooks."""

import logging
from typing import Optional

from src.data.user_db import get_user_db, utcnow_iso

logger = logging.getLogger(__name__)


def send_notification(
    user_id: int,
    title: str,
    body: str = "",
    notification_type: str = "info",
) -> int:
    conn = get_user_db()
    try:
        cursor = conn.execute(
            """INSERT INTO notifications (user_id, type, title, body, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, notification_type, title, body, utcnow_iso()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_unread_notifications(user_id: int, limit: int = 20) -> list[dict]:
    conn = get_user_db()
    try:
        rows = conn.execute(
            """SELECT id, type, title, body, created_at FROM notifications
               WHERE user_id = ? AND read = 0
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_notifications(user_id: int, limit: int = 50, include_read: bool = True) -> list[dict]:
    conn = get_user_db()
    try:
        if include_read:
            rows = conn.execute(
                """SELECT id, type, title, body, read, created_at FROM notifications
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, type, title, body, read, created_at FROM notifications
                   WHERE user_id = ? AND read = 0
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unread_count(user_id: int) -> int:
    conn = get_user_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND read = 0",
            (user_id,),
        ).fetchone()
        return row["c"]
    finally:
        conn.close()


def mark_as_read(user_id: int, notification_id: int) -> bool:
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_all_read(user_id: int) -> int:
    conn = get_user_db()
    try:
        cursor = conn.execute(
            "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
            (user_id,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
