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
