"""
Tests for the FastAPI backend (Phase 5).

Tests the API endpoints using FastAPI's test client.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from fastapi.testclient import TestClient
from ui.app import app

client = TestClient(app)


class TestGreeksEndpoint:
    """Greeks calculator is fully local — no external deps."""

    def test_call_greeks(self):
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25, "option_type": "call",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "price" in data
        assert data["price"] > 0
        assert "greeks" in data
        assert "Delta" in data["greeks"] or "delta" in data["greeks"]

    def test_put_greeks(self):
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25, "option_type": "put",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["price"] > 0
        delta_key = "Delta" if "Delta" in data["greeks"] else "delta"
        assert data["greeks"][delta_key] < 0

    def test_deep_itm_call(self):
        resp = client.post("/api/greeks", json={
            "spot": 150, "strike": 100, "dte": 30, "iv": 0.20, "option_type": "call",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["price"] > 49  # at least intrinsic

    def test_low_dte(self):
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 1, "iv": 0.30, "option_type": "call",
        })
        assert resp.status_code == 200

    def test_missing_fields(self):
        resp = client.post("/api/greeks", json={"spot": 100})
        assert resp.status_code == 422  # validation error


class TestJournalEndpoint:
    """Journal uses SQLite — fully local."""

    def test_empty_journal(self):
        resp = client.get("/api/journal")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_add_and_list(self):
        resp = client.post("/api/journal", json={
            "strategy": "iron_condor",
            "symbol": "SPY",
            "entry_date": "2026-04-20",
            "entry_price": 2.50,
            "notes": "test trade",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = client.get("/api/journal")
        entries = resp.json()["entries"]
        assert any(e["symbol"] == "SPY" and e["notes"] == "test trade" for e in entries)


class TestHealthEndpoints:
    """Basic connectivity tests (these don't require market data)."""

    def test_greeks_endpoint_exists(self):
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25,
        })
        assert resp.status_code == 200

    def test_journal_endpoint_exists(self):
        resp = client.get("/api/journal")
        assert resp.status_code == 200


class TestPathTraversal:
    """Verify static file serving rejects path traversal attempts.

    In test env, frontend/dist may not exist so SPA route isn't registered.
    Either way, traversal must not return sensitive file contents.
    """

    def test_traversal_no_sensitive_content(self):
        resp = client.get("/../../etc/passwd")
        assert "root:" not in resp.text

    def test_dot_dot_slash_no_leak(self):
        resp = client.get("/../../../etc/shadow")
        assert "root:" not in resp.text

    def test_encoded_traversal_no_leak(self):
        resp = client.get("/%2e%2e/%2e%2e/etc/passwd")
        assert "root:" not in resp.text


class TestApiKeyAuth:
    """Verify API key enforcement on mutating endpoints."""

    def test_order_no_key_when_key_set(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "test-secret-key-123")
        resp = client.post("/api/order", json={
            "underlying": "SPY", "strategy": "iron_condor", "legs": [],
        })
        assert resp.status_code == 401

    def test_order_wrong_key(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "test-secret-key-123")
        resp = client.post(
            "/api/order",
            json={"underlying": "SPY", "strategy": "iron_condor", "legs": []},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_order_correct_key(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "test-secret-key-123")
        resp = client.post(
            "/api/order",
            json={"underlying": "SPY", "strategy": "iron_condor", "legs": []},
            headers={"X-API-Key": "test-secret-key-123"},
        )
        # Should pass auth (may fail on Tastytrade connect, but not 401)
        assert resp.status_code != 401

    def test_journal_no_key_when_key_set(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "test-secret-key-123")
        resp = client.post("/api/journal", json={
            "strategy": "test", "symbol": "SPY",
            "entry_date": "2026-01-01", "entry_price": 1.0,
        })
        assert resp.status_code == 401

    def test_read_endpoints_no_auth(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "test-secret-key-123")
        resp = client.get("/api/journal")
        assert resp.status_code == 200
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25,
        })
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self, monkeypatch):
        monkeypatch.setattr("ui.app._API_KEY", "")
        resp = client.post("/api/journal", json={
            "strategy": "test", "symbol": "SPY",
            "entry_date": "2026-01-01", "entry_price": 1.0,
        })
        assert resp.status_code == 200


class TestInputValidation:
    """Verify query param bounds are enforced."""

    def test_top_too_large(self):
        resp = client.get("/api/scan?top=999")
        assert resp.status_code == 422

    def test_max_dte_negative(self):
        resp = client.get("/api/scan?max_dte=-1")
        assert resp.status_code == 422

    def test_limit_too_large(self):
        resp = client.get("/api/journal?limit=9999")
        assert resp.status_code == 422

    def test_limit_zero(self):
        resp = client.get("/api/journal?limit=0")
        assert resp.status_code == 422

    def test_valid_bounds_accepted(self):
        resp = client.get("/api/journal?limit=10")
        assert resp.status_code == 200


class TestSecurityHeaders:
    """Verify security headers are present on responses."""

    def test_headers_on_api(self):
        resp = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25,
        })
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "Referrer-Policy" in resp.headers

    def test_headers_on_journal(self):
        resp = client.get("/api/journal")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


class TestErrorSanitization:
    """Verify 500 errors don't leak implementation details."""

    def test_greeks_invalid_doesnt_leak(self):
        resp = client.post("/api/greeks", json={
            "spot": -1, "strike": -1, "dte": 0, "iv": -1, "option_type": "call",
        })
        if resp.status_code == 500:
            detail = resp.json().get("detail", "")
            assert "Traceback" not in detail
            assert "/app/" not in detail
            assert "File " not in detail
