"""Tests for sentiment pipeline with keyword fallback scorer.

Validates the full pipeline works without torch/FinBERT:
CSV provider → keyword scorer → aggregator → signal.
"""

import os
import tempfile
import pytest
from datetime import datetime, timedelta

from src.sentiment.keyword_scorer import KeywordScorer
from src.sentiment.models import Headline, SentimentLabel, SignalLabel
from src.sentiment.store import SentimentStore
from src.sentiment.aggregator import SentimentAggregator
from src.sentiment.signal import generate_signal


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def store(tmp_db):
    s = SentimentStore(db_path=tmp_db)
    yield s
    s.close()


def _make_headlines(texts, ticker="MACRO", base_time=None):
    base = base_time or datetime.utcnow()
    return [
        Headline(
            text=t,
            ticker=ticker,
            published_at=base - timedelta(minutes=i * 10),
            source="test",
        )
        for i, t in enumerate(texts)
    ]


class TestFullPipelineKeywordFallback:
    def test_positive_signal_from_bullish_headlines(self, store):
        headlines = _make_headlines([
            "Markets surge on strong earnings rally",
            "Bull market gains momentum with record highs",
            "Tech stocks rally as optimism grows",
            "S&P beats expectations with strong growth",
            "Recovery continues with bullish momentum",
        ])
        scorer = KeywordScorer()
        scored = scorer.score_batch(headlines)
        store.save_scored(scored)

        agg = SentimentAggregator(store=store, min_headlines=2)
        snapshots = agg.aggregate("MACRO")
        signal = generate_signal("MACRO", snapshots)

        assert signal.score > 0
        assert signal.label in (SignalLabel.LEAN_POSITIVE, SignalLabel.STRONG_POSITIVE)
        assert signal.headline_count >= 5

    def test_negative_signal_from_bearish_headlines(self, store):
        headlines = _make_headlines([
            "Stocks crash amid recession fears",
            "Market plunges on tariff concerns and layoffs",
            "Bear market selloff deepens with losses",
            "Economy shows weakness with declining growth",
            "Investors fear default and bankruptcy risks",
        ])
        scorer = KeywordScorer()
        scored = scorer.score_batch(headlines)
        store.save_scored(scored)

        agg = SentimentAggregator(store=store, min_headlines=2)
        snapshots = agg.aggregate("MACRO")
        signal = generate_signal("MACRO", snapshots)

        assert signal.score < 0
        assert signal.label in (SignalLabel.LEAN_NEGATIVE, SignalLabel.STRONG_NEGATIVE)

    def test_neutral_signal_from_mixed_headlines(self, store):
        headlines = _make_headlines([
            "Company announces quarterly results today",
            "Markets see regular trading day",
            "Investors await upcoming meeting",
            "Earnings season begins next week",
        ])
        scorer = KeywordScorer()
        scored = scorer.score_batch(headlines)
        store.save_scored(scored)

        agg = SentimentAggregator(store=store, min_headlines=2)
        snapshots = agg.aggregate("MACRO")
        signal = generate_signal("MACRO", snapshots)

        assert -0.3 < signal.score < 0.3

    def test_empty_headlines_give_neutral(self, store):
        scorer = KeywordScorer()
        scored = scorer.score_batch([])
        assert scored == []

        agg = SentimentAggregator(store=store, min_headlines=2)
        snapshots = agg.aggregate("MACRO")
        signal = generate_signal("MACRO", snapshots)

        assert signal.score == 0.0
        assert signal.label == SignalLabel.NEUTRAL

    def test_scored_headlines_persisted(self, store):
        headlines = _make_headlines(["Markets surge with strong rally gains"])
        scorer = KeywordScorer()
        scored = scorer.score_batch(headlines)
        assert scored[0].label == SentimentLabel.POSITIVE
        store.save_scored(scored)

        rows = store.get_scored_headlines("MACRO", model_version="keyword-v1")
        assert len(rows) == 1
        assert rows[0]["label"] == "positive"

    def test_snapshots_persisted_after_aggregate(self, store):
        headlines = _make_headlines([
            "Strong rally in markets",
            "Bull market continues higher",
            "Gains across all sectors",
        ])
        scorer = KeywordScorer()
        scored = scorer.score_batch(headlines)
        store.save_scored(scored)

        agg = SentimentAggregator(store=store, min_headlines=2)
        agg.aggregate("MACRO")

        snap = store.get_latest_snapshot("MACRO", "1h")
        assert snap is not None
        assert snap.headline_count >= 2

    def test_velocity_computed_on_second_run(self, store):
        base = datetime.utcnow()
        h1 = _make_headlines(
            ["Markets rally", "Strong gains today", "Bull run continues"],
            base_time=base - timedelta(hours=1),
        )
        scorer = KeywordScorer()
        store.save_scored(scorer.score_batch(h1))

        agg = SentimentAggregator(store=store, min_headlines=2)
        agg.aggregate("MACRO", as_of=base - timedelta(hours=1))

        h2 = _make_headlines(
            ["Crash fears grow", "Selloff deepens", "Bear market warning"],
            base_time=base,
        )
        store.save_scored(scorer.score_batch(h2))
        snapshots = agg.aggregate("MACRO", as_of=base)

        has_velocity = any(
            s.velocity is not None for s in snapshots.values()
        )
        assert has_velocity
