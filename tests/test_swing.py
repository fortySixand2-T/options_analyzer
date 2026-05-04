"""Tests for Phase 2 swing modules: bias detector, decision matrix, registry."""

import numpy as np
import pandas as pd
import pytest

from swing.bias import (
    SwingBiasResult,
    detect_swing_bias,
    _sma,
    _score_to_label,
    STRONG_BULLISH,
    LEAN_BULLISH,
    NEUTRAL,
    LEAN_BEARISH,
    STRONG_BEARISH,
)
from swing.decision_matrix import SwingRecommendation, map_swing_strategy


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(prices: list) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from close prices."""
    n = len(prices)
    closes = np.array(prices, dtype=float)
    return pd.DataFrame({
        "Open": closes * 0.999,
        "High": closes * 1.005,
        "Low": closes * 0.995,
        "Close": closes,
        "Volume": np.full(n, 1_000_000),
    })


def _trending_up(n=250, start=100.0, daily_return=0.002):
    """Generate a steady uptrend series."""
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return _make_ohlcv(prices)


def _trending_down(n=250, start=200.0, daily_return=-0.002):
    """Generate a steady downtrend series."""
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return _make_ohlcv(prices)


def _flat_series(n=250, price=100.0, noise=0.001):
    """Generate a flat/ranging series oscillating around price."""
    np.random.seed(42)
    prices = price + np.sin(np.linspace(0, 20 * np.pi, n)) * noise * price
    return _make_ohlcv(prices.tolist())


# ── Swing Bias Tests ─────────────────────────────────────────────────────────

class TestSwingBias:

    def test_insufficient_data_returns_neutral(self):
        df = _make_ohlcv([100, 101, 102])
        result = detect_swing_bias(df)
        assert result.label == NEUTRAL
        assert result.score == 0

    def test_none_input_returns_neutral(self):
        result = detect_swing_bias(None)
        assert result.label == NEUTRAL

    def test_uptrend_is_bullish(self):
        df = _trending_up(250, start=100, daily_return=0.003)
        result = detect_swing_bias(df)
        assert result.label in (STRONG_BULLISH, LEAN_BULLISH)
        assert result.score > 0

    def test_downtrend_is_bearish(self):
        df = _trending_down(250, start=200, daily_return=-0.003)
        result = detect_swing_bias(df)
        assert result.label in (STRONG_BEARISH, LEAN_BEARISH)
        assert result.score < 0

    def test_flat_has_low_absolute_score(self):
        df = _flat_series(250, price=100, noise=0.0001)
        result = detect_swing_bias(df)
        assert abs(result.score) <= 5

    def test_result_has_detail(self):
        df = _trending_up(250)
        result = detect_swing_bias(df)
        assert "sma_alignment" in result.detail
        assert "sma_cross" in result.detail
        assert "weekly_rsi" in result.detail
        assert "momentum_20d" in result.detail

    def test_atr_percentile_in_range(self):
        df = _trending_up(250)
        result = detect_swing_bias(df)
        assert 0 <= result.atr_percentile <= 100


class TestSMAHelper:

    def test_sma_basic(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _sma(values, 3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_sma_insufficient_data(self):
        values = np.array([1.0, 2.0])
        result = _sma(values, 5)
        assert all(np.isnan(result))


class TestScoreToLabel:

    def test_strong_bullish(self):
        assert _score_to_label(5) == STRONG_BULLISH
        assert _score_to_label(10) == STRONG_BULLISH

    def test_lean_bullish(self):
        assert _score_to_label(2) == LEAN_BULLISH
        assert _score_to_label(4) == LEAN_BULLISH

    def test_neutral(self):
        assert _score_to_label(0) == NEUTRAL
        assert _score_to_label(1) == NEUTRAL
        assert _score_to_label(-1) == NEUTRAL

    def test_lean_bearish(self):
        assert _score_to_label(-2) == LEAN_BEARISH
        assert _score_to_label(-4) == LEAN_BEARISH

    def test_strong_bearish(self):
        assert _score_to_label(-5) == STRONG_BEARISH
        assert _score_to_label(-10) == STRONG_BEARISH


# ── Decision Matrix Tests ────────────────────────────────────────────────────

class TestSwingDecisionMatrix:

    def test_spike_returns_none(self):
        result = map_swing_strategy(
            regime="SPIKE", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=True, vrp_pct=5.0, calendar_signal=0.0,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is None

    def test_earnings_low_inflation_long_straddle(self):
        result = map_swing_strategy(
            regime="LOW_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=False, vrp_pct=-2.0, calendar_signal=0.0,
            in_earnings_window=True, earnings_iv_inflation=0.3,
        )
        assert result is not None
        assert result.strategy == "long_straddle"
        assert "earnings" in result.rationale.lower()

    def test_earnings_high_inflation_iron_butterfly(self):
        result = map_swing_strategy(
            regime="HIGH_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=True, vrp_pct=8.0, calendar_signal=0.0,
            in_earnings_window=True, earnings_iv_inflation=0.7,
        )
        assert result is not None
        assert result.strategy == "iron_butterfly"

    def test_earnings_high_inflation_no_vrp_returns_none(self):
        result = map_swing_strategy(
            regime="MODERATE_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=False, vrp_pct=1.0, calendar_signal=0.0,
            in_earnings_window=True, earnings_iv_inflation=0.7,
        )
        assert result is None

    def test_high_iv_vrp_calendar(self):
        result = map_swing_strategy(
            regime="HIGH_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=True, vrp_pct=6.0, calendar_signal=0.4,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is not None
        assert result.strategy == "calendar_spread"

    def test_high_iv_vrp_neutral_long_gamma_iron_butterfly(self):
        result = map_swing_strategy(
            regime="HIGH_IV", swing_bias="NEUTRAL", dealer_regime="LONG_GAMMA",
            vrp_rich=True, vrp_pct=5.0, calendar_signal=0.1,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is not None
        assert result.strategy == "iron_butterfly"

    def test_high_iv_vrp_directional_diagonal(self):
        result = map_swing_strategy(
            regime="HIGH_IV", swing_bias="LEAN_BULLISH", dealer_regime=None,
            vrp_rich=True, vrp_pct=5.0, calendar_signal=0.0,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is not None
        assert result.strategy == "diagonal_spread"

    def test_moderate_iv_calendar_signal(self):
        result = map_swing_strategy(
            regime="MODERATE_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=True, vrp_pct=3.0, calendar_signal=0.5,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is not None
        assert result.strategy == "calendar_spread"

    def test_moderate_iv_no_edge_returns_none(self):
        result = map_swing_strategy(
            regime="MODERATE_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=False, vrp_pct=-1.0, calendar_signal=0.0,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is None

    def test_low_iv_neutral_long_straddle(self):
        result = map_swing_strategy(
            regime="LOW_IV", swing_bias="NEUTRAL", dealer_regime=None,
            vrp_rich=False, vrp_pct=-2.0, calendar_signal=0.0,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is not None
        assert result.strategy == "long_straddle"
        assert result.edge_source == "iv_underpriced"

    def test_low_iv_directional_returns_none(self):
        result = map_swing_strategy(
            regime="LOW_IV", swing_bias="LEAN_BULLISH", dealer_regime=None,
            vrp_rich=False, vrp_pct=-2.0, calendar_signal=0.0,
            in_earnings_window=False, earnings_iv_inflation=0.0,
        )
        assert result is None

    def test_all_recommendations_defined_risk(self):
        """Every recommendation must be defined-risk."""
        test_cases = [
            ("HIGH_IV", "NEUTRAL", "LONG_GAMMA", True, 6.0, 0.4, False, 0.0),
            ("HIGH_IV", "LEAN_BEARISH", None, True, 5.0, 0.0, False, 0.0),
            ("MODERATE_IV", "LEAN_BULLISH", None, True, 3.0, 0.0, False, 0.0),
            ("LOW_IV", "NEUTRAL", None, False, -2.0, 0.0, False, 0.0),
            ("LOW_IV", "NEUTRAL", None, False, -2.0, 0.0, True, 0.3),
        ]
        for args in test_cases:
            result = map_swing_strategy(*args)
            if result is not None:
                assert result.risk_profile == "defined", (
                    f"Strategy {result.strategy} is not defined risk"
                )


# ── Registry Tests ───────────────────────────────────────────────────────────

class TestSwingRegistry:

    def test_swing_registry_has_four_strategies(self):
        from strategies.registry import SWING_REGISTRY
        assert len(SWING_REGISTRY) == 4

    def test_swing_registry_names(self):
        from strategies.registry import SWING_REGISTRY
        names = {s.name for s in SWING_REGISTRY}
        assert names == {"calendar_spread", "diagonal_spread", "iron_butterfly", "long_straddle"}

    def test_for_swing_regime_high_iv(self):
        from strategies.registry import for_swing_regime
        from regime.detector import MarketRegime
        strategies = for_swing_regime(MarketRegime.HIGH_IV)
        names = {s.name for s in strategies}
        assert "calendar_spread" in names
        assert "iron_butterfly" in names

    def test_for_swing_regime_low_iv(self):
        from strategies.registry import for_swing_regime
        from regime.detector import MarketRegime
        strategies = for_swing_regime(MarketRegime.LOW_IV)
        names = {s.name for s in strategies}
        assert "long_straddle" in names

    def test_get_strategy_finds_swing(self):
        from strategies.registry import get_strategy
        s = get_strategy("iron_butterfly")
        assert s.name == "iron_butterfly"

    def test_short_dte_registry_unchanged(self):
        from strategies.registry import STRATEGY_REGISTRY
        assert len(STRATEGY_REGISTRY) == 6


# ── Config Tests ─────────────────────────────────────────────────────────────

class TestSwingConfig:

    def test_swing_config_exists(self):
        from config import SWING_SCANNER_CONFIG
        assert "filter" in SWING_SCANNER_CONFIG
        assert "scoring_weights" in SWING_SCANNER_CONFIG

    def test_swing_dte_range(self):
        from config import SWING_SCANNER_CONFIG
        f = SWING_SCANNER_CONFIG["filter"]
        assert f["min_dte"] == 14
        assert f["max_dte"] == 60

    def test_swing_weights_sum_to_one(self):
        from config import SWING_SCANNER_CONFIG
        weights = SWING_SCANNER_CONFIG["scoring_weights"]
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_vrp_is_highest_weight(self):
        from config import SWING_SCANNER_CONFIG
        weights = SWING_SCANNER_CONFIG["scoring_weights"]
        assert weights["vrp"] == max(weights.values())


# ── Signal Persistence Tests ─────────────────────────────────────────────────

class TestSwingSignalPersistence:

    def test_store_and_retrieve_swing_signals(self, tmp_path):
        import os
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_swing_signals, get_swing_signals

        store_swing_signals(
            ticker="SPY",
            snapshot_date="2026-05-01",
            vrp_overall=0.035,
            vrp_overall_pct=12.5,
            vrp_richest_bucket="30-60",
            term_structure_slope=3.2,
            calendar_signal=0.4,
            contango=True,
            swing_bias_label="LEAN_BULLISH",
            swing_bias_score=3,
            earnings_days=None,
            in_earnings_window=False,
            recommended_strategy="calendar_spread",
        )

        rows = get_swing_signals("SPY")
        assert len(rows) == 1
        row = rows[0]
        assert row["ticker"] == "SPY"
        assert row["vrp_overall"] == pytest.approx(0.035)
        assert row["vrp_overall_pct"] == pytest.approx(12.5)
        assert row["swing_bias_label"] == "LEAN_BULLISH"
        assert row["recommended_strategy"] == "calendar_spread"
        assert row["contango"] == 1

        # Clean up
        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_upsert_overwrites(self, tmp_path):
        import os
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_swing_signals, get_swing_signals

        store_swing_signals(
            ticker="SPY", snapshot_date="2026-05-01",
            vrp_overall=0.035, recommended_strategy="calendar_spread",
        )
        store_swing_signals(
            ticker="SPY", snapshot_date="2026-05-01",
            vrp_overall=0.050, recommended_strategy="iron_butterfly",
        )

        rows = get_swing_signals("SPY")
        assert len(rows) == 1
        assert rows[0]["vrp_overall"] == pytest.approx(0.050)
        assert rows[0]["recommended_strategy"] == "iron_butterfly"

        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_date_range_filter(self, tmp_path):
        import os
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_swing_signals, get_swing_signals

        for d in ["2026-05-01", "2026-05-02", "2026-05-03"]:
            store_swing_signals(ticker="SPY", snapshot_date=d, vrp_overall=0.03)

        rows = get_swing_signals("SPY", start_date="2026-05-02")
        assert len(rows) == 2

        rows = get_swing_signals("SPY", start_date="2026-05-01", end_date="2026-05-02")
        assert len(rows) == 2

        del os.environ["CHAIN_SNAPSHOTS_DB"]
