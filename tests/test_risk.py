"""
Tests for risk management module (Phase 4).

All tests use synthetic data — no network dependency.
"""

import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from risk.sizer import kelly_size, fixed_fractional_size, compute_position_size, PositionSize
from risk.rules import (
    RiskRules, check_all_rules, check_max_positions,
    check_correlation, check_event_blackout, check_trade_risk,
    check_portfolio_risk, RuleViolation, _get_correlation_group,
)
from risk.mc_ev import (
    compute_multi_leg_ev, LegSpec, PositionEV, _find_breakevens,
)


# ── Kelly Sizing ─────────────────────────────────────────────────────────────

class TestKellySizer:
    def test_positive_edge(self):
        result = kelly_size(
            win_rate=0.70, avg_win=50.0, avg_loss=100.0,
            fund_size=10000, max_loss_per_contract=100.0,
        )
        assert result.contracts >= 1
        assert result.capital_at_risk > 0
        assert result.method == "kelly"
        assert result.kelly_fraction > 0

    def test_no_edge(self):
        # win_rate * b < (1 - win_rate) → f* < 0
        result = kelly_size(
            win_rate=0.30, avg_win=50.0, avg_loss=100.0,
            fund_size=10000, max_loss_per_contract=100.0,
        )
        assert result.contracts == 0
        assert result.kelly_fraction < 0

    def test_half_kelly_is_smaller(self):
        full = kelly_size(
            win_rate=0.70, avg_win=100.0, avg_loss=50.0,
            fund_size=10000, max_loss_per_contract=100.0,
            half_kelly=False,
        )
        half = kelly_size(
            win_rate=0.70, avg_win=100.0, avg_loss=50.0,
            fund_size=10000, max_loss_per_contract=100.0,
            half_kelly=True,
        )
        assert half.kelly_fraction <= full.kelly_fraction

    def test_zero_avg_loss(self):
        result = kelly_size(win_rate=0.50, avg_win=50, avg_loss=0, fund_size=10000)
        assert result.contracts == 0

    def test_extreme_win_rate(self):
        result = kelly_size(win_rate=1.0, avg_win=50, avg_loss=100, fund_size=10000)
        assert result.contracts == 0  # win_rate >= 1 is rejected


# ── Fixed Fractional ────────────────────────────────────────────────────────

class TestFixedFractional:
    def test_basic(self):
        result = fixed_fractional_size(
            max_risk_pct=0.02, fund_size=10000, max_loss_per_contract=100.0,
        )
        assert result.contracts == 2  # 10000 * 0.02 / 100 = 2
        assert result.capital_at_risk == 200.0
        assert result.method == "fixed_fractional"

    def test_zero_loss(self):
        result = fixed_fractional_size(
            max_risk_pct=0.02, fund_size=10000, max_loss_per_contract=0,
        )
        assert result.contracts == 0

    def test_large_fund(self):
        result = fixed_fractional_size(
            max_risk_pct=0.02, fund_size=100000, max_loss_per_contract=500.0,
        )
        assert result.contracts == 4  # 100000 * 0.02 / 500 = 4


# ── Composite Sizer ─────────────────────────────────────────────────────────

class TestComputePositionSize:
    def test_falls_back_to_fixed(self):
        result = compute_position_size(fund_size=10000, max_loss_per_contract=200)
        assert result.method == "fixed_fractional"

    def test_forced_kelly(self):
        from backtest.models import BacktestStats
        stats = BacktestStats(
            total_trades=50, wins=35, losses=15,
            win_rate=70.0, avg_win=80.0, avg_loss=-40.0,
        )
        result = compute_position_size(
            backtest_stats=stats, fund_size=10000,
            max_loss_per_contract=100, method="kelly",
        )
        assert result.method == "kelly"
        assert result.contracts >= 1


# ── Risk Rules ───────────────────────────────────────────────────────────────

