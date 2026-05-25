"""Tests for watchlist CRUD — src/ui/watchlist_router.py"""

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
def auth():
    return get_auth_headers(client)


class TestWatchlistCRUD:
    def test_empty_watchlist(self, auth):
        resp = client.get("/api/watchlist", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["count"] == 0

    def test_add_symbol(self, auth):
        resp = client.post("/api/watchlist", json={"symbol": "SPY"}, headers=auth)
        assert resp.status_code == 201
        assert resp.json()["symbol"] == "SPY"

    def test_add_normalizes_to_uppercase(self, auth):
        resp = client.post("/api/watchlist", json={"symbol": "qqq"}, headers=auth)
        assert resp.status_code == 201
        assert resp.json()["symbol"] == "QQQ"

    def test_add_duplicate_rejected(self, auth):
        client.post("/api/watchlist", json={"symbol": "SPY"}, headers=auth)
        resp = client.post("/api/watchlist", json={"symbol": "SPY"}, headers=auth)
        assert resp.status_code == 409

    def test_add_empty_symbol_rejected(self, auth):
        resp = client.post("/api/watchlist", json={"symbol": "  "}, headers=auth)
        assert resp.status_code == 400

    def test_list_returns_added_items(self, auth):
        client.post("/api/watchlist", json={"symbol": "SPY"}, headers=auth)
        client.post("/api/watchlist", json={"symbol": "QQQ"}, headers=auth)
        resp = client.get("/api/watchlist", headers=auth)
        symbols = [i["symbol"] for i in resp.json()["items"]]
        assert "SPY" in symbols
        assert "QQQ" in symbols
        assert resp.json()["count"] == 2

    def test_update_thresholds(self, auth):
        client.post("/api/watchlist", json={"symbol": "SPY"}, headers=auth)
        items = client.get("/api/watchlist", headers=auth).json()["items"]
        item_id = items[0]["id"]
        resp = client.put(f"/api/watchlist/{item_id}", json={
            "alert_iv_rank_above": 70.0, "notes": "watch for high IV"
        }, headers=auth)
        assert resp.status_code == 200

    def test_update_nonexistent_returns_404(self, auth):
        resp = client.put("/api/watchlist/9999", json={"notes": "x"}, headers=auth)
        assert resp.status_code == 404

    def test_delete_item(self, auth):
        client.post("/api/watchlist", json={"symbol": "IWM"}, headers=auth)
        items = client.get("/api/watchlist", headers=auth).json()["items"]
        item_id = items[0]["id"]
        resp = client.delete(f"/api/watchlist/{item_id}", headers=auth)
        assert resp.status_code == 200
        assert client.get("/api/watchlist", headers=auth).json()["count"] == 0

    def test_delete_nonexistent_returns_404(self, auth):
        resp = client.delete("/api/watchlist/9999", headers=auth)
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 401

    def test_add_with_alert_thresholds(self, auth):
        resp = client.post("/api/watchlist", json={
            "symbol": "AAPL", "alert_iv_rank_above": 80, "alert_iv_rank_below": 20,
            "notes": "earnings play",
        }, headers=auth)
        assert resp.status_code == 201
        items = client.get("/api/watchlist", headers=auth).json()["items"]
        aapl = [i for i in items if i["symbol"] == "AAPL"][0]
        assert aapl["alert_iv_rank_above"] == 80
        assert aapl["notes"] == "earnings play"
