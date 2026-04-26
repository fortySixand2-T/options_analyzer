"""
Tests for L4 Portfolio Engine.

Covers: position limits, Greeks limits, correlation risk, hedge triggers,
position management, serialization.

Options Analytics Team — 2026-04
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import math

from portfolio import Portfolio, PortfolioLimits, Position


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_position(
    symbol="SPY", strategy="long_call_spread", contracts=1,
    max_loss=500, delta=10.0, gamma=1.0, theta=-5.0, vega=20.0,
    **kw
) -> Position:
    defaults = dict(
        position_id=f"{symbol}_{strategy}_{id(object())}",
        symbol=symbol, strategy=strategy, contracts=contracts,
        entry_price=2.00, is_credit=False, max_loss=max_loss,
        entry_time=datetime.now(),
        delta=delta, gamma=gamma, theta=theta, vega=vega,
    )
    defaults.update(kw)
    return Position(**defaults)


def _make_portfolio(**kw) -> Portfolio:
    limits = PortfolioLimits(**kw) if kw else PortfolioLimits()
    return Portfolio(limits=limits, portfolio_value=100_000)


# ── Test position limits ──────────────────────────────────────────────────────

class TestPositionLimits:
    def test_can_add_when_empty(self):
        pf = _make_portfolio()
        ok, reason = pf.can_add("SPY", "long_call_spread", max_loss=500)
        assert ok is True

    def test_max_positions_reached(self):
        pf = _make_portfolio(max_positions=2)
        pf.add_position(_make_position(position_id="1"))
        pf.add_position(_make_position(position_id="2"))
        ok, reason = pf.can_add("QQQ", "butterfly", max_loss=500)
        assert ok is False
        assert "max positions" in reason

    def test_max_per_symbol(self):
        pf = _make_portfolio(max_per_symbol=1)
        pf.add_position(_make_position(symbol="SPY", position_id="1"))
        ok, reason = pf.can_add("SPY", "butterfly", max_loss=500)
        assert ok is False
        assert "SPY" in reason

    def test_different_symbol_ok(self):
        pf = _make_portfolio(max_per_symbol=1)
        pf.add_position(_make_position(symbol="SPY", position_id="1"))
        ok, reason = pf.can_add("QQQ", "long_call_spread", max_loss=500)
        assert ok is True


# ── Test Greeks limits ────────────────────────────────────────────────────────

class TestGreeksLimits:
    def test_delta_limit(self):
        pf = _make_portfolio(max_delta=20)
        ok, _ = pf.can_add("SPY", "x", 500, delta=25)
        assert ok is False

    def test_negative_delta_limit(self):
        pf = _make_portfolio(max_delta=20)
        ok, _ = pf.can_add("SPY", "x", 500, delta=-25)
        assert ok is False

    def test_gamma_limit(self):
        pf = _make_portfolio(max_gamma=5)
        ok, _ = pf.can_add("SPY", "x", 500, gamma=6)
        assert ok is False

    def test_theta_limit(self):
        pf = _make_portfolio(max_theta=-100)
        ok, reason = pf.can_add("SPY", "x", 500, theta=-110)
        assert ok is False
        assert "theta" in reason

    def test_vega_limit(self):
        pf = _make_portfolio(max_vega=100)
        ok, _ = pf.can_add("SPY", "x", 500, vega=110)
        assert ok is False

    def test_within_limits(self):
        pf = _make_portfolio()
        ok, _ = pf.can_add("SPY", "x", 500, delta=10, gamma=2, theta=-20, vega=30)
        assert ok is True


# ── Test risk limits ──────────────────────────────────────────────────────────

class TestRiskLimits:
    def test_max_risk_dollar(self):
        pf = _make_portfolio(max_risk=1000)
        pf.add_position(_make_position(max_loss=800, position_id="1"))
        ok, reason = pf.can_add("QQQ", "x", max_loss=500)
        assert ok is False
        assert "total risk" in reason

    def test_max_risk_pct(self):
        pf = _make_portfolio(max_risk_pct=0.05, max_risk=100_000)
        pf.portfolio_value = 100_000
        # 5% of 100k = 5000
        pf.add_position(_make_position(max_loss=4000, position_id="1"))
        ok, reason = pf.can_add("QQQ", "x", max_loss=2000)
        assert ok is False
        assert "risk" in reason.lower()


# ── Test aggregate Greeks ─────────────────────────────────────────────────────

class TestAggregateGreeks:
    def test_net_delta(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(delta=10, position_id="1"))
        pf.add_position(_make_position(delta=-5, position_id="2"))
        assert pf.net_delta == 5.0

    def test_net_theta(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(theta=-10, position_id="1"))
        pf.add_position(_make_position(theta=-15, position_id="2"))
        assert pf.net_theta == -25.0

    def test_total_risk(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(max_loss=500, position_id="1"))
        pf.add_position(_make_position(max_loss=300, position_id="2"))
        assert pf.total_risk == 800.0

    def test_empty_portfolio_zeros(self):
        pf = _make_portfolio()
        assert pf.net_delta == 0
        assert pf.net_gamma == 0
        assert pf.total_risk == 0


# ── Test correlation-aware risk ───────────────────────────────────────────────

class TestCorrelatedRisk:
    def test_single_position(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(max_loss=1000, position_id="1"))
        assert pf.correlated_risk() == pytest.approx(1000, abs=1)

    def test_correlated_higher_than_independent(self):
        """Correlated risk > independent risk (sqrt of sum of squares)."""
        pf = _make_portfolio()
        pf.add_position(_make_position(max_loss=1000, position_id="1"))
        pf.add_position(_make_position(max_loss=1000, symbol="QQQ", position_id="2"))

        corr_risk = pf.correlated_risk(correlation=0.7)
        indep_risk = math.sqrt(1000**2 + 1000**2)  # ~1414
        assert corr_risk > indep_risk

    def test_zero_correlation_is_independent(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(max_loss=1000, position_id="1"))
        pf.add_position(_make_position(max_loss=1000, symbol="QQQ", position_id="2"))

        corr_risk = pf.correlated_risk(correlation=0.0)
        indep_risk = math.sqrt(1000**2 + 1000**2)
        assert corr_risk == pytest.approx(indep_risk, abs=1)

    def test_perfect_correlation(self):
        """Perfect correlation → risk = sum of individual risks."""
        pf = _make_portfolio()
        pf.add_position(_make_position(max_loss=1000, position_id="1"))
        pf.add_position(_make_position(max_loss=1000, symbol="QQQ", position_id="2"))

        corr_risk = pf.correlated_risk(correlation=1.0)
        assert corr_risk == pytest.approx(2000, abs=1)

    def test_empty_portfolio_zero(self):
        pf = _make_portfolio()
        assert pf.correlated_risk() == 0.0


# ── Test hedge triggers ──────────────────────────────────────────────────────

class TestHedgeTriggers:
    def test_positive_delta_trigger(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(delta=35, position_id="1"))
        triggers = pf.hedge_triggers()
        assert any("delta" in t["trigger"].lower() for t in triggers)
        assert any("put spread" in t["action"].lower() for t in triggers)

    def test_negative_delta_trigger(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(delta=-35, position_id="1"))
        triggers = pf.hedge_triggers()
        assert any("delta" in t["trigger"].lower() for t in triggers)
        assert any("call spread" in t["action"].lower() for t in triggers)

    def test_high_vega_trigger(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(vega=160, position_id="1"))
        triggers = pf.hedge_triggers()
        assert any("vega" in t["trigger"].lower() for t in triggers)

    def test_no_triggers_balanced(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(delta=5, vega=20, theta=-10, position_id="1"))
        triggers = pf.hedge_triggers()
        assert len(triggers) == 0


# ── Test position management ─────────────────────────────────────────────────

class TestPositionManagement:
    def test_add_position(self):
        pf = _make_portfolio()
        p = _make_position(position_id="test1")
        ok, reason = pf.add_position(p)
        assert ok is True
        assert pf.position_count == 1

    def test_add_violating_limit_rejected(self):
        pf = _make_portfolio(max_positions=1)
        pf.add_position(_make_position(position_id="1"))
        p2 = _make_position(position_id="2")
        ok, reason = pf.add_position(p2)
        assert ok is False
        assert pf.position_count == 1

    def test_remove_position(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(position_id="rm_me"))
        removed = pf.remove_position("rm_me")
        assert removed is not None
        assert removed.position_id == "rm_me"
        assert pf.position_count == 0

    def test_remove_nonexistent(self):
        pf = _make_portfolio()
        removed = pf.remove_position("nope")
        assert removed is None

    def test_update_pnl(self):
        p = _make_position(entry_price=2.00, is_credit=False, contracts=2)
        p.update_pnl(current_price=3.00)
        # Debit: (3.00 - 2.00) * 2 * 100 = 200
        assert p.unrealized_pnl == pytest.approx(200.0)

    def test_update_pnl_credit(self):
        p = _make_position(entry_price=1.50, is_credit=True, contracts=1)
        p.update_pnl(current_price=0.75)
        # Credit: (1.50 - 0.75) * 1 * 100 = 75
        assert p.unrealized_pnl == pytest.approx(75.0)


# ── Test serialization ───────────────────────────────────────────────────────

class TestSerialization:
    def test_portfolio_to_dict(self):
        pf = _make_portfolio()
        pf.add_position(_make_position(position_id="1"))
        d = pf.to_dict()
        assert "positions" in d
        assert "greeks" in d
        assert "risk" in d
        assert "pnl" in d
        assert "limits" in d
        assert "hedge_triggers" in d

    def test_position_to_dict(self):
        p = _make_position()
        d = p.to_dict()
        assert "symbol" in d
        assert "delta" in d
        assert "max_loss" in d

    def test_empty_portfolio_dict(self):
        pf = _make_portfolio()
        d = pf.to_dict()
        assert d["position_count"] == 0
        assert d["risk"]["total_risk"] == 0
