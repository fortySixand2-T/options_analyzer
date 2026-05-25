"""Tests for user isolation — ensures one user cannot access another's data."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from fastapi.testclient import TestClient
from ui.app import app
from conftest import get_auth_headers

client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_db():
    from src.auth.database import init_auth_db, get_connection
    from src.data.user_db import init_user_tables
    init_auth_db()
    init_user_tables()
    conn = get_connection()
    conn.execute("DELETE FROM refresh_tokens")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()


@pytest.fixture
def user_a():
    return get_auth_headers(client, email="alice@test.com", display_name="Alice")


@pytest.fixture
def user_b():
    return get_auth_headers(client, email="bob@test.com", display_name="Bob")


class TestWatchlistIsolation:
    def test_users_see_only_own_items(self, user_a, user_b):
        client.post("/api/watchlist", json={"symbol": "SPY"}, headers=user_a)
        client.post("/api/watchlist", json={"symbol": "QQQ"}, headers=user_b)

        a_items = client.get("/api/watchlist", headers=user_a).json()["items"]
        b_items = client.get("/api/watchlist", headers=user_b).json()["items"]
        assert len(a_items) == 1 and a_items[0]["symbol"] == "SPY"
        assert len(b_items) == 1 and b_items[0]["symbol"] == "QQQ"

    def test_cannot_delete_other_users_item(self, user_a, user_b):
        client.post("/api/watchlist", json={"symbol": "AAPL"}, headers=user_a)
        items = client.get("/api/watchlist", headers=user_a).json()["items"]
        item_id = items[0]["id"]
        resp = client.delete(f"/api/watchlist/{item_id}", headers=user_b)
        assert resp.status_code == 404
        assert client.get("/api/watchlist", headers=user_a).json()["count"] == 1


class TestPositionIsolation:
    def test_users_see_only_own_positions(self, user_a, user_b):
        body = {"symbol": "SPY", "strategy": "iron_condor",
                "entry_date": "2026-05-20", "entry_price": 3.0}
        client.post("/api/positions", json=body, headers=user_a)
        client.post("/api/positions", json={**body, "symbol": "QQQ"}, headers=user_b)

        a_pos = client.get("/api/positions", headers=user_a).json()["positions"]
        b_pos = client.get("/api/positions", headers=user_b).json()["positions"]
        assert len(a_pos) == 1 and a_pos[0]["symbol"] == "SPY"
        assert len(b_pos) == 1 and b_pos[0]["symbol"] == "QQQ"

    def test_cannot_close_other_users_position(self, user_a, user_b):
        body = {"symbol": "SPY", "strategy": "iron_condor",
                "entry_date": "2026-05-20", "entry_price": 3.0}
        r = client.post("/api/positions", json=body, headers=user_a)
        pid = r.json()["id"]
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 1.0}, headers=user_b)
        assert resp.status_code == 404


class TestAlertIsolation:
    def test_users_see_only_own_alerts(self, user_a, user_b):
        alert = {"name": "A alert", "trigger_type": "iv_rank_above",
                 "trigger_config": {"symbol": "SPY", "threshold": 70}}
        client.post("/api/alerts", json=alert, headers=user_a)
        client.post("/api/alerts", json={**alert, "name": "B alert"}, headers=user_b)

        a_alerts = client.get("/api/alerts", headers=user_a).json()["alerts"]
        b_alerts = client.get("/api/alerts", headers=user_b).json()["alerts"]
        assert len(a_alerts) == 1 and a_alerts[0]["name"] == "A alert"
        assert len(b_alerts) == 1 and b_alerts[0]["name"] == "B alert"

    def test_cannot_delete_other_users_alert(self, user_a, user_b):
        alert = {"name": "Private", "trigger_type": "price_above",
                 "trigger_config": {"symbol": "AAPL", "threshold": 200}}
        r = client.post("/api/alerts", json=alert, headers=user_a)
        aid = r.json()["id"]
        resp = client.delete(f"/api/alerts/{aid}", headers=user_b)
        assert resp.status_code == 404


class TestJournalIsolation:
    def test_users_see_only_own_entries(self, user_a, user_b):
        entry = {"strategy": "iron_condor", "symbol": "SPY",
                 "entry_date": "2026-05-20", "entry_price": 2.50}
        client.post("/api/journal", json=entry, headers=user_a)
        client.post("/api/journal", json={**entry, "symbol": "QQQ"}, headers=user_b)

        a_entries = client.get("/api/journal", headers=user_a).json()["entries"]
        b_entries = client.get("/api/journal", headers=user_b).json()["entries"]
        a_symbols = [e["symbol"] for e in a_entries]
        b_symbols = [e["symbol"] for e in b_entries]
        assert "SPY" in a_symbols and "QQQ" not in a_symbols
        assert "QQQ" in b_symbols and "SPY" not in b_symbols
