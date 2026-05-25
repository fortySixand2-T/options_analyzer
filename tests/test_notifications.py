"""Tests for notification dispatcher — src/notifications/dispatcher.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from src.auth.database import init_auth_db, get_connection
from src.data.user_db import init_user_tables, get_user_db
from src.notifications.dispatcher import (
    send_notification, get_unread_notifications, get_notifications,
    get_unread_count, mark_as_read, mark_all_read,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_auth_db()
    init_user_tables()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notifications")
        conn.execute("DELETE FROM users")
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (1, 'a@b.com', 'x', 'A', '2026-01-01T00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    yield


class TestSendNotification:
    def test_returns_id(self):
        nid = send_notification(1, title="Hello")
        assert isinstance(nid, int)
        assert nid > 0

    def test_stores_fields(self):
        send_notification(1, title="Test", body="Body", notification_type="alert")
        notifs = get_notifications(1)
        assert len(notifs) == 1
        assert notifs[0]["title"] == "Test"
        assert notifs[0]["body"] == "Body"
        assert notifs[0]["type"] == "alert"


class TestGetNotifications:
    def test_empty(self):
        assert get_notifications(1) == []

    def test_unread_only(self):
        send_notification(1, title="A")
        nid = send_notification(1, title="B")
        mark_as_read(1, nid)
        unread = get_notifications(1, include_read=False)
        assert len(unread) == 1
        assert unread[0]["title"] == "A"

    def test_includes_read(self):
        send_notification(1, title="A")
        nid = send_notification(1, title="B")
        mark_as_read(1, nid)
        all_notifs = get_notifications(1, include_read=True)
        assert len(all_notifs) == 2


class TestUnreadCount:
    def test_zero_initially(self):
        assert get_unread_count(1) == 0

    def test_increments(self):
        send_notification(1, title="X")
        send_notification(1, title="Y")
        assert get_unread_count(1) == 2

    def test_decrements_on_read(self):
        nid = send_notification(1, title="X")
        mark_as_read(1, nid)
        assert get_unread_count(1) == 0


class TestMarkAsRead:
    def test_returns_true_on_success(self):
        nid = send_notification(1, title="X")
        assert mark_as_read(1, nid) is True

    def test_returns_false_wrong_user(self):
        nid = send_notification(1, title="X")
        assert mark_as_read(999, nid) is False

    def test_already_read_still_succeeds(self):
        nid = send_notification(1, title="X")
        mark_as_read(1, nid)
        # UPDATE still matches the row even if already read=1
        assert mark_as_read(1, nid) is True


class TestMarkAllRead:
    def test_marks_all(self):
        send_notification(1, title="A")
        send_notification(1, title="B")
        send_notification(1, title="C")
        count = mark_all_read(1)
        assert count == 3
        assert get_unread_count(1) == 0

    def test_returns_zero_when_none_unread(self):
        assert mark_all_read(1) == 0
