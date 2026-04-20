"""
FlashAlpha GEX (Gamma Exposure) client.

Fetches dealer gamma exposure, GEX walls, gamma flip level, and dealer
regime classification from the FlashAlpha API (free tier: 5 calls/day).

Options Analytics Team — 2026-04
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FLASHALPHA_BASE_URL = "https://api.flashalpha.com/v1"


@dataclass
class GexLevel:
    """A single GEX strike level."""
    strike: float
    gex: float          # gamma exposure in $M notional
    call_gex: float
    put_gex: float


@dataclass
class GexSnapshot:
    """Full GEX snapshot for one symbol."""
    symbol: str
    spot: float
    gamma_flip: float               # price where dealer gamma flips sign
    dealer_regime: str              # "POSITIVE_GAMMA" or "NEGATIVE_GAMMA"
    net_gex: float                  # total net GEX ($M)
    top_call_wall: Optional[float]  # largest call GEX strike
    top_put_wall: Optional[float]   # largest put GEX strike
    levels: List[GexLevel]          # per-strike GEX breakdown
    timestamp: str                  # ISO timestamp from API


def get_flashalpha_api_key() -> str:
    """Read FlashAlpha API key from environment."""
    return os.getenv("FLASHALPHA_API_KEY", "")


def fetch_gex(symbol: str, api_key: Optional[str] = None) -> Optional[GexSnapshot]:
    """Fetch GEX data for a symbol from FlashAlpha.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "SPY", "SPX").
    api_key : str, optional
        FlashAlpha API key. Reads from FLASHALPHA_API_KEY env var if not given.

    Returns
    -------
    GexSnapshot or None if API unavailable or request fails.
    """
    key = api_key or get_flashalpha_api_key()
    if not key:
        logger.info("FLASHALPHA_API_KEY not set, skipping GEX fetch")
        return None

    try:
        import requests
    except ImportError:
        logger.warning("requests package not installed, cannot fetch GEX data")
        return None

    url = f"{FLASHALPHA_BASE_URL}/gex/{symbol.upper()}"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return _parse_gex_response(symbol, data)
    except Exception as e:
        logger.warning("FlashAlpha GEX request failed for %s: %s", symbol, e)
        return None


def _parse_gex_response(symbol: str, data: dict) -> GexSnapshot:
    """Parse FlashAlpha API response into GexSnapshot."""
    gex_data = data.get("data", data)

    levels = []
    for level in gex_data.get("levels", []):
        levels.append(GexLevel(
            strike=float(level.get("strike", 0)),
            gex=float(level.get("gex", 0)),
            call_gex=float(level.get("call_gex", 0)),
            put_gex=float(level.get("put_gex", 0)),
        ))

    # Sort by absolute GEX to find walls
    levels_sorted = sorted(levels, key=lambda x: abs(x.gex), reverse=True)

    top_call_wall = None
    top_put_wall = None
    for lv in levels_sorted:
        if lv.call_gex > 0 and top_call_wall is None:
            top_call_wall = lv.strike
        if lv.put_gex < 0 and top_put_wall is None:
            top_put_wall = lv.strike
        if top_call_wall and top_put_wall:
            break

    gamma_flip = float(gex_data.get("gamma_flip", 0))
    spot = float(gex_data.get("spot", 0))
    net_gex = float(gex_data.get("net_gex", 0))

    # Dealer regime: positive gamma = dealers sell dips / buy rips (mean-reverting)
    #                negative gamma = dealers amplify moves (trending)
    if spot >= gamma_flip:
        dealer_regime = "POSITIVE_GAMMA"
    else:
        dealer_regime = "NEGATIVE_GAMMA"

    return GexSnapshot(
        symbol=symbol.upper(),
        spot=spot,
        gamma_flip=gamma_flip,
        dealer_regime=dealer_regime,
        net_gex=net_gex,
        top_call_wall=top_call_wall,
        top_put_wall=top_put_wall,
        levels=levels,
        timestamp=gex_data.get("timestamp", ""),
    )


def classify_dealer_regime(gex: GexSnapshot) -> Dict:
    """Classify dealer positioning and its implications.

    Returns
    -------
    dict with keys: regime, implication, support, resistance, bias
    """
    result = {
        "regime": gex.dealer_regime,
        "gamma_flip": gex.gamma_flip,
        "net_gex": gex.net_gex,
        "support": gex.top_put_wall,
        "resistance": gex.top_call_wall,
    }

    if gex.dealer_regime == "POSITIVE_GAMMA":
        result["implication"] = (
            "Dealers are long gamma — they sell into rallies and buy dips. "
            "Expect mean-reversion and lower realized vol. Favors premium selling."
        )
        result["bias"] = "neutral"
    else:
        result["implication"] = (
            "Dealers are short gamma — they amplify moves in both directions. "
            "Expect trending behavior and higher realized vol. Favors directional plays."
        )
        # Below gamma flip: bearish pressure. Above: bullish pressure.
        if gex.spot < gex.gamma_flip:
            result["bias"] = "bearish"
        else:
            result["bias"] = "bullish"

    return result
