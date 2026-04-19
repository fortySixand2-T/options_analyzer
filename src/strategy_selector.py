"""
Selects option strategy, strikes, and expiry for each (bias, outlook) pair.
Strikes are anchored to support/resistance levels wherever possible.

Every strategy is represented as a list of legs so multi-leg structures
(iron condor, spreads) price all contracts rather than just the primary one.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import OUTLOOKS, RISK_FREE_RATE  # noqa: F401 (re-exported)

OUTLOOK_ORDER = ["short", "medium", "long"]

# Credit strategies: net premium is received (positive net)
CREDIT_STRATEGIES = {"iron_condor", "short_strangle"}

# Primary strategy per (bias, outlook)
STRATEGY_MAP: Dict[Tuple[str, str], str] = {
    ("bullish",         "short"):  "long_call",
    ("bullish",         "medium"): "bull_call_spread",
    ("bullish",         "long"):   "long_call",
    ("bearish",         "short"):  "long_put",
    ("bearish",         "medium"): "bear_put_spread",
    ("bearish",         "long"):   "long_put",
    ("neutral_high_iv", "short"):  "iron_condor",
    ("neutral_high_iv", "medium"): "short_strangle",
    ("neutral_high_iv", "long"):   "iron_condor",
    ("neutral_low_iv",  "short"):  "long_straddle",
    ("neutral_low_iv",  "medium"): "long_strangle",
    ("neutral_low_iv",  "long"):   "long_strangle",
}


def _round_strike(price: float) -> float:
    """Round to the nearest natural strike increment based on price."""
    inc = 5.0 if price >= 100 else (2.5 if price >= 50 else 1.0)
    return round(round(price / inc) * inc, 2)


def find_expiry(
    vol_surface_df: Optional[pd.DataFrame],
    min_dte: int,
    max_dte: int,
    today: date,
) -> Tuple[str, float]:
    """
    Return (expiry_str 'YYYY-MM-DD', T_years) within the DTE window.
    Falls back to the midpoint DTE if the vol surface has no matching expiry.
    """
    if vol_surface_df is not None and not vol_surface_df.empty:
        exp_col = vol_surface_df[["expiry", "T"]].drop_duplicates().copy()
        exp_col["dte"] = exp_col["T"] * 365
        in_range = exp_col[(exp_col["dte"] >= min_dte) & (exp_col["dte"] <= max_dte)]
        if not in_range.empty:
            row = in_range.sort_values("dte").iloc[0]
            return str(row["expiry"]), float(row["T"])

    target_dte  = (min_dte + max_dte) // 2
    expiry_date = today + timedelta(days=target_dte)
    return expiry_date.strftime("%Y-%m-%d"), target_dte / 365.0


def get_iv_for_strike(
    vol_surface_df: Optional[pd.DataFrame],
    expiry: str,
    strike: float,
    option_type: str,
    fallback_iv: float,
) -> float:
    """
    Nearest-strike IV lookup from the vol surface.
    Returns fallback_iv when no surface data is available.
    """
    if vol_surface_df is None or vol_surface_df.empty:
        return fallback_iv

    subset = vol_surface_df[
        (vol_surface_df["expiry"].astype(str) == str(expiry)) &
        (vol_surface_df["option_type"] == option_type)
    ].copy()

    if subset.empty:
        subset = vol_surface_df[vol_surface_df["option_type"] == option_type].copy()

    if subset.empty:
        return fallback_iv

    subset["dist"] = (subset["strike"] - strike).abs()
    iv = float(subset.nsmallest(1, "dist")["iv"].iloc[0])
    return iv if 0 < iv < 5.0 else fallback_iv


def select_strikes(
    strategy: str,
    current_price: float,
    sr: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a structure describing every leg of the strategy.

    Return shape:
        {
            "legs": [
                {"action": "buy"|"sell", "option_type": "call"|"put", "strike": float},
                ...
            ],
            "target_price": float | None,
            "spread_width": float | None,
        }
    """
    res      = sr["nearest_resistance"]
    sup      = sr["nearest_support"]
    next_res = sr["next_resistance"]
    next_sup = sr["next_support"]

    if strategy == "long_call":
        k = _round_strike(res)
        return {
            "legs": [{"action": "buy", "option_type": "call", "strike": k}],
            "target_price": next_res,
            "spread_width": None,
        }

    if strategy == "long_put":
        k = _round_strike(sup)
        return {
            "legs": [{"action": "buy", "option_type": "put", "strike": k}],
            "target_price": next_sup,
            "spread_width": None,
        }

    if strategy == "bull_call_spread":
        long_k  = _round_strike(current_price)
        short_k = _round_strike(res)
        return {
            "legs": [
                {"action": "buy",  "option_type": "call", "strike": long_k},
                {"action": "sell", "option_type": "call", "strike": short_k},
            ],
            "target_price": res,
            "spread_width": round(short_k - long_k, 2),
        }

    if strategy == "bear_put_spread":
        long_k  = _round_strike(current_price)
        short_k = _round_strike(sup)
        return {
            "legs": [
                {"action": "buy",  "option_type": "put", "strike": long_k},
                {"action": "sell", "option_type": "put", "strike": short_k},
            ],
            "target_price": sup,
            "spread_width": round(long_k - short_k, 2),
        }

    if strategy == "iron_condor":
        long_put   = _round_strike(next_sup)
        short_put  = _round_strike(sup)
        short_call = _round_strike(res)
        long_call  = _round_strike(next_res)
        put_width  = round(short_put  - long_put,   2)
        call_width = round(long_call  - short_call, 2)
        return {
            "legs": [
                {"action": "buy",  "option_type": "put",  "strike": long_put},
                {"action": "sell", "option_type": "put",  "strike": short_put},
                {"action": "sell", "option_type": "call", "strike": short_call},
                {"action": "buy",  "option_type": "call", "strike": long_call},
            ],
            "target_price": None,
            "spread_width": max(put_width, call_width),
        }

    if strategy == "short_strangle":
        return {
            "legs": [
                {"action": "sell", "option_type": "put",  "strike": _round_strike(sup)},
                {"action": "sell", "option_type": "call", "strike": _round_strike(res)},
            ],
            "target_price": None,
            "spread_width": None,
        }

    if strategy == "long_straddle":
        k = _round_strike(current_price)
        return {
            "legs": [
                {"action": "buy", "option_type": "put",  "strike": k},
                {"action": "buy", "option_type": "call", "strike": k},
            ],
            "target_price": None,
            "spread_width": None,
        }

    if strategy == "long_strangle":
        return {
            "legs": [
                {"action": "buy", "option_type": "put",  "strike": _round_strike(sup)},
                {"action": "buy", "option_type": "call", "strike": _round_strike(res)},
            ],
            "target_price": None,
            "spread_width": None,
        }

    # Fallback — single ATM call
    return {
        "legs": [{"action": "buy", "option_type": "call", "strike": _round_strike(current_price)}],
        "target_price": None,
        "spread_width": None,
    }


def get_primary_leg(legs: List[Dict]) -> Dict:
    """
    Return the leg most representative of the position's risk for MC simulation.
    For credit strategies: the first short leg.
    For debit strategies: the first buy leg.
    """
    for leg in legs:
        if leg["action"] == "sell":
            return leg
    return legs[0]
