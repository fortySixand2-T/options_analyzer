"""Tests for alerts CRUD — src/ui/alerts_router.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from fastapi.testclient import TestClient
from ui.app import app
from conftest import get_auth_headers

client = TestClient(app)

ALERT_BODY = {
    "name": "SPY IV High",
    "trigger_type": "iv_rank_above",
    "trigger_config": {"symbol": "SPY", "threshold": 70},
    "channels": ["in_app"],
    "cooldown_minutes": 60,
}


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


class TestAlertsCRUD:
    def test_empty_alerts(self, auth):
        resp = client.get("/api/alerts", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["alerts"] == []

    def test_create_alert(self, auth):
        resp = client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_invalid_trigger_type(self, auth):
        body = {**ALERT_BODY, "trigger_type": "invalid_type"}
        resp = client.post("/api/alerts", json=body, headers=auth)
        assert resp.status_code == 400

    def test_create_empty_name_rejected(self, auth):
        body = {**ALERT_BODY, "name": "   "}
        resp = client.post("/api/alerts", json=body, headers=auth)
        assert resp.status_code == 400

    def test_list_returns_created(self, auth):
        client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        resp = client.get("/api/alerts", headers=auth).json()
        assert resp["count"] == 1
        alert = resp["alerts"][0]
        assert alert["name"] == "SPY IV High"
        assert alert["trigger_config"]["symbol"] == "SPY"

    def test_update_alert(self, auth):
        r = client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        aid = r.json()["id"]
        resp = client.put(f"/api/alerts/{aid}", json={
            "name": "Renamed", "is_active": False,
        }, headers=auth)
        assert resp.status_code == 200
        updated = client.get("/api/alerts", headers=auth).json()["alerts"][0]
        assert updated["name"] == "Renamed"
        assert updated["is_active"] == 0

    def test_update_nonexistent_returns_404(self, auth):
        resp = client.put("/api/alerts/9999", json={"name": "x"}, headers=auth)
        assert resp.status_code == 404

    def test_delete_alert(self, auth):
        r = client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        aid = r.json()["id"]
        resp = client.delete(f"/api/alerts/{aid}", headers=auth)
        assert resp.status_code == 200
        assert client.get("/api/alerts", headers=auth).json()["count"] == 0

    def test_delete_nonexistent_returns_404(self, auth):
        resp = client.delete("/api/alerts/9999", headers=auth)
        assert resp.status_code == 404

    def test_test_alert_sends_notification(self, auth):
        r = client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        aid = r.json()["id"]
        resp = client.post(f"/api/alerts/{aid}/test", headers=auth)
        assert resp.status_code == 200
        assert "test" in resp.json()["message"].lower()

    def test_test_nonexistent_returns_404(self, auth):
        resp = client.post("/api/alerts/9999/test", headers=auth)
        assert resp.status_code == 404

    def test_alert_history_empty(self, auth):
        resp = client.get("/api/alerts/history", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["history"] == []

    def test_alert_history_after_test(self, auth):
        r = client.post("/api/alerts", json=ALERT_BODY, headers=auth)
        aid = r.json()["id"]
        client.post(f"/api/alerts/{aid}/test", headers=auth)
        resp = client.get("/api/alerts/history", headers=auth).json()
        assert resp["count"] == 1
        assert "Test" in resp["history"][0]["title"]

    def test_requires_auth(self):
        assert client.get("/api/alerts").status_code == 401
        assert client.post("/api/alerts", json=ALERT_BODY).status_code == 401

    def test_all_valid_trigger_types(self, auth):
        for tt in ["iv_rank_above", "iv_rank_below", "regime_change",
                   "scan_match", "price_above", "price_below"]:
            body = {**ALERT_BODY, "name": f"test-{tt}", "trigger_type": tt}
            resp = client.post("/api/alerts", json=body, headers=auth)
            assert resp.status_code == 201
