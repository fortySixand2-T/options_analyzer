"""
Tests for sentiment signal generation.

Verifies the weighted composition (40% composite + 40% velocity + 20% breadth),
label classification, clamping, and edge cases.
"""

import pytest
from datetime import datetime

from src.sentiment.models import SentimentSnapshot, SentimentSignal, SignalLabel
from src.sentiment.signal import generate_signal


def _make_snapshot(
    window="6h",
    composite=0.3,
    velocity=0.05,
    breadth=0.7,
    count=10,
    label=SignalLabel.LEAN_POSITIVE,
):
    return SentimentSnapshot(
        ticker="SPY",
        window=window,
        composite_score=composite,
        velocity=velocity,
        breadth=breadth,
        headline_count=count,
        computed_at=datetime(2025, 6, 1, 16, 0),
        signal_label=label,
    )


class TestSignalGeneration:
    def test_bullish_signal(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.5, velocity=0.1, breadth=0.8),
            "6h": _make_snapshot("6h", composite=0.5, velocity=0.08, breadth=0.75),
            "24h": _make_snapshot("24h", composite=0.4, velocity=0.05, breadth=0.7),
        }
        sig = generate_signal("SPY", snapshots, primary_window="6h", velocity_window="1h")

        assert sig.ticker == "SPY"
        assert sig.score > 0
        assert sig.label in (SignalLabel.LEAN_POSITIVE, SignalLabel.STRONG_POSITIVE)

    def test_bearish_signal(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=-0.5, velocity=-0.1, breadth=0.2),
            "6h": _make_snapshot("6h", composite=-0.5, velocity=-0.08, breadth=0.25),
        }
        sig = generate_signal("SPY", snapshots, primary_window="6h", velocity_window="1h")

        assert sig.score < 0
        assert sig.label in (SignalLabel.LEAN_NEGATIVE, SignalLabel.STRONG_NEGATIVE)

    def test_neutral_signal(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.0, velocity=0.0, breadth=0.5),
            "6h": _make_snapshot("6h", composite=0.0, velocity=0.0, breadth=0.5),
        }
        sig = generate_signal("SPY", snapshots, primary_window="6h", velocity_window="1h")

        assert sig.label == SignalLabel.NEUTRAL
        assert abs(sig.score) < 0.15

    def test_no_primary_window_returns_neutral(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.5, velocity=0.1, breadth=0.8),
        }
        sig = generate_signal("SPY", snapshots, primary_window="6h", velocity_window="1h")

        assert sig.label == SignalLabel.NEUTRAL
        assert sig.score == 0.0
        assert sig.headline_count == 0
        assert "no data" in sig.detail.get("reason", "")

    def test_no_velocity_window_uses_zero(self):
        snapshots = {
            "6h": _make_snapshot("6h", composite=0.3, velocity=0.05, breadth=0.6),
        }
        sig = generate_signal("SPY", snapshots, primary_window="6h", velocity_window="1h")

        assert sig.velocity == 0.0
        assert sig.score > 0


class TestScoreClamping:
    def test_score_clamped_to_one(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=1.0, velocity=1.0, breadth=1.0),
            "6h": _make_snapshot("6h", composite=1.0, velocity=0.5, breadth=1.0),
        }
        sig = generate_signal("SPY", snapshots)
        assert sig.score <= 1.0

    def test_score_clamped_to_negative_one(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=-1.0, velocity=-1.0, breadth=0.0),
            "6h": _make_snapshot("6h", composite=-1.0, velocity=-0.5, breadth=0.0),
        }
        sig = generate_signal("SPY", snapshots)
        assert sig.score >= -1.0


class TestSignalLabels:
    def test_strong_positive_threshold(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.6, velocity=0.2, breadth=0.9),
            "6h": _make_snapshot("6h", composite=0.6, velocity=0.15, breadth=0.85),
        }
        sig = generate_signal("SPY", snapshots)
        assert sig.label == SignalLabel.STRONG_POSITIVE

    def test_strong_negative_threshold(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=-0.6, velocity=-0.2, breadth=0.1),
            "6h": _make_snapshot("6h", composite=-0.6, velocity=-0.15, breadth=0.15),
        }
        sig = generate_signal("SPY", snapshots)
        assert sig.label == SignalLabel.STRONG_NEGATIVE


class TestSignalWeights:
    def test_custom_weights(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.0, velocity=0.2, breadth=0.5),
            "6h": _make_snapshot("6h", composite=0.0, velocity=0.1, breadth=0.5),
        }
        # All weight on velocity
        sig = generate_signal(
            "SPY", snapshots,
            weights={"composite": 0.0, "velocity": 1.0, "breadth": 0.0},
        )
        assert sig.score > 0

        # All weight on composite (which is 0)
        sig2 = generate_signal(
            "SPY", snapshots,
            weights={"composite": 1.0, "velocity": 0.0, "breadth": 0.0},
        )
        assert abs(sig2.score) < 0.01


class TestSignalDetail:
    def test_detail_contains_components(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.3, velocity=0.05, breadth=0.6),
            "6h": _make_snapshot("6h", composite=0.3, velocity=0.04, breadth=0.6),
        }
        sig = generate_signal("SPY", snapshots)

        assert "composite" in sig.detail
        assert "velocity_raw" in sig.detail
        assert "velocity_scaled" in sig.detail
        assert "breadth" in sig.detail
        assert "weights" in sig.detail
        assert "primary_window" in sig.detail

    def test_snapshots_preserved(self):
        snapshots = {
            "1h": _make_snapshot("1h"),
            "6h": _make_snapshot("6h"),
        }
        sig = generate_signal("SPY", snapshots)
        assert "1h" in sig.snapshots
        assert "6h" in sig.snapshots


class TestSignalActionable:
    def test_actionable_with_enough_data(self):
        snapshots = {
            "1h": _make_snapshot("1h", composite=0.5, count=10),
            "6h": _make_snapshot("6h", composite=0.5, count=15),
        }
        sig = generate_signal("SPY", snapshots)
        assert sig.headline_count >= 3
        assert sig.confidence > 0

    def test_empty_snapshots_not_actionable(self):
        sig = generate_signal("SPY", {}, primary_window="6h")
        assert not sig.is_actionable
