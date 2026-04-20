"""
Tests for streaming + execution modules (Phase 6).

All tests use synthetic data — no network dependency.
"""

import sys
import os
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from streaming.dxfeed_streamer import DXFeedStreamer, StreamerState, QuoteUpdate
from streaming.score_engine import (
    LiveScoreEngine, LiveScore,
    _parse_streamer_symbol, _compute_dte,
)
from execution.order_manager import (
    OrderManager, OrderRequest, OrderResult, OrderStatus, OrderLeg,
    build_order_from_strategy, _build_occ_symbol,
)


# ── Streamer Symbol Parsing ────────────────────────────────────────────────

class TestSymbolParsing:
    def test_parse_call(self):
        result = _parse_streamer_symbol(".SPY260417C590")
        assert result is not None
        underlying, expiry, opt_type, strike = result
        assert underlying == "SPY"
        assert expiry == "2026-04-17"
        assert opt_type == "call"
        assert strike == 590.0

    def test_parse_put(self):
        result = _parse_streamer_symbol(".QQQ260501P450")
        assert result is not None
        underlying, expiry, opt_type, strike = result
        assert underlying == "QQQ"
        assert opt_type == "put"
        assert strike == 450.0

    def test_parse_nvda(self):
        result = _parse_streamer_symbol(".NVDA260320C120")
        assert result is not None
        assert result[0] == "NVDA"
        assert result[2] == "call"
        assert result[3] == 120.0

    def test_invalid_symbol(self):
        assert _parse_streamer_symbol("") is None
        assert _parse_streamer_symbol("SPY") is None
        assert _parse_streamer_symbol("noperiod260417C590") is None

    def test_no_leading_dot(self):
        assert _parse_streamer_symbol("SPY260417C590") is None


