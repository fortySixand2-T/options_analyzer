#!/usr/bin/env python3
"""
MC Greeks via Bump-and-Reprice (Common Random Numbers)
=======================================================

Estimates Delta, Gamma, Vega, Theta, Rho by perturbing one parameter at a
time and repricing via Monte Carlo.  All repricing calls share the same
random seed (Common Random Numbers) so path-level noise cancels in the
finite differences, giving low-variance Greek estimates.

All Greeks are scaled to match the Black-Scholes conventions in
models/black_scholes.py:
  - Vega  : per 1 percentage-point (0.01) change in sigma
  - Rho   : per 1 percentage-point (0.01) change in r
  - Theta : per calendar day (negative for long options)
  - Delta : per $1 change in S
  - Gamma : per $1 change in S (second derivative)

Author: Options Analytics Team
Date: March 2026
"""

import copy
import numpy as np
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def _bump_config(config: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Return a deep copy of config with given fields overridden."""
    c = copy.deepcopy(config)
    c.update(overrides)
    return c


def _bump_expiry(config: Dict[str, Any], days: int) -> Dict[str, Any]:
    """Return config copy with expiration_date shifted by `days` calendar days."""
    c = copy.deepcopy(config)
    exp_date = datetime.strptime(c['expiration_date'], '%Y-%m-%d')
    new_date = exp_date + timedelta(days=days)
    c['expiration_date'] = new_date.strftime('%Y-%m-%d')
    return c


def compute_mc_greeks(
    config: Dict[str, Any],
    num_paths: int = 3000,
    num_steps: int = 252,
    seed: int = 42,
    use_garch: bool = False,
    historical_returns: Optional[np.ndarray] = None,
    use_jumps: bool = False,
    jump_params: Optional[Dict[str, float]] = None,
    eps_S_pct: float = 0.01,
    eps_sigma: float = 0.01,
    eps_r: float = 0.001,
) -> Dict[str, float]:
    """
    Compute MC Greeks for a single option config via bump-and-reprice.

    Uses Common Random Numbers (same seed for all calls) to minimise
    noise in finite-difference estimates.

    Parameters
    ----------
    config : dict
        Standard option config (current_price, strike_price, expiration_date,
        implied_volatility, risk_free_rate, option_type, ...).
    num_paths : int
        Paths per reprice call (3 000 gives ~1 s total runtime).
    num_steps : int
        Steps per path.
    seed : int
        Shared seed for CRN.
    use_garch : bool
        Pass through to run_monte_carlo().
    historical_returns : np.ndarray, optional
        Pass through to run_monte_carlo() for GARCH calibration.
    use_jumps : bool
        Pass through to run_monte_carlo().
    jump_params : dict, optional
        Pass through to run_monte_carlo().
    eps_S_pct : float
        Fractional bump size for S (default 1 %).
    eps_sigma : float
        Absolute bump size for sigma (default 0.01 = 1 vol point).
    eps_r : float
        Absolute bump size for r (default 0.001 = 10 bps).

    Returns
    -------
    dict with keys:
        delta, gamma, vega, theta, rho  (MC estimates)
        bs_delta, bs_gamma, bs_vega, bs_theta, bs_rho  (Black-Scholes values)
    """
    from .gbm_simulator import run_monte_carlo
    from models.black_scholes import calculate_greeks, black_scholes_price
    from .gbm_simulator import _time_to_expiry

    S0 = config['current_price']
    sigma = config['implied_volatility']
    r = config.get('risk_free_rate', 0.045)
    option_type = config.get('option_type', 'call').lower()
    T = _time_to_expiry(config)

    # Shared kwargs for all run_monte_carlo calls (CRN via same seed)
    mc_kw = dict(
        num_paths=num_paths,
        num_steps=num_steps,
        seed=seed,
        use_garch=use_garch,
        historical_returns=historical_returns,
        use_jumps=use_jumps,
        jump_params=jump_params,
    )

    # --- Base price ---
    V0 = run_monte_carlo(config, **mc_kw)['mc_price']

    # --- Delta & Gamma: bump S ---
    h_S = S0 * eps_S_pct
    V_S_up = run_monte_carlo(_bump_config(config, current_price=S0 + h_S), **mc_kw)['mc_price']
    V_S_dn = run_monte_carlo(_bump_config(config, current_price=S0 - h_S), **mc_kw)['mc_price']

    mc_delta = (V_S_up - V_S_dn) / (2.0 * h_S)
    mc_gamma = (V_S_up - 2.0 * V0 + V_S_dn) / (h_S ** 2)

    # --- Vega: bump sigma (per 1 vol point = per eps_sigma change) ---
    V_sig_up = run_monte_carlo(_bump_config(config, implied_volatility=sigma + eps_sigma), **mc_kw)['mc_price']
    V_sig_dn = run_monte_carlo(_bump_config(config, implied_volatility=sigma - eps_sigma), **mc_kw)['mc_price']
    # Scale to "per 1 percentage-point (0.01)" change — matches BS convention
    mc_vega = (V_sig_up - V_sig_dn) / (2.0 * eps_sigma) * 0.01

    # --- Theta: bump expiration -1 day (one-sided backward) ---
    # V_theta - V0 is already the per-calendar-day change, matching BS convention
    config_theta = _bump_expiry(config, days=-1)
    V_theta = run_monte_carlo(config_theta, **mc_kw)['mc_price']
    mc_theta = V_theta - V0   # per calendar day (negative for long options)

    # --- Rho: bump r (per 1 percentage-point = per 0.01 change in r) ---
    V_r_up = run_monte_carlo(_bump_config(config, risk_free_rate=r + eps_r), **mc_kw)['mc_price']
    V_r_dn = run_monte_carlo(_bump_config(config, risk_free_rate=r - eps_r), **mc_kw)['mc_price']
    # Scale to "per 1 percentage-point (0.01)" — matches BS convention
    mc_rho = (V_r_up - V_r_dn) / (2.0 * eps_r) * 0.01

    # --- Black-Scholes reference Greeks ---
    bs_g = calculate_greeks(S0, config['strike_price'], T, r, sigma, option_type)

    return {
        'delta':    mc_delta,
        'gamma':    mc_gamma,
        'vega':     mc_vega,
        'theta':    mc_theta,
        'rho':      mc_rho,
        'bs_delta': bs_g['Delta'],
        'bs_gamma': bs_g['Gamma'],
        'bs_vega':  bs_g['Vega'],
        'bs_theta': bs_g['Theta'],
        'bs_rho':   bs_g['Rho'],
    }
