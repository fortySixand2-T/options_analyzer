"""Tests for scanner presets + backtest configs — CRUD routers."""

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


class TestScannerPresets:
    def test_empty_presets(self, auth):
        resp = client.get("/api/scanner/presets", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["presets"] == []

    def test_create_preset(self, auth):
        resp = client.post("/api/scanner/presets", json={
            "name": "High IV Scan", "config": {"regime": "HIGH_IV", "min_score": 70},
        }, headers=auth)
        assert resp.status_code == 201

    def test_create_empty_name_rejected(self, auth):
        resp = client.post("/api/scanner/presets", json={
            "name": "  ", "config": {},
        }, headers=auth)
        assert resp.status_code == 400

    def test_list_returns_created(self, auth):
        client.post("/api/scanner/presets", json={
            "name": "P1", "config": {"x": 1}, "is_pinned": True,
        }, headers=auth)
        client.post("/api/scanner/presets", json={
            "name": "P2", "config": {"x": 2},
        }, headers=auth)
        presets = client.get("/api/scanner/presets", headers=auth).json()["presets"]
        assert len(presets) == 2
        assert presets[0]["name"] == "P1"  # pinned first

    def test_delete_preset(self, auth):
        client.post("/api/scanner/presets", json={
            "name": "ToDelete", "config": {},
        }, headers=auth)
        presets = client.get("/api/scanner/presets", headers=auth).json()["presets"]
        pid = presets[0]["id"]
        resp = client.delete(f"/api/scanner/presets/{pid}", headers=auth)
        assert resp.status_code == 200
        assert client.get("/api/scanner/presets", headers=auth).json()["count"] == 0

    def test_delete_nonexistent_404(self, auth):
        resp = client.delete("/api/scanner/presets/9999", headers=auth)
        assert resp.status_code == 404

    def test_requires_auth(self):
        assert client.get("/api/scanner/presets").status_code == 401


class TestBacktestConfigs:
    def test_empty_configs(self, auth):
        resp = client.get("/api/backtest/configs", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["configs"] == []

    def test_save_config(self, auth):
        resp = client.post("/api/backtest/configs", json={
            "name": "IC Baseline", "config": {
                "strategy": "iron_condor", "regime_filter": True,
            },
        }, headers=auth)
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_save_empty_name_rejected(self, auth):
        resp = client.post("/api/backtest/configs", json={
            "name": "", "config": {},
        }, headers=auth)
        assert resp.status_code == 400

    def test_list_returns_saved(self, auth):
        client.post("/api/backtest/configs", json={
            "name": "Config A", "config": {"a": 1},
        }, headers=auth)
        configs = client.get("/api/backtest/configs", headers=auth).json()["configs"]
        assert len(configs) == 1
        assert configs[0]["config"]["a"] == 1

    def test_delete_config(self, auth):
        r = client.post("/api/backtest/configs", json={
            "name": "Del Me", "config": {},
        }, headers=auth)
        cid = r.json()["id"]
        resp = client.delete(f"/api/backtest/configs/{cid}", headers=auth)
        assert resp.status_code == 200

    def test_delete_nonexistent_404(self, auth):
        resp = client.delete("/api/backtest/configs/9999", headers=auth)
        assert resp.status_code == 404

    def test_requires_auth(self):
        assert client.get("/api/backtest/configs").status_code == 401
