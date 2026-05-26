"""Sentiment API router — standalone sentiment signals, separate from scanner pipeline."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from src.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


@router.get("/signal/{ticker}")
def get_sentiment_signal(
    ticker: str,
    provider: str = Query("csv", description="News provider: csv, newsapi"),
    primary_window: str = Query("6h", description="Primary sentiment window"),
    velocity_window: str = Query("1h", description="Velocity window"),
    _user: dict = Depends(get_current_user),
):
    """Get current sentiment signal for a ticker.

    Returns FinBERT-scored headline aggregation with label, score, velocity.
    This is independent of the scanner pipeline.
    """
    try:
        from src.sentiment import get_sentiment
        signal = get_sentiment(
            ticker=ticker.upper(),
            provider_type=provider,
            primary_window=primary_window,
            velocity_window=velocity_window,
        )
        return {
            "ticker": signal.ticker,
            "label": signal.label.value,
            "score": signal.score,
            "velocity": signal.velocity,
            "confidence": signal.confidence,
            "headline_count": signal.headline_count,
            "is_actionable": signal.is_actionable,
            "computed_at": signal.computed_at.isoformat() if signal.computed_at else None,
            "snapshots": {
                k: {
                    "window": v.window,
                    "composite_score": v.composite_score,
                    "velocity": v.velocity,
                    "breadth": v.breadth,
                    "headline_count": v.headline_count,
                    "signal_label": v.signal_label.value,
                }
                for k, v in signal.snapshots.items()
            },
            "detail": signal.detail,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=f"Sentiment dependency not available: {e}",
        )
    except Exception as e:
        logger.exception("Sentiment signal failed for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/headlines/{ticker}")
def get_scored_headlines(
    ticker: str,
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(get_current_user),
):
    """Get recent scored headlines for a ticker from the sentiment store."""
    try:
        from src.sentiment.store import SentimentStore
        store = SentimentStore()
        rows = store.get_scored_headlines(ticker=ticker.upper())
        store.close()
        return {
            "ticker": ticker.upper(),
            "headlines": rows[:limit],
            "count": len(rows[:limit]),
        }
    except Exception as e:
        logger.exception("Failed to fetch headlines for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/snapshots/{ticker}")
def get_snapshot_history(
    ticker: str,
    window: str = Query("6h", description="Window: 1h, 6h, 24h"),
    limit: int = Query(100, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    """Get historical sentiment snapshots for charting."""
    try:
        from src.sentiment.store import SentimentStore
        store = SentimentStore()
        snapshots = store.get_snapshot_history(ticker=ticker.upper(), window=window, limit=limit)
        store.close()
        return {
            "ticker": ticker.upper(),
            "window": window,
            "snapshots": [
                {
                    "composite_score": s.composite_score,
                    "velocity": s.velocity,
                    "breadth": s.breadth,
                    "headline_count": s.headline_count,
                    "signal_label": s.signal_label.value,
                    "computed_at": s.computed_at.isoformat(),
                }
                for s in snapshots
            ],
            "count": len(snapshots),
        }
    except Exception as e:
        logger.exception("Failed to fetch snapshots for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
def get_sentiment_stats(_user: dict = Depends(get_current_user)):
    """Get overall sentiment store statistics."""
    try:
        from src.sentiment.store import SentimentStore
        store = SentimentStore()
        stats = {
            "total_headlines": store.headline_count(),
            "total_scored": store.scored_count(),
        }
        store.close()
        return stats
    except Exception as e:
        logger.exception("Failed to fetch sentiment stats")
        raise HTTPException(status_code=500, detail="Internal server error")
