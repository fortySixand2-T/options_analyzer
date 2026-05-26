"""
Tests for sentiment scorer.

FinBERT requires torch (~2GB) which isn't in the dev image yet.
These tests fully mock torch and the model to verify scoring logic,
batch processing, and label assignment without the dependency.
"""

import pytest
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.sentiment.models import Headline, ScoredHeadline, SentimentLabel


def _make_headline(text="Market rallies on strong earnings", ticker="SPY"):
    return Headline(
        text=text,
        ticker=ticker,
        published_at=datetime(2025, 6, 1, 10, 0),
        source="test",
    )


class FakeTensor:
    """Minimal tensor mock that supports indexing like probs[j][k]."""

    def __init__(self, data):
        self.data = data

    def __getitem__(self, idx):
        item = self.data[idx]
        if isinstance(item, list):
            return FakeTensor(item)
        return item

    def __float__(self):
        if isinstance(self.data, (int, float)):
            return float(self.data)
        raise TypeError(f"Cannot convert {type(self.data)} to float")


def _fake_softmax(logits, dim=-1):
    """Simplified softmax for testing."""
    import math
    result = []
    for row in logits.data:
        exp_vals = [math.exp(x) for x in row]
        total = sum(exp_vals)
        result.append([e / total for e in exp_vals])
    return FakeTensor(result)


class FakeOutputs:
    def __init__(self, logits):
        self.logits = logits


@pytest.fixture
def mock_torch_and_model():
    """Mock torch, the model, and the tokenizer without importing torch."""
    fake_torch = MagicMock()
    fake_torch.no_grad.return_value.__enter__ = MagicMock()
    fake_torch.no_grad.return_value.__exit__ = MagicMock()
    fake_torch.softmax = _fake_softmax

    fake_tokenizer = MagicMock()
    fake_model = MagicMock()
    fake_model.eval = MagicMock()

    # Patch at module level so scorer.py can import torch
    with patch.dict(sys.modules, {"torch": fake_torch}), \
         patch("src.sentiment.scorer._model", fake_model), \
         patch("src.sentiment.scorer._tokenizer", fake_tokenizer):
        from src.sentiment.scorer import SentimentScorer
        yield SentimentScorer, fake_model, fake_tokenizer, fake_torch


def _setup_logits(mock_tuple, logits_data):
    """Configure the mock model to return specific logits."""
    SentimentScorer, model, tokenizer, torch_mock = mock_tuple
    logits = FakeTensor(logits_data)
    model.return_value = FakeOutputs(logits)
    return SentimentScorer


class TestScorerBatchEmpty:
    def test_empty_batch_returns_empty(self, mock_torch_and_model):
        SentimentScorer = mock_torch_and_model[0]
        scorer = SentimentScorer()
        assert scorer.score_batch([]) == []


class TestScorerLabeling:
    def test_positive_label(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[2.0, 0.1, 0.3]])
        results = Scorer(batch_size=32).score_batch([_make_headline("Stocks surge")])

        assert len(results) == 1
        assert results[0].label == SentimentLabel.POSITIVE
        assert results[0].positive > results[0].negative
        assert results[0].positive > results[0].neutral

    def test_negative_label(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[0.1, 2.5, 0.2]])
        results = Scorer(batch_size=32).score_batch([_make_headline("Market crashes")])

        assert results[0].label == SentimentLabel.NEGATIVE
        assert results[0].negative > results[0].positive

    def test_neutral_label(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[0.1, 0.2, 2.0]])
        results = Scorer(batch_size=32).score_batch([_make_headline("Fed holds")])

        assert results[0].label == SentimentLabel.NEUTRAL
        assert results[0].neutral > results[0].positive


class TestScorerBatch:
    def test_multiple_headlines(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [
            [2.0, 0.1, 0.3],
            [0.1, 2.5, 0.2],
            [0.3, 0.2, 2.0],
        ])
        headlines = [
            _make_headline("Earnings beat"),
            _make_headline("Sell-off"),
            _make_headline("Steady"),
        ]
        results = Scorer(batch_size=32).score_batch(headlines)

        assert len(results) == 3
        assert results[0].label == SentimentLabel.POSITIVE
        assert results[1].label == SentimentLabel.NEGATIVE
        assert results[2].label == SentimentLabel.NEUTRAL

    def test_scores_sum_to_one(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[1.5, 0.8, 0.3]])
        result = Scorer(batch_size=32).score_batch([_make_headline()])[0]

        total = result.positive + result.negative + result.neutral
        assert abs(total - 1.0) < 0.01

    def test_confidence_is_max(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[1.0, 2.0, 0.5]])
        result = Scorer(batch_size=32).score_batch([_make_headline()])[0]

        assert result.confidence == max(result.positive, result.negative, result.neutral)


class TestScorerMetadata:
    def test_model_version(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[1.0, 0.5, 0.3]])
        result = Scorer(batch_size=32).score_batch([_make_headline()])[0]
        assert result.model_version == "ProsusAI/finbert"

    def test_scored_at_set(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[1.0, 0.5, 0.3]])
        result = Scorer(batch_size=32).score_batch([_make_headline()])[0]
        assert result.scored_at is not None

    def test_headline_preserved(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [[1.0, 0.5, 0.3]])
        h = _make_headline("Special headline text")
        result = Scorer(batch_size=32).score_batch([h])[0]
        assert result.headline.text == "Special headline text"


class TestScoreTexts:
    def test_score_texts_convenience(self, mock_torch_and_model):
        Scorer = _setup_logits(mock_torch_and_model, [
            [1.0, 0.5, 0.3],
            [0.3, 1.0, 0.5],
        ])
        results = Scorer(batch_size=32).score_texts(["Good news", "Bad news"], ticker="QQQ")

        assert len(results) == 2
        assert results[0].headline.ticker == "QQQ"
        assert results[0].headline.source == "direct"
