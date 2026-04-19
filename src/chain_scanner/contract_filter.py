"""
Contract filter for the options chain scanner.

Filters raw option contracts by DTE, moneyness, liquidity (open interest
and bid-ask spread), and BS delta. Contracts with NaN IV are excluded.

Options Analytics Team — 2026-04-02
"""

import logging
import math
from pathlib import Path
import sys
from datetime import datetime
from typing import List

_SRC = str(Path(__file__).resolve().parent.parent / "pricing" / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from models.black_scholes import calculate_greeks

from .providers.base import OptionContract

logger = logging.getLogger(__name__)


def filter_contracts(contracts: List[OptionContract],
                     spot: float,
                     risk_free_rate: float,
                     min_dte: int = 20,
                     max_dte: int = 60,
                     min_delta: float = 0.15,
                     max_delta: float = 0.50,
                     min_oi: int = 100,
                     max_spread_pct: float = 15.0,
                     moneyness_range: tuple = (0.85, 1.15)) -> List[OptionContract]:
    """Filter option contracts by DTE, moneyness, liquidity, and delta.

    Parameters
    ----------
    contracts : List[OptionContract]
        Raw contracts from a ChainSnapshot.
    spot : float
        Current spot price.
    risk_free_rate : float
        Annualized risk-free rate.
    min_dte, max_dte : int
        Allowed DTE range (inclusive).
    min_delta, max_delta : float
        Allowed absolute delta range (inclusive).
    min_oi : int
        Minimum open interest.
    max_spread_pct : float
        Maximum bid-ask spread as % of mid price.
    moneyness_range : tuple
        (low, high) bounds for strike/spot.

    Returns
    -------
    List[OptionContract]
        Contracts passing all filters.
    """
    now = datetime.now()
    passed = []

    for c in contracts:
        # --- IV check ---
        if math.isnan(c.implied_volatility) or c.implied_volatility <= 0:
            continue

        # --- DTE ---
        try:
            exp_dt = datetime.strptime(c.expiry, '%Y-%m-%d')
        except ValueError:
            continue
        dte = (exp_dt - now).days
        if dte < min_dte or dte > max_dte:
            continue

        # --- Moneyness ---
        moneyness = c.strike / spot
        if moneyness < moneyness_range[0] or moneyness > moneyness_range[1]:
            continue

        # --- Liquidity: open interest ---
        if c.open_interest < min_oi:
            continue

        # --- Liquidity: bid-ask spread ---
        if c.mid <= 0:
            continue
        spread_pct = (c.ask - c.bid) / c.mid * 100
        if spread_pct > max_spread_pct:
            continue

        # --- Delta filter ---
        T = dte / 365.0
        try:
            greeks = calculate_greeks(
                S=spot, K=c.strike, T=T, r=risk_free_rate,
                sigma=c.implied_volatility, option_type=c.option_type,
            )
            delta = abs(greeks['Delta'])
        except Exception:
            continue
        if delta < min_delta or delta > max_delta:
            continue

        passed.append(c)

    logger.debug("Filter: %d/%d contracts passed", len(passed), len(contracts))
    return passed