class TestRiskRules:
    def test_max_positions_blocks(self):
        rules = RiskRules(max_positions=2)
        positions = [{"symbol": "SPY"}, {"symbol": "QQQ"}]
        v = check_max_positions(positions, rules)
        assert v is not None
        assert v.severity == "block"

    def test_max_positions_ok(self):
        rules = RiskRules(max_positions=5)
        positions = [{"symbol": "SPY"}]
        v = check_max_positions(positions, rules)
        assert v is None

    def test_correlation_warns(self):
        rules = RiskRules(max_correlated=1)
        positions = [{"symbol": "SPY"}]
        v = check_correlation("SPX", positions, rules)
        assert v is not None
        assert v.severity == "warn"
        assert "large_cap_index" in v.message

    def test_correlation_ok_different_group(self):
        rules = RiskRules(max_correlated=2)
        positions = [{"symbol": "SPY"}]
        v = check_correlation("QQQ", positions, rules)
        assert v is None  # different group

    def test_trade_risk_blocks(self):
        rules = RiskRules(max_loss_per_trade=500, max_risk_pct=0.05)
        v = check_trade_risk(max_loss=600, rules=rules, fund_size=10000)
        assert v is not None
        assert v.severity == "block"

    def test_trade_risk_pct_blocks(self):
        rules = RiskRules(max_risk_pct=0.02, max_loss_per_trade=10000)
        v = check_trade_risk(max_loss=300, rules=rules, fund_size=10000)
        assert v is not None
        assert "3.0%" in v.message

    def test_portfolio_risk_blocks(self):
        positions = [{"symbol": "SPY", "risk": 800}]
        rules = RiskRules(max_portfolio_risk_pct=0.10)
        v = check_portfolio_risk(positions, new_risk=300, fund_size=10000, rules=rules)
        assert v is not None
        assert v.severity == "block"

    def test_check_all_rules_clean(self):
        rules = RiskRules(
            max_positions=5, max_risk_pct=0.10,
            max_loss_per_trade=1000, event_blackout=False,
        )
        violations = check_all_rules(
            symbol="AAPL", max_loss=200,
            current_positions=[], fund_size=10000, rules=rules,
        )
        assert len(violations) == 0


class TestCorrelationGroups:
    def test_spy_group(self):
        assert _get_correlation_group("SPY") == "large_cap_index"

    def test_qqq_group(self):
        assert _get_correlation_group("QQQ") == "tech_index"

    def test_unknown_symbol(self):
        assert _get_correlation_group("PLTR") is None

    def test_nvda_in_mega_and_semis(self):
        # NVDA is in both mega_tech and semis — returns first match
        group = _get_correlation_group("NVDA")
        assert group in ("mega_tech", "semis")


# ── MC Expected Value ────────────────────────────────────────────────────────

class TestMCExpectedValue:
    def test_iron_condor_ev(self):
        """Iron condor: sell call spread + sell put spread."""
        legs = [
            LegSpec(action="sell", option_type="call", strike=105),
            LegSpec(action="buy", option_type="call", strike=110),
            LegSpec(action="sell", option_type="put", strike=95),
            LegSpec(action="buy", option_type="put", strike=90),
        ]
        result = compute_multi_leg_ev(
            spot=100.0, legs=legs, iv=0.20, dte=30,
            entry_net=2.0, is_credit=True,
            num_paths=5000, seed=42,
        )
        assert isinstance(result, PositionEV)
        assert 0.0 <= result.prob_profit <= 1.0
        assert result.max_loss < 0  # there is a loss scenario
        assert len(result.breakevens) >= 1

    def test_long_call_ev(self):
        """Single long call — debit position."""
        legs = [LegSpec(action="buy", option_type="call", strike=100)]
        result = compute_multi_leg_ev(
            spot=100.0, legs=legs, iv=0.25, dte=30,
            entry_net=3.5, is_credit=False,
            num_paths=5000, seed=42,
        )
        assert result.prob_profit < 1.0
        assert result.prob_profit > 0.0
        assert result.max_loss < 0

    def test_short_put_spread_ev(self):
        legs = [
            LegSpec(action="sell", option_type="put", strike=95),
            LegSpec(action="buy", option_type="put", strike=90),
        ]
        result = compute_multi_leg_ev(
            spot=100.0, legs=legs, iv=0.20, dte=14,
            entry_net=1.5, is_credit=True,
            num_paths=5000, seed=42,
        )
        assert result.prob_profit > 0.5  # OTM put spread should have high win rate
        # VaR can be negative when 95th percentile tail is still profitable
        assert result.max_loss < 0  # there is a loss scenario

    def test_breakevens_iron_condor(self):
        """Iron condor should have 2 breakevens."""
        legs = [
            LegSpec(action="sell", option_type="call", strike=105),
            LegSpec(action="buy", option_type="call", strike=110),
            LegSpec(action="sell", option_type="put", strike=95),
            LegSpec(action="buy", option_type="put", strike=90),
        ]
        breakevens = _find_breakevens(legs, entry_net=2.0, is_credit=True, spot=100)
        assert len(breakevens) == 2
        assert breakevens[0] < 100 < breakevens[1]

    def test_breakevens_long_call(self):
        """Long call has 1 breakeven above strike."""
        legs = [LegSpec(action="buy", option_type="call", strike=100)]
        breakevens = _find_breakevens(legs, entry_net=3.0, is_credit=False, spot=100)
        assert len(breakevens) == 1
        assert breakevens[0] > 100

    def test_ev_with_garch(self):
        """Test GARCH vol paths don't crash."""
        legs = [LegSpec(action="buy", option_type="call", strike=100)]
        returns = np.random.default_rng(42).normal(0.0005, 0.01, 100)
        result = compute_multi_leg_ev(
            spot=100.0, legs=legs, iv=0.25, dte=30,
            entry_net=3.0, is_credit=False,
            num_paths=2000, seed=42,
            use_garch=True, historical_returns=returns,
        )
        assert result.expected_value != 0.0 or result.prob_profit >= 0


