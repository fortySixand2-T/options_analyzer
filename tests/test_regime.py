"""
Tests for regime detection and strategy evaluation (Phase 2).

All tests use mocked VIX data — no network dependency.
"""

import sys
import os
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from regime.detector import detect_regime, MarketRegime, RegimeResult
from regime.vix_analysis import VixSnapshot
from regime.calendar import days_to_next_event, is_event_window, FOMC_2026, CPI_2026
from strategies import STRATEGY_REGISTRY, for_regime, StrategyResult, SignalCheck
from strategies.registry import get_strategy
from scanner import OptionSignal


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_vix(vix=15.0, vix3m=16.0, contango=True):
    return VixSnapshot(
        vix=vix, vix9d=vix - 1, vix3m=vix3m, vix6m=vix3m + 1,
        contango=contango, backwardation=not contango,
        term_structure_slope=(vix3m - vix) / vix * 100 if vix > 0 else 0,
        vix_percentile_1y=50.0,
    )


def _make_signal(**overrides):
    defaults = dict(
        ticker="SPY", strike=450.0, expiry="2026-06-15", option_type="put",
        dte=30, spot=455.0, bid=3.0, ask=3.40, mid=3.20,
        open_interest=5000, bid_ask_spread_pct=12.5,
        chain_iv=0.22, iv_rank=65.0, iv_percentile=70.0, iv_regime="ELEVATED",
        garch_vol=0.20, theo_price=2.80, edge_pct=-12.5, direction="SELL",
        delta=-0.25, gamma=0.005, theta=-0.08, vega=0.15, conviction=72.0,
    )
    defaults.update(overrides)
    return OptionSignal(**defaults)


# ── Regime detection ──────────────────────────────────────────────────────────

class TestRegimeDetection:
    def test_low_vol_ranging(self):
        vix = _make_vix(vix=14.0, vix3m=15.5, contango=True)
        result = detect_regime(vix)
        assert result.regime == MarketRegime.LOW_VOL_RANGING

    def test_high_vol_trending(self):
        vix = _make_vix(vix=24.0, vix3m=22.0, contango=False)
        result = detect_regime(vix)
        assert result.regime == MarketRegime.HIGH_VOL_TRENDING

    def test_spike_event_high_vix(self):
        vix = _make_vix(vix=35.0, vix3m=28.0, contango=False)
        result = detect_regime(vix)
        assert result.regime == MarketRegime.SPIKE_EVENT

    def test_rationale_present(self):
        vix = _make_vix(vix=14.0)
        result = detect_regime(vix)
        assert "VIX" in result.rationale
        assert "14.0" in result.rationale

    def test_vix_snapshot_stored(self):
        vix = _make_vix(vix=20.0)
        result = detect_regime(vix)
        assert result.vix.vix == 20.0


# ── Calendar ──────────────────────────────────────────────────────────────────

class TestCalendar:
    def test_fomc_dates_exist(self):
        assert len(FOMC_2026) == 8

    def test_cpi_dates_exist(self):
        assert len(CPI_2026) == 12

    def test_days_to_next_event_fomc(self):
        # Day before first FOMC
        ref = date(2026, 1, 28)
        event_type, days = days_to_next_event(ref)
        assert event_type == "FOMC"
        assert days == 1

    def test_no_event_far_future(self):
        ref = date(2027, 6, 1)
        event_type, days = days_to_next_event(ref)
        assert event_type is None
        assert days == 999

    def test_event_window(self):
        # Day before FOMC
        ref = date(2026, 1, 28)
        in_window, event_type, days = is_event_window(ref)
        assert in_window is True
        assert event_type == "FOMC"


# ── Strategy registry ────────────────────────────────────────────────────────

