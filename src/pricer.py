"""
Thin wrapper over the bundled options pricing source (pricing/src/).

The pricing source (Black-Scholes, Monte Carlo, IV surface) is bundled
verbatim under src/ and accessed via a local sys.path shim — the same
pattern used in the standalone scanner.  No external path dependencies.
"""
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from config import MC_NUM_PATHS, MC_NUM_STEPS, MC_SEED, RISK_FREE_RATE

logger = logging.getLogger(__name__)

# ── Bootstrap bundled pricing source ─────────────────────────────────────────
# The source modules use bare imports (e.g. `from models import ...` or
# `from .sibling import ...`), so we add src/ — not the package root — to
# sys.path so those bare imports resolve correctly.
_SRC = str(Path(__file__).parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

try:
    from models.black_scholes import black_scholes_price, calculate_greeks
    from monte_carlo.gbm_simulator import run_monte_carlo
    from analytics.vol_surface import fetch_vol_surface
    _AVAILABLE = True
except ImportError as exc:
    logger.error(f"Options pricing source import failed: {exc}")
    _AVAILABLE = False


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
    if not _AVAILABLE:
        return {"price": 0.0, "greeks": {}}
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
    if not _AVAILABLE:
        return {"mc_price": config.get("implied_volatility", 0), "payoffs": np.array([])}

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
    if not _AVAILABLE:
        return None
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
    if not _AVAILABLE or T_remaining <= 0:
        return max(S_target - K, 0) if option_type == "call" else max(K - S_target, 0)
    return float(black_scholes_price(S_target, K, T_remaining, r, sigma, option_type))