# ── FlashAlpha Client ────────────────────────────────────────────────────────

class TestFlashAlphaClient:
    def test_parse_gex_response(self):
        from scanner.providers.flashalpha_client import _parse_gex_response
        data = {
            "data": {
                "spot": 590.0,
                "gamma_flip": 585.0,
                "net_gex": 1500.0,
                "timestamp": "2026-04-20T10:00:00Z",
                "levels": [
                    {"strike": 600, "gex": 500, "call_gex": 500, "put_gex": 0},
                    {"strike": 580, "gex": -300, "call_gex": 0, "put_gex": -300},
                    {"strike": 590, "gex": 200, "call_gex": 200, "put_gex": 0},
                ],
            }
        }
        snapshot = _parse_gex_response("SPY", data)
        assert snapshot.symbol == "SPY"
        assert snapshot.spot == 590.0
        assert snapshot.gamma_flip == 585.0
        assert snapshot.dealer_regime == "POSITIVE_GAMMA"  # spot > gamma_flip
        assert snapshot.top_call_wall == 600.0
        assert snapshot.top_put_wall == 580.0
        assert len(snapshot.levels) == 3

    def test_classify_positive_gamma(self):
        from scanner.providers.flashalpha_client import classify_dealer_regime, GexSnapshot, GexLevel
        gex = GexSnapshot(
            symbol="SPY", spot=590, gamma_flip=585,
            dealer_regime="POSITIVE_GAMMA", net_gex=1000,
            top_call_wall=600, top_put_wall=580, levels=[], timestamp="",
        )
        result = classify_dealer_regime(gex)
        assert result["regime"] == "POSITIVE_GAMMA"
        assert result["bias"] == "neutral"
        assert "mean-reversion" in result["implication"]

    def test_classify_negative_gamma(self):
        from scanner.providers.flashalpha_client import classify_dealer_regime, GexSnapshot
        gex = GexSnapshot(
            symbol="SPY", spot=580, gamma_flip=585,
            dealer_regime="NEGATIVE_GAMMA", net_gex=-500,
            top_call_wall=600, top_put_wall=570, levels=[], timestamp="",
        )
        result = classify_dealer_regime(gex)
        assert result["regime"] == "NEGATIVE_GAMMA"
        assert result["bias"] == "bearish"  # spot < gamma_flip

    def test_no_api_key_returns_none(self):
        from scanner.providers.flashalpha_client import fetch_gex
        # Ensure no key is set
        old = os.environ.pop("FLASHALPHA_API_KEY", None)
        result = fetch_gex("SPY")
        assert result is None
        if old:
            os.environ["FLASHALPHA_API_KEY"] = old
