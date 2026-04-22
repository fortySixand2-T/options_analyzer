"""Tests for the 3-input strategy decision matrix (SIGNALS.md)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from scanner.strategy_mapper import map_strategy, map_signal, StrategyRecommendation


class TestDecisionMatrix:
    def test_high_iv_neutral_long_gamma_iron_condor(self):
        r = map_strategy("HIGH_IV", "NEUTRAL", "LONG_GAMMA")
        assert r is not None
        assert r.strategy == "iron_condor"

    def test_high_iv_neutral_short_gamma_no_iron_condor(self):
        """SHORT_GAMMA override: never sell iron condor."""
        r = map_strategy("HIGH_IV", "NEUTRAL", "SHORT_GAMMA")
        assert r is None

    def test_high_iv_lean_bullish_short_put_spread(self):
        r = map_strategy("HIGH_IV", "LEAN_BULLISH")
        assert r is not None
        assert r.strategy == "short_put_spread"

    def test_high_iv_lean_bearish_short_call_spread(self):
        r = map_strategy("HIGH_IV", "LEAN_BEARISH")
        assert r is not None
        assert r.strategy == "short_call_spread"

    def test_high_iv_strong_bullish_tight_put_spread(self):
        r = map_strategy("HIGH_IV", "STRONG_BULLISH")
        assert r is not None
        assert r.strategy == "short_put_spread"
        assert r.suggested_dte == (3, 7)

    def test_moderate_iv_neutral_long_gamma_butterfly(self):
        r = map_strategy("MODERATE_IV", "NEUTRAL", "LONG_GAMMA")
        assert r is not None
        assert r.strategy == "butterfly"

    def test_moderate_iv_lean_bullish_long_call_spread(self):
        r = map_strategy("MODERATE_IV", "LEAN_BULLISH")
        assert r is not None
        assert r.strategy == "long_call_spread"

    def test_low_iv_lean_bearish_long_put_spread(self):
        r = map_strategy("LOW_IV", "LEAN_BEARISH")
        assert r is not None
        assert r.strategy == "long_put_spread"

    def test_low_iv_strong_bullish_tight_call_spread(self):
        r = map_strategy("LOW_IV", "STRONG_BULLISH")
        assert r is not None
        assert r.strategy == "long_call_spread"
        assert r.suggested_dte == (3, 5)

    def test_spike_returns_debit(self):
        r = map_strategy("SPIKE", "NEUTRAL")
        assert r is not None
        assert "debit" in r.strategy_label.lower() or "debit" in r.rationale.lower()

    def test_spike_any_bias(self):
        for bias in ["STRONG_BULLISH", "LEAN_BEARISH", "NEUTRAL"]:
            r = map_strategy("SPIKE", bias)
            assert r is not None

    def test_result_has_rationale(self):
        r = map_strategy("HIGH_IV", "LEAN_BULLISH", "LONG_GAMMA")
        assert r is not None
        assert "HIGH_IV" in r.rationale
        assert "LEAN_BULLISH" in r.rationale

    def test_all_defined_risk(self):
        combos = [
            ("HIGH_IV", "LEAN_BULLISH"),
            ("MODERATE_IV", "LEAN_BEARISH"),
            ("LOW_IV", "NEUTRAL"),
            ("SPIKE", "NEUTRAL"),
        ]
        for regime, bias in combos:
            r = map_strategy(regime, bias)
            assert r is not None
            assert r.risk_profile == "defined"

    def test_unknown_regime_returns_none(self):
        r = map_strategy("UNKNOWN", "NEUTRAL")
        assert r is None


class TestLegacyMapSignal:
    def test_backward_compat(self):
        """map_signal still works with OptionSignal."""
        from scanner import OptionSignal
        signal = OptionSignal(
            ticker="SPY", strike=590, expiry="2026-05-01", option_type="call",
            dte=10, spot=585, bid=3, ask=3.5, mid=3.25, open_interest=5000,
            bid_ask_spread_pct=15.0, chain_iv=0.25, iv_rank=60, iv_percentile=65,
            iv_regime="HIGH_IV", garch_vol=0.22, theo_price=3.0, edge_pct=-8.0,
            direction="BUY", delta=0.35, gamma=0.01, theta=-0.05, vega=0.15,
            conviction=65.0,
        )
        r = map_signal(signal)
        assert r is not None
