"""Variance Risk Premium (VRP) measurement across the term structure.

VRP = implied_vol - realized_vol.  Positive VRP means options are
overpriced relative to actual vol — the primary edge for premium sellers.

Uses Yang-Zhang realized vol (~8x more efficient than close-to-close).
Extended to 180 DTE for medium/long-term strategies.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.edge.realized_vol import yang_zhang, TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)

DTE_BUCKETS: List[Tuple[str, int, int]] = [
    ("0-7", 0, 7),
    ("7-14", 7, 14),
    ("14-30", 14, 30),
    ("30-60", 30, 60),
    ("60-90", 60, 90),
    ("90-180", 90, 180),
]


class VRPRegime(str, Enum):
    RICH = "RICH"
    NEUTRAL = "NEUTRAL"
    CHEAP = "CHEAP"


@dataclass
class VRPBucket:
    """VRP for a single DTE bucket."""
    label: str
    min_dte: int
    max_dte: int
    implied_vol: float          # avg chain IV for contracts in this bucket
    realized_vol: float         # realized vol (annualized)
    vrp: float                  # implied - realized (positive = rich)
    vrp_pct: float              # vrp / implied * 100 (% overpriced)
    contract_count: int         # how many contracts contributed
    rv_method: str = "yang_zhang"
    regime: VRPRegime = VRPRegime.NEUTRAL


@dataclass
class VRPCurve:
    """VRP across the full term structure."""
    buckets: List[VRPBucket] = field(default_factory=list)
    overall_vrp: float = 0.0            # weighted average VRP
    overall_vrp_pct: float = 0.0        # weighted average VRP %
    richest_bucket: Optional[str] = None  # bucket with highest VRP %
    overall_regime: VRPRegime = VRPRegime.NEUTRAL
    vrp_z_score: Optional[float] = None  # vs historical distribution
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "buckets": [
                {
                    "label": b.label,
                    "implied_vol": round(b.implied_vol, 4),
                    "realized_vol": round(b.realized_vol, 4),
                    "vrp": round(b.vrp, 4),
                    "vrp_pct": round(b.vrp_pct, 2),
                    "contract_count": b.contract_count,
                    "rv_method": b.rv_method,
                    "regime": b.regime.value,
                }
                for b in self.buckets
            ],
            "overall_vrp": round(self.overall_vrp, 4),
            "overall_vrp_pct": round(self.overall_vrp_pct, 2),
            "richest_bucket": self.richest_bucket,
            "overall_regime": self.overall_regime.value,
            "vrp_z_score": round(self.vrp_z_score, 2) if self.vrp_z_score is not None else None,
        }


def compute_vrp_curve(
    chain_iv_by_dte: Dict[int, List[float]],
    realized_vol: float,
) -> VRPCurve:
    """Compute VRP across DTE buckets.

    Parameters
    ----------
    chain_iv_by_dte : dict
        Mapping of DTE → list of implied vols for contracts at that DTE.
        Example: {3: [0.18, 0.19, 0.20], 7: [0.21, 0.22], 30: [0.25, 0.26]}
    realized_vol : float
        Annualized realized vol (e.g. HV20 or HV30).

    Returns
    -------
    VRPCurve with per-bucket and overall VRP.
    """
    buckets: List[VRPBucket] = []

    for label, min_dte, max_dte in DTE_BUCKETS:
        ivs = []
        for dte, iv_list in chain_iv_by_dte.items():
            if min_dte <= dte < max_dte:
                ivs.extend(iv_list)

        if not ivs:
            continue

        avg_iv = float(np.mean(ivs))
        vrp = avg_iv - realized_vol
        vrp_pct = (vrp / avg_iv * 100) if avg_iv > 0 else 0.0

        buckets.append(VRPBucket(
            label=label,
            min_dte=min_dte,
            max_dte=max_dte,
            implied_vol=avg_iv,
            realized_vol=realized_vol,
            vrp=vrp,
            vrp_pct=vrp_pct,
            contract_count=len(ivs),
        ))

    if not buckets:
        return VRPCurve()

    total_contracts = sum(b.contract_count for b in buckets)
    overall_vrp = sum(b.vrp * b.contract_count for b in buckets) / total_contracts
    overall_iv = sum(b.implied_vol * b.contract_count for b in buckets) / total_contracts
    overall_vrp_pct = (overall_vrp / overall_iv * 100) if overall_iv > 0 else 0.0
    richest = max(buckets, key=lambda b: b.vrp_pct)

    return VRPCurve(
        buckets=buckets,
        overall_vrp=overall_vrp,
        overall_vrp_pct=overall_vrp_pct,
        richest_bucket=richest.label,
    )


def compute_vrp_simple(chain_iv: float, realized_vol: float) -> dict:
    """Simple single-point VRP when full chain data isn't available.

    Falls back to ATM IV vs HV for a quick VRP read.
    """
    vrp = chain_iv - realized_vol
    vrp_pct = (vrp / chain_iv * 100) if chain_iv > 0 else 0.0
    return {
        "vrp": round(vrp, 4),
        "vrp_pct": round(vrp_pct, 2),
        "rich": vrp > 0,
    }


_DTE_TO_RV_WINDOW = {
    "0-7": 5,
    "7-14": 10,
    "14-30": 20,
    "30-60": 30,
    "60-90": 45,
    "90-180": 60,
}

# VRP regime thresholds (% of IV)
_VRP_RICH_THRESHOLD = 10.0    # VRP > 10% of IV → sell premium
_VRP_CHEAP_THRESHOLD = -5.0   # VRP < -5% of IV → buy premium


def _classify_vrp(vrp_pct: float) -> VRPRegime:
    if vrp_pct >= _VRP_RICH_THRESHOLD:
        return VRPRegime.RICH
    if vrp_pct <= _VRP_CHEAP_THRESHOLD:
        return VRPRegime.CHEAP
    return VRPRegime.NEUTRAL


def _realized_vol_yang_zhang(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int,
) -> Optional[float]:
    """Yang-Zhang realized vol. Falls back to close-to-close if OHLC unavailable."""
    est = yang_zhang(opens, highs, lows, closes, window=window)
    if est is not None:
        return est.annualized
    # Fallback: close-to-close
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    returns = np.diff(np.log(tail))
    return float(np.std(returns, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def compute_vrp_by_dte(
    chain_iv_by_dte: Dict[int, List[float]],
    price_history: np.ndarray,
    ohlc: Optional[Dict[str, np.ndarray]] = None,
) -> VRPCurve:
    """Compute VRP with per-bucket realized vol matched to the DTE horizon.

    Uses Yang-Zhang when OHLC data is provided, close-to-close otherwise.

    Parameters
    ----------
    chain_iv_by_dte : dict
        Mapping of DTE → list of implied vols.
    price_history : np.ndarray
        Close prices array.
    ohlc : dict, optional
        Keys: "opens", "highs", "lows", "closes" — all np.ndarray.
        When provided, Yang-Zhang is used (~8x more efficient than close-to-close).
    """
    buckets: List[VRPBucket] = []

    for label, min_dte, max_dte in DTE_BUCKETS:
        ivs = []
        for dte, iv_list in chain_iv_by_dte.items():
            if min_dte <= dte < max_dte:
                ivs.extend(iv_list)

        if not ivs:
            continue

        window = _DTE_TO_RV_WINDOW.get(label, 20)

        if ohlc is not None:
            rv = _realized_vol_yang_zhang(
                ohlc["opens"], ohlc["highs"], ohlc["lows"], ohlc["closes"],
                window,
            )
            rv_method = "yang_zhang"
        else:
            if len(price_history) < window + 1:
                rv = None
            else:
                tail = price_history[-(window + 1):]
                returns = np.diff(np.log(tail))
                rv = float(np.std(returns, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
            rv_method = "close_to_close"

        if rv is None:
            continue

        avg_iv = float(np.mean(ivs))
        vrp = avg_iv - rv
        vrp_pct = (vrp / avg_iv * 100) if avg_iv > 0 else 0.0
        regime = _classify_vrp(vrp_pct)

        buckets.append(VRPBucket(
            label=label, min_dte=min_dte, max_dte=max_dte,
            implied_vol=avg_iv, realized_vol=rv,
            vrp=vrp, vrp_pct=vrp_pct, contract_count=len(ivs),
            rv_method=rv_method, regime=regime,
        ))

    if not buckets:
        return VRPCurve()

    total_contracts = sum(b.contract_count for b in buckets)
    overall_vrp = sum(b.vrp * b.contract_count for b in buckets) / total_contracts
    overall_iv = sum(b.implied_vol * b.contract_count for b in buckets) / total_contracts
    overall_vrp_pct = (overall_vrp / overall_iv * 100) if overall_iv > 0 else 0.0
    richest = max(buckets, key=lambda b: b.vrp_pct)
    overall_regime = _classify_vrp(overall_vrp_pct)

    return VRPCurve(
        buckets=buckets, overall_vrp=overall_vrp,
        overall_vrp_pct=overall_vrp_pct, richest_bucket=richest.label,
        overall_regime=overall_regime,
    )


def compute_vrp_zscore(
    current_vrp_pct: float,
    historical_vrp_pcts: np.ndarray,
) -> Optional[float]:
    """Z-score of current VRP% vs historical distribution.

    Entry signal: z > 1.5 means VRP is unusually rich — best time to sell premium.
    z < -1.0 means VRP is unusually cheap — consider buying premium.

    Parameters
    ----------
    current_vrp_pct : float
        Today's VRP as % of IV.
    historical_vrp_pcts : np.ndarray
        60+ days of historical VRP% values from swing_signals table.
    """
    if len(historical_vrp_pcts) < 20:
        return None
    clean = historical_vrp_pcts[~np.isnan(historical_vrp_pcts)]
    if len(clean) < 20:
        return None
    mean = float(np.mean(clean))
    std = float(np.std(clean, ddof=1))
    if std < 0.01:
        return None
    return (current_vrp_pct - mean) / std


VRP_ENTRY_Z_THRESHOLD = 1.5    # sell premium when z > 1.5
VRP_BUY_Z_THRESHOLD = -1.0     # buy premium when z < -1.0


def extract_chain_iv_by_dte(chain_snapshot) -> Dict[int, List[float]]:
    """Extract IV grouped by DTE from a ChainSnapshot.

    Parameters
    ----------
    chain_snapshot : ChainSnapshot
        From scanner.providers.base — has .contracts list with .expiry and .implied_volatility.

    Returns
    -------
    Dict mapping DTE (int) to list of implied vols.
    """
    from datetime import date, datetime

    today = date.today()
    iv_by_dte: Dict[int, List[float]] = {}

    for c in chain_snapshot.contracts:
        if c.implied_volatility is None or np.isnan(c.implied_volatility):
            continue
        if c.implied_volatility <= 0:
            continue

        try:
            expiry_date = datetime.strptime(c.expiry, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        dte = (expiry_date - today).days
        if dte < 0:
            continue

        iv_by_dte.setdefault(dte, []).append(c.implied_volatility)

    return iv_by_dte
