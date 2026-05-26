"""
Sentiment aggregator.

Takes scored headlines from the store, computes rolling sentiment
per time window with exponential decay, derives velocity (sentiment
rate of change), and produces SentimentSnapshot objects.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .config import (
    DECAY_HALFLIFE_HOURS,
    MIN_CONFIDENCE,
    MIN_HEADLINES,
    WINDOWS,
)
from .models import SentimentSnapshot, SignalLabel
from .store import SentimentStore

logger = logging.getLogger(__name__)


def _exp_decay_weight(age_hours: float, halflife: float) -> float:
    """Exponential decay weight. Returns 1.0 for age=0, 0.5 for age=halflife."""
    if halflife <= 0:
        return 1.0
    return math.exp(-0.693147 * age_hours / halflife)  # ln(2) ≈ 0.693147


def _classify_score(score: float) -> SignalLabel:
    """Map composite score to signal label."""
    from .config import STRONG_THRESHOLD, LEAN_THRESHOLD
    if score >= STRONG_THRESHOLD:
        return SignalLabel.STRONG_POSITIVE
    if score >= LEAN_THRESHOLD:
        return SignalLabel.LEAN_POSITIVE
    if score <= -STRONG_THRESHOLD:
        return SignalLabel.STRONG_NEGATIVE
    if score <= -LEAN_THRESHOLD:
        return SignalLabel.LEAN_NEGATIVE
    return SignalLabel.NEUTRAL


class SentimentAggregator:
    """Compute rolling sentiment snapshots from scored headlines."""

    def __init__(
        self,
        store: SentimentStore,
        windows: Dict[str, float] = None,
        halflife: float = None,
        min_confidence: float = None,
        min_headlines: int = None,
    ):
        self.store = store
        self.windows = windows or WINDOWS
        self.halflife = halflife or DECAY_HALFLIFE_HOURS
        self.min_confidence = min_confidence or MIN_CONFIDENCE
        self.min_headlines = min_headlines or MIN_HEADLINES

    def aggregate(
        self,
        ticker: str,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, SentimentSnapshot]:
        """Compute sentiment snapshots for all windows.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        as_of : datetime, optional
            Compute as of this time (default: now). Used for backtesting.

        Returns
        -------
        Dict[str, SentimentSnapshot]
            Keyed by window name ('1h', '6h', '24h').
        """
        now = as_of or datetime.utcnow()
        snapshots: Dict[str, SentimentSnapshot] = {}

        for window_name, window_hours in self.windows.items():
            since = now - timedelta(hours=window_hours)

            # Fetch scored headlines from store
            rows = self.store.get_scored_headlines(
                ticker=ticker,
                since=since,
                until=now,
            )

            # Filter by confidence
            rows = [r for r in rows if r["confidence"] >= self.min_confidence]

            if len(rows) < self.min_headlines:
                # Not enough data — produce a neutral snapshot
                snapshots[window_name] = SentimentSnapshot(
                    ticker=ticker,
                    window=window_name,
                    composite_score=0.0,
                    velocity=None,
                    breadth=0.5,
                    headline_count=len(rows),
                    computed_at=now,
                    signal_label=SignalLabel.NEUTRAL,
                )
                continue

            # Compute weighted composite score
            total_weight = 0.0
            weighted_sum = 0.0
            positive_count = 0

            for row in rows:
                pub_dt = datetime.fromisoformat(row["published_at"])
                age_hours = (now - pub_dt).total_seconds() / 3600.0
                weight = _exp_decay_weight(age_hours, self.halflife)

                signed = row["positive"] - row["negative"]
                weighted_sum += signed * weight
                total_weight += weight

                if row["label"] == "positive":
                    positive_count += 1

            composite = weighted_sum / total_weight if total_weight > 0 else 0.0
            breadth = positive_count / len(rows) if rows else 0.5

            # Compute velocity against the prior snapshot of the same window
            velocity = self._compute_velocity(ticker, window_name, composite)

            label = _classify_score(composite)

            snapshot = SentimentSnapshot(
                ticker=ticker,
                window=window_name,
                composite_score=round(composite, 4),
                velocity=round(velocity, 4) if velocity is not None else None,
                breadth=round(breadth, 4),
                headline_count=len(rows),
                computed_at=now,
                signal_label=label,
            )
            snapshots[window_name] = snapshot

            # Persist snapshot
            self.store.save_snapshot(snapshot)

        return snapshots

    def _compute_velocity(
        self,
        ticker: str,
        window: str,
        current_score: float,
    ) -> Optional[float]:
        """Velocity = current composite - prior composite for the same window."""
        prior = self.store.get_latest_snapshot(ticker, window)
        if prior is None:
            return None
        return current_score - prior.composite_score

    def aggregate_from_scored(
        self,
        scored_rows: List[Dict],
        ticker: str,
        window_name: str,
        window_hours: float,
        as_of: datetime,
        prior_score: Optional[float] = None,
    ) -> SentimentSnapshot:
        """Aggregate from a pre-fetched list of scored rows.

        Used by the backtester to avoid repeated DB queries.
        """
        now = as_of
        cutoff = now - timedelta(hours=window_hours)

        rows = [
            r for r in scored_rows
            if r["confidence"] >= self.min_confidence
            and datetime.fromisoformat(r["published_at"]) >= cutoff
        ]

        if len(rows) < self.min_headlines:
            return SentimentSnapshot(
                ticker=ticker,
                window=window_name,
                composite_score=0.0,
                velocity=None,
                breadth=0.5,
                headline_count=len(rows),
                computed_at=now,
                signal_label=SignalLabel.NEUTRAL,
            )

        total_weight = 0.0
        weighted_sum = 0.0
        positive_count = 0

        for row in rows:
            pub_dt = datetime.fromisoformat(row["published_at"])
            age_hours = (now - pub_dt).total_seconds() / 3600.0
            weight = _exp_decay_weight(age_hours, self.halflife)

            signed = row["positive"] - row["negative"]
            weighted_sum += signed * weight
            total_weight += weight

            if row["label"] == "positive":
                positive_count += 1

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0
        breadth = positive_count / len(rows)

        velocity = None
        if prior_score is not None:
            velocity = composite - prior_score

        return SentimentSnapshot(
            ticker=ticker,
            window=window_name,
            composite_score=round(composite, 4),
            velocity=round(velocity, 4) if velocity is not None else None,
            breadth=round(breadth, 4),
            headline_count=len(rows),
            computed_at=now,
            signal_label=_classify_score(composite),
        )
