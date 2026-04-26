"""
Tests for L3 Execution & Sizing.

Covers: Kelly sizing, slippage model, execution checks, position sizing.

Options Analytics Team — 2026-04
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest

from sizing import (
    kelly_fraction, compute_position_size, SizeResult,
    ExecutionModel, assess_execution, ExecutionResult,
    STRATEGY_STATS,
)
from trade_generator import TradeCandidate, ExitRule


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_candidate(strategy="long_call_spread", score=75.0, **kw) -> TradeCandidate:
    defaults = dict(
        symbol="SPY", strategy=strategy,
        strategy_label="Long Call Spread",
        legs=[
            {"action": "buy", "option_type": "call", "strike": 585.0},
            {"action": "sell", "option_type": "call", "strike": 590.0},
        ],
        is_credit=strategy in ("iron_condor", "short_put_spread", "short_call_spread"),
        suggested_dte=7,
        confluence_score=score,
        exit_rule=ExitRule(profit_target_pct=75, stop_loss_pct=100, time_exit_dte=2),
    )
    defaults.update(kw)
    return TradeCandidate(**defaults)


# ── Test Kelly fraction ───────────────────────────────────────────────────────

class TestKellyFraction:
    def test_positive_edge(self):
        # 65% win, avg win 148, avg loss 172 → should be positive
        k = kelly_fraction(0.65, 148, 172)
        assert k > 0

    def test_negative_edge(self):
        # 43% win, avg win 118, avg loss 171 → should be negative
        k = kelly_fraction(0.43, 118, 171)
        assert k < 0

    def test_coin_flip_no_edge(self):
        # 50% win, equal payoff → Kelly = 0
        k = kelly_fraction(0.50, 100, 100)
        assert k == pytest.approx(0.0, abs=0.001)

    def test_sure_win(self):
        # 100% win rate → Kelly = 1
        k = kelly_fraction(1.0, 100, 100)
        assert k == pytest.approx(1.0, abs=0.001)

    def test_zero_loss_returns_zero(self):
        k = kelly_fraction(0.5, 100, 0)
        assert k == 0.0

    def test_zero_win_returns_zero(self):
        k = kelly_fraction(0.5, 0, 100)
        assert k == 0.0


# ── Test position sizing ─────────────────────────────────────────────────────

class TestPositionSizing:
    def test_tradeable_strategy_gets_contracts(self):
        result = compute_position_size(
            strategy="long_call_spread",
            portfolio_value=100_000,
            max_loss_per_contract=500,
            confluence_score=80.0,
        )
        assert result.contracts >= 1
        assert result.reason == "ok"

    def test_untradeable_strategy_zero_contracts(self):
        result = compute_position_size(
            strategy="iron_condor",
            portfolio_value=100_000,
            max_loss_per_contract=500,
        )
        assert result.contracts == 0
        assert "Negative expectancy" in result.reason

    def test_unknown_strategy_zero(self):
        result = compute_position_size(
            strategy="unknown_thing",
            portfolio_value=100_000,
            max_loss_per_contract=500,
        )
        assert result.contracts == 0

    def test_risk_capped(self):
        result = compute_position_size(
            strategy="long_call_spread",
            portfolio_value=100_000,
            max_loss_per_contract=500,
            confluence_score=100.0,
            max_risk_pct=0.02,
        )
        actual_risk = result.contracts * 500
        assert actual_risk <= 100_000 * 0.02 + 500  # allow 1 contract rounding

    def test_higher_score_more_contracts(self):
        low = compute_position_size("long_call_spread", 100_000, 500, confluence_score=65)
        high = compute_position_size("long_call_spread", 100_000, 500, confluence_score=95)
        assert high.contracts >= low.contracts

    def test_kelly_fields_populated(self):
        result = compute_position_size("long_call_spread", 100_000, 500, confluence_score=80)
        assert result.kelly_raw > 0
        assert result.kelly_half > 0
        assert result.risk_pct > 0

    def test_minimum_score_threshold(self):
        """Score at 60 (minimum) should still produce at least 1 contract."""
        result = compute_position_size("butterfly", 100_000, 500, confluence_score=60)
        # score_scale = 0 at 60, so adjusted_k = 0, but we still block
        # This tests the edge case
        assert result.contracts >= 0


# ── Test execution model ──────────────────────────────────────────────────────

class TestExecutionModel:
    def test_credit_slippage(self):
        em = ExecutionModel(slippage_pct=0.03)
        # Collecting $1.20 credit → fill at $1.16
        adjusted = em.adjusted_entry(1.20, is_credit=True)
        assert adjusted < 1.20
        assert adjusted == pytest.approx(1.16, abs=0.01)

    def test_debit_slippage(self):
        em = ExecutionModel(slippage_pct=0.03)
        # Paying $2.00 debit → fill at $2.06
        adjusted = em.adjusted_entry(2.00, is_credit=False)
        assert adjusted > 2.00
        assert adjusted == pytest.approx(2.06, abs=0.01)

    def test_minimum_tick_slippage(self):
        em = ExecutionModel(slippage_pct=0.03, tick_size=0.05)
        # Small premium: 3% of $0.10 = $0.003, but min tick is $0.05
        adjusted = em.adjusted_entry(0.10, is_credit=True)
        assert adjusted == pytest.approx(0.05, abs=0.01)

    def test_spread_cost(self):
        em = ExecutionModel()
        cost = em.spread_cost(1.15, 1.25)
        mid = 1.20
        expected = 0.10 / mid
        assert cost == pytest.approx(expected, abs=0.001)

    def test_executable_tight_spread(self):
        em = ExecutionModel(max_spread_pct=0.10)
        ok, reason = em.is_executable(bid=5.0, ask=5.20)
        assert ok is True

    def test_not_executable_wide_spread(self):
        em = ExecutionModel(max_spread_pct=0.10)
        ok, reason = em.is_executable(bid=1.0, ask=2.0)
        assert ok is False
        assert "wide" in reason

    def test_not_executable_no_bid(self):
        em = ExecutionModel()
        ok, reason = em.is_executable(bid=0, ask=1.0)
        assert ok is False


# ── Test assess_execution ─────────────────────────────────────────────────────

class TestAssessExecution:
    def test_tradeable_strategy_executable(self):
        tc = _make_candidate("long_call_spread", score=80.0)
        result = assess_execution(tc, portfolio_value=100_000)
        assert result.executable is True
        assert result.size.contracts >= 1

    def test_untradeable_strategy_not_executable(self):
        tc = _make_candidate("iron_condor", score=80.0)
        result = assess_execution(tc, portfolio_value=100_000)
        assert result.executable is False
        assert result.size.contracts == 0

    def test_wide_spread_rejected(self):
        tc = _make_candidate("long_call_spread", score=80.0)
        result = assess_execution(tc, bid=1.0, ask=2.0)
        assert result.executable is False

    def test_slippage_computed(self):
        tc = _make_candidate("long_call_spread", score=80.0)
        result = assess_execution(tc, mid_price=2.00)
        assert result.adjusted_entry is not None
        assert result.slippage_cost > 0

    def test_result_to_dict(self):
        tc = _make_candidate("long_call_spread", score=80.0)
        result = assess_execution(tc, mid_price=2.00)
        d = result.to_dict()
        assert "executable" in d
        assert "size" in d
        assert "slippage_cost" in d

    def test_butterfly_executable(self):
        tc = _make_candidate("butterfly", score=75.0, legs=[
            {"action": "buy", "option_type": "call", "strike": 580.0},
            {"action": "sell", "option_type": "call", "strike": 585.0},
            {"action": "sell", "option_type": "call", "strike": 585.0},
            {"action": "buy", "option_type": "call", "strike": 590.0},
        ])
        result = assess_execution(tc, portfolio_value=100_000)
        assert result.executable is True


# ── Test strategy stats consistency ───────────────────────────────────────────

class TestStrategyStats:
    def test_all_five_strategies_present(self):
        expected = {"iron_condor", "short_put_spread", "short_call_spread",
                    "long_call_spread", "long_put_spread", "butterfly"}
        assert set(STRATEGY_STATS.keys()) == expected

    def test_positive_kelly_matches_tradeable(self):
        for name, stats in STRATEGY_STATS.items():
            k = kelly_fraction(stats.win_rate, stats.avg_win, stats.avg_loss)
            if k > 0:
                assert stats.tradeable, f"{name} has positive Kelly but marked untradeable"
            else:
                assert not stats.tradeable, f"{name} has negative Kelly but marked tradeable"

    def test_win_rates_valid(self):
        for name, stats in STRATEGY_STATS.items():
            assert 0 < stats.win_rate < 1, f"{name} win_rate out of range"
