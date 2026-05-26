"""
Tests for sentiment data models — Phase 1 validation.

Run: pytest tests/test_sentiment_models.py -v
"""

from datetime import datetime

from sentiment.models import (
    Headline,
    ScoredHeadline,
    SentimentLabel,
    SentimentSignal,
    SentimentSnapshot,
    SignalLabel,
)


class TestHeadline:
    def test_auto_collected_at(self):
        h = Headline(
            text="Test headline",
            ticker="SPY",
            published_at=datetime(2024, 6, 1),
            source="test",
        )
        assert h.collected_at is not None

    def test_explicit_collected_at(self):
        ts = datetime(2024, 1, 1)
        h = Headline(
            text="Test",
            ticker="SPY",
            published_at=datetime(2024, 6, 1),
            source="test",
            collected_at=ts,
        )
        assert h.collected_at == ts


class TestScoredHeadline:
    def test_signed_score_positive(self):
        h = Headline(text="Bullish", ticker="SPY",
                      published_at=datetime.utcnow(), source="test")
        s = ScoredHeadline(
            headline=h,
            positive=0.85, negative=0.05, neutral=0.10,
            confidence=0.85, label=SentimentLabel.POSITIVE,
        )
        assert s.signed_score == pytest.approx(0.80, abs=0.01)

    def test_signed_score_negative(self):
        h = Headline(text="Bearish", ticker="SPY",
                      published_at=datetime.utcnow(), source="test")
        s = ScoredHeadline(
            headline=h,
            positive=0.10, negative=0.75, neutral=0.15,
            confidence=0.75, label=SentimentLabel.NEGATIVE,
        )
        assert s.signed_score == pytest.approx(-0.65, abs=0.01)

    def test_auto_scored_at(self):
        h = Headline(text="Test", ticker="SPY",
                      published_at=datetime.utcnow(), source="test")
        s = ScoredHeadline(
            headline=h,
            positive=0.5, negative=0.3, neutral=0.2,
            confidence=0.5, label=SentimentLabel.POSITIVE,
        )
        assert s.scored_at is not None


class TestSentimentSignal:
    def test_is_actionable_enough_data(self):
        sig = SentimentSignal(
            ticker="SPY",
            label=SignalLabel.LEAN_POSITIVE,
            score=0.25,
            velocity=0.05,
            confidence=0.6,
            headline_count=10,
        )
        assert sig.is_actionable is True

    def test_not_actionable_low_count(self):
        sig = SentimentSignal(
            ticker="SPY",
            label=SignalLabel.LEAN_POSITIVE,
            score=0.25,
            velocity=0.05,
            confidence=0.6,
            headline_count=2,  # below minimum
        )
        assert sig.is_actionable is False

    def test_not_actionable_low_confidence(self):
        sig = SentimentSignal(
            ticker="SPY",
            label=SignalLabel.LEAN_POSITIVE,
            score=0.25,
            velocity=0.05,
            confidence=0.3,  # below threshold
            headline_count=10,
        )
        assert sig.is_actionable is False

    def test_auto_computed_at(self):
        sig = SentimentSignal(
            ticker="SPY",
            label=SignalLabel.NEUTRAL,
            score=0.0,
            velocity=0.0,
            confidence=0.0,
            headline_count=0,
        )
        assert sig.computed_at is not None


class TestSignalLabel:
    def test_label_values(self):
        assert SignalLabel.STRONG_POSITIVE.value == "STRONG_POSITIVE"
        assert SignalLabel.LEAN_NEGATIVE.value == "LEAN_NEGATIVE"
        assert SignalLabel.NEUTRAL.value == "NEUTRAL"


class TestSentimentLabel:
    def test_finbert_labels(self):
        assert SentimentLabel.POSITIVE.value == "positive"
        assert SentimentLabel.NEGATIVE.value == "negative"
        assert SentimentLabel.NEUTRAL.value == "neutral"


# Need pytest for approx
import pytest
