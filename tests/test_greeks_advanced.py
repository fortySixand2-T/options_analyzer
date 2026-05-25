"""Tests for advanced Greeks endpoints — Monte Carlo forward + payoff diagrams."""

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


class TestMonteCarloForward:
    def test_basic_request(self, auth):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 450, "iv": 0.20, "days_forward": 30, "num_paths": 500,
        }, headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "fan" in data
        assert "terminal" in data
        assert len(data["fan"]) > 0

    def test_fan_has_percentiles(self, auth):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 100, "iv": 0.30, "days_forward": 14, "num_paths": 200,
            "percentiles": [10, 50, 90],
        }, headers=auth)
        fan = resp.json()["fan"]
        assert "p10" in fan[0]
        assert "p50" in fan[0]
        assert "p90" in fan[0]

    def test_fan_starts_at_spot(self, auth):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 500, "iv": 0.25, "days_forward": 7, "num_paths": 100,
        }, headers=auth)
        first = resp.json()["fan"][0]
        assert first["day"] == 0
        assert abs(first["p50"] - 500) < 5

    def test_terminal_stats_reasonable(self, auth):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 100, "iv": 0.20, "days_forward": 30, "num_paths": 1000,
        }, headers=auth)
        t = resp.json()["terminal"]
        assert 80 < t["mean"] < 120
        assert t["std"] > 0
        assert t["min"] < t["max"]

    def test_inputs_echoed(self, auth):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 200, "iv": 0.15, "days_forward": 60, "num_paths": 300,
        }, headers=auth)
        inputs = resp.json()["inputs"]
        assert inputs["spot"] == 200
        assert inputs["iv"] == 0.15

    def test_requires_auth(self):
        resp = client.post("/api/greeks/monte-carlo-forward", json={
            "spot": 100, "iv": 0.20, "days_forward": 30,
        })
        assert resp.status_code == 401


class TestPayoffDiagram:
    def test_long_call(self, auth):
        resp = client.post("/api/greeks/payoff-diagram", json={
            "spot": 100,
            "legs": [{"strike": 100, "option_type": "call", "position": "long", "premium": 3.0}],
        }, headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) == 100
        assert data["max_loss"] < 0
        assert data["max_profit"] > 0
        assert len(data["breakevens"]) == 1

    def test_iron_condor_payoff(self, auth):
        resp = client.post("/api/greeks/payoff-diagram", json={
            "spot": 450,
            "legs": [
                {"strike": 440, "option_type": "put", "position": "short", "premium": 2.0},
                {"strike": 435, "option_type": "put", "position": "long", "premium": 1.0},
                {"strike": 460, "option_type": "call", "position": "short", "premium": 2.0},
                {"strike": 465, "option_type": "call", "position": "long", "premium": 1.0},
            ],
        }, headers=auth)
        data = resp.json()
        assert data["max_profit"] > 0
        assert data["max_loss"] < 0
        assert len(data["breakevens"]) == 2

    def test_credit_spread_payoff(self, auth):
        resp = client.post("/api/greeks/payoff-diagram", json={
            "spot": 100,
            "legs": [
                {"strike": 95, "option_type": "put", "position": "short", "premium": 2.5},
                {"strike": 90, "option_type": "put", "position": "long", "premium": 1.0},
            ],
        }, headers=auth)
        data = resp.json()
        assert data["max_profit"] > 0
        assert len(data["breakevens"]) == 1

    def test_spot_echoed(self, auth):
        resp = client.post("/api/greeks/payoff-diagram", json={
            "spot": 250,
            "legs": [{"strike": 250, "option_type": "put", "position": "long", "premium": 5.0}],
        }, headers=auth)
        assert resp.json()["spot"] == 250

    def test_requires_auth(self):
        resp = client.post("/api/greeks/payoff-diagram", json={
            "spot": 100, "legs": [],
        })
        assert resp.status_code == 401