class TestStrategyRegistry:
    def test_registry_count(self):
        assert len(STRATEGY_REGISTRY) == 11

    def test_all_have_names(self):
        names = [s.name for s in STRATEGY_REGISTRY]
        assert len(names) == len(set(names))  # unique

    def test_for_regime_low_vol(self):
        strats = for_regime(MarketRegime.LOW_VOL_RANGING)
        names = [s.name for s in strats]
        assert "iron_condor" in names
        assert "butterfly" in names
        assert "naked_put_1dte" in names

    def test_for_regime_spike(self):
        strats = for_regime(MarketRegime.SPIKE_EVENT)
        names = [s.name for s in strats]
        assert "long_straddle" in names
        assert "iron_condor" not in names

    def test_get_strategy(self):
        s = get_strategy("iron_condor")
        assert s.label == "Iron Condor"

    def test_get_strategy_unknown(self):
        with pytest.raises(KeyError):
            get_strategy("nonexistent")


# ── Strategy evaluation ──────────────────────────────────────────────────────

class TestStrategyEvaluation:
    def test_iron_condor_low_vol(self):
        vix = _make_vix(vix=14.0, contango=True)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=70.0, delta=-0.18, dte=30,
                              direction="SELL", conviction=65.0)
        strategy = get_strategy("iron_condor")
        result = strategy.evaluate(signal, regime)
        assert result is not None
        assert result.strategy_name == "iron_condor"
        assert 0 <= result.score <= 100
        assert result.checks_total > 0

    def test_iron_condor_wrong_regime(self):
        vix = _make_vix(vix=35.0, contango=False)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=70.0)
        strategy = get_strategy("iron_condor")
        result = strategy.evaluate(signal, regime)
        assert result is None  # SPIKE_EVENT not in ideal regimes

    def test_iron_condor_iv_too_low(self):
        vix = _make_vix(vix=14.0)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=20.0)  # below 50% threshold
        strategy = get_strategy("iron_condor")
        result = strategy.evaluate(signal, regime)
        assert result is None

    def test_checklist_items(self):
        vix = _make_vix(vix=14.0, contango=True)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=70.0, delta=-0.18, dte=30)
        strategy = get_strategy("iron_condor")
        checklist = strategy.build_checklist(signal, regime)
        assert len(checklist) > 0
        assert all(isinstance(c, SignalCheck) for c in checklist)

    def test_short_put_spread_evaluation(self):
        vix = _make_vix(vix=14.0)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=55.0, option_type="put",
                              direction="SELL", dte=25, conviction=60.0)
        strategy = get_strategy("short_put_spread")
        result = strategy.evaluate(signal, regime)
        assert result is not None
        assert result.strategy_name == "short_put_spread"

    def test_long_straddle_low_iv(self):
        vix = _make_vix(vix=13.0)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=20.0, delta=-0.10, dte=35,
                              direction="BUY", conviction=55.0)
        strategy = get_strategy("long_straddle")
        result = strategy.evaluate(signal, regime)
        assert result is not None

    def test_naked_put_dte_filter(self):
        vix = _make_vix(vix=14.0)
        regime = detect_regime(vix)
        signal = _make_signal(dte=30)  # too many DTE for naked_put_1dte
        strategy = get_strategy("naked_put_1dte")
        result = strategy.evaluate(signal, regime)
        assert result is None

    def test_build_legs_iron_condor(self):
        strategy = get_strategy("iron_condor")
        signal = _make_signal(spot=450.0)
        legs = strategy.build_legs(signal, 450.0)
        assert len(legs) == 4
        actions = [l["action"] for l in legs]
        assert actions.count("sell") == 2
        assert actions.count("buy") == 2

    def test_result_score_bounds(self):
        vix = _make_vix(vix=14.0, contango=True)
        regime = detect_regime(vix)
        signal = _make_signal(iv_rank=70.0, delta=-0.18, dte=30,
                              direction="SELL", conviction=80.0)
        strategy = get_strategy("iron_condor")
        result = strategy.evaluate(signal, regime)
        if result:
            assert 0 <= result.score <= 100
