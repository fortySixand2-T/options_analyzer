"""
VIX term structure analysis.

Fetches VIX, VIX9D, VIX3M, VIX6M from yfinance and computes
contango/backwardation state.

Options Analytics Team — 2026-04
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# VIX family tickers
_VIX_TICKERS = {
    'vix': '^VIX',
    'vix9d': '^VIX9D',
    'vix3m': '^VIX3M',
    'vix6m': '^VIX6M',
}


@dataclass
class VixSnapshot:
    """Current VIX term structure snapshot."""
    vix: float                      # VIX (30-day)
    vix9d: Optional[float]          # VIX9D (9-day)
    vix3m: Optional[float]          # VIX3M (3-month)
    vix6m: Optional[float]          # VIX6M (6-month)
    contango: bool                  # True if VIX < VIX3M (normal)
    backwardation: bool             # True if VIX > VIX3M (fear)
    term_structure_slope: float     # (VIX3M - VIX) / VIX * 100
    vix_percentile_1y: float        # VIX percentile vs last year
    vix9d_vix_ratio: Optional[float] = None  # VIX9D/VIX ratio (>1 = short-term fear)


def _fetch_last_close(ticker: str) -> Optional[float]:
    """Fetch last close for a ticker via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period='5d')
        if hist.empty:
            return None
        return float(hist['Close'].iloc[-1])
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", ticker, e)
        return None


def _fetch_vix_percentile(days: int = 252) -> float:
    """Compute VIX percentile rank over the last N trading days."""
    try:
        import yfinance as yf
        t = yf.Ticker('^VIX')
        hist = t.history(period='1y')
        if hist.empty or len(hist) < 20:
            return 50.0
        closes = hist['Close'].values
        current = closes[-1]
        return float(np.mean(closes <= current) * 100)
    except Exception:
        return 50.0


def get_vix_data() -> VixSnapshot:
    """Fetch current VIX term structure.

    Returns a VixSnapshot with all available VIX family values
    and contango/backwardation classification.
    """
    vix = _fetch_last_close(_VIX_TICKERS['vix'])
    if vix is None:
        vix = 20.0  # fallback

    vix9d = _fetch_last_close(_VIX_TICKERS['vix9d'])
    vix3m = _fetch_last_close(_VIX_TICKERS['vix3m'])
    vix6m = _fetch_last_close(_VIX_TICKERS['vix6m'])

    # Term structure analysis
    if vix3m is not None and vix3m > 0:
        contango = vix < vix3m
        backwardation = vix > vix3m
        slope = (vix3m - vix) / vix * 100
    else:
        contango = True  # assume normal
        backwardation = False
        slope = 0.0

    percentile = _fetch_vix_percentile()

    # VIX9D/VIX ratio: >1 signals elevated short-term fear
    vix9d_vix_ratio = None
    if vix9d is not None and vix > 0:
        vix9d_vix_ratio = round(vix9d / vix, 3)

    return VixSnapshot(
        vix=round(vix, 2),
        vix9d=round(vix9d, 2) if vix9d else None,
        vix3m=round(vix3m, 2) if vix3m else None,
        vix6m=round(vix6m, 2) if vix6m else None,
        contango=contango,
        backwardation=backwardation,
        term_structure_slope=round(slope, 2),
        vix_percentile_1y=round(percentile, 1),
        vix9d_vix_ratio=vix9d_vix_ratio,
    )
