"""Tests for alert evaluation engine internals — src/alerts/engine.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import pytest
from datetime import datetime, timezone, timedelta

from unittest.mock import patch, call, MagicMock

from src.auth.database import init_auth_db, get_connection
from src.data.user_db import init_user_tables, get_user_db
from src.alerts.engine import _should_skip_cooldown, _evaluate_trigger, _fire_alert, _dispatch_webhooks


@pytest.fixture(autouse=True)
def _setup_db():
    init_auth_db()
    init_user_tables()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notifications")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM webhooks")
        conn.execute("DELETE FROM users")
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (1, 'a@b.com', 'x', 'A', '2026-01-01T00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    yield


def _make_alert(trigger_type="iv_rank_above", config=None, cooldown=60, last_triggered=None):
    """Create a mock alert row dict."""
    return {
        "id": 1,
        "user_id": 1,
        "name": "Test Alert",
        "trigger_type": trigger_type,
        "trigger_config_json": json.dumps(config or {"symbol": "SPY", "threshold": 70}),
        "channels_json": '["in_app"]',
        "is_active": 1,
        "cooldown_minutes": cooldown,
        "last_triggered_at": last_triggered,
        "email": "a@b.com",
    }


class TestCooldown:
    def test_no_last_triggered_not_skipped(self):
        alert = _make_alert(last_triggered=None)
        assert _should_skip_cooldown(alert) is False

    def test_recent_trigger_skipped(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        alert = _make_alert(cooldown=60, last_triggered=recent)
        assert _should_skip_cooldown(alert) is True

    def test_old_trigger_not_skipped(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
        alert = _make_alert(cooldown=60, last_triggered=old)
        assert _should_skip_cooldown(alert) is False

    def test_zero_cooldown_not_skipped(self):
        recent = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        alert = _make_alert(cooldown=0, last_triggered=recent)
        assert _should_skip_cooldown(alert) is False


class TestEvaluateTrigger:
    @patch("src.alerts.engine._get_iv_rank", return_value=80)
    def test_iv_rank_above_fires(self, _):
        alert = _make_alert("iv_rank_above", {"symbol": "SPY", "threshold": 70})
        assert _evaluate_trigger(alert) is True

    @patch("src.alerts.engine._get_iv_rank", return_value=50)
    def test_iv_rank_above_not_met(self, _):
        alert = _make_alert("iv_rank_above", {"symbol": "SPY", "threshold": 70})
        assert _evaluate_trigger(alert) is False

    @patch("src.alerts.engine._get_iv_rank", return_value=15)
    def test_iv_rank_below_fires(self, _):
        alert = _make_alert("iv_rank_below", {"symbol": "SPY", "threshold": 20})
        assert _evaluate_trigger(alert) is True

    @patch("src.alerts.engine._get_spot", return_value=510.0)
    def test_price_above_fires(self, _):
        alert = _make_alert("price_above", {"symbol": "SPY", "threshold": 500})
        assert _evaluate_trigger(alert) is True

    @patch("src.alerts.engine._get_spot", return_value=490.0)
    def test_price_above_not_met(self, _):
        alert = _make_alert("price_above", {"symbol": "SPY", "threshold": 500})
        assert _evaluate_trigger(alert) is False

    @patch("src.alerts.engine._get_spot", return_value=95.0)
    def test_price_below_fires(self, _):
        alert = _make_alert("price_below", {"symbol": "AAPL", "threshold": 100})
        assert _evaluate_trigger(alert) is True

    def test_regime_change_returns_false(self):
        alert = _make_alert("regime_change", {"symbol": "SPY"})
        assert _evaluate_trigger(alert) is False

    def test_scan_match_returns_false(self):
        alert = _make_alert("scan_match", {"symbol": "SPY"})
        assert _evaluate_trigger(alert) is False

    @patch("src.alerts.engine._get_iv_rank", return_value=None)
    def test_none_data_does_not_fire(self, _):
        alert = _make_alert("iv_rank_above", {"symbol": "XYZ", "threshold": 50})
        assert _evaluate_trigger(alert) is False


def _insert_webhook(user_id, name, wh_type, url, config=None, is_active=1):
    """Helper: insert a webhook row directly into the DB."""
    conn = get_user_db()
    try:
        conn.execute(
            """INSERT INTO webhooks (user_id, name, type, url, config_json, is_active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, name, wh_type, url, json.dumps(config or {}), is_active),
        )
        conn.commit()
    finally:
        conn.close()


