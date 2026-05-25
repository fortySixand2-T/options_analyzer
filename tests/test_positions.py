"""Tests for positions CRUD + P&L math — src/ui/positions_router.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import pytest
from fastapi.testclient import TestClient
from ui.app import app
from conftest import get_auth_headers

client = TestClient(app)

POSITION_BODY = {
    "symbol": "SPY",
    "strategy": "iron_condor",
    "entry_date": "2026-05-20",
    "entry_price": 3.50,
    "is_credit": True,
    "contracts": 2,
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


class TestPositionCRUD:
    def test_empty_positions(self, auth):
        resp = client.get("/api/positions", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["positions"] == []
        assert resp.json()["total"] == 0

    def test_create_position(self, auth):
        resp = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_normalizes_symbol(self, auth):
        body = {**POSITION_BODY, "symbol": "spy"}
        resp = client.post("/api/positions", json=body, headers=auth)
        assert resp.status_code == 201
        positions = client.get("/api/positions", headers=auth).json()["positions"]
        assert positions[0]["symbol"] == "SPY"

    def test_create_empty_symbol_rejected(self, auth):
        body = {**POSITION_BODY, "symbol": "  "}
        resp = client.post("/api/positions", json=body, headers=auth)
        assert resp.status_code == 400

    def test_list_open_by_default(self, auth):
        client.post("/api/positions", json=POSITION_BODY, headers=auth)
        resp = client.get("/api/positions", headers=auth)
        assert resp.json()["total"] == 1
        assert resp.json()["positions"][0]["status"] == "open"

    def test_list_closed_filter(self, auth):
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        client.post(f"/api/positions/{pid}/close",
                     json={"exit_price": 1.50}, headers=auth)
        resp = client.get("/api/positions?status=closed", headers=auth)
        assert resp.json()["total"] == 1

    def test_list_all_filter(self, auth):
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        client.post("/api/positions", json=POSITION_BODY, headers=auth)
        client.post(f"/api/positions/{pid}/close",
                     json={"exit_price": 1.50}, headers=auth)
        resp = client.get("/api/positions?status=all", headers=auth)
        assert resp.json()["total"] == 2

    def test_update_position(self, auth):
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        resp = client.put(f"/api/positions/{pid}", json={
            "notes": "adjusted stop", "stop_loss": 7.0,
        }, headers=auth)
        assert resp.status_code == 200

    def test_update_nonexistent_returns_404(self, auth):
        resp = client.put("/api/positions/9999", json={"notes": "x"}, headers=auth)
        assert resp.status_code == 404

    def test_update_closed_position_rejected(self, auth):
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        client.post(f"/api/positions/{pid}/close",
                     json={"exit_price": 1.50}, headers=auth)
        resp = client.put(f"/api/positions/{pid}", json={"notes": "oops"}, headers=auth)
        assert resp.status_code == 400

    def test_close_nonexistent_returns_404(self, auth):
        resp = client.post("/api/positions/9999/close",
                            json={"exit_price": 1.0}, headers=auth)
        assert resp.status_code == 404

    def test_close_already_closed_rejected(self, auth):
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        client.post(f"/api/positions/{pid}/close",
                     json={"exit_price": 1.50}, headers=auth)
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 1.50}, headers=auth)
        assert resp.status_code == 400

    def test_requires_auth(self):
        assert client.get("/api/positions").status_code == 401
        assert client.post("/api/positions", json=POSITION_BODY).status_code == 401


class TestPositionPnL:
    def test_credit_pnl_profit(self, auth):
        """Credit trade: entry 3.50, exit 1.50, 2 contracts → (3.50-1.50)*2*100 = 400"""
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 1.50}, headers=auth)
        assert resp.json()["pnl"] == 400.0

    def test_credit_pnl_loss(self, auth):
        """Credit trade: entry 3.50, exit 5.00, 2 contracts → (3.50-5.00)*2*100 = -300"""
        r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
        pid = r.json()["id"]
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 5.00}, headers=auth)
        assert resp.json()["pnl"] == -300.0

    def test_debit_pnl_profit(self, auth):
        """Debit trade: entry 2.00, exit 4.00, 1 contract → (4.00-2.00)*1*100 = 200"""
        body = {**POSITION_BODY, "entry_price": 2.00, "is_credit": False, "contracts": 1}
        r = client.post("/api/positions", json=body, headers=auth)
        pid = r.json()["id"]
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 4.00}, headers=auth)
        assert resp.json()["pnl"] == 200.0

    def test_debit_pnl_loss(self, auth):
        """Debit trade: entry 2.00, exit 0.50, 1 contract → (0.50-2.00)*1*100 = -150"""
        body = {**POSITION_BODY, "entry_price": 2.00, "is_credit": False, "contracts": 1}
        r = client.post("/api/positions", json=body, headers=auth)
        pid = r.json()["id"]
        resp = client.post(f"/api/positions/{pid}/close",
                            json={"exit_price": 0.50}, headers=auth)
        assert resp.json()["pnl"] == -150.0


class TestPositionSummary:
    def test_empty_summary(self, auth):
        resp = client.get("/api/positions/summary", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["open"] == 0
        assert resp.json()["win_rate"] == 0

    def test_summary_after_trades(self, auth):
        for exit_p in [1.50, 1.00, 5.00]:
            r = client.post("/api/positions", json=POSITION_BODY, headers=auth)
            client.post(f"/api/positions/{r.json()['id']}/close",
                         json={"exit_price": exit_p}, headers=auth)
        resp = client.get("/api/positions/summary", headers=auth)
        data = resp.json()
        assert data["closed"] == 3
        assert data["wins"] == 2
        assert data["win_rate"] > 0


class TestPositionGreeks:
    def test_empty_greeks(self, auth):
        resp = client.get("/api/positions/greeks", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["open_count"] == 0
        g = resp.json()["greeks"]
        assert g["delta"] == 0

    def test_greeks_with_legs(self, auth):
        legs = [
            {"delta": 0.3, "gamma": 0.02, "theta": -0.05, "vega": 0.1},
            {"delta": -0.2, "gamma": 0.01, "theta": -0.03, "vega": 0.05},
        ]
        body = {**POSITION_BODY, "legs_json": json.dumps(legs), "contracts": 1}
        client.post("/api/positions", json=body, headers=auth)
        resp = client.get("/api/positions/greeks", headers=auth)
        g = resp.json()["greeks"]
        assert abs(g["delta"] - (0.3 - 0.2) * 100) < 0.01
        assert resp.json()["open_count"] == 1
