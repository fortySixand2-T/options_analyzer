"""
Keyword-based sentiment scorer — lightweight fallback when FinBERT is unavailable.

Uses a curated financial-sentiment lexicon to approximate headline sentiment.
No torch/transformers dependency. Same output interface as SentimentScorer.
"""

import logging
from datetime import datetime
from typing import List

from .models import Headline, ScoredHeadline, SentimentLabel

logger = logging.getLogger(__name__)

POSITIVE_WORDS = frozenset([
    "rally", "rallies", "surge", "surges", "soar", "soars", "gain", "gains",
    "jump", "jumps", "rise", "rises", "bull", "bullish", "upbeat", "optimism",
    "beat", "beats", "exceed", "exceeds", "outperform", "upgrade", "upgrades",
    "recovery", "recover", "rebounds", "rebound", "strong", "strength",
    "record high", "breakout", "boost", "profit", "profitable", "growth",
    "positive", "buy", "accumulate", "overweight", "dovish", "easing",
    "stimulus", "expansion", "hiring", "boom",
])

NEGATIVE_WORDS = frozenset([
    "crash", "crashes", "plunge", "plunges", "tank", "tanks", "drop", "drops",
    "fall", "falls", "decline", "declines", "bear", "bearish", "sell-off",
    "selloff", "slump", "tumble", "tumbles", "miss", "misses", "downgrade",
    "downgrades", "underperform", "recession", "layoff", "layoffs", "cut",
    "cuts", "loss", "losses", "weak", "weakness", "fear", "fears",
    "default", "bankruptcy", "hawkish", "tightening", "inflation",
    "tariff", "tariffs", "sanctions", "investigation", "fraud",
    "warning", "risk", "debt", "deficit", "contraction",
])

INTENSIFIERS = frozenset([
    "very", "extremely", "sharply", "significantly", "dramatically",
    "massive", "huge", "major", "severe", "deep",
])

def _count_matches(text_lower: str, lexicon: frozenset) -> int:
    """Count how many lexicon entries appear in the text."""
    count = 0
    for term in lexicon:
        if term in text_lower:
            count += 1
    return count


def _score_text(text: str) -> tuple:
    """Score a headline text using keyword matching.

    Returns (positive, negative, neutral) probabilities summing to ~1.0.
    """
    lower = text.lower()

    pos_count = _count_matches(lower, POSITIVE_WORDS)
    neg_count = _count_matches(lower, NEGATIVE_WORDS)
    int_count = _count_matches(lower, INTENSIFIERS)

    intensity = 1.0 + 0.2 * int_count

    pos_score = pos_count * intensity
    neg_score = neg_count * intensity

    total = pos_score + neg_score
    if total == 0:
        return (0.15, 0.15, 0.70)

    strength = min(total / 2.5, 1.0)

    if pos_score > neg_score:
        ratio = pos_score / total
        p = 0.35 + 0.45 * ratio * strength
        n = 0.05 * (1 - ratio) * strength
        u = max(0.05, 1.0 - p - n)
    elif neg_score > pos_score:
        ratio = neg_score / total
        n = 0.35 + 0.45 * ratio * strength
        p = 0.05 * (1 - ratio) * strength
        u = max(0.05, 1.0 - p - n)
    else:
        p = 0.30 * strength
        n = 0.30 * strength
        u = max(0.05, 1.0 - p - n)

    total_prob = p + n + u
    return (p / total_prob, n / total_prob, u / total_prob)


class KeywordScorer:
    """Score financial headlines using keyword matching.

    Drop-in replacement for SentimentScorer when FinBERT is unavailable.
    """

    MODEL_VERSION = "keyword-v1"

    def __init__(self, batch_size: int = None):
        self.batch_size = batch_size or 64

    def score_one(self, headline: Headline) -> ScoredHeadline:
        return self.score_batch([headline])[0]

    def score_batch(self, headlines: List[Headline]) -> List[ScoredHeadline]:
        if not headlines:
            return []

        results: List[ScoredHeadline] = []

        for headline in headlines:
            pos, neg, neu = _score_text(headline.text)
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
                model_version=self.MODEL_VERSION,
            ))

        pos_count = sum(1 for r in results if r.label == SentimentLabel.POSITIVE)
        neg_count = sum(1 for r in results if r.label == SentimentLabel.NEGATIVE)
        neu_count = sum(1 for r in results if r.label == SentimentLabel.NEUTRAL)
        logger.info("Keyword-scored %d headlines (%.1f%% pos, %.1f%% neg, %.1f%% neu)",
                     len(results),
                     pos_count / len(results) * 100,
                     neg_count / len(results) * 100,
                     neu_count / len(results) * 100)
        return results

    def score_texts(self, texts: List[str], ticker: str = "UNKNOWN") -> List[ScoredHeadline]:
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
