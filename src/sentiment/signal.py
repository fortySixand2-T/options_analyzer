"""
Sentiment signal generator.

Takes aggregated snapshots across windows and produces a single
SentimentSignal — the final pluggable output of the sentiment module.

The signal combines:
- Composite level (40%) — current sentiment score
- Velocity (40%)        — rate of sentiment change
- Breadth (20%)         — fraction of positive headlines vs total

These weights are configurable in config.py.
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from .config import SIGNAL_WEIGHTS, STRONG_THRESHOLD, LEAN_THRESHOLD
from .models import SentimentSignal, SentimentSnapshot, SignalLabel

logger = logging.getLogger(__name__)


def _classify_signal(score: float) -> SignalLabel:
    """Map final signal score to label."""
    if score >= STRONG_THRESHOLD:
        return SignalLabel.STRONG_POSITIVE
    if score >= LEAN_THRESHOLD:
        return SignalLabel.LEAN_POSITIVE
    if score <= -STRONG_THRESHOLD:
        return SignalLabel.STRONG_NEGATIVE
    if score <= -LEAN_THRESHOLD:
        return SignalLabel.LEAN_NEGATIVE
    return SignalLabel.NEUTRAL


def generate_signal(
    ticker: str,
    snapshots: Dict[str, SentimentSnapshot],
    primary_window: str = "6h",
    velocity_window: str = "1h",
    weights: Dict[str, float] = None,
) -> SentimentSignal:
    """Generate a single SentimentSignal from aggregated snapshots.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    snapshots : Dict[str, SentimentSnapshot]
        Keyed by window name ('1h', '6h', '24h').
    primary_window : str
        Which window's composite score to use as the primary level.
    velocity_window : str
        Which window's velocity to use (shorter = more responsive).
    weights : dict, optional
        Override signal composition weights.

    Returns
    -------
    SentimentSignal
    """
    w = weights or SIGNAL_WEIGHTS

    primary = snapshots.get(primary_window)
    velocity_snap = snapshots.get(velocity_window)

    if primary is None:
        # No data for primary window — return neutral
        return SentimentSignal(
            ticker=ticker,
            label=SignalLabel.NEUTRAL,
            score=0.0,
            velocity=0.0,
            confidence=0.0,
            headline_count=0,
            snapshots=snapshots,
            detail={"reason": f"no data for {primary_window} window"},
        )

    composite = primary.composite_score
    velocity = (velocity_snap.velocity if velocity_snap and velocity_snap.velocity is not None
                else 0.0)
    breadth = primary.breadth

    # Breadth divergence from 0.5 (neutral). Range: [-0.5, +0.5]
    breadth_signal = breadth - 0.5

    # Weighted combination
    # Velocity is already signed (positive = improving sentiment)
    # Clamp velocity contribution to [-1, 1] to prevent extreme outliers
    clamped_velocity = max(-1.0, min(1.0, velocity * 5.0))  # scale up since raw velocity is small

    final_score = (
        w.get("composite", 0.4) * composite +
        w.get("velocity", 0.4) * clamped_velocity +
        w.get("breadth", 0.2) * (breadth_signal * 2.0)  # scale to [-1, +1] range
    )

    # Clamp to [-1, +1]
    final_score = max(-1.0, min(1.0, final_score))

    # Total headline count across all windows (use the largest window)
    total_headlines = max(
        (s.headline_count for s in snapshots.values()),
        default=0,
    )

    # Average confidence (proxy from composite magnitude)
    avg_confidence = abs(composite)  # rough proxy

    label = _classify_signal(final_score)

    return SentimentSignal(
        ticker=ticker,
        label=label,
        score=round(final_score, 4),
        velocity=round(velocity, 4),
        confidence=round(avg_confidence, 4),
        headline_count=total_headlines,
        snapshots=snapshots,
        detail={
            "composite": round(composite, 4),
            "velocity_raw": round(velocity, 4),
            "velocity_scaled": round(clamped_velocity, 4),
            "breadth": round(breadth, 4),
            "breadth_signal": round(breadth_signal, 4),
            "primary_window": primary_window,
            "velocity_window": velocity_window,
            "weights": w,
        },
    )
