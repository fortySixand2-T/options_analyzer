"""
Data models for 0 DTE intraday trading signals.

Pydantic v2 models for day-type classification, intraday state, and
signal outputs used by the 0 DTE signal pipeline.

Options Analytics Team — 2026-04
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DayType(str, Enum):
    """Day-type classification for 0 DTE decision-making.

    0 DTE is a bet on intraday price path, not volatility.
    The primary signal is whether the day is range-bound or trending.
    """
    RANGE_DAY = "RANGE_DAY"
    TREND_DAY = "TREND_DAY"
    UNCERTAIN = "UNCERTAIN"


class DayClassification(BaseModel):
    """Output of the day-type classifier."""
    day_type: DayType
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in classification")
    first_30min_range: float = Field(description="High-low range of first 30 min ($)")
    expected_daily_move: float = Field(description="ATM 0DTE straddle price ($) — proxy for expected move")
    range_vs_expected: float = Field(description="first_30min_range / expected_daily_move ratio")
    overnight_gap_pct: float = Field(description="Gap from prior close to open (%)")
    vix_change_pct: float = Field(description="VIX change from prior close (%)")
    detail: str = Field(default="", description="Human-readable reasoning")


class MoveExhaustion(BaseModel):
    """How much of the expected daily move has been consumed."""
    exhaustion_pct: float = Field(description="abs(current - open) / expected_daily_move * 100")
    intraday_move: float = Field(description="Current price minus open ($)")
    expected_daily_move: float = Field(description="Expected daily move ($)")
    signal: str = Field(description="safe / caution / exhausted / overextended")
    detail: str = Field(default="")


class IntradayState(BaseModel):
    """Complete intraday state snapshot for 0 DTE decision-making.

    Analogous to the daily MarketState but at intraday resolution.
    Combines price action, day classification, dealer positioning,
    and move exhaustion into a single object.
    """
    # Identity
    symbol: str
    timestamp: datetime
    spot: float

    # Price context
    open_price: float
    overnight_gap_pct: float
    first_30min_range: float
    expected_daily_move: float
    range_vs_expected: float

    # Day classification (most important 0 DTE signal)
    day_type: DayType
    day_type_confidence: float = Field(ge=0.0, le=1.0)

    # Move exhaustion
    intraday_move: float = Field(description="Current - Open ($)")
    move_exhaustion_pct: float = Field(description="How much of expected move consumed")
    exhaustion_signal: str = Field(description="safe / caution / exhausted / overextended")

    # VIX context
    vix_current: Optional[float] = None
    vix_open: Optional[float] = None
    vix_change_pct: Optional[float] = None

    # Dealer positioning (from intraday chain recomputation)
    gamma_flip: Optional[float] = None
    gamma_flip_distance_pct: Optional[float] = Field(
        default=None, description="(spot - gamma_flip) / spot * 100"
    )
    dealer_regime: Optional[str] = Field(
        default=None, description="LONG_GAMMA or SHORT_GAMMA"
    )
    net_gex: Optional[float] = None
    call_wall: Optional[float] = None
    put_wall: Optional[float] = None
    max_pain: Optional[float] = None

    # Derived signals
    is_pinned: bool = Field(
        default=False,
        description="True if spot near gamma flip and LONG_GAMMA"
    )

    # Data freshness
    bars_count: int = Field(default=0, description="Number of intraday bars loaded")
    chain_label: Optional[str] = Field(
        default=None, description="Label of intraday chain used"
    )
