"""
FinBERT sentiment scorer.

Loads ProsusAI/finbert from HuggingFace and scores financial headlines.
Lazy model loading — the model is only downloaded/loaded on first call.
Batch processing for efficiency.

Dependencies: transformers, torch (CPU-only is sufficient).
"""

import logging
from datetime import datetime
from typing import List, Optional

from .models import Headline, ScoredHeadline, SentimentLabel

logger = logging.getLogger(__name__)

# Module-level model cache (singleton per process)
_model = None
_tokenizer = None


def _ensure_model():
    """Lazy-load FinBERT model and tokenizer."""
    global _model, _tokenizer
    if _model is not None:
        return

    from .config import FINBERT_MODEL

    logger.info("Loading FinBERT model: %s (first call, may download ~420MB)",
                FINBERT_MODEL)

    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        _tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
        _model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)
        _model.eval()  # inference mode
        logger.info("FinBERT loaded successfully")
    except ImportError as e:
        raise ImportError(
            "FinBERT requires 'transformers' and 'torch'. "
            "Install with: pip install transformers torch"
        ) from e
    except Exception as e:
        logger.error("Failed to load FinBERT: %s", e)
        raise


class SentimentScorer:
    """Score financial headlines using FinBERT.

    Usage:
        scorer = SentimentScorer()
        scored = scorer.score_batch(headlines)
    """

    def __init__(self, model_name: str = None, batch_size: int = None):
        from .config import FINBERT_MODEL, FINBERT_BATCH_SIZE, FINBERT_MAX_LENGTH
        self.model_name = model_name or FINBERT_MODEL
        self.batch_size = batch_size or FINBERT_BATCH_SIZE
        self.max_length = FINBERT_MAX_LENGTH

    def score_one(self, headline: Headline) -> ScoredHeadline:
        """Score a single headline."""
        return self.score_batch([headline])[0]

    def score_batch(self, headlines: List[Headline]) -> List[ScoredHeadline]:
        """Score a batch of headlines with FinBERT.

        Parameters
        ----------
        headlines : List[Headline]
            Raw headlines to score.

        Returns
        -------
        List[ScoredHeadline]
            Scored headlines in the same order as input.
        """
        if not headlines:
            return []

        _ensure_model()
        import torch

        texts = [h.text for h in headlines]
        results: List[ScoredHeadline] = []

        # Process in batches
        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]
            batch_headlines = headlines[i : i + self.batch_size]

            # Tokenize
            inputs = _tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )

            # Inference (no gradients needed)
            with torch.no_grad():
                outputs = _model(**inputs)

            # Softmax to get probabilities
            probs = torch.softmax(outputs.logits, dim=-1)

            # FinBERT label order: positive=0, negative=1, neutral=2
            for j, headline in enumerate(batch_headlines):
                pos = float(probs[j][0])
                neg = float(probs[j][1])
                neu = float(probs[j][2])
                confidence = max(pos, neg, neu)

                if pos >= neg and pos >= neu:
                    label = SentimentLabel.POSITIVE
                elif neg >= pos and neg >= neu:
                    label = SentimentLabel.NEGATIVE
                else:
                    label = SentimentLabel.NEUTRAL

                results.append(ScoredHeadline(
                    headline=headline,
                    positive=round(pos, 4),
                    negative=round(neg, 4),
                    neutral=round(neu, 4),
                    confidence=round(confidence, 4),
                    label=label,
                    model_version=self.model_name,
                ))

        logger.info("Scored %d headlines (%.1f%% positive, %.1f%% negative, %.1f%% neutral)",
                     len(results),
                     sum(1 for r in results if r.label == SentimentLabel.POSITIVE) / len(results) * 100,
                     sum(1 for r in results if r.label == SentimentLabel.NEGATIVE) / len(results) * 100,
                     sum(1 for r in results if r.label == SentimentLabel.NEUTRAL) / len(results) * 100)
        return results

    def score_texts(self, texts: List[str], ticker: str = "UNKNOWN") -> List[ScoredHeadline]:
        """Convenience: score raw text strings without creating Headline objects."""
        headlines = [
            Headline(
                text=t,
                ticker=ticker,
                published_at=datetime.utcnow(),
                source="direct",
            )
            for t in texts
        ]
        return self.score_batch(headlines)
