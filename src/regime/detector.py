"""
Market regime detector.

Classifies the current market into one of three regimes based on
VIX level, term structure, and macro calendar proximity:

    LOW_VOL_RANGING  — VIX < 18, contango, no imminent events
    HIGH_VOL_TRENDING — VIX 18-30, may be backwardation
    SPIKE_EVENT      — VIX > 30 or within event window (FOMC/CPI)

Options Analytics Team — 2026-04
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .vix_analysis import VixSnapshot, get_vix_data
from .calendar import is_event_window

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    LOW_VOL_RANGING = "LOW_VOL_RANGING"
    HIGH_VOL_TRENDING = "HIGH_VOL_TRENDING"
    SPIKE_EVENT = "SPIKE_EVENT"


@dataclass
class RegimeResult:
    """Full regime classification result."""
    regime: MarketRegime
    vix: VixSnapshot
    event_active: bool
    event_type: Optional[str]       # FOMC, CPI, OPEX
    event_days: int                 # days to event
    rationale: str                  # human-readable explanation


def detect_regime(vix_data: Optional[VixSnapshot] = None) -> RegimeResult:
    """Classify the current market regime.

    Parameters
    ----------
    vix_data : VixSnapshot, optional
        Pre-fetched VIX data. If None, fetches live data.

    Returns
    -------
    RegimeResult
    """
    if vix_data is None:
        vix_data = get_vix_data()

    # Check for event window
    in_event, event_type, event_days = is_event_window()

    vix = vix_data.vix

    # SPIKE_EVENT: VIX > 30 or in event window with elevated VIX
    if vix > 30:
        return RegimeResult(
            regime=MarketRegime.SPIKE_EVENT,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} (>30) signals extreme fear/event risk",
        )

    if in_event and vix > 22:
        return RegimeResult(
            regime=MarketRegime.SPIKE_EVENT,
            vix=vix_data,
            event_active=True,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX {vix:.1f} with {event_type} in {event_days}d — elevated event risk",
        )

    # HIGH_VOL_TRENDING: VIX 18-30
    if vix >= 18:
        backwardation_note = ""
        if vix_data.backwardation:
            backwardation_note = ", term structure in backwardation"
        return RegimeResult(
            regime=MarketRegime.HIGH_VOL_TRENDING,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} (18-30) — elevated vol, trending market{backwardation_note}",
        )

    # LOW_VOL_RANGING: VIX < 18
    contango_note = ""
    if vix_data.contango:
        contango_note = ", contango (normal term structure)"
    return RegimeResult(
        regime=MarketRegime.LOW_VOL_RANGING,
        vix=vix_data,
        event_active=in_event,
        event_type=event_type,
        event_days=event_days,
        rationale=f"VIX at {vix:.1f} (<18) — low vol, range-bound{contango_note}",
    )
