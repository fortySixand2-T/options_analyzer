"""Tests for keyword-based sentiment scorer."""

import pytest
from datetime import datetime

from src.sentiment.keyword_scorer import KeywordScorer, _score_text
from src.sentiment.models import Headline, SentimentLabel


def _make_headline(text, ticker="TEST"):
    return Headline(
        text=text,
        ticker=ticker,
        published_at=datetime(2025, 6, 1, 10, 0),
        source="test",
    )


class TestScoreText:
    def test_positive_headline(self):
        pos, neg, neu = _score_text("Markets rally on strong earnings beat")
        assert pos > neg
        assert pos > neu

    def test_negative_headline(self):
        pos, neg, neu = _score_text("Stocks crash amid recession fears and layoffs")
        assert neg > pos
        assert neg > neu

    def test_neutral_headline(self):
        pos, neg, neu = _score_text("Company announces quarterly results today")
        assert neu > pos
        assert neu > neg

    def test_mixed_headline(self):
        pos, neg, neu = _score_text("Rally fades as recession fears grow")
        total = pos + neg + neu
        assert abs(total - 1.0) < 0.01

    def test_intensifiers_boost(self):
        _, neg_base, _ = _score_text("Stocks decline")
        _, neg_intense, _ = _score_text("Stocks sharply decline in massive selloff")
        assert neg_intense > neg_base

    def test_probabilities_sum_to_one(self):
        texts = [
            "Fed cuts rates dramatically",
            "Mixed signals from earnings",
            "Regular trading day",
            "",
        ]
        for text in texts:
            pos, neg, neu = _score_text(text)
            assert abs(pos + neg + neu - 1.0) < 0.01, f"Failed for: {text}"

    def test_empty_string(self):
        pos, neg, neu = _score_text("")
        assert neu > pos
        assert neu > neg


class TestKeywordScorer:
    def test_score_batch_empty(self):
        scorer = KeywordScorer()
        assert scorer.score_batch([]) == []

    def test_score_batch_returns_scored_headlines(self):
        scorer = KeywordScorer()
        headlines = [
            _make_headline("Markets surge on bullish outlook"),
            _make_headline("Stocks plunge on tariff fears"),
            _make_headline("Company reports quarterly results"),
        ]
        scored = scorer.score_batch(headlines)
        assert len(scored) == 3
        assert all(s.model_version == "keyword-v1" for s in scored)

    def test_positive_classified(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Rally surge gains bullish optimism"))
        assert scored.label == SentimentLabel.POSITIVE
        assert scored.positive > scored.negative

    def test_negative_classified(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Crash plunge losses bearish fears"))
        assert scored.label == SentimentLabel.NEGATIVE
        assert scored.negative > scored.positive

    def test_neutral_classified(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Company holds annual meeting"))
        assert scored.label == SentimentLabel.NEUTRAL

    def test_confidence_is_max_prob(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Strong rally in tech stocks"))
        assert scored.confidence == max(scored.positive, scored.negative, scored.neutral)

    def test_score_texts_convenience(self):
        scorer = KeywordScorer()
        scored = scorer.score_texts(["Bull market rally", "Bear market crash"], ticker="SPY")
        assert len(scored) == 2
        assert scored[0].headline.ticker == "SPY"
        assert scored[1].headline.ticker == "SPY"

    def test_scored_at_set(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Test headline"))
        assert scored.scored_at is not None

    def test_signed_score_property(self):
        scorer = KeywordScorer()
        scored = scorer.score_one(_make_headline("Markets rally strongly"))
        assert scored.signed_score == scored.positive - scored.negative


class TestScorerFactory:
    def test_factory_returns_keyword_when_no_torch(self):
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules, {"torch": None}):
            from src.sentiment.scorer_factory import create_scorer
            scorer = create_scorer(prefer_finbert=True)
            assert hasattr(scorer, 'MODEL_VERSION')
            assert scorer.MODEL_VERSION == "keyword-v1"

    def test_factory_keyword_when_explicit(self):
        from src.sentiment.scorer_factory import create_scorer
        scorer = create_scorer(prefer_finbert=False)
        assert hasattr(scorer, 'MODEL_VERSION')
        assert scorer.MODEL_VERSION == "keyword-v1"