class TestComputeDte:
    def test_future_date(self):
        future = (date.today() + timedelta(days=10)).isoformat()
        assert _compute_dte(future) == 10

    def test_today(self):
        assert _compute_dte(date.today().isoformat()) == 0

    def test_past_date(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        assert _compute_dte(past) == -5

    def test_invalid_date(self):
        assert _compute_dte("not-a-date") == 0


# ── Live Score Engine ────────────────────────────────────────────────────────

class TestLiveScoreEngine:
    def _make_update(self, symbol=".SPY260501C590", bid=2.0, ask=2.5,
                     iv=0.20, volume=500, underlying=590.0):
        return QuoteUpdate(
            symbol=symbol, bid=bid, ask=ask, mid=(bid + ask) / 2,
            last=2.2, volume=volume, iv=iv,
            delta=0.45, gamma=0.03, theta=-0.05, vega=0.12,
            underlying=underlying, timestamp=1000.0,
        )

    def test_score_valid_update(self):
        engine = LiveScoreEngine()
        update = self._make_update()
        score = engine.on_quote_update(update)
        assert score is not None
        assert isinstance(score, LiveScore)
        assert score.conviction > 0
        assert score.symbol == ".SPY260501C590"

    def test_score_zero_mid_skipped(self):
        engine = LiveScoreEngine()
        update = self._make_update(bid=0, ask=0)
        score = engine.on_quote_update(update)
        assert score is None

    def test_score_zero_iv_skipped(self):
        engine = LiveScoreEngine()
        update = self._make_update(iv=0)
        score = engine.on_quote_update(update)
        assert score is None

    def test_get_top(self):
        engine = LiveScoreEngine()
        # Add multiple scores
        for i in range(5):
            update = self._make_update(
                symbol=f".SPY260501C{590 + i}",
                iv=0.20 + i * 0.05,
                volume=100 + i * 200,
            )
            engine.on_quote_update(update)
        top = engine.get_top(3)
        assert len(top) == 3
        assert top[0].conviction >= top[1].conviction

    def test_callback_invoked(self):
        engine = LiveScoreEngine()
        results = []
        engine.on_callback(lambda s: results.append(s))
        engine.on_quote_update(self._make_update())
        assert len(results) == 1

    def test_update_count(self):
        engine = LiveScoreEngine()
        engine.on_quote_update(self._make_update())
        engine.on_quote_update(self._make_update(symbol=".QQQ260501P450"))
        assert engine.update_count == 2


# ── Streamer State ───────────────────────────────────────────────────────────

class TestDXFeedStreamer:
    def test_initial_state(self):
        streamer = DXFeedStreamer()
        assert streamer.state == StreamerState.DISCONNECTED

    def test_get_latest_empty(self):
        streamer = DXFeedStreamer()
        assert streamer.get_latest() == {}
        assert streamer.get_latest("SPY") == {}


# ── Order Manager ────────────────────────────────────────────────────────────

class TestOrderManager:
    def test_validate_empty_legs(self):
        mgr = OrderManager()
        req = OrderRequest(underlying="SPY", strategy="test", legs=[])
        errors = mgr.validate(req)
        assert any("no legs" in e for e in errors)

    def test_validate_over_max_contracts(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="buy_to_open", symbol="TEST", quantity=15,
            option_type="call", strike=100, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="test", legs=legs)
        errors = mgr.validate(req)
        assert any("exceeds max" in e for e in errors)

    def test_validate_limit_no_price(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="buy_to_open", symbol="TEST", quantity=1,
            option_type="call", strike=100, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="test", legs=legs,
                           order_type="limit", price=None)
        errors = mgr.validate(req)
        assert any("price" in e.lower() for e in errors)

    def test_validate_valid_order(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="sell_to_open", symbol="TEST", quantity=1,
            option_type="put", strike=95, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="short_put", legs=legs,
                           order_type="limit", price=1.50)
        errors = mgr.validate(req)
        # May have risk rule warnings but no validation errors about structure
        structural = [e for e in errors if "no legs" in e or "exceeds" in e or "Limit order" in e]
        assert len(structural) == 0

    def test_dry_run(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="buy_to_open", symbol="TEST", quantity=1,
            option_type="call", strike=100, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="test", legs=legs,
                           order_type="limit", price=2.00, dry_run=True)
        result = mgr.submit(req)
        assert result.status == OrderStatus.PENDING
        assert "Dry run" in result.message

    def test_submit_without_connection(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="buy_to_open", symbol="TEST", quantity=1,
            option_type="call", strike=100, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="test", legs=legs,
                           order_type="limit", price=2.00)
        result = mgr.submit(req)
        assert result.status == OrderStatus.ERROR
        assert "Not connected" in result.message

    def test_is_paper_default(self):
        mgr = OrderManager()
        assert mgr.is_paper is True

    def test_order_history(self):
        mgr = OrderManager()
        legs = [OrderLeg(
            action="buy_to_open", symbol="TEST", quantity=1,
            option_type="call", strike=100, expiry="2026-05-01",
        )]
        req = OrderRequest(underlying="SPY", strategy="test", legs=legs,
                           order_type="limit", price=2.00, dry_run=True)
        mgr.submit(req)
        assert len(mgr.order_history) == 1


class TestBuildOCCSymbol:
    def test_call_symbol(self):
        symbol = _build_occ_symbol("SPY", 590.0, "call", 14)
        assert "SPY" in symbol
        assert "C" in symbol

    def test_put_symbol(self):
        symbol = _build_occ_symbol("QQQ", 450.0, "put", 7)
        assert "QQQ" in symbol
        assert "P" in symbol


# ── API Endpoint Tests ───────────────────────────────────────────────────────

class TestStreamingAPI:
    def test_streamer_status(self):
        from fastapi.testclient import TestClient
        from ui.app import app
        client = TestClient(app)
        resp = client.get("/api/streamer/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "streaming_available" in data
        assert data["websocket_url"] == "/ws/greeks"

    def test_positions_no_connection(self):
        from fastapi.testclient import TestClient
        from ui.app import app
        client = TestClient(app)
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
