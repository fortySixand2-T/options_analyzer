"""
Tests for SentimentAggregator and generate_signal — Phase 3 validation.

These test the math without requiring FinBERT (uses pre-scored data in the store).

Run: pytest tests/test_sentiment_aggregator.py -v
"""

from datetime import datetime, timedelta

import pytest

from sentiment.aggregator import SentimentAggregator, _exp_decay_weight, _classify_score
from sentiment.models import (
    Headline,
    ScoredHeadline,
    SentimentLabel,
    SentimentSnapshot,
    SignalLabel,
)
from sentiment.signal import generate_signal
from sentiment.store import SentimentStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_agg.db")
    s = SentimentStore(db_path=db_path)
    yield s
    s.close()


def _insert_scored(store, ticker, text, published_at, pos, neg, neu):
    """Helper to insert a scored headline directly."""
    label = SentimentLabel.POSITIVE if pos > neg and pos > neu else (
        SentimentLabel.NEGATIVE if neg > pos and neg > neu else SentimentLabel.NEUTRAL
    )
    h = Headline(text=text, ticker=ticker, published_at=published_at, source="test")
    s = ScoredHeadline(
        headline=h,
        positive=pos, negative=neg, neutral=neu,
        confidence=max(pos, neg, neu),
        label=label,
    )
    store.save_scored([s])


class TestDecayWeight:
    def test_weight_at_zero(self):
        assert _exp_decay_weight(0.0, 4.0) == pytest.approx(1.0)

    def test_weight_at_halflife(self):
        assert _exp_decay_weight(4.0, 4.0) == pytest.approx(0.5, abs=0.01)

    def test_weight_decreases(self):
        w1 = _exp_decay_weight(1.0, 4.0)
        w2 = _exp_decay_weight(2.0, 4.0)
        w3 = _exp_decay_weight(3.0, 4.0)
        assert w1 > w2 > w3

    def test_zero_halflife(self):
        assert _exp_decay_weight(10.0, 0.0) == 1.0


class TestClassifyScore:
    def test_strong_positive(self):
        assert _classify_score(0.5) == SignalLabel.STRONG_POSITIVE

    def test_lean_positive(self):
        assert _classify_score(0.2) == SignalLabel.LEAN_POSITIVE

    def test_neutral(self):
        assert _classify_score(0.0) == SignalLabel.NEUTRAL
        assert _classify_score(0.1) == SignalLabel.NEUTRAL
        assert _classify_score(-0.1) == SignalLabel.NEUTRAL

    def test_lean_negative(self):
        assert _classify_score(-0.2) == SignalLabel.LEAN_NEGATIVE

    def test_strong_negative(self):
        assert _classify_score(-0.5) == SignalLabel.STRONG_NEGATIVE


