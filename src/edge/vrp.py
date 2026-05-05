"""Variance Risk Premium (VRP) measurement across the term structure.

VRP = implied_vol - realized_vol.  Positive VRP means options are
overpriced relative to actual vol — the primary edge for premium sellers.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DTE_BUCKETS: List[Tuple[str, int, int]] = [
    ("0-7", 0, 7),
    ("7-14", 7, 14),
    ("14-30", 14, 30),
    ("30-60", 30, 60),
]


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


@dataclass
class VRPCurve:
    """VRP across the full term structure."""
    buckets: List[VRPBucket] = field(default_factory=list)
    overall_vrp: float = 0.0            # weighted average VRP
    overall_vrp_pct: float = 0.0        # weighted average VRP %
    richest_bucket: Optional[str] = None  # bucket with highest VRP %
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
                }
                for b in self.buckets
            ],
            "overall_vrp": round(self.overall_vrp, 4),
            "overall_vrp_pct": round(self.overall_vrp_pct, 2),
            "richest_bucket": self.richest_bucket,
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


def _realized_vol(prices: np.ndarray, window: int) -> Optional[float]:
    """Compute annualized realized vol from a price array over a given window."""
    if len(prices) < window + 1:
        return None
    tail = prices[-(window + 1):]
    returns = np.diff(np.log(tail))
    return float(np.std(returns, ddof=1) * np.sqrt(252))


# Matched windows: each DTE bucket maps to a realized vol lookback
_DTE_TO_RV_WINDOW = {
    "0-7": 5,
    "7-14": 10,
    "14-30": 20,
    "30-60": 30,
}


def compute_vrp_by_dte(
    chain_iv_by_dte: Dict[int, List[float]],
    price_history: np.ndarray,
) -> VRPCurve:
    """Compute VRP with per-bucket realized vol matched to the DTE horizon.

    Unlike compute_vrp_curve() which uses a single realized_vol for all
    buckets, this matches each bucket to a realized vol window:
        0-7 DTE  → 5-day realized vol
        7-14 DTE → 10-day realized vol
        14-30 DTE → 20-day realized vol
        30-60 DTE → 30-day realized vol
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
        rv = _realized_vol(price_history, window)
        if rv is None:
            continue

        avg_iv = float(np.mean(ivs))
        vrp = avg_iv - rv
        vrp_pct = (vrp / avg_iv * 100) if avg_iv > 0 else 0.0

        buckets.append(VRPBucket(
            label=label, min_dte=min_dte, max_dte=max_dte,
            implied_vol=avg_iv, realized_vol=rv,
            vrp=vrp, vrp_pct=vrp_pct, contract_count=len(ivs),
        ))

    if not buckets:
        return VRPCurve()

    total_contracts = sum(b.contract_count for b in buckets)
    overall_vrp = sum(b.vrp * b.contract_count for b in buckets) / total_contracts
    overall_iv = sum(b.implied_vol * b.contract_count for b in buckets) / total_contracts
    overall_vrp_pct = (overall_vrp / overall_iv * 100) if overall_iv > 0 else 0.0
    richest = max(buckets, key=lambda b: b.vrp_pct)

    return VRPCurve(
        buckets=buckets, overall_vrp=overall_vrp,
        overall_vrp_pct=overall_vrp_pct, richest_bucket=richest.label,
    )


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
