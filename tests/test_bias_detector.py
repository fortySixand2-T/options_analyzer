"""Tests for the new bias detector (SIGNALS.md Layer 2)."""

import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bias_detector import (
    detect_bias, BiasResult,
    STRONG_BULLISH, LEAN_BULLISH, NEUTRAL, LEAN_BEARISH, STRONG_BEARISH,
)


def _make_ohlcv(n=60, trend=0.0, volatility=0.02, base=450.0):
    """Generate synthetic OHLCV data.

    trend > 0 → bullish, trend < 0 → bearish, trend ≈ 0 → flat.
    """
    np.random.seed(42)
    closes = [base]
    for _ in range(n - 1):
        ret = trend + volatility * np.random.randn()
        closes.append(closes[-1] * (1 + ret))
    closes = np.array(closes)
    highs = closes * (1 + np.abs(np.random.randn(n)) * 0.005)
    lows = closes * (1 - np.abs(np.random.randn(n)) * 0.005)
    opens = (closes + lows) / 2
    volume = np.random.randint(1_000_000, 10_000_000, n)
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows,
        "Close": closes, "Volume": volume,
    })


class TestBiasResult:
    def test_returns_bias_result(self):
        df = _make_ohlcv()
        result = detect_bias(df)
        assert isinstance(result, BiasResult)
        assert result.label in (STRONG_BULLISH, LEAN_BULLISH, NEUTRAL,
                                LEAN_BEARISH, STRONG_BEARISH)

    def test_score_is_integer(self):
        df = _make_ohlcv()
        result = detect_bias(df)
        assert isinstance(result.score, int)

    def test_atr_percentile_range(self):
        df = _make_ohlcv()
        result = detect_bias(df)
        assert 0 <= result.atr_percentile <= 100

    def test_detail_has_rsi(self):
        df = _make_ohlcv()
        result = detect_bias(df)
        assert "rsi" in result.detail
        assert 0 <= result.detail["rsi"] <= 100

    def test_detail_has_macd(self):
        df = _make_ohlcv()
        result = detect_bias(df)
        assert "macd_histogram" in result.detail


class TestBullishBias:
    def test_strong_uptrend_bullish(self):
        df = _make_ohlcv(trend=0.01, volatility=0.005)
        result = detect_bias(df)
        assert result.score > 0
        assert result.label in (STRONG_BULLISH, LEAN_BULLISH)

    def test_strong_uptrend_ema_above(self):
        df = _make_ohlcv(trend=0.01, volatility=0.005)
        result = detect_bias(df)
        assert result.detail["ema9_vs_ema21"] == "above"


class TestBearishBias:
    def test_strong_downtrend_bearish(self):
        df = _make_ohlcv(trend=-0.01, volatility=0.005)
        result = detect_bias(df)
        assert result.score < 0
        assert result.label in (STRONG_BEARISH, LEAN_BEARISH)

    def test_strong_downtrend_ema_below(self):
        df = _make_ohlcv(trend=-0.01, volatility=0.005)
        result = detect_bias(df)
        assert result.detail["ema9_vs_ema21"] == "below"


class TestNeutralBias:
    def test_flat_market_neutral(self):
        df = _make_ohlcv(trend=0.0, volatility=0.003)
        result = detect_bias(df)
        assert result.label in (NEUTRAL, LEAN_BULLISH, LEAN_BEARISH)
        assert abs(result.score) <= 4


class TestEdgeCases:
    def test_insufficient_data(self):
        df = _make_ohlcv(n=10)
        result = detect_bias(df)
        assert result.label == NEUTRAL
        assert result.score == 0

    def test_lowercase_columns(self):
        df = _make_ohlcv()
        df.columns = [c.lower() for c in df.columns]
        result = detect_bias(df)
        assert isinstance(result, BiasResult)
        assert "rsi" in result.detail

    def test_score_thresholds(self):
        """Verify label boundaries match SIGNALS.md."""
        df = _make_ohlcv(trend=0.015, volatility=0.003)
        result = detect_bias(df)
        if result.score >= 4:
            assert result.label == STRONG_BULLISH
        elif result.score >= 2:
            assert result.label == LEAN_BULLISH

    def test_two_day_momentum_in_detail(self):
        df = _make_ohlcv(trend=0.01)
        result = detect_bias(df)
        assert "two_day_momentum" in result.detail
