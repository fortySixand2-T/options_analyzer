"""IV term structure analysis for calendar/diagonal spread signals.

Calendars profit when front-month IV is elevated relative to back-month.
Kinks in the term structure (abnormal IV at one expiry) signal event-driven
opportunity or mispricing.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ExpiryIV:
    """IV summary for a single expiry."""
    expiry: str             # YYYY-MM-DD
    dte: int
    atm_iv: float           # ATM implied vol
    put_25d_iv: float       # 25-delta put IV (0 if unavailable)
    call_25d_iv: float      # 25-delta call IV (0 if unavailable)
    contract_count: int


@dataclass
class TermStructure:
    """Full IV term structure snapshot."""
    expiries: List[ExpiryIV] = field(default_factory=list)
    front_iv: float = 0.0          # shortest expiry ATM IV
    back_iv: float = 0.0           # longest expiry ATM IV
    slope: float = 0.0             # (back - front) / front * 100 (positive = contango)
    slope_per_dte: float = 0.0     # slope normalized by DTE difference
    kink_expiry: Optional[str] = None   # expiry with abnormal IV elevation
    kink_magnitude: float = 0.0         # how many stdevs above trend
    contango: bool = True               # back > front
    calendar_signal: float = 0.0        # -1 to +1: positive = sell front / buy back

    def to_dict(self) -> dict:
        return {
            "expiries": [
                {
                    "expiry": e.expiry,
                    "dte": e.dte,
                    "atm_iv": round(e.atm_iv, 4),
                    "put_25d_iv": round(e.put_25d_iv, 4),
                    "call_25d_iv": round(e.call_25d_iv, 4),
                    "contract_count": e.contract_count,
                }
                for e in self.expiries
            ],
            "front_iv": round(self.front_iv, 4),
            "back_iv": round(self.back_iv, 4),
            "slope": round(self.slope, 2),
            "slope_per_dte": round(self.slope_per_dte, 4),
            "kink_expiry": self.kink_expiry,
            "kink_magnitude": round(self.kink_magnitude, 2),
            "contango": self.contango,
            "calendar_signal": round(self.calendar_signal, 3),
        }


def compute_iv_term_structure(chain_snapshot, spot: float) -> TermStructure:
    """Compute IV term structure from a chain snapshot.

    Groups contracts by expiry, computes ATM IV (nearest-to-money) and
    25-delta IV for each expiry, then analyzes the structure.

    Parameters
    ----------
    chain_snapshot : ChainSnapshot
        Full option chain with contracts.
    spot : float
        Current underlying price.

    Returns
    -------
    TermStructure
    """
    today = date.today()

    # Group contracts by expiry
    by_expiry: Dict[str, list] = {}
    for c in chain_snapshot.contracts:
        if c.implied_volatility is None or np.isnan(c.implied_volatility):
            continue
        if c.implied_volatility <= 0:
            continue
        by_expiry.setdefault(c.expiry, []).append(c)

    if not by_expiry:
        return TermStructure()

    expiry_ivs: List[ExpiryIV] = []

    for expiry_str, contracts in sorted(by_expiry.items()):
        try:
            expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        dte = (expiry_date - today).days
        if dte < 0:
            continue

        atm_iv = _compute_atm_iv(contracts, spot)
        put_25d_iv, call_25d_iv = _compute_wing_iv(contracts, spot)

        expiry_ivs.append(ExpiryIV(
            expiry=expiry_str,
            dte=dte,
            atm_iv=atm_iv,
            put_25d_iv=put_25d_iv,
            call_25d_iv=call_25d_iv,
            contract_count=len(contracts),
        ))

    if not expiry_ivs:
        return TermStructure()

    expiry_ivs.sort(key=lambda e: e.dte)

    front = expiry_ivs[0]
    back = expiry_ivs[-1]

    slope = ((back.atm_iv - front.atm_iv) / front.atm_iv * 100) if front.atm_iv > 0 else 0.0
    dte_diff = back.dte - front.dte
    slope_per_dte = (slope / dte_diff) if dte_diff > 0 else 0.0
    contango = back.atm_iv > front.atm_iv

    kink_expiry, kink_magnitude = _detect_kink(expiry_ivs)

    calendar_signal = _compute_calendar_signal(slope, kink_magnitude, contango)

    return TermStructure(
        expiries=expiry_ivs,
        front_iv=front.atm_iv,
        back_iv=back.atm_iv,
        slope=slope,
        slope_per_dte=slope_per_dte,
        kink_expiry=kink_expiry,
        kink_magnitude=kink_magnitude,
        contango=contango,
        calendar_signal=calendar_signal,
    )


def _compute_atm_iv(contracts: list, spot: float) -> float:
    """ATM IV = average IV of the two strikes nearest to spot."""
    by_distance = sorted(contracts, key=lambda c: abs(c.strike - spot))
    nearest = by_distance[:4]
    if not nearest:
        return 0.0
    return float(np.mean([c.implied_volatility for c in nearest]))


def _compute_wing_iv(contracts: list, spot: float) -> Tuple[float, float]:
    """Approximate 25-delta wing IVs.

    Uses strikes at ~5% OTM for puts and calls as a proxy for 25-delta.
    """
    put_target = spot * 0.95
    call_target = spot * 1.05

    puts = [c for c in contracts if c.option_type == "put"]
    calls = [c for c in contracts if c.option_type == "call"]

    put_25d = 0.0
    if puts:
        nearest_put = min(puts, key=lambda c: abs(c.strike - put_target))
        put_25d = nearest_put.implied_volatility

    call_25d = 0.0
    if calls:
        nearest_call = min(calls, key=lambda c: abs(c.strike - call_target))
        call_25d = nearest_call.implied_volatility

    return put_25d, call_25d


def _detect_kink(expiry_ivs: List[ExpiryIV]) -> Tuple[Optional[str], float]:
    """Detect abnormal IV elevation at a specific expiry.

    Fits a linear trend through the term structure and finds the
    expiry with the largest positive residual (in standard deviations).
    A kink > 1.5 stdev suggests event-driven IV inflation at that expiry.
    """
    if len(expiry_ivs) < 3:
        return None, 0.0

    dtes = np.array([e.dte for e in expiry_ivs], dtype=float)
    ivs = np.array([e.atm_iv for e in expiry_ivs])

    coeffs = np.polyfit(dtes, ivs, 1)
    trend = np.polyval(coeffs, dtes)
    residuals = ivs - trend

    std = float(np.std(residuals))
    if std < 1e-6:
        return None, 0.0

    zscores = residuals / std
    max_idx = int(np.argmax(zscores))
    max_zscore = float(zscores[max_idx])

    if max_zscore > 1.5:
        return expiry_ivs[max_idx].expiry, max_zscore

    return None, 0.0


def _compute_calendar_signal(slope: float, kink_magnitude: float, contango: bool) -> float:
    """Calendar trade signal: -1 (avoid) to +1 (strong opportunity).

    Positive signal = sell front-month, buy back-month.
    Strong signal when: front IV is elevated (backwardation or kink at front),
    and back-month IV is relatively cheap.
    """
    signal = 0.0

    # Backwardation (front > back) is good for calendars
    if not contango:
        signal += min(abs(slope) / 10.0, 0.5)

    # Kink at a specific expiry amplifies the signal
    if kink_magnitude > 1.5:
        signal += min((kink_magnitude - 1.5) / 3.0, 0.5)

    # Strong contango reduces calendar attractiveness
    if contango and slope > 5.0:
        signal -= min((slope - 5.0) / 15.0, 0.5)

    return max(-1.0, min(1.0, signal))


def term_structure_slope(front_iv: float, back_iv: float) -> float:
    """Normalized slope between two IV points."""
    if front_iv <= 0:
        return 0.0
    return (back_iv - front_iv) / front_iv * 100
