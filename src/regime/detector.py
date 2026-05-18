"""
Market regime detector.

Classifies the current market into one of four regimes based on
IV rank, VIX level, and term structure:

    HIGH_IV     — IV rank > 50, VIX < 25, contango → sell premium
    MODERATE_IV — IV rank 30-50, VIX < 20 → either side, weaker edge
    LOW_IV      — IV rank < 30, VIX < 18 → buy premium
    SPIKE       — VIX > 30 or backwardation → small debit only or stand aside

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
    HIGH_IV = "HIGH_IV"
    MODERATE_IV = "MODERATE_IV"
    LOW_IV = "LOW_IV"
    SPIKE = "SPIKE"


@dataclass
class RegimeResult:
    """Full regime classification result."""
    regime: MarketRegime
    vix: VixSnapshot
    event_active: bool
    event_type: Optional[str]       # FOMC, CPI, OPEX
    event_days: int                 # days to event
    rationale: str                  # human-readable explanation


def detect_regime(
    vix_data: Optional[VixSnapshot] = None,
    iv_rank: Optional[float] = None,
    ticker: Optional[str] = None,
) -> RegimeResult:
    """Classify the current market regime.

    Parameters
    ----------
    vix_data : VixSnapshot, optional
        Pre-fetched VIX data. If None, fetches live data.
    iv_rank : float, optional
        Current IV rank (0-100). Used for refined classification.
    ticker : str, optional
        Ticker symbol for per-class threshold adjustment.

    Returns
    -------
    RegimeResult
    """
    if vix_data is None:
        vix_data = get_vix_data()

    # Check for event window
    in_event, event_type, event_days = is_event_window()

    vix = vix_data.vix

    # SPIKE: VIX > 30 or backwardation
    if vix > 30:
        return RegimeResult(
            regime=MarketRegime.SPIKE,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} (>30) — spike regime, small debit only",
        )

    if vix_data.backwardation:
        return RegimeResult(
            regime=MarketRegime.SPIKE,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} with backwardation — spike regime",
        )

    # Within 24h of FOMC/CPI with elevated VIX → SPIKE
    if in_event and event_days <= 1 and vix > 22:
        return RegimeResult(
            regime=MarketRegime.SPIKE,
            vix=vix_data,
            event_active=True,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX {vix:.1f} with {event_type} in {event_days}d — spike regime",
        )

    # Use IV rank if available for finer classification
    # Per-ticker-class thresholds: mega-cap >40, high-vol >35, ETF/default >50
    if iv_rank is not None:
        from scanner.iv_rank import get_regime_thresholds, get_ticker_class
        thresholds = get_regime_thresholds(ticker or "")
        high_iv_threshold = thresholds[0][0]  # first tuple is HIGH_IV
        mod_iv_threshold = thresholds[1][0]    # second is MODERATE_IV
        ticker_class = get_ticker_class(ticker or "")

        if iv_rank > high_iv_threshold and vix < 25:
            return RegimeResult(
                regime=MarketRegime.HIGH_IV,
                vix=vix_data,
                event_active=in_event,
                event_type=event_type,
                event_days=event_days,
                rationale=f"IV rank {iv_rank:.0f}% (>{high_iv_threshold}, {ticker_class}), VIX {vix:.1f} — sell premium",
            )
        if iv_rank >= mod_iv_threshold:
            return RegimeResult(
                regime=MarketRegime.MODERATE_IV,
                vix=vix_data,
                event_active=in_event,
                event_type=event_type,
                event_days=event_days,
                rationale=f"IV rank {iv_rank:.0f}% ({mod_iv_threshold}-{high_iv_threshold}, {ticker_class}), VIX {vix:.1f} — either side",
            )
        return RegimeResult(
            regime=MarketRegime.LOW_IV,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"IV rank {iv_rank:.0f}% (<{mod_iv_threshold}, {ticker_class}), VIX {vix:.1f} — buy premium",
        )

    # Fallback: use VIX level when IV rank not available
    if vix >= 20:
        return RegimeResult(
            regime=MarketRegime.HIGH_IV,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} (>=20) — high IV, sell premium",
        )

    if vix >= 15:
        return RegimeResult(
            regime=MarketRegime.MODERATE_IV,
            vix=vix_data,
            event_active=in_event,
            event_type=event_type,
            event_days=event_days,
            rationale=f"VIX at {vix:.1f} (15-20) — moderate IV",
        )

    return RegimeResult(
        regime=MarketRegime.LOW_IV,
        vix=vix_data,
        event_active=in_event,
        event_type=event_type,
        event_days=event_days,
        rationale=f"VIX at {vix:.1f} (<15) — low IV, buy premium",
    )
