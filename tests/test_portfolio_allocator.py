"""Tests for portfolio allocator and cross-book risk management (Phase 4)."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ── Portfolio Allocator ─────────────────────────────────────────────────────

class TestComputeAllocation:

    def test_base_allocation(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="MODERATE_IV")
        assert alloc.short_dte_pct == 0.60
        assert alloc.swing_pct == 0.40

    def test_high_iv_shifts_to_swing(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="HIGH_IV")
        assert alloc.short_dte_pct < 0.60
        assert alloc.swing_pct > 0.40

    def test_low_iv_shifts_to_short_dte(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="LOW_IV")
        assert alloc.short_dte_pct > 0.60
        assert alloc.swing_pct < 0.40

    def test_spike_caps_swing(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="SPIKE")
        assert alloc.swing_pct <= 0.20
        assert alloc.short_dte_pct >= 0.80

    def test_vrp_rich_shifts_to_swing(self):
        from portfolio_allocator import compute_allocation
        base = compute_allocation(regime="HIGH_IV", vrp_rich=False)
        rich = compute_allocation(regime="HIGH_IV", vrp_rich=True, vrp_pct=5.0)
        assert rich.swing_pct > base.swing_pct

    def test_vrp_rich_ignored_in_spike(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="SPIKE", vrp_rich=True, vrp_pct=10.0)
        assert alloc.swing_pct <= 0.20

    def test_strong_directional_shifts_short_dte(self):
        from portfolio_allocator import compute_allocation
        neutral = compute_allocation(regime="LOW_IV", directional=False)
        directional = compute_allocation(
            regime="LOW_IV", directional=True, swing_bias_score=8
        )
        assert directional.short_dte_pct > neutral.short_dte_pct

    def test_allocation_sums_to_one(self):
        from portfolio_allocator import compute_allocation
        for regime in ["HIGH_IV", "MODERATE_IV", "LOW_IV", "SPIKE"]:
            alloc = compute_allocation(regime=regime, vrp_rich=True, vrp_pct=5.0)
            assert abs(alloc.short_dte_pct + alloc.swing_pct - 1.0) < 0.01

    def test_allocation_clamped(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="SPIKE", vrp_rich=False, directional=True,
                                   swing_bias_score=10)
        assert alloc.short_dte_pct <= 0.90
        assert alloc.swing_pct >= 0.10

    def test_for_portfolio_dollars(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="MODERATE_IV")
        result = alloc.for_portfolio(100_000, max_risk_pct=0.10)
        assert result["short_dte"]["dollars"] == 6_000.0
        assert result["swing"]["dollars"] == 4_000.0
        assert result["total_risk_budget"] == 10_000.0

    def test_to_dict(self):
        from portfolio_allocator import compute_allocation
        alloc = compute_allocation(regime="HIGH_IV", vrp_rich=True, vrp_pct=5.0)
        d = alloc.to_dict()
        assert "short_dte_pct" in d
        assert "swing_pct" in d
        assert "rationale" in d
        assert d["vrp_rich"] is True


class TestAvailableRisk:

    def test_full_budget_available(self):
        from portfolio_allocator import compute_allocation, available_risk_for_book
        alloc = compute_allocation(regime="MODERATE_IV")
        available = available_risk_for_book(
            "swing", alloc, portfolio_value=100_000, current_book_risk=0
        )
        assert available == 4_000.0

    def test_partial_budget_used(self):
        from portfolio_allocator import compute_allocation, available_risk_for_book
        alloc = compute_allocation(regime="MODERATE_IV")
        available = available_risk_for_book(
            "swing", alloc, portfolio_value=100_000, current_book_risk=2_500
        )
        assert available == 1_500.0

    def test_over_budget_returns_zero(self):
        from portfolio_allocator import compute_allocation, available_risk_for_book
        alloc = compute_allocation(regime="MODERATE_IV")
        available = available_risk_for_book(
            "swing", alloc, portfolio_value=100_000, current_book_risk=5_000
        )
        assert available == 0.0


# ── Portfolio: Book Tracking ────────────────────────────────────────────────

class TestPositionBook:

    def test_short_dte_strategy_book(self):
        from portfolio import Position
        p = Position(
            position_id="1", symbol="SPY", strategy="iron_condor",
            contracts=1, entry_price=2.0, is_credit=True,
            max_loss=500, entry_time=datetime.now(),
        )
        assert p.book == "short_dte"

    def test_swing_strategy_book(self):
        from portfolio import Position
        p = Position(
            position_id="1", symbol="SPY", strategy="calendar_spread",
            contracts=1, entry_price=1.5, is_credit=False,
            max_loss=300, entry_time=datetime.now(),
        )
        assert p.book == "swing"

    def test_iron_butterfly_is_swing(self):
        from portfolio import Position
        p = Position(
            position_id="1", symbol="SPY", strategy="iron_butterfly",
            contracts=1, entry_price=5.0, is_credit=True,
            max_loss=500, entry_time=datetime.now(),
        )
        assert p.book == "swing"


class TestPortfolioBooks:

    def _make_position(self, **kwargs):
        from portfolio import Position
        defaults = dict(
            position_id="1", symbol="SPY", contracts=1,
            entry_price=2.0, is_credit=True, max_loss=500,
            entry_time=datetime.now(), strategy="iron_condor",
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_positions_for_book(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(position_id="1", strategy="iron_condor"),
            self._make_position(position_id="2", strategy="calendar_spread"),
            self._make_position(position_id="3", strategy="butterfly"),
        ]
        assert len(pf.positions_for_book("short_dte")) == 2
        assert len(pf.positions_for_book("swing")) == 1

    def test_book_risk(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(position_id="1", strategy="iron_condor", max_loss=500),
            self._make_position(position_id="2", strategy="calendar_spread", max_loss=300),
            self._make_position(position_id="3", strategy="butterfly", max_loss=200),
        ]
        assert pf.book_risk("short_dte") == 700
        assert pf.book_risk("swing") == 300

    def test_book_greeks(self):
        from portfolio import Portfolio
        pf = Portfolio()
        p1 = self._make_position(position_id="1", strategy="iron_condor")
        p1.delta = 5.0
        p1.vega = -20.0
        p2 = self._make_position(position_id="2", strategy="calendar_spread")
        p2.delta = -3.0
        p2.vega = 15.0
        pf.positions = [p1, p2]

        short_g = pf.book_greeks("short_dte")
        assert short_g["delta"] == 5.0
        assert short_g["vega"] == -20.0
        swing_g = pf.book_greeks("swing")
        assert swing_g["delta"] == -3.0

    def test_to_dict_has_books(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(position_id="1", strategy="iron_condor", max_loss=500),
            self._make_position(position_id="2", strategy="calendar_spread", max_loss=300),
        ]
        d = pf.to_dict()
        assert "books" in d
        assert d["books"]["short_dte"]["positions"] == 1
        assert d["books"]["swing"]["positions"] == 1
        assert d["books"]["short_dte"]["risk"] == 500
        assert d["books"]["swing"]["risk"] == 300

    def test_to_dict_has_cross_book_warnings(self):
        from portfolio import Portfolio
        pf = Portfolio()
        d = pf.to_dict()
        assert "cross_book_warnings" in d


# ── Cross-Book Warnings ────────────────────────────────────────────────────

class TestCrossBookWarnings:

    def _make_position(self, **kwargs):
        from portfolio import Position
        defaults = dict(
            position_id="1", symbol="SPY", contracts=1,
            entry_price=2.0, is_credit=True, max_loss=500,
            entry_time=datetime.now(), strategy="iron_condor",
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_no_warnings_single_book(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(position_id="1", strategy="iron_condor"),
            self._make_position(position_id="2", strategy="butterfly"),
        ]
        assert pf.cross_book_warnings() == []

    def test_correlated_short_vol_warning(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(
                position_id="1", strategy="short_put_spread",
                symbol="SPY", is_credit=True,
            ),
            self._make_position(
                position_id="2", strategy="iron_butterfly",
                symbol="SPY", is_credit=True,
            ),
        ]
        warnings = pf.cross_book_warnings()
        assert len(warnings) >= 1
        assert any("short vol" in w["warning"].lower() for w in warnings)
        assert any(w["severity"] == "high" for w in warnings)

    def test_no_warning_different_symbols(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(
                position_id="1", strategy="short_put_spread",
                symbol="SPY", is_credit=True,
            ),
            self._make_position(
                position_id="2", strategy="iron_butterfly",
                symbol="QQQ", is_credit=True,
            ),
        ]
        warnings = pf.cross_book_warnings()
        corr_warnings = [w for w in warnings if "short vol" in w["warning"].lower()]
        assert len(corr_warnings) == 0

    def test_combined_delta_warning(self):
        from portfolio import Portfolio
        pf = Portfolio()
        p1 = self._make_position(
            position_id="1", strategy="long_call_spread",
            symbol="SPY", is_credit=False,
        )
        p1.delta = 25.0
        p2 = self._make_position(
            position_id="2", strategy="diagonal_spread",
            symbol="SPY", is_credit=False,
        )
        p2.delta = 10.0
        pf.positions = [p1, p2]
        warnings = pf.cross_book_warnings()
        assert any("delta" in w["warning"].lower() for w in warnings)

    def test_combined_vega_warning(self):
        from portfolio import Portfolio
        pf = Portfolio()
        p1 = self._make_position(position_id="1", strategy="iron_condor")
        p1.vega = -120.0
        p2 = self._make_position(position_id="2", strategy="iron_butterfly")
        p2.vega = -100.0
        pf.positions = [p1, p2]
        warnings = pf.cross_book_warnings()
        assert any("vega" in w["warning"].lower() for w in warnings)


class TestCanAddToBook:

    def _make_position(self, **kwargs):
        from portfolio import Position
        defaults = dict(
            position_id="1", symbol="SPY", contracts=1,
            entry_price=2.0, is_credit=True, max_loss=500,
            entry_time=datetime.now(), strategy="iron_condor",
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_can_add_within_limit(self):
        from portfolio import Portfolio
        pf = Portfolio()
        ok, reason = pf.can_add_to_book(
            book="swing", symbol="SPY", strategy="calendar_spread",
            max_loss=500, book_risk_limit=5000,
        )
        assert ok is True

    def test_book_limit_exceeded(self):
        from portfolio import Portfolio
        pf = Portfolio()
        pf.positions = [
            self._make_position(position_id="1", strategy="calendar_spread", max_loss=4000),
        ]
        ok, reason = pf.can_add_to_book(
            book="swing", symbol="QQQ", strategy="iron_butterfly",
            max_loss=2000, book_risk_limit=5000,
        )
        assert ok is False
        assert "book risk" in reason.lower()

    def test_portfolio_limit_still_checked(self):
        from portfolio import Portfolio, PortfolioLimits
        pf = Portfolio(limits=PortfolioLimits(max_positions=1))
        pf.positions = [
            self._make_position(position_id="1", strategy="iron_condor"),
        ]
        ok, reason = pf.can_add_to_book(
            book="swing", symbol="QQQ", strategy="calendar_spread",
            max_loss=500, book_risk_limit=10000,
        )
        assert ok is False
        assert "max positions" in reason


# ── Sizing: Swing Strategies ───────────────────────────────────────────────

class TestSwingSizing:

    def test_swing_strategies_in_stats(self):
        from sizing import STRATEGY_STATS
        for name in ["calendar_spread", "diagonal_spread", "iron_butterfly", "long_straddle"]:
            assert name in STRATEGY_STATS
            assert STRATEGY_STATS[name].tradeable is True

    def test_compute_size_for_swing(self):
        from sizing import compute_position_size
        result = compute_position_size(
            strategy="calendar_spread",
            portfolio_value=100_000,
            max_loss_per_contract=300,
            confluence_score=75,
        )
        assert result.contracts >= 1
        assert result.reason == "ok"


# ── API: Allocation Endpoint ──────────────────────────────────────────────

class TestAllocationAPI:

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi.testclient import TestClient
        from ui.app import app
        self.client = TestClient(app)

    def test_allocation_route_exists(self):
        resp = self.client.get("/api/portfolio/allocation")
        assert resp.status_code == 200

    def test_allocation_returns_expected_shape(self):
        resp = self.client.get("/api/portfolio/allocation?regime=HIGH_IV&vrp_rich=true&vrp_pct=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "short_dte_pct" in data
        assert "swing_pct" in data
        assert "rationale" in data
        assert "dollars" in data

    def test_allocation_spike(self):
        resp = self.client.get("/api/portfolio/allocation?regime=SPIKE")
        data = resp.json()
        assert data["swing_pct"] <= 0.20
