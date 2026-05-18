"""Cross-asset regime signals: VVIX, MOVE/VIX, correlation risk premium.

VVIX (vol-of-vol):
    - VVIX/VIX ratio < 3.5 → contrarian bullish (vol is "asleep")
    - VVIX/VIX ratio > 5.0 → vol regime unstable, reduce position size
    - VVIX z-score > 2.0 → vol explosion likely, buy premium

MOVE/VIX divergence:
    - MOVE rising + VIX compressed → equity options mispriced cheap
    - Bond vol leading equity vol by 5-10 days (Choi et al 2017)
    - Best signal at 60-90 DTE where term premium misalignment peaks

Correlation risk premium:
    - Implied correlation exceeds realized by 6.7-8.9 points on average
    - Dispersion trades at 60-90 DTE capture this premium
    - VIX² ≈ avg(component_IV²) × implied_corr (Driessen et al 2009)

References:
    Park (2015), "The VVIX and VIX Options"
    Choi, Mueller & Vedolin (2017), "Bond Variance Risk Premiums"
    Driessen, Maenhout & Vilkov (2009), "The Price of Correlation Risk"
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class VolOfVolRegime(str, Enum):
    STABLE = "STABLE"       # VVIX/VIX < 3.5 — vol compressed, good for selling
    NORMAL = "NORMAL"       # 3.5-5.0
    UNSTABLE = "UNSTABLE"   # > 5.0 — reduce size, vol regime shifting


class CrossAssetSignal(str, Enum):
    ALIGNED = "ALIGNED"             # bond + equity vol moving together
    EQUITY_VOL_CHEAP = "EQUITY_VOL_CHEAP"   # MOVE up, VIX flat → buy equity vol
    EQUITY_VOL_RICH = "EQUITY_VOL_RICH"     # MOVE flat, VIX elevated


@dataclass
class VVIXSignal:
    """Vol-of-vol signal for position sizing and regime detection."""
    vvix: float
    vix: float
    ratio: float                    # VVIX / VIX
    regime: VolOfVolRegime
    z_score: Optional[float]        # VVIX z-score vs 60-day history
    position_size_factor: float     # 0.25-1.0 Kelly scaling

    def to_dict(self) -> dict:
        return {
            "vvix": round(self.vvix, 2),
            "vix": round(self.vix, 2),
            "ratio": round(self.ratio, 2),
            "regime": self.regime.value,
            "z_score": round(self.z_score, 2) if self.z_score else None,
            "position_size_factor": round(self.position_size_factor, 2),
        }


@dataclass
class MOVEVIXSignal:
    """MOVE/VIX divergence signal."""
    move_index: float
    vix: float
    move_vix_ratio: float
    move_z_score: Optional[float]
    vix_z_score: Optional[float]
    divergence: float               # move_z - vix_z (positive = equity vol cheap)
    signal: CrossAssetSignal

    def to_dict(self) -> dict:
        return {
            "move_index": round(self.move_index, 2),
            "vix": round(self.vix, 2),
            "move_vix_ratio": round(self.move_vix_ratio, 2),
            "move_z_score": round(self.move_z_score, 2) if self.move_z_score else None,
            "vix_z_score": round(self.vix_z_score, 2) if self.vix_z_score else None,
            "divergence": round(self.divergence, 2),
            "signal": self.signal.value,
        }


@dataclass
class CorrelationPremium:
    """Implied vs realized correlation for dispersion signal."""
    implied_corr: float
    realized_corr: float
    premium: float          # implied - realized
    dispersion_signal: bool # True if premium > threshold → sell index vol, buy singles

    def to_dict(self) -> dict:
        return {
            "implied_corr": round(self.implied_corr, 4),
            "realized_corr": round(self.realized_corr, 4),
            "premium": round(self.premium, 4),
            "dispersion_signal": self.dispersion_signal,
        }


_VVIX_STABLE_THRESHOLD = 3.5
_VVIX_UNSTABLE_THRESHOLD = 5.0
_DIVERGENCE_THRESHOLD = 1.0
_CORR_PREMIUM_THRESHOLD = 0.05  # 5 points


def compute_vvix_signal(
    vvix: float,
    vix: float,
    vvix_history: Optional[np.ndarray] = None,
) -> VVIXSignal:
    """Compute vol-of-vol regime signal.

    Parameters
    ----------
    vvix : float
        Current VVIX level.
    vix : float
        Current VIX level.
    vvix_history : np.ndarray, optional
        Historical VVIX values for z-score (60+ days recommended).
    """
    ratio = vvix / vix if vix > 0 else 0.0

    if ratio < _VVIX_STABLE_THRESHOLD:
        regime = VolOfVolRegime.STABLE
    elif ratio > _VVIX_UNSTABLE_THRESHOLD:
        regime = VolOfVolRegime.UNSTABLE
    else:
        regime = VolOfVolRegime.NORMAL

    z_score = None
    if vvix_history is not None and len(vvix_history) >= 20:
        mean = float(np.mean(vvix_history))
        std = float(np.std(vvix_history, ddof=1))
        if std > 0.1:
            z_score = (vvix - mean) / std

    # Kelly scaling: full size when stable, reduce when unstable
    if regime == VolOfVolRegime.STABLE:
        size_factor = 1.0
    elif regime == VolOfVolRegime.UNSTABLE:
        size_factor = 0.25
    else:
        size_factor = 0.5 if (z_score is not None and z_score > 1.5) else 0.75

    return VVIXSignal(
        vvix=vvix,
        vix=vix,
        ratio=ratio,
        regime=regime,
        z_score=z_score,
        position_size_factor=size_factor,
    )


def compute_move_vix_signal(
    move_index: float,
    vix: float,
    move_history: Optional[np.ndarray] = None,
    vix_history: Optional[np.ndarray] = None,
) -> MOVEVIXSignal:
    """Detect MOVE/VIX divergence — bond vol leading equity vol.

    Parameters
    ----------
    move_index : float
        Current ICE BofA MOVE index.
    vix : float
        Current VIX level.
    move_history, vix_history : np.ndarray, optional
        60+ days of history for z-scores.
    """
    ratio = move_index / vix if vix > 0 else 0.0

    move_z = None
    if move_history is not None and len(move_history) >= 20:
        mean = float(np.mean(move_history))
        std = float(np.std(move_history, ddof=1))
        if std > 0.1:
            move_z = (move_index - mean) / std

    vix_z = None
    if vix_history is not None and len(vix_history) >= 20:
        mean = float(np.mean(vix_history))
        std = float(np.std(vix_history, ddof=1))
        if std > 0.1:
            vix_z = (vix - mean) / std

    divergence = 0.0
    if move_z is not None and vix_z is not None:
        divergence = move_z - vix_z

    if divergence > _DIVERGENCE_THRESHOLD:
        signal = CrossAssetSignal.EQUITY_VOL_CHEAP
    elif divergence < -_DIVERGENCE_THRESHOLD:
        signal = CrossAssetSignal.EQUITY_VOL_RICH
    else:
        signal = CrossAssetSignal.ALIGNED

    return MOVEVIXSignal(
        move_index=move_index,
        vix=vix,
        move_vix_ratio=ratio,
        move_z_score=move_z,
        vix_z_score=vix_z,
        divergence=divergence,
        signal=signal,
    )


def compute_correlation_premium(
    index_iv: float,
    component_ivs: np.ndarray,
    component_weights: np.ndarray,
    realized_corr: float,
) -> CorrelationPremium:
    """Estimate implied correlation and correlation risk premium.

    Implied correlation from: VIX² ≈ Σ(wᵢ²σᵢ²) + 2Σ(wᵢwⱼσᵢσⱼρ_impl)
    Simplified: ρ_impl ≈ (σ_index² - Σwᵢ²σᵢ²) / (Σwᵢσᵢ)² - Σwᵢ²σᵢ²)

    Parameters
    ----------
    index_iv : float
        Index implied vol (e.g., SPX ATM IV).
    component_ivs : np.ndarray
        Individual stock IVs.
    component_weights : np.ndarray
        Portfolio weights for each component.
    realized_corr : float
        Realized pairwise correlation over matching window.
    """
    w = component_weights / component_weights.sum()
    weighted_var_sum = float(np.sum((w * component_ivs) ** 2))
    weighted_vol_sum = float(np.sum(w * component_ivs))

    index_var = index_iv ** 2
    cross_term = weighted_vol_sum ** 2 - weighted_var_sum

    if cross_term > 1e-8:
        implied_corr = (index_var - weighted_var_sum) / cross_term
        implied_corr = float(np.clip(implied_corr, -1.0, 1.0))
    else:
        implied_corr = realized_corr

    premium = implied_corr - realized_corr
    dispersion = premium > _CORR_PREMIUM_THRESHOLD

    return CorrelationPremium(
        implied_corr=implied_corr,
        realized_corr=realized_corr,
        premium=premium,
        dispersion_signal=dispersion,
    )
