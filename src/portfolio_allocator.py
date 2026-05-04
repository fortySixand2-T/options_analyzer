"""
Portfolio Allocator — Capital allocation between short-DTE and swing books.

Regime-based allocation rules:
    HIGH_IV + high VRP  → favor swing (VRP harvest via calendars/iron butterflies)
    LOW_IV + directional → favor short-DTE (debit spreads ride momentum)
    SPIKE               → reduce both, favor small debit only
    Base split           → 60% short-DTE / 40% swing

Options Analytics Team — 2026-05
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AllocationResult:
    """Capital allocation between short-DTE and swing books."""
    short_dte_pct: float        # 0-1, fraction of risk capital for short-DTE
    swing_pct: float            # 0-1, fraction of risk capital for swing
    rationale: str
    regime: str
    vrp_rich: bool
    directional: bool

    @property
    def short_dte_dollars(self) -> float:
        return 0.0

    def for_portfolio(self, portfolio_value: float, max_risk_pct: float = 0.10):
        """Compute dollar allocations for a given portfolio."""
        total_risk = portfolio_value * max_risk_pct
        return {
            "short_dte": {
                "pct": round(self.short_dte_pct, 2),
                "dollars": round(total_risk * self.short_dte_pct, 2),
            },
            "swing": {
                "pct": round(self.swing_pct, 2),
                "dollars": round(total_risk * self.swing_pct, 2),
            },
            "total_risk_budget": round(total_risk, 2),
            "rationale": self.rationale,
        }

    def to_dict(self) -> dict:
        return {
            "short_dte_pct": round(self.short_dte_pct, 2),
            "swing_pct": round(self.swing_pct, 2),
            "rationale": self.rationale,
            "regime": self.regime,
            "vrp_rich": self.vrp_rich,
            "directional": self.directional,
        }


# Base allocation: 60% short-DTE, 40% swing
BASE_SHORT_DTE = 0.60
BASE_SWING = 0.40

# Regime adjustments (additive shifts to short-DTE allocation, swing gets remainder)
_REGIME_SHIFTS = {
    "HIGH_IV": -0.10,       # shift 10% from short-DTE to swing
    "MODERATE_IV": 0.0,     # keep base
    "LOW_IV": 0.10,         # shift 10% to short-DTE
    "SPIKE": 0.20,          # heavily favor short-DTE (small debits only)
}


def compute_allocation(
    regime: str,
    vrp_rich: bool = False,
    vrp_pct: float = 0.0,
    directional: bool = False,
    swing_bias_score: int = 0,
) -> AllocationResult:
    """Compute capital allocation between short-DTE and swing books.

    Parameters
    ----------
    regime : str
        Current market regime (HIGH_IV, MODERATE_IV, LOW_IV, SPIKE).
    vrp_rich : bool
        Whether VRP exceeds threshold (premium sellers' edge).
    vrp_pct : float
        VRP as percentage (e.g., 5.0 means 5%).
    directional : bool
        Whether swing bias shows clear direction (not NEUTRAL).
    swing_bias_score : int
        Swing bias score (-10 to +10). Absolute value > 5 = strong direction.
    """
    short_pct = BASE_SHORT_DTE
    parts = []

    # 1. Regime shift
    shift = _REGIME_SHIFTS.get(regime, 0.0)
    short_pct += shift
    if shift != 0:
        direction = "short-DTE" if shift > 0 else "swing"
        parts.append(f"{regime} shifts {abs(shift):.0%} to {direction}")

    # 2. VRP adjustment: rich VRP favors swing (sell premium at 30-45 DTE)
    if vrp_rich and regime != "SPIKE":
        vrp_shift = min(0.10, vrp_pct / 100.0)  # up to 10% extra to swing
        short_pct -= vrp_shift
        parts.append(f"VRP {vrp_pct:.1f}% shifts {vrp_shift:.0%} to swing")

    # 3. Strong directional bias favors short-DTE (momentum plays, tight DTE)
    if directional and abs(swing_bias_score) >= 7 and regime in ("LOW_IV", "MODERATE_IV"):
        short_pct += 0.05
        parts.append("strong directional shifts 5% to short-DTE")

    # 4. SPIKE override: cap swing at 20% (high uncertainty, avoid long-dated short vol)
    if regime == "SPIKE":
        short_pct = max(short_pct, 0.80)
        parts.append("SPIKE caps swing at 20%")

    # Clamp to valid range
    short_pct = max(0.20, min(0.90, short_pct))
    swing_pct = 1.0 - short_pct

    rationale = "; ".join(parts) if parts else "base allocation 60/40"

    return AllocationResult(
        short_dte_pct=round(short_pct, 2),
        swing_pct=round(swing_pct, 2),
        rationale=rationale,
        regime=regime,
        vrp_rich=vrp_rich,
        directional=directional,
    )


def available_risk_for_book(
    book: str,
    allocation: AllocationResult,
    portfolio_value: float,
    max_risk_pct: float = 0.10,
    current_book_risk: float = 0.0,
) -> float:
    """How much additional risk budget remains for a given book.

    Parameters
    ----------
    book : str
        "short_dte" or "swing".
    allocation : AllocationResult
        Current allocation split.
    portfolio_value : float
        Total portfolio value.
    max_risk_pct : float
        Max total risk as fraction of portfolio.
    current_book_risk : float
        Current risk already deployed in this book.

    Returns
    -------
    float
        Available risk in dollars (>= 0).
    """
    total_budget = portfolio_value * max_risk_pct
    if book == "short_dte":
        book_budget = total_budget * allocation.short_dte_pct
    elif book == "swing":
        book_budget = total_budget * allocation.swing_pct
    else:
        return 0.0

    return max(0.0, book_budget - current_book_risk)
