"""Tests for webhook notifier + settings router — src/notifications/webhook_notifier.py, src/ui/settings_router.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from ui.app import app
from conftest import get_auth_headers
from src.notifications.webhook_notifier import (
    send_discord, send_slack, send_telegram, send_generic_webhook, dispatch_webhook,
)


client = TestClient(app)


@pytest.fixture
def _setup_db():
    from src.auth.database import init_auth_db, get_connection
    from src.data.user_db import init_user_tables
    init_auth_db()
    init_user_tables()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM refresh_tokens")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture
def auth(_setup_db):
    return get_auth_headers(client)


class TestWebhookNotifierUnit:
    @patch("src.notifications.webhook_notifier.requests.post")
    def test_discord_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        assert send_discord("https://discord.com/api/webhooks/x", "Title", "Body") is True
        call_kwargs = mock_post.call_args[1]
        assert "embeds" in call_kwargs["json"]

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_discord_failure(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400)
        assert send_discord("https://bad", "T") is False

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_slack_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        assert send_slack("https://hooks.slack.com/x", "Title") is True

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_slack_includes_title_in_text(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        send_slack("https://hooks.slack.com/x", "My Alert", "Some body")
        payload = mock_post.call_args[1]["json"]
        assert "My Alert" in payload["text"]
        assert "Some body" in payload["text"]

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_slack_failure(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500)
        assert send_slack("https://hooks.slack.com/x", "T") is False

    # ── Telegram ────────────────────────────────────────────────────────────────

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_telegram_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        assert send_telegram("123:ABC", "456", "Title", "Body") is True

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_telegram_posts_to_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        send_telegram("MY_TOKEN", "MY_CHAT", "Title")
        url = mock_post.call_args.args[0]
        assert "MY_TOKEN" in url
        assert "sendMessage" in url

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_telegram_sends_chat_id(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        send_telegram("tok", "999", "Title", "Body")
        payload = mock_post.call_args[1]["json"]
        assert payload["chat_id"] == "999"
        assert "Title" in payload["text"]

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_telegram_failure(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400)
        assert send_telegram("tok", "123", "T") is False

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_telegram_network_error_returns_false(self, mock_post):
        mock_post.side_effect = Exception("timeout")
        assert send_telegram("tok", "123", "T") is False

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_dispatch_routes_telegram(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        result = dispatch_webhook(
            "telegram",
            {"url": "", "bot_token": "123:ABC", "chat_id": "456"},
            "Title", "Body",
        )
        assert result is True

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_generic_webhook_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        assert send_generic_webhook("https://example.com/hook", "Title", "Body") is True
        payload = mock_post.call_args[1]["json"]
        assert payload["title"] == "Title"
        assert payload["source"] == "options-analyzer"

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_dispatch_routes_correctly(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        assert dispatch_webhook("discord", {"url": "https://x"}, "T") is True

    def test_dispatch_unknown_type(self):
        assert dispatch_webhook("unknown", {"url": "x"}, "T") is False

    @patch("src.notifications.webhook_notifier.requests.post")
    def test_network_error_returns_false(self, mock_post):
        mock_post.side_effect = Exception("timeout")
        assert send_discord("https://x", "T") is False


class TestSettingsRouter:
    def test_get_settings(self, auth):
        resp = client.get("/api/user/settings", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "tier" in data
        assert "limits" in data
        assert "webhooks" in data

    def test_update_settings(self, auth):
        resp = client.put("/api/user/settings", json={
            "notification_prefs": {"email": False, "in_app": True}
        }, headers=auth)
        assert resp.status_code == 200
        settings = client.get("/api/user/settings", headers=auth).json()["settings"]
        assert settings["notification_prefs"]["email"] is False

    def test_create_webhook(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "My Discord", "type": "discord",
            "url": "https://discord.com/api/webhooks/123/abc",
        }, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_webhook_invalid_type(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "Bad", "type": "sms", "url": "https://x",
        }, headers=auth)
        assert resp.status_code == 400

    def test_create_webhook_empty_url(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "X", "type": "slack", "url": "  ",
        }, headers=auth)
        assert resp.status_code == 400

    def test_delete_webhook(self, auth):
        r = client.post("/api/user/webhooks", json={
            "name": "Test", "type": "webhook", "url": "https://x.com/hook",
        }, headers=auth)
        wid = r.json()["id"]
        resp = client.delete(f"/api/user/webhooks/{wid}", headers=auth)
        assert resp.status_code == 200

    def test_delete_nonexistent_webhook_404(self, auth):
        resp = client.delete("/api/user/webhooks/9999", headers=auth)
        assert resp.status_code == 404

    def test_create_slack_webhook(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "My Slack", "type": "slack",
            "url": "https://hooks.slack.com/services/T/B/token",
        }, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_telegram_webhook(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "My Telegram", "type": "telegram",
            "url": "",
            "config": {"bot_token": "123:ABC", "chat_id": "456"},
        }, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_telegram_missing_bot_token_400(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "Bad Tg", "type": "telegram", "url": "",
            "config": {"chat_id": "456"},
        }, headers=auth)
        assert resp.status_code == 400

    def test_create_telegram_missing_chat_id_400(self, auth):
        resp = client.post("/api/user/webhooks", json={
            "name": "Bad Tg", "type": "telegram", "url": "",
            "config": {"bot_token": "123:ABC"},
        }, headers=auth)
        assert resp.status_code == 400

    def test_telegram_webhook_appears_in_settings(self, auth):
        client.post("/api/user/webhooks", json={
            "name": "Tg", "type": "telegram", "url": "",
            "config": {"bot_token": "tok", "chat_id": "123"},
        }, headers=auth)
        webhooks = client.get("/api/user/settings", headers=auth).json()["webhooks"]
        tg = next((w for w in webhooks if w["type"] == "telegram"), None)
        assert tg is not None
        assert tg["name"] == "Tg"

    def test_requires_auth(self):
        assert client.get("/api/user/settings").status_code == 401
