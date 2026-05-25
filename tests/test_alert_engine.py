"""Tests for alert evaluation engine internals — src/alerts/engine.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.auth.database import init_auth_db, get_connection
from src.data.user_db import init_user_tables, get_user_db
from src.alerts.engine import _should_skip_cooldown, _evaluate_trigger, _fire_alert


@pytest.fixture(autouse=True)
def _setup_db():
    init_auth_db()
    init_user_tables()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notifications")
        conn.execute("DELETE FROM alerts")
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


class TestFireAlert:
    def test_creates_notification(self):
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