class TestFireAlert:
    def test_creates_in_app_notification(self):
        alert = _make_alert()
        _fire_alert(alert)
        conn = get_user_db()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM notifications WHERE user_id = 1"
        ).fetchone()["c"]
        conn.close()
        assert count == 1

    def test_updates_last_triggered(self):
        conn = get_user_db()
        conn.execute(
            """INSERT INTO alerts (id, user_id, name, trigger_type, trigger_config_json,
               channels_json, is_active, cooldown_minutes)
               VALUES (1, 1, 'Test', 'iv_rank_above', '{}', '["in_app"]', 1, 60)"""
        )
        conn.commit()
        conn.close()

        alert = _make_alert()
        _fire_alert(alert)

        conn = get_user_db()
        row = conn.execute("SELECT last_triggered_at FROM alerts WHERE id = 1").fetchone()
        conn.close()
        assert row["last_triggered_at"] is not None

    @patch("src.alerts.engine.dispatch_webhook")
    def test_fire_alert_calls_active_webhooks(self, mock_dispatch):
        mock_dispatch.return_value = True
        _insert_webhook(1, "Discord", "discord", "https://discord.com/api/webhooks/x")
        _insert_webhook(1, "Slack",   "slack",   "https://hooks.slack.com/x")

        alert = _make_alert()
        _fire_alert(alert)

        assert mock_dispatch.call_count == 2
        called_types = {c.args[0] for c in mock_dispatch.call_args_list}
        assert called_types == {"discord", "slack"}

    @patch("src.alerts.engine.dispatch_webhook")
    def test_fire_alert_skips_inactive_webhooks(self, mock_dispatch):
        mock_dispatch.return_value = True
        _insert_webhook(1, "Inactive", "slack", "https://hooks.slack.com/x", is_active=0)

        alert = _make_alert()
        _fire_alert(alert)

        mock_dispatch.assert_not_called()

    @patch("src.alerts.engine.dispatch_webhook")
    def test_fire_alert_webhook_failure_does_not_raise(self, mock_dispatch):
        mock_dispatch.side_effect = Exception("network error")
        _insert_webhook(1, "Broken", "discord", "https://discord.com/x")

        alert = _make_alert()
        _fire_alert(alert)  # should not raise

        conn = get_user_db()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM notifications WHERE user_id = 1"
        ).fetchone()["c"]
        conn.close()
        assert count == 1  # in-app notification still created


class TestDispatchWebhooks:
    @patch("src.alerts.engine.dispatch_webhook")
    def test_dispatches_to_all_active(self, mock_dispatch):
        mock_dispatch.return_value = True
        _insert_webhook(1, "Discord",  "discord",  "https://discord.com/x")
        _insert_webhook(1, "Slack",    "slack",    "https://hooks.slack.com/x")
        _insert_webhook(1, "Telegram", "telegram", "", config={"bot_token": "tok", "chat_id": "123"})

        _dispatch_webhooks(1, "Test Title", "Test Body")

        assert mock_dispatch.call_count == 3
        called_types = [c.args[0] for c in mock_dispatch.call_args_list]
        assert set(called_types) == {"discord", "slack", "telegram"}

    @patch("src.alerts.engine.dispatch_webhook")
    def test_passes_url_in_config(self, mock_dispatch):
        mock_dispatch.return_value = True
        _insert_webhook(1, "Slack", "slack", "https://hooks.slack.com/mytoken")

        _dispatch_webhooks(1, "Title", "Body")

        cfg = mock_dispatch.call_args.args[1]
        assert cfg["url"] == "https://hooks.slack.com/mytoken"

    @patch("src.alerts.engine.dispatch_webhook")
    def test_passes_telegram_config_fields(self, mock_dispatch):
        mock_dispatch.return_value = True
        _insert_webhook(1, "Tg", "telegram", "",
                        config={"bot_token": "123:ABC", "chat_id": "456"})

        _dispatch_webhooks(1, "Title", "Body")

        cfg = mock_dispatch.call_args.args[1]
        assert cfg["bot_token"] == "123:ABC"
        assert cfg["chat_id"] == "456"

    @patch("src.alerts.engine.dispatch_webhook")
    def test_ignores_inactive_webhooks(self, mock_dispatch):
        _insert_webhook(1, "Off", "slack", "https://x", is_active=0)
        _dispatch_webhooks(1, "T", "B")
        mock_dispatch.assert_not_called()

    @patch("src.alerts.engine.dispatch_webhook")
    def test_no_webhooks_no_calls(self, mock_dispatch):
        _dispatch_webhooks(1, "T", "B")
        mock_dispatch.assert_not_called()

    @patch("src.alerts.engine.dispatch_webhook")
    def test_failed_webhook_does_not_stop_others(self, mock_dispatch):
        mock_dispatch.side_effect = [Exception("fail"), True]
        _insert_webhook(1, "Bad",  "discord", "https://bad.com")
        _insert_webhook(1, "Good", "slack",   "https://hooks.slack.com/x")

        _dispatch_webhooks(1, "T", "B")  # should not raise
        assert mock_dispatch.call_count == 2

    @patch("src.alerts.engine.dispatch_webhook")
    def test_only_dispatches_for_correct_user(self, mock_dispatch):
        mock_dispatch.return_value = True
        # Insert a webhook for user 2 — should not be called
        conn = get_user_db()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (2, 'b@b.com', 'x', 'B', '2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()
        _insert_webhook(2, "Other", "slack", "https://hooks.slack.com/other")
        _insert_webhook(1, "Mine",  "discord", "https://discord.com/x")

        _dispatch_webhooks(1, "T", "B")

        assert mock_dispatch.call_count == 1
        assert mock_dispatch.call_args.args[0] == "discord"
