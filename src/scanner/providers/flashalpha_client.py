"""
FlashAlpha GEX (Gamma Exposure) client — Layer 3 dealer positioning.

Signals F1-F7 from SIGNALS.md:
    F1: Net GEX sign → positive = range-bound, negative = trending
    F2: Gamma flip level → above = pinned, below = volatile
    F3: Call wall → resistance, place short calls near
    F4: Put wall → support, place short puts near
    F5: Max pain → price magnet into expiry, center butterflies
    F6: Put/call OI ratio → >1.5 contrarian bullish, <0.5 contrarian bearish
    F7: Dealer regime → LONG_GAMMA or SHORT_GAMMA

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
class DealerData:
    """Full dealer positioning snapshot — signals F1-F7."""
    symbol: str
    spot: float
    net_gex: float                  # F1: total net GEX ($M)
    gamma_flip: float               # F2: price where dealer gamma flips sign
    call_wall: Optional[float]      # F3: largest call GEX strike (resistance)
    put_wall: Optional[float]       # F4: largest put GEX strike (support)
    max_pain: Optional[float]       # F5: max pain strike
    put_call_ratio: Optional[float] # F6: put/call OI ratio
    dealer_regime: str              # F7: "LONG_GAMMA" or "SHORT_GAMMA"
    levels: List[GexLevel] = field(default_factory=list)
    timestamp: str = ""
    source: str = "flashalpha"      # "flashalpha" or "chain"


# Keep backward compat alias
GexSnapshot = DealerData


def get_flashalpha_api_key() -> str:
    """Read FlashAlpha API key from environment."""
    return os.getenv("FLASHALPHA_API_KEY", "")


def fetch_gex(symbol: str, api_key: Optional[str] = None) -> Optional[DealerData]:
    """Fetch GEX data for a symbol from FlashAlpha.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "SPY", "SPX").
    api_key : str, optional
        FlashAlpha API key. Reads from FLASHALPHA_API_KEY env var if not given.

    Returns
    -------
    DealerData or None if API unavailable or request fails.
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


def _parse_gex_response(symbol: str, data: dict) -> DealerData:
    """Parse FlashAlpha API response into DealerData."""
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

    call_wall = None
    put_wall = None
    for lv in levels_sorted:
        if lv.call_gex > 0 and call_wall is None:
            call_wall = lv.strike
        if lv.put_gex < 0 and put_wall is None:
            put_wall = lv.strike
        if call_wall and put_wall:
            break

    gamma_flip = float(gex_data.get("gamma_flip", 0))
    spot = float(gex_data.get("spot", 0))
    net_gex = float(gex_data.get("net_gex", 0))
    max_pain = gex_data.get("max_pain")
    if max_pain is not None:
        max_pain = float(max_pain)
    put_call_ratio = gex_data.get("put_call_ratio")
    if put_call_ratio is not None:
        put_call_ratio = float(put_call_ratio)

    # F7: Dealer regime — LONG_GAMMA (range-bound) or SHORT_GAMMA (trending)
    if net_gex > 0 and spot >= gamma_flip:
        dealer_regime = "LONG_GAMMA"
    else:
        dealer_regime = "SHORT_GAMMA"

    return DealerData(
        symbol=symbol.upper(),
        spot=spot,
        net_gex=net_gex,
        gamma_flip=gamma_flip,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        put_call_ratio=put_call_ratio,
        dealer_regime=dealer_regime,
        levels=levels,
        timestamp=gex_data.get("timestamp", ""),
        source="flashalpha",
    )


