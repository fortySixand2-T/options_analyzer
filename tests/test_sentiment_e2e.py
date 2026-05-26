"""
End-to-end sentiment pipeline test.

Runs the full pipeline: CSV → FinBERT scoring → aggregation → signal generation.
Uses a small sample dataset and real FinBERT (downloads ~420MB model on first run).

These tests require sufficient Docker memory (4GB+) and are skipped by default.
Run explicitly with: pytest tests/test_sentiment_e2e.py -m e2e
"""

import os
import tempfile
import pytest

from src.sentiment.models import SignalLabel, SentimentLabel
from src.sentiment.providers.csv_provider import CSVProvider
from src.sentiment.aggregator import SentimentAggregator
from src.sentiment.signal import generate_signal
from src.sentiment.store import SentimentStore


SAMPLE_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "headlines_sample.csv",
)

HAS_CSV = os.path.exists(SAMPLE_CSV)

# FinBERT needs ~1.5GB free memory (model + torch runtime)
try:
    import psutil
    HAS_ENOUGH_MEMORY = psutil.virtual_memory().available > 2 * 1024**3
except ImportError:
    HAS_ENOUGH_MEMORY = True  # assume OK if psutil not installed


def _can_load_finbert():
    try:
        from src.sentiment.scorer import SentimentScorer
        scorer = SentimentScorer(batch_size=1)
        return True
    except Exception:
        return False


@pytest.fixture
def tmp_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = SentimentStore(db_path=db_path)
    yield store
    store.close()
    os.unlink(db_path)


@pytest.mark.skipif(not HAS_CSV, reason="Sample headlines CSV not found")
class TestCSVPipeline:
    """Tests that work without FinBERT — just CSV + aggregation."""

    def test_csv_loads(self):
        provider = CSVProvider(csv_path=SAMPLE_CSV, default_ticker="MACRO")
        headlines = provider.fetch_headlines("MACRO", limit=999)
        assert len(headlines) > 0
        assert all(h.ticker == "MACRO" for h in headlines)

    def test_csv_date_range(self):
        provider = CSVProvider(csv_path=SAMPLE_CSV, default_ticker="MACRO")
        start, end = provider.get_date_range()
        assert start is not None
        assert end is not None
        assert start < end


@pytest.mark.skipif(not HAS_CSV, reason="Sample headlines CSV not found")
@pytest.mark.skipif(not HAS_ENOUGH_MEMORY, reason="Not enough memory for FinBERT")
class TestFinBERTPipeline:
    """Full pipeline tests that require FinBERT model download.

    These need 4GB+ Docker memory. Skip in CI or low-memory environments.
    """

    def test_score_small_batch(self, tmp_store):
        from src.sentiment.scorer import SentimentScorer

        provider = CSVProvider(csv_path=SAMPLE_CSV, default_ticker="MACRO")
        headlines = provider.fetch_headlines("MACRO", limit=3)

        scorer = SentimentScorer(batch_size=1)
        scored = scorer.score_batch(headlines)

        assert len(scored) == len(headlines)
        for s in scored:
            assert abs(s.positive + s.negative + s.neutral - 1.0) < 0.01
            assert s.confidence == max(s.positive, s.negative, s.neutral)
            assert s.label in list(SentimentLabel)

        tmp_store.save_scored(scored)
        assert tmp_store.scored_count("MACRO") == len(scored)

    def test_full_pipeline(self, tmp_store):
        from src.sentiment.scorer import SentimentScorer

        provider = CSVProvider(csv_path=SAMPLE_CSV, default_ticker="MACRO")
        headlines = provider.fetch_headlines("MACRO", limit=20)

        scorer = SentimentScorer(batch_size=4)
        scored = scorer.score_batch(headlines)
        tmp_store.save_scored(scored)

        aggregator = SentimentAggregator(store=tmp_store)
        date_range = provider.get_date_range()
        snapshots = aggregator.aggregate("MACRO", as_of=date_range[1])

        assert len(snapshots) > 0

        signal = generate_signal("MACRO", snapshots)
        assert signal.ticker == "MACRO"
        assert signal.label in list(SignalLabel)
        assert -1.0 <= signal.score <= 1.0
