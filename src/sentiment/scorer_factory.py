"""
Scorer factory — returns the best available scorer.

Tries FinBERT first. If torch/transformers is missing or model load fails
(e.g. OOM), falls back to the keyword scorer transparently.
"""

import logging

logger = logging.getLogger(__name__)


def create_scorer(prefer_finbert: bool = True):
    """Return the best available scorer instance.

    Parameters
    ----------
    prefer_finbert : bool
        If True (default), attempt FinBERT first.
        If False, use keyword scorer directly.

    Returns
    -------
    SentimentScorer or KeywordScorer
        Both have the same interface: score_batch(), score_one(), score_texts().
    """
    if prefer_finbert:
        try:
            import torch
            from transformers import AutoTokenizer
            from .scorer import SentimentScorer
            logger.info("FinBERT scorer available (torch found)")
            return SentimentScorer()
        except ImportError:
            logger.warning("torch/transformers not installed — using keyword fallback")
        except Exception as e:
            logger.warning("FinBERT unavailable (%s) — using keyword fallback", e)

    from .keyword_scorer import KeywordScorer
    logger.info("Using keyword-based sentiment scorer")
    return KeywordScorer()