def compute_dealer_data_from_chain(
    symbol: str,
    spot: float,
    contracts: list,
) -> DealerData:
    """Compute dealer positioning from raw option chain data.

    Fallback when FlashAlpha API is not available. Computes:
    - Max pain (F5) from OI
    - Put/call OI ratio (F6)
    - Call/put walls from max OI strikes (F3/F4)
    - Approximate net GEX sign (F1)
    - Gamma flip estimate (F2)

    Parameters
    ----------
    symbol : str
    spot : float
    contracts : list
        List of OptionContract objects from chain snapshot.

    Returns
    -------
    DealerData
    """
    call_oi_by_strike: Dict[float, int] = {}
    put_oi_by_strike: Dict[float, int] = {}
    total_call_oi = 0
    total_put_oi = 0

    for c in contracts:
        strike = c.strike
        oi = getattr(c, 'open_interest', 0)
        if c.option_type == "call":
            call_oi_by_strike[strike] = call_oi_by_strike.get(strike, 0) + oi
            total_call_oi += oi
        else:
            put_oi_by_strike[strike] = put_oi_by_strike.get(strike, 0) + oi
            total_put_oi += oi

    # F5: Max pain — strike where total OI-weighted exercise cost is minimized
    max_pain = _compute_max_pain(call_oi_by_strike, put_oi_by_strike, spot)

    # F6: Put/call OI ratio
    put_call_ratio = (total_put_oi / total_call_oi) if total_call_oi > 0 else 1.0

    # F3/F4: Call wall = max call OI strike, Put wall = max put OI strike
    call_wall = max(call_oi_by_strike, key=call_oi_by_strike.get) if call_oi_by_strike else None
    put_wall = max(put_oi_by_strike, key=put_oi_by_strike.get) if put_oi_by_strike else None

    # F1/F2: Approximate GEX and gamma flip from OI distribution
    # Positive net call OI above spot → dealers long gamma
    above_spot_call_oi = sum(oi for s, oi in call_oi_by_strike.items() if s > spot)
    below_spot_put_oi = sum(oi for s, oi in put_oi_by_strike.items() if s < spot)
    net_gex = float(above_spot_call_oi - below_spot_put_oi)

    # Gamma flip: approximate as the strike where cumulative call gamma
    # crosses cumulative put gamma. Simplified: use max pain as proxy.
    gamma_flip = max_pain if max_pain else spot

    # F7: Dealer regime
    if net_gex > 0 and spot >= gamma_flip:
        dealer_regime = "LONG_GAMMA"
    else:
        dealer_regime = "SHORT_GAMMA"

    return DealerData(
        symbol=symbol.upper(),
        spot=spot,
        net_gex=net_gex,
        gamma_flip=gamma_flip,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        put_call_ratio=round(put_call_ratio, 3),
        dealer_regime=dealer_regime,
        source="chain",
    )


def _compute_max_pain(
    call_oi: Dict[float, int],
    put_oi: Dict[float, int],
    spot: float,
) -> Optional[float]:
    """Compute max pain strike — price that causes maximum loss for option holders.

    For each candidate strike, compute total intrinsic value paid out to
    call and put holders weighted by OI. Max pain = strike with minimum payout.
    """
    all_strikes = sorted(set(list(call_oi.keys()) + list(put_oi.keys())))
    if not all_strikes:
        return None

    min_pain = float('inf')
    max_pain_strike = spot

    for candidate in all_strikes:
        pain = 0.0
        # Call holders' gain at this settlement price
        for strike, oi in call_oi.items():
            if candidate > strike:
                pain += (candidate - strike) * oi
        # Put holders' gain at this settlement price
        for strike, oi in put_oi.items():
            if candidate < strike:
                pain += (strike - candidate) * oi
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = candidate

    return max_pain_strike


def classify_dealer_regime(dealer: DealerData) -> Dict:
    """Classify dealer positioning and its implications.

    Returns
    -------
    dict with keys: regime, implication, support, resistance, bias,
                    max_pain, put_call_ratio
    """
    result = {
        "regime": dealer.dealer_regime,
        "gamma_flip": dealer.gamma_flip,
        "net_gex": dealer.net_gex,
        "support": dealer.put_wall,
        "resistance": dealer.call_wall,
        "max_pain": dealer.max_pain,
        "put_call_ratio": dealer.put_call_ratio,
    }

    if dealer.dealer_regime == "LONG_GAMMA":
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
        if dealer.spot < dealer.gamma_flip:
            result["bias"] = "bearish"
        else:
            result["bias"] = "bullish"

    # F6 interpretation
    if dealer.put_call_ratio is not None:
        if dealer.put_call_ratio > 1.5:
            result["pc_signal"] = "contrarian_bullish"
        elif dealer.put_call_ratio < 0.5:
            result["pc_signal"] = "contrarian_bearish"
        else:
            result["pc_signal"] = "neutral"

    return result
