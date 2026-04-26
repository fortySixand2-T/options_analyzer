"""
Tests for L2 Trade Generator.

Covers: confluence scoring, per-strategy exit rules, strike selection,
DTE selection, entry windows, and end-to-end generate_trades pipeline.

Options Analytics Team — 2026-04
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest

from market_state import MarketState, VolSurface, ChainQuality
from trade_generator import (
    EXIT_RULES, ExitRule, TradeCandidate,
    compute_confluence_score,
    build_legs, select_dte, optimal_entry_window,
    generate_trades,
    _edge_sub_score, _regime_sub_score, _dealer_sub_score,
    _bias_sub_score, _skew_sub_score, _timing_sub_score,
    CREDIT_STRATEGIES, DEBIT_STRATEGIES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(**overrides) -> MarketState:
    """Build a MarketState with sensible defaults for testing."""
    defaults = dict(
        symbol="SPY", spot=587.0, timestamp=datetime(2026, 4, 25, 10, 30),
        regime="HIGH_IV", regime_rationale="test",
        iv_rank=65.0, vix=22.0, vix_term_slope=5.0,
        chain_iv=0.25, garch_vol=0.18, iv_rv_spread=0.07,
        iv_rv_edge_pct=28.0, hv20=0.19,
        vol_surface=VolSurface(atm_iv=0.25, put_25d_iv=0.29, call_25d_iv=0.23,
                               skew_25d=0.04, skew_rr=-0.06,
                               iv_by_strike={580: 0.27, 585: 0.26, 590: 0.25,
                                             595: 0.24, 600: 0.23}),
        chain_quality=ChainQuality(quality_score=0.7, avg_spread_pct=4.0,
                                   median_spread_pct=3.5, total_oi=50000,
                                   liquid_strikes=12),
        bias_label="NEUTRAL", bias_score=0, atr_percentile=50.0,
        dealer_regime="LONG_GAMMA",
        call_wall=600.0, put_wall=575.0, max_pain=590.0,
    )
    defaults.update(overrides)
    return MarketState(**defaults)


# ── Test exit rules ───────────────────────────────────────────────────────────

class TestExitRules:
    def test_all_strategies_have_exit_rules(self):
        for strat in list(CREDIT_STRATEGIES) + list(DEBIT_STRATEGIES):
            assert strat in EXIT_RULES, f"Missing exit rule for {strat}"

    def test_credit_strategies_50pct_target(self):
        for strat in CREDIT_STRATEGIES:
            assert EXIT_RULES[strat].profit_target_pct == 50

    def test_credit_strategies_2x_stop(self):
        for strat in CREDIT_STRATEGIES:
            assert EXIT_RULES[strat].stop_loss_pct == 200

    def test_butterfly_hold_to_expiry(self):
        assert EXIT_RULES["butterfly"].hold_to_expiry is True
        assert EXIT_RULES["butterfly"].time_exit_dte == 0

    def test_debit_spread_time_exit(self):
        assert EXIT_RULES["long_call_spread"].time_exit_dte == 2
        assert EXIT_RULES["long_put_spread"].time_exit_dte == 2


# ── Test sub-scores ───────────────────────────────────────────────────────────

class TestEdgeSubScore:
    def test_credit_positive_edge(self):
        state = _make_state(iv_rv_edge_pct=15.0)
        assert _edge_sub_score(state, "iron_condor") == pytest.approx(0.75, abs=0.01)

    def test_credit_no_edge(self):
        state = _make_state(iv_rv_edge_pct=-5.0)
        assert _edge_sub_score(state, "iron_condor") == 0.0

    def test_debit_negative_edge(self):
        state = _make_state(iv_rv_edge_pct=-10.0)
        assert _edge_sub_score(state, "long_call_spread") == pytest.approx(0.5, abs=0.01)

    def test_debit_no_edge(self):
        state = _make_state(iv_rv_edge_pct=5.0)
        assert _edge_sub_score(state, "long_call_spread") == 0.0

    def test_edge_capped_at_1(self):
        state = _make_state(iv_rv_edge_pct=30.0)
        assert _edge_sub_score(state, "iron_condor") == 1.0


class TestRegimeSubScore:
    def test_high_iv_credit(self):
        state = _make_state(regime="HIGH_IV")
        assert _regime_sub_score(state, "iron_condor") == 1.0

    def test_spike_credit_zero(self):
        state = _make_state(regime="SPIKE")
        assert _regime_sub_score(state, "short_put_spread") == 0.0

    def test_low_iv_debit(self):
        state = _make_state(regime="LOW_IV")
        assert _regime_sub_score(state, "long_call_spread") == 1.0


class TestDealerSubScore:
    def test_iron_condor_needs_long_gamma(self):
        state = _make_state(dealer_regime="LONG_GAMMA")
        assert _dealer_sub_score(state, "iron_condor") == 1.0

    def test_iron_condor_short_gamma_zero(self):
        state = _make_state(dealer_regime="SHORT_GAMMA")
        assert _dealer_sub_score(state, "iron_condor") == 0.0

    def test_no_dealer_data_neutral(self):
        state = _make_state(dealer_regime=None)
        assert _dealer_sub_score(state, "iron_condor") == 0.5


class TestBiasSubScore:
    def test_neutral_good_for_iron_condor(self):
        state = _make_state(bias_score=0, bias_label="NEUTRAL")
        assert _bias_sub_score(state, "iron_condor") == 1.0

    def test_strong_bias_bad_for_iron_condor(self):
        state = _make_state(bias_score=5, bias_label="STRONG_BULLISH")
        assert _bias_sub_score(state, "iron_condor") == 0.0

    def test_bullish_good_for_long_call(self):
        state = _make_state(bias_score=4, bias_label="STRONG_BULLISH")
        assert _bias_sub_score(state, "long_call_spread") == 1.0

    def test_bearish_bad_for_long_call(self):
        state = _make_state(bias_score=-3, bias_label="LEAN_BEARISH")
        assert _bias_sub_score(state, "long_call_spread") == 0.0


class TestSkewSubScore:
    def test_steep_skew_good_for_selling_puts(self):
        state = _make_state(vol_surface=VolSurface(atm_iv=0.25, skew_25d=0.06))
        assert _skew_sub_score(state, "short_put_spread") == 1.0

    def test_flat_skew_for_selling_puts(self):
        state = _make_state(vol_surface=VolSurface(atm_iv=0.25, skew_25d=0.01))
        assert _skew_sub_score(state, "short_put_spread") == 0.4


class TestTimingSubScore:
    def test_credit_optimal_window(self):
        state = _make_state(timestamp=datetime(2026, 4, 25, 10, 30))
        assert _timing_sub_score(state, "iron_condor") == 1.0

    def test_debit_optimal_window(self):
        state = _make_state(timestamp=datetime(2026, 4, 25, 15, 15))
        assert _timing_sub_score(state, "long_call_spread") == 1.0

    def test_credit_late_day_penalty(self):
        state = _make_state(timestamp=datetime(2026, 4, 25, 15, 30))
        score = _timing_sub_score(state, "iron_condor")
        assert score < 0.5


# ── Test confluence score ─────────────────────────────────────────────────────

class TestConfluenceScore:
    def test_score_range(self):
        state = _make_state()
        score, breakdown = compute_confluence_score(state, "iron_condor")
        assert 0 <= score <= 100

    def test_breakdown_sums_to_score(self):
        state = _make_state()
        score, breakdown = compute_confluence_score(state, "iron_condor")
        assert abs(sum(breakdown.values()) - score) < 1.0  # rounding tolerance

    def test_strong_signals_high_score(self):
        """All signals aligned → high score."""
        state = _make_state(
            regime="HIGH_IV", iv_rv_edge_pct=20.0, iv_rv_spread=0.07,
            dealer_regime="LONG_GAMMA", bias_score=0, bias_label="NEUTRAL",
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        score, _ = compute_confluence_score(state, "iron_condor")
        assert score >= 75

    def test_misaligned_signals_low_score(self):
        """Regime misaligned → low score."""
        state = _make_state(
            regime="LOW_IV", iv_rv_edge_pct=5.0,
            dealer_regime="SHORT_GAMMA", bias_score=4,
        )
        score, _ = compute_confluence_score(state, "iron_condor")
        assert score < 50


# ── Test strike selection ─────────────────────────────────────────────────────

class TestBuildLegs:
    def test_iron_condor_has_4_legs(self):
        legs = build_legs("iron_condor", spot=587.0)
        assert len(legs) == 4

    def test_iron_condor_structure(self):
        legs = build_legs("iron_condor", spot=587.0)
        actions = [l["action"] for l in legs]
        assert actions.count("sell") == 2
        assert actions.count("buy") == 2

    def test_credit_spread_has_2_legs(self):
        legs = build_legs("short_put_spread", spot=587.0)
        assert len(legs) == 2

    def test_butterfly_has_4_legs(self):
        legs = build_legs("butterfly", spot=587.0)
        assert len(legs) == 4

    def test_butterfly_centered_at_max_pain(self):
        legs = build_legs("butterfly", spot=587.0, max_pain=590.0)
        center_strikes = [l["strike"] for l in legs if l["action"] == "sell"]
        assert all(s == 590.0 for s in center_strikes)

    def test_iron_condor_uses_call_wall(self):
        legs = build_legs("iron_condor", spot=587.0, call_wall=600.0)
        short_call = next(l for l in legs
                          if l["action"] == "sell" and l["option_type"] == "call")
        assert short_call["strike"] == 600.0

    def test_iron_condor_uses_put_wall(self):
        legs = build_legs("iron_condor", spot=587.0, put_wall=575.0)
        short_put = next(l for l in legs
                         if l["action"] == "sell" and l["option_type"] == "put")
        assert short_put["strike"] == 575.0

    def test_debit_spread_legs(self):
        legs = build_legs("long_call_spread", spot=587.0)
        assert len(legs) == 2
        buy_leg = next(l for l in legs if l["action"] == "buy")
        sell_leg = next(l for l in legs if l["action"] == "sell")
        assert sell_leg["strike"] > buy_leg["strike"]

    def test_long_put_spread_legs(self):
        legs = build_legs("long_put_spread", spot=587.0)
        buy_leg = next(l for l in legs if l["action"] == "buy")
        sell_leg = next(l for l in legs if l["action"] == "sell")
        assert buy_leg["strike"] > sell_leg["strike"]

    def test_wall_outside_range_ignored(self):
        """Dealer wall too far from spot should be ignored."""
        legs = build_legs("iron_condor", spot=587.0, call_wall=700.0)
        short_call = next(l for l in legs
                          if l["action"] == "sell" and l["option_type"] == "call")
        # Should fallback to ATM + inc, not 700
        assert short_call["strike"] < 600.0


# ── Test DTE selection ────────────────────────────────────────────────────────

class TestSelectDTE:
    def test_high_iv_credit_short_dte(self):
        state = _make_state(iv_rank=80.0)
        dte = select_dte("iron_condor", state)
        assert 7 <= dte <= 14
        assert dte <= 10  # should lean short

    def test_low_iv_debit_longer_dte(self):
        state = _make_state(iv_rank=20.0, bias_score=1)
        dte = select_dte("long_call_spread", state)
        assert 3 <= dte <= 14
        assert dte >= 10  # weak bias, longer DTE

    def test_strong_bias_short_dte(self):
        state = _make_state(bias_score=5)
        dte = select_dte("long_call_spread", state)
        assert dte <= 5  # strong bias, short DTE

    def test_butterfly_range(self):
        state = _make_state()
        dte = select_dte("butterfly", state)
        assert 0 <= dte <= 7


# ── Test entry windows ────────────────────────────────────────────────────────

class TestEntryWindow:
    def test_credit_morning_window(self):
        state = _make_state()
        start, end = optimal_entry_window("iron_condor", state)
        assert start.startswith("10")

    def test_debit_afternoon_window(self):
        state = _make_state()
        start, end = optimal_entry_window("long_call_spread", state)
        assert start.startswith("15")

    def test_spike_delayed_window(self):
        state = _make_state(regime="SPIKE")
        start, end = optimal_entry_window("iron_condor", state)
        assert start == "10:30"

    def test_trending_day_delayed(self):
        state = _make_state(atr_percentile=75.0)
        start, end = optimal_entry_window("short_put_spread", state)
        assert start == "10:30"


# ── Test end-to-end generate_trades ───────────────────────────────────────────

class TestGenerateTrades:
    def test_high_iv_neutral_long_gamma_produces_iron_condor(self):
        state = _make_state(
            regime="HIGH_IV", bias_label="NEUTRAL", bias_score=0,
            dealer_regime="LONG_GAMMA",
            iv_rv_spread=0.07, iv_rv_edge_pct=28.0,
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        trades = generate_trades(state)
        strategies = [t.strategy for t in trades]
        assert "iron_condor" in strategies

    def test_no_edge_no_trades(self):
        state = _make_state(iv_rv_spread=0.001, iv_rv_edge_pct=0.5)
        trades = generate_trades(state)
        assert trades == []

    def test_illiquid_chain_no_trades(self):
        state = _make_state(
            chain_quality=ChainQuality(quality_score=0.1),
        )
        trades = generate_trades(state)
        assert trades == []

    def test_trades_sorted_by_score(self):
        """Multiple candidates should be sorted by confluence score."""
        state = _make_state(
            regime="HIGH_IV", bias_label="LEAN_BULLISH", bias_score=3,
            dealer_regime="LONG_GAMMA",
            iv_rv_spread=0.07, iv_rv_edge_pct=28.0,
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        trades = generate_trades(state)
        if len(trades) > 1:
            scores = [t.confluence_score for t in trades]
            assert scores == sorted(scores, reverse=True)

    def test_spike_no_credit_trades(self):
        """SPIKE regime should not produce credit trades."""
        state = _make_state(
            regime="SPIKE", bias_label="LEAN_BEARISH", bias_score=-3,
            iv_rv_spread=-0.08, iv_rv_edge_pct=-32.0,
            chain_iv=0.25, garch_vol=0.33,
        )
        trades = generate_trades(state)
        for t in trades:
            assert t.strategy not in CREDIT_STRATEGIES

    def test_low_iv_bullish_produces_long_call(self):
        state = _make_state(
            regime="LOW_IV", bias_label="LEAN_BULLISH", bias_score=3,
            dealer_regime="SHORT_GAMMA",
            iv_rv_spread=-0.08, iv_rv_edge_pct=-40.0,
            chain_iv=0.20, garch_vol=0.28,
            iv_rank=20.0,
            timestamp=datetime(2026, 4, 25, 15, 15),
        )
        trades = generate_trades(state)
        strategies = [t.strategy for t in trades]
        assert "long_call_spread" in strategies

    def test_trade_candidate_has_exit_rule(self):
        state = _make_state(
            regime="HIGH_IV", bias_label="NEUTRAL", bias_score=0,
            dealer_regime="LONG_GAMMA",
            iv_rv_spread=0.07, iv_rv_edge_pct=28.0,
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        trades = generate_trades(state)
        if trades:
            tc = trades[0]
            assert tc.exit_rule.profit_target_pct > 0
            assert tc.exit_rule.stop_loss_pct > 0

    def test_trade_candidate_to_dict(self):
        state = _make_state(
            regime="HIGH_IV", bias_label="NEUTRAL", bias_score=0,
            dealer_regime="LONG_GAMMA",
            iv_rv_spread=0.07, iv_rv_edge_pct=28.0,
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        trades = generate_trades(state)
        if trades:
            d = trades[0].to_dict()
            assert "confluence_score" in d
            assert "score_breakdown" in d
            assert "exit_rule" in d
            assert "entry_window" in d
            assert "legs" in d

    def test_trade_has_rationale(self):
        state = _make_state(
            regime="HIGH_IV", bias_label="NEUTRAL", bias_score=0,
            dealer_regime="LONG_GAMMA",
            iv_rv_spread=0.07, iv_rv_edge_pct=28.0,
            timestamp=datetime(2026, 4, 25, 10, 30),
        )
        trades = generate_trades(state)
        if trades:
            assert len(trades[0].rationale) > 0
            assert "28%" in trades[0].rationale or "28" in trades[0].rationale
