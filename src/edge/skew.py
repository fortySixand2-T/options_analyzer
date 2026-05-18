"""Volatility skew signal — 25-delta put-call IV spread.

Steep skew (expensive puts relative to calls) predicts lower future returns.
Steepest-smirk quintile underperforms by 10.9%/year (Xing, Zhang & Zhao 2010).

For medium/long-term (30-180 DTE):
    - Skew z-score > 1.5σ above mean → bearish tilt, avoid long equity exposure
    - Skew z-score < -1.0σ → unusually flat, contrarian bullish
    - Mean-reverting: extreme skew normalizes over 30-60 days

References:
    Xing, Zhang & Zhao (2010), "What Does the Individual Option Volatility Smirk
        Tell Us About Future Equity Returns?"
    Bollen & Whaley (2004), "Does Net Buying Pressure Affect the Shape of
        Implied Volatility Functions?"
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class SkewRegime(str, Enum):
    STEEP = "STEEP"         # puts expensive — bearish signal
    NORMAL = "NORMAL"
    FLAT = "FLAT"           # puts cheap — contrarian bullish
    INVERTED = "INVERTED"   # calls more expensive than puts — rare, very bullish


@dataclass
class SkewSignal:
    """Skew measurement for a single expiry or DTE bucket."""
    dte_bucket: str
    put_iv_25d: float       # 25-delta put IV
    call_iv_25d: float      # 25-delta call IV
    atm_iv: float
    skew: float             # put_iv - call_iv (positive = normal smirk)
    skew_ratio: float       # put_iv / call_iv
    skew_normalized: float  # skew / atm_iv (comparable across underlyings)
    regime: SkewRegime


@dataclass
class SkewCurve:
    """Skew across the term structure."""
    signals: List[SkewSignal]
    skew_z_score: Optional[float] = None  # vs historical distribution
    overall_regime: SkewRegime = SkewRegime.NORMAL
    mean_skew_normalized: float = 0.0

    def to_dict(self) -> dict:
        return {
            "signals": [
                {
                    "dte_bucket": s.dte_bucket,
                    "put_iv_25d": round(s.put_iv_25d, 4),
                    "call_iv_25d": round(s.call_iv_25d, 4),
                    "atm_iv": round(s.atm_iv, 4),
                    "skew": round(s.skew, 4),
                    "skew_ratio": round(s.skew_ratio, 4),
                    "skew_normalized": round(s.skew_normalized, 4),
                    "regime": s.regime.value,
                }
                for s in self.signals
            ],
            "skew_z_score": round(self.skew_z_score, 2) if self.skew_z_score else None,
            "overall_regime": self.overall_regime.value,
            "mean_skew_normalized": round(self.mean_skew_normalized, 4),
        }


_STEEP_THRESHOLD = 0.15     # normalized skew > 15% of ATM IV
_FLAT_THRESHOLD = 0.03      # normalized skew < 3% of ATM IV
_INVERTED_THRESHOLD = -0.01 # calls more expensive than puts

_DTE_BUCKETS: List[Tuple[str, int, int]] = [
    ("14-30", 14, 30),
    ("30-60", 30, 60),
    ("60-90", 60, 90),
    ("90-180", 90, 180),
]


def _classify_skew(skew_normalized: float) -> SkewRegime:
    if skew_normalized <= _INVERTED_THRESHOLD:
        return SkewRegime.INVERTED
    if skew_normalized <= _FLAT_THRESHOLD:
        return SkewRegime.FLAT
    if skew_normalized >= _STEEP_THRESHOLD:
        return SkewRegime.STEEP
    return SkewRegime.NORMAL


def compute_skew_from_chain(
    chain_data: Dict[int, Dict[str, List[Tuple[float, float]]]],
    spot_price: float,
) -> SkewCurve:
    """Compute skew signals from option chain data.

    Parameters
    ----------
    chain_data : dict
        DTE → {"puts": [(strike, iv), ...], "calls": [(strike, iv), ...]}
    spot_price : float
        Current underlying price, used to identify ATM and 25-delta approximation.

    Returns
    -------
    SkewCurve with per-bucket skew signals.
    """
    signals: List[SkewSignal] = []

    for label, min_dte, max_dte in _DTE_BUCKETS:
        put_ivs_25d = []
        call_ivs_25d = []
        atm_ivs = []

        for dte, sides in chain_data.items():
            if not (min_dte <= dte < max_dte):
                continue

            puts = sides.get("puts", [])
            calls = sides.get("calls", [])

            if not puts or not calls:
                continue

            atm_iv = _find_atm_iv(puts, calls, spot_price)
            if atm_iv:
                atm_ivs.append(atm_iv)

            put_25d = _find_delta_iv(puts, spot_price, target_moneyness=0.95)
            call_25d = _find_delta_iv(calls, spot_price, target_moneyness=1.05)

            if put_25d is not None:
                put_ivs_25d.append(put_25d)
            if call_25d is not None:
                call_ivs_25d.append(call_25d)

        if not put_ivs_25d or not call_ivs_25d or not atm_ivs:
            continue

        avg_put = float(np.mean(put_ivs_25d))
        avg_call = float(np.mean(call_ivs_25d))
        avg_atm = float(np.mean(atm_ivs))

        skew = avg_put - avg_call
        skew_ratio = avg_put / avg_call if avg_call > 0 else 1.0
        skew_norm = skew / avg_atm if avg_atm > 0 else 0.0
        regime = _classify_skew(skew_norm)

        signals.append(SkewSignal(
            dte_bucket=label,
            put_iv_25d=avg_put,
            call_iv_25d=avg_call,
            atm_iv=avg_atm,
            skew=skew,
            skew_ratio=skew_ratio,
            skew_normalized=skew_norm,
            regime=regime,
        ))

    if not signals:
        return SkewCurve(signals=[])

    mean_norm = float(np.mean([s.skew_normalized for s in signals]))
    overall = _classify_skew(mean_norm)

    return SkewCurve(
        signals=signals,
        overall_regime=overall,
        mean_skew_normalized=mean_norm,
    )


def compute_skew_zscore(
    current_skew_normalized: float,
    historical_skews: np.ndarray,
) -> Optional[float]:
    """Z-score of current skew vs historical distribution.

    Parameters
    ----------
    current_skew_normalized : float
        Today's normalized skew (put-call spread / ATM IV).
    historical_skews : np.ndarray
        Array of past normalized skew values (e.g., 252 trading days).
    """
    if len(historical_skews) < 20:
        return None
    mean = float(np.mean(historical_skews))
    std = float(np.std(historical_skews, ddof=1))
    if std < 1e-8:
        return None
    return (current_skew_normalized - mean) / std


def _find_atm_iv(
    puts: List[Tuple[float, float]],
    calls: List[Tuple[float, float]],
    spot: float,
) -> Optional[float]:
    """Average IV of the nearest-to-ATM put and call."""
    nearest_put = min(puts, key=lambda x: abs(x[0] - spot), default=None)
    nearest_call = min(calls, key=lambda x: abs(x[0] - spot), default=None)
    if nearest_put and nearest_call:
        return (nearest_put[1] + nearest_call[1]) / 2
    return None


def _find_delta_iv(
    options: List[Tuple[float, float]],
    spot: float,
    target_moneyness: float,
) -> Optional[float]:
    """Find IV at approximate 25-delta using moneyness as proxy.

    For puts: ~0.95 moneyness (5% OTM) ≈ 25 delta
    For calls: ~1.05 moneyness (5% OTM) ≈ 25 delta
    """
    target_strike = spot * target_moneyness
    nearest = min(options, key=lambda x: abs(x[0] - target_strike), default=None)
    if nearest is None:
        return None
    if abs(nearest[0] - target_strike) / spot > 0.03:
        return None
    return nearest[1]
