"""
Sentiment module data models.

All dataclasses used across the sentiment pipeline — from raw headlines
through scoring, aggregation, and final signal output.

Zero imports from other src/ packages.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# ── Enums ──────────────────────────────────────────────────────────────────────

class SentimentLabel(str, Enum):
    """FinBERT output label for a single headline."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalLabel(str, Enum):
    """Aggregate sentiment signal — matches bias_detector label convention."""
    STRONG_POSITIVE = "STRONG_POSITIVE"
    LEAN_POSITIVE = "LEAN_POSITIVE"
    NEUTRAL = "NEUTRAL"
    LEAN_NEGATIVE = "LEAN_NEGATIVE"
    STRONG_NEGATIVE = "STRONG_NEGATIVE"


# ── Raw headline ───────────────────────────────────────────────────────────────

@dataclass
class Headline:
    """Raw headline from a news provider."""
    text: str
    ticker: str                     # mapped ticker or 'MACRO' for index-level
    published_at: datetime
    source: str                     # provider name: 'newsapi', 'benzinga', 'csv'
    url: Optional[str] = None
    collected_at: Optional[datetime] = None

    def __post_init__(self):
        if self.collected_at is None:
            self.collected_at = datetime.utcnow()


# ── Scored headline ────────────────────────────────────────────────────────────

@dataclass
class ScoredHeadline:
    """Headline after FinBERT scoring."""
    headline: Headline

    # FinBERT softmax outputs (sum to 1.0)
    positive: float
    negative: float
    neutral: float

    # Derived
    confidence: float               # max(positive, negative, neutral)
    label: SentimentLabel           # argmax of the three scores

    # Metadata
    model_version: str = "ProsusAI/finbert"
    scored_at: Optional[datetime] = None

    def __post_init__(self):
        if self.scored_at is None:
            self.scored_at = datetime.utcnow()

    @property
    def signed_score(self) -> float:
        """Signed sentiment: positive minus negative. Range [-1, +1]."""
        return self.positive - self.negative


# ── Aggregated snapshot ────────────────────────────────────────────────────────

@dataclass
class SentimentSnapshot:
    """Aggregated sentiment for one ticker over one time window."""
    ticker: str
    window: str                     # '1h', '6h', '24h'
    composite_score: float          # weighted mean of signed_score, range [-1, +1]
    velocity: Optional[float]       # change vs prior window (None if no prior)
    breadth: float                  # fraction of headlines that are positive
    headline_count: int
    computed_at: datetime
    signal_label: SignalLabel


# ── Final signal ───────────────────────────────────────────────────────────────

@dataclass
class SentimentSignal:
    """Final pluggable output — the interface consumed by external systems.

    Mirrors the pattern of BiasResult and RegimeResult:
    a label, a numeric score, and a detail dict for transparency.
    """
    ticker: str
    label: SignalLabel
    score: float                    # composite, range [-1, +1]
    velocity: float                 # sentiment rate of change
    confidence: float               # average confidence of underlying headlines
    headline_count: int             # how many headlines contributed
    snapshots: Dict[str, SentimentSnapshot] = field(default_factory=dict)
    detail: Dict[str, object] = field(default_factory=dict)
    computed_at: Optional[datetime] = None

    def __post_init__(self):
        if self.computed_at is None:
            self.computed_at = datetime.utcnow()

    @property
    def is_actionable(self) -> bool:
        """Signal is actionable if enough headlines and reasonable confidence."""
        return self.headline_count >= 3 and self.confidence >= 0.5
