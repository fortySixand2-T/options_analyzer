"""
Thin wrapper over the options pricing modules.

Provides convenience functions for Black-Scholes pricing, Monte Carlo
simulation, volatility surface fetching, and scenario repricing.
"""
import logging
from typing import Any, Dict, Optional

import numpy as np

from config import MC_NUM_PATHS, MC_NUM_STEPS, MC_SEED, RISK_FREE_RATE
from models.black_scholes import black_scholes_price, calculate_greeks
from monte_carlo.gbm_simulator import run_monte_carlo
from analytics.vol_surface import fetch_vol_surface

logger = logging.getLogger(__name__)


# ── Public helpers ─────────────────────────────────────────────────────────────

def price_bs(
    S: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str = "call",
    r: float = RISK_FREE_RATE,
) -> Dict[str, Any]:
    """Black-Scholes price and Greeks. Returns zeros if T <= 0."""
    if T <= 0:
        intrinsic = max(S - K, 0) if option_type == "call" else max(K - S, 0)
        return {"price": intrinsic, "greeks": {}}

    price  = float(black_scholes_price(S, K, T, r, sigma, option_type))
    greeks = calculate_greeks(S, K, T, r, sigma, option_type)
    return {"price": price, "greeks": greeks}


def price_mc(
    config: Dict[str, Any],
    historical_returns: Optional[np.ndarray] = None,
    use_jumps: bool = True,
    option_style: str = "european",
) -> Dict[str, Any]:
    """Run Monte Carlo simulation. Returns a minimal dict on failure."""
    jump_params = {"lam": 0.1, "mu_J": -0.05, "sigma_J": 0.15} if use_jumps else None

    try:
        return run_monte_carlo(
            config=config,
            num_paths=MC_NUM_PATHS,
            num_steps=MC_NUM_STEPS,
            seed=MC_SEED,
            antithetic=True,
            use_garch=False,
            historical_returns=historical_returns,
            use_jumps=use_jumps,
            jump_params=jump_params,
            option_style=option_style,
        )
    except Exception as exc:
        logger.warning(f"MC simulation failed: {exc}")
        return {"mc_price": 0.0, "payoffs": np.array([])}


def get_vol_surface(ticker: str, r: float = RISK_FREE_RATE):
    """Fetch IV surface DataFrame. Returns None if unavailable or empty."""
    try:
        df = fetch_vol_surface(ticker, r=r, max_expiries=6)
        return df if (df is not None and not df.empty) else None
    except Exception as exc:
        logger.warning(f"Vol surface fetch failed for {ticker}: {exc}")
        return None


def reprice_at(
    S_target: float,
    K: float,
    T_remaining: float,
    sigma: float,
    option_type: str,
    r: float = RISK_FREE_RATE,
) -> float:
    """BS price at a target underlying price with remaining time T_remaining."""
    if T_remaining <= 0:
        return max(S_target - K, 0) if option_type == "call" else max(K - S_target, 0)
    return float(black_scholes_price(S_target, K, T_remaining, r, sigma, option_type))
