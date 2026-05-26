"""
Tests for SentimentStore — Phase 1 validation.

Run: pytest tests/test_sentiment_store.py -v
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from sentiment.models import (
    Headline,
    ScoredHeadline,
    SentimentLabel,
    SentimentSnapshot,
    SignalLabel,
)
from sentiment.store import SentimentStore


@pytest.fixture
def store(tmp_path):
    """Create a fresh store with a temp database."""
    db_path = str(tmp_path / "test_sentiment.db")
    s = SentimentStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture
def sample_headlines():
    now = datetime.utcnow()
    return [
        Headline(
            text="S&P 500 rallies to new high on strong earnings",
            ticker="SPY",
            published_at=now - timedelta(hours=2),
            source="test",
        ),
        Headline(
            text="Fed signals rate cut may come sooner than expected",
            ticker="MACRO",
            published_at=now - timedelta(hours=1),
            source="test",
        ),
        Headline(
            text="Tech stocks sell off on trade war fears",
            ticker="QQQ",
            published_at=now - timedelta(minutes=30),
            source="test",
        ),
    ]


class TestStoreSchema:
    def test_creates_tables(self, store):
        """Schema should be created on first connection."""
        conn = store._ensure_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "headlines" in table_names
        assert "scored_headlines" in table_names
        assert "sentiment_snapshots" in table_names

    def test_idempotent_schema(self, store):
        """Calling _ensure_conn twice should not fail."""
        store._ensure_conn()
        store.close()
        store._ensure_conn()  # should not raise


class TestHeadlines:
    def test_save_headlines(self, store, sample_headlines):
        store.save_headlines(sample_headlines)
        count = store.headline_count()
        assert count == 3

    def test_save_deduplicates(self, store, sample_headlines):
        store.save_headlines(sample_headlines)
        store.save_headlines(sample_headlines)  # same headlines again
        count = store.headline_count()
        assert count == 3  # no duplicates

    def test_headline_count_by_ticker(self, store, sample_headlines):
        store.save_headlines(sample_headlines)
        assert store.headline_count("SPY") == 1
        assert store.headline_count("MACRO") == 1
        assert store.headline_count("QQQ") == 1
        assert store.headline_count("AAPL") == 0

    def test_get_headline_id(self, store, sample_headlines):
        store.save_headlines(sample_headlines)
        h_id = store.get_headline_id(sample_headlines[0])
        assert h_id is not None
        assert isinstance(h_id, int)

    def test_get_headline_id_missing(self, store):
        h = Headline(
            text="nonexistent headline",
            ticker="XXX",
            published_at=datetime.utcnow(),
            source="test",
        )
        assert store.get_headline_id(h) is None


class TestScoredHeadlines:
    def test_save_scored(self, store, sample_headlines):
        scored = [
            ScoredHeadline(
                headline=sample_headlines[0],
                positive=0.85,
                negative=0.05,
                neutral=0.10,
                confidence=0.85,
                label=SentimentLabel.POSITIVE,
            ),
            ScoredHeadline(
                headline=sample_headlines[2],
                positive=0.10,
                negative=0.75,
                neutral=0.15,
                confidence=0.75,
                label=SentimentLabel.NEGATIVE,
            ),
        ]
        inserted = store.save_scored(scored)
        assert inserted == 2

    def test_get_scored_headlines(self, store, sample_headlines):
        scored = [
            ScoredHeadline(
                headline=sample_headlines[0],
                positive=0.85,
                negative=0.05,
                neutral=0.10,
                confidence=0.85,
                label=SentimentLabel.POSITIVE,
            ),
        ]
        store.save_scored(scored)
        rows = store.get_scored_headlines("SPY")
        assert len(rows) == 1
        assert rows[0]["positive"] == 0.85
        assert rows[0]["label"] == "positive"

    def test_get_scored_with_time_filter(self, store, sample_headlines):
        scored = [
            ScoredHeadline(
                headline=h,
                positive=0.5,
                negative=0.3,
                neutral=0.2,
                confidence=0.5,
                label=SentimentLabel.POSITIVE,
            )
            for h in sample_headlines
        ]
        store.save_scored(scored)

        now = datetime.utcnow()
        # Only headlines in last hour
        rows = store.get_scored_headlines(
            "MACRO",
            since=now - timedelta(hours=1, minutes=1),
        )
        assert len(rows) == 1

    def test_scored_count(self, store, sample_headlines):
        scored = [
            ScoredHeadline(
                headline=sample_headlines[0],
                positive=0.8,
                negative=0.1,
                neutral=0.1,
                confidence=0.8,
                label=SentimentLabel.POSITIVE,
            ),
        ]
        store.save_scored(scored)
        assert store.scored_count() == 1
        assert store.scored_count("SPY") == 1
        assert store.scored_count("QQQ") == 0


class TestSentimentSnapshots:
    def test_save_and_get_snapshot(self, store):
        now = datetime.utcnow()
        snapshot = SentimentSnapshot(
            ticker="SPY",
            window="6h",
            composite_score=0.35,
            velocity=0.08,
            breadth=0.65,
            headline_count=12,
            computed_at=now,
            signal_label=SignalLabel.LEAN_POSITIVE,
        )
        store.save_snapshot(snapshot)

        retrieved = store.get_latest_snapshot("SPY", "6h")
        assert retrieved is not None
        assert retrieved.composite_score == 0.35
        assert retrieved.velocity == 0.08
        assert retrieved.signal_label == SignalLabel.LEAN_POSITIVE

    def test_get_latest_returns_most_recent(self, store):
        now = datetime.utcnow()
        for i in range(3):
            store.save_snapshot(SentimentSnapshot(
                ticker="SPY",
                window="6h",
                composite_score=0.1 * (i + 1),
                velocity=None,
                breadth=0.5,
                headline_count=5,
                computed_at=now - timedelta(hours=3 - i),
                signal_label=SignalLabel.NEUTRAL,
            ))

        latest = store.get_latest_snapshot("SPY", "6h")
        assert latest is not None
        assert latest.composite_score == pytest.approx(0.3, abs=1e-9)  # most recent

    def test_snapshot_history(self, store):
        now = datetime.utcnow()
        for i in range(5):
            store.save_snapshot(SentimentSnapshot(
                ticker="QQQ",
                window="24h",
                composite_score=0.1 * i,
                velocity=None,
                breadth=0.5,
                headline_count=10,
                computed_at=now - timedelta(hours=i),
                signal_label=SignalLabel.NEUTRAL,
            ))

        history = store.get_snapshot_history("QQQ", "24h", limit=3)
        assert len(history) == 3

    def test_get_latest_missing(self, store):
        assert store.get_latest_snapshot("XXX", "1h") is None