class TestAggregator:
    def test_aggregate_bullish_headlines(self, store):
        now = datetime.utcnow()
        # Insert 5 positive headlines in the last hour
        for i in range(5):
            _insert_scored(
                store, "SPY",
                f"Market rallies on strong earnings #{i}",
                now - timedelta(minutes=10 * i),
                pos=0.85, neg=0.05, neu=0.10,
            )

        agg = SentimentAggregator(store=store, min_headlines=3)
        snapshots = agg.aggregate("SPY", as_of=now)

        # 1h window should show positive sentiment
        snap_1h = snapshots.get("1h")
        assert snap_1h is not None
        assert snap_1h.composite_score > 0.5
        assert snap_1h.signal_label in (SignalLabel.STRONG_POSITIVE, SignalLabel.LEAN_POSITIVE)
        assert snap_1h.headline_count >= 4  # 4-5 depending on boundary
        assert snap_1h.breadth == 1.0  # all positive

    def test_aggregate_bearish_headlines(self, store):
        now = datetime.utcnow()
        for i in range(4):
            _insert_scored(
                store, "QQQ",
                f"Tech stocks plunge on regulation fears #{i}",
                now - timedelta(minutes=15 * i),
                pos=0.05, neg=0.80, neu=0.15,
            )

        agg = SentimentAggregator(store=store, min_headlines=3)
        snapshots = agg.aggregate("QQQ", as_of=now)

        snap_1h = snapshots.get("1h")
        assert snap_1h is not None
        assert snap_1h.composite_score < -0.5
        assert snap_1h.signal_label in (SignalLabel.STRONG_NEGATIVE, SignalLabel.LEAN_NEGATIVE)
        assert snap_1h.breadth == 0.0  # none positive

    def test_aggregate_mixed_headlines(self, store):
        now = datetime.utcnow()
        # 3 positive, 2 negative
        for i in range(3):
            _insert_scored(store, "SPY", f"Good news #{i}",
                           now - timedelta(minutes=5 * i),
                           pos=0.70, neg=0.10, neu=0.20)
        for i in range(2):
            _insert_scored(store, "SPY", f"Bad news #{i}",
                           now - timedelta(minutes=5 * (i + 3)),
                           pos=0.10, neg=0.70, neu=0.20)

        agg = SentimentAggregator(store=store, min_headlines=3)
        snapshots = agg.aggregate("SPY", as_of=now)

        snap_1h = snapshots.get("1h")
        assert snap_1h is not None
        # Should be slightly positive (3 vs 2, with recency favoring the positive ones)
        assert snap_1h.composite_score > 0
        assert snap_1h.breadth == pytest.approx(0.6, abs=0.01)  # 3/5

    def test_not_enough_headlines_returns_neutral(self, store):
        now = datetime.utcnow()
        _insert_scored(store, "IWM", "Single headline",
                       now - timedelta(minutes=5),
                       pos=0.90, neg=0.05, neu=0.05)

        agg = SentimentAggregator(store=store, min_headlines=3)
        snapshots = agg.aggregate("IWM", as_of=now)

        snap_1h = snapshots.get("1h")
        assert snap_1h is not None
        assert snap_1h.composite_score == 0.0
        assert snap_1h.signal_label == SignalLabel.NEUTRAL

    def test_velocity_computation(self, store):
        now = datetime.utcnow()

        # Save a prior snapshot
        prior = SentimentSnapshot(
            ticker="SPY", window="1h",
            composite_score=0.1, velocity=None,
            breadth=0.5, headline_count=5,
            computed_at=now - timedelta(hours=1),
            signal_label=SignalLabel.NEUTRAL,
        )
        store.save_snapshot(prior)

        # Insert positive headlines (should produce higher composite than 0.1)
        for i in range(5):
            _insert_scored(store, "SPY", f"Bullish #{i}",
                           now - timedelta(minutes=5 * i),
                           pos=0.80, neg=0.05, neu=0.15)

        agg = SentimentAggregator(store=store, min_headlines=3)
        snapshots = agg.aggregate("SPY", as_of=now)

        snap_1h = snapshots.get("1h")
        assert snap_1h is not None
        assert snap_1h.velocity is not None
        # Velocity should be positive (improved from 0.1)
        assert snap_1h.velocity > 0

    def test_confidence_filter(self, store):
        now = datetime.utcnow()
        # Insert 5 low-confidence headlines
        for i in range(5):
            _insert_scored(store, "SPY", f"Uncertain #{i}",
                           now - timedelta(minutes=5 * i),
                           pos=0.35, neg=0.33, neu=0.32)

        agg = SentimentAggregator(store=store, min_headlines=3, min_confidence=0.5)
        snapshots = agg.aggregate("SPY", as_of=now)

        snap_1h = snapshots.get("1h")
        # All headlines have confidence 0.35 < 0.5, so filtered out
        assert snap_1h.headline_count == 0
        assert snap_1h.signal_label == SignalLabel.NEUTRAL


class TestSignalGeneration:
    def test_generate_bullish_signal(self):
        now = datetime.utcnow()
        snapshots = {
            "1h": SentimentSnapshot(
                ticker="SPY", window="1h",
                composite_score=0.6, velocity=0.15,
                breadth=0.8, headline_count=10,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
            "6h": SentimentSnapshot(
                ticker="SPY", window="6h",
                composite_score=0.5, velocity=0.10,
                breadth=0.7, headline_count=25,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
            "24h": SentimentSnapshot(
                ticker="SPY", window="24h",
                composite_score=0.3, velocity=0.05,
                breadth=0.6, headline_count=50,
                computed_at=now,
                signal_label=SignalLabel.LEAN_POSITIVE,
            ),
        }

        signal = generate_signal("SPY", snapshots)
        assert signal.label in (SignalLabel.STRONG_POSITIVE, SignalLabel.LEAN_POSITIVE)
        assert signal.score > 0
        assert signal.ticker == "SPY"
        assert signal.headline_count > 0

    def test_generate_neutral_no_data(self):
        signal = generate_signal("SPY", {})
        assert signal.label == SignalLabel.NEUTRAL
        assert signal.score == 0.0

    def test_signal_is_actionable(self):
        now = datetime.utcnow()
        snapshots = {
            "6h": SentimentSnapshot(
                ticker="SPY", window="6h",
                composite_score=0.6, velocity=None,
                breadth=0.7, headline_count=15,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
            "1h": SentimentSnapshot(
                ticker="SPY", window="1h",
                composite_score=0.7, velocity=0.1,
                breadth=0.8, headline_count=8,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
        }
        signal = generate_signal("SPY", snapshots)
        assert signal.is_actionable is True

    def test_signal_score_clamped(self):
        """Signal score should be clamped to [-1, +1]."""
        now = datetime.utcnow()
        # Extreme values
        snapshots = {
            "6h": SentimentSnapshot(
                ticker="SPY", window="6h",
                composite_score=0.99, velocity=None,
                breadth=0.99, headline_count=50,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
            "1h": SentimentSnapshot(
                ticker="SPY", window="1h",
                composite_score=0.99, velocity=0.5,
                breadth=0.99, headline_count=20,
                computed_at=now,
                signal_label=SignalLabel.STRONG_POSITIVE,
            ),
        }
        signal = generate_signal("SPY", snapshots)
        assert -1.0 <= signal.score <= 1.0
