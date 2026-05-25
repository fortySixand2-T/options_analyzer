"""Tests for performance analytics — src/ui/performance_router.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from fastapi.testclient import TestClient
from ui.app import app
from conftest import get_auth_headers

client = TestClient(app)

BASE_POS = {
    "symbol": "SPY", "strategy": "iron_condor", "entry_date": "2026-01-15",
    "entry_price": 3.00, "is_credit": True, "contracts": 1,
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


def _create_and_close(auth, strategy="iron_condor", exit_price=1.50,
                       regime="HIGH_IV", entry_date="2026-01-15"):
    body = {**BASE_POS, "strategy": strategy, "regime_at_entry": regime,
            "entry_date": entry_date}
    r = client.post("/api/positions", json=body, headers=auth)
    pid = r.json()["id"]
    client.post(f"/api/positions/{pid}/close",
                 json={"exit_price": exit_price}, headers=auth)


class TestPerformanceSummary:
    def test_empty_summary(self, auth):
        resp = client.get("/api/performance/summary", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["total_trades"] == 0

    def test_summary_with_trades(self, auth):
        _create_and_close(auth, exit_price=1.50)  # win: (3-1.5)*100=150
        _create_and_close(auth, exit_price=5.00)  # loss: (3-5)*100=-200
        resp = client.get("/api/performance/summary", headers=auth).json()
        assert resp["total_trades"] == 2
        assert resp["wins"] == 1
        assert resp["losses"] == 1
        assert resp["total_pnl"] == -50.0
        assert resp["profit_factor"] > 0

    def test_all_wins_profit_factor_is_999(self, auth):
        _create_and_close(auth, exit_price=1.00)
        resp = client.get("/api/performance/summary", headers=auth).json()
        assert resp["profit_factor"] == 999

    def test_requires_auth(self):
        assert client.get("/api/performance/summary").status_code == 401


class TestPerformanceByStrategy:
    def test_empty(self, auth):
        resp = client.get("/api/performance/by-strategy", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["strategies"] == []

    def test_grouped_by_strategy(self, auth):
        _create_and_close(auth, strategy="iron_condor", exit_price=1.50)
        _create_and_close(auth, strategy="credit_spread", exit_price=1.00)
        resp = client.get("/api/performance/by-strategy", headers=auth).json()
        names = [s["strategy"] for s in resp["strategies"]]
        assert "iron_condor" in names
        assert "credit_spread" in names


class TestPerformanceByRegime:
    def test_grouped_by_regime(self, auth):
        _create_and_close(auth, regime="HIGH_IV", exit_price=1.50)
        _create_and_close(auth, regime="LOW_IV", exit_price=1.00)
        resp = client.get("/api/performance/by-regime", headers=auth).json()
        regimes = [r["regime"] for r in resp["regimes"]]
        assert "HIGH_IV" in regimes
        assert "LOW_IV" in regimes


class TestEquityCurve:
    def test_empty_curve(self, auth):
        resp = client.get("/api/performance/equity-curve", headers=auth)
        assert resp.json()["curve"] == []

    def test_cumulative_pnl(self, auth):
        _create_and_close(auth, exit_price=1.50)  # +150
        _create_and_close(auth, exit_price=5.00)  # -200
        curve = client.get("/api/performance/equity-curve", headers=auth).json()["curve"]
        assert len(curve) == 2
        assert curve[-1]["cumulative"] == -50.0


class TestDrawdown:
    def test_empty_drawdown(self, auth):
        resp = client.get("/api/performance/drawdown", headers=auth)
        assert resp.json()["series"] == []
        assert resp.json()["max_drawdown"] == 0

    def test_drawdown_calculation(self, auth):
        _create_and_close(auth, exit_price=1.00)  # +200
        _create_and_close(auth, exit_price=5.00)  # -200
        dd = client.get("/api/performance/drawdown", headers=auth).json()
        assert dd["max_drawdown"] < 0


class TestByMonth:
    def test_empty_months(self, auth):
        resp = client.get("/api/performance/by-month", headers=auth)
        assert resp.json()["months"] == []

    def test_month_grouping(self, auth):
        _create_and_close(auth, exit_price=1.50, entry_date="2026-01-15")
        _create_and_close(auth, exit_price=1.50, entry_date="2026-02-15")
        months = client.get("/api/performance/by-month", headers=auth).json()["months"]
        assert len(months) >= 1
