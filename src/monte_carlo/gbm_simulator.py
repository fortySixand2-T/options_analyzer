#!/usr/bin/env python3
"""
GBM Path Simulator
==================

Core Monte Carlo simulation engine using Geometric Brownian Motion.
Implements vectorized path generation and option pricing on simulated paths.

GBM dynamics:
    S(t+dt) = S(t) * exp((r - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
where Z ~ N(0,1).

Author: Options Analytics Team
Date: March 2026
"""

import warnings
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any

from .risk_metrics import compute_var, compute_cvar, compute_distribution_stats


def simulate_gbm_paths(
    S0: float,
    r: float,
    sigma: float,
    T: float,
    num_paths: int,
    num_steps: int,
    seed: Optional[int] = None,
    antithetic: bool = False,
) -> np.ndarray:
    """
    Simulate GBM stock price paths.

    Parameters:
    -----------
    S0 : float
        Initial stock price
    r : float
        Risk-free rate (annual)
    sigma : float
        Volatility (annual)
    T : float
        Time to expiration (in years)
    num_paths : int
        Number of simulation paths
    num_steps : int
        Number of time steps per path
    seed : int, optional
        Random seed for reproducibility
    antithetic : bool
        If True, use antithetic variates for variance reduction
        (generates num_paths/2 base paths + their negatives)

    Returns:
    --------
    np.ndarray
        Shape (num_paths, num_steps+1); paths[:, 0] == S0
    """
    rng = np.random.default_rng(seed)
    dt = T / num_steps
    drift = (r - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt)

    if antithetic:
        half = num_paths // 2
        Z_half = rng.standard_normal((half, num_steps))
        Z = np.concatenate([Z_half, -Z_half], axis=0)
        # If num_paths is odd, add one more path
        if num_paths % 2 == 1:
            Z = np.concatenate([Z, rng.standard_normal((1, num_steps))], axis=0)
    else:
        Z = rng.standard_normal((num_paths, num_steps))

    # Increments: shape (num_paths, num_steps)
    log_increments = drift + diffusion * Z

    # Build paths: prepend log(S0), cumsum, exponentiate
    log_paths = np.empty((num_paths, num_steps + 1))
    log_paths[:, 0] = np.log(S0)
    log_paths[:, 1:] = np.log(S0) + np.cumsum(log_increments, axis=1)

    return np.exp(log_paths)


def price_option_on_paths(
    paths: np.ndarray,
    K: float,
    r: float,
    T: float,
    option_type: str = 'call',
) -> np.ndarray:
    """
    Price a European option on simulated terminal prices.

    Computes discounted payoff for each path using the terminal stock price.

    Parameters:
    -----------
    paths : np.ndarray
        Shape (num_paths, num_steps+1) from simulate_gbm_paths
    K : float
        Strike price
    r : float
        Risk-free rate (annual)
    T : float
        Time to expiration (in years)
    option_type : str
        'call' or 'put'

    Returns:
    --------
    np.ndarray
        Shape (num_paths,); discounted payoff per path
    """
    S_T = paths[:, -1]
    discount = np.exp(-r * T)

    if option_type.lower() == 'call':
        payoffs = discount * np.maximum(S_T - K, 0.0)
    else:
        payoffs = discount * np.maximum(K - S_T, 0.0)

    return payoffs


def simulate_garch_paths(
    S0: float,
    r: float,
    omega: float,
    alpha: float,
    beta: float,
    sigma0: float,
    T: float,
    num_paths: int,
    num_steps: int,
    seed: Optional[int] = None,
    antithetic: bool = False,
) -> np.ndarray:
    """
    Simulate stock price paths using GARCH(1,1) time-varying volatility.

    Each path has its own independent GARCH vol trajectory driven by the
    same random shocks used for the price dynamics.

    Parameters
    ----------
    S0 : float
        Initial stock price.
    r : float
        Risk-free rate (annual).
    omega, alpha, beta : float
        Fitted GARCH(1,1) parameters (daily units).
    sigma0 : float
        Starting conditional vol (annualised).
    T : float
        Time to expiration (years).
    num_paths, num_steps : int
    seed : int, optional
    antithetic : bool
        Mirror half the paths for variance reduction.

    Returns
    -------
    np.ndarray, shape (num_paths, num_steps+1)
        paths[:, 0] == S0 for all paths.
    """
    from .garch_vol import simulate_garch_vol_paths

    rng = np.random.default_rng(seed)
    dt = T / num_steps

    if antithetic:
        half = num_paths // 2
        Z_half = rng.standard_normal((half, num_steps))
        Z = np.concatenate([Z_half, -Z_half], axis=0)
        if num_paths % 2 == 1:
            Z = np.concatenate([Z, rng.standard_normal((1, num_steps))], axis=0)
    else:
        Z = rng.standard_normal((num_paths, num_steps))

    # GARCH vol paths: shape (num_paths, num_steps), annualised vol per step
    garch_vols = simulate_garch_vol_paths(omega, alpha, beta, sigma0, num_paths, num_steps, Z)

    # Convert annualised vols to per-step increments
    sigma_dt = garch_vols * np.sqrt(dt)                    # (num_paths, num_steps)
    drift_dt = (r - 0.5 * garch_vols ** 2) * dt           # (num_paths, num_steps)

    log_increments = drift_dt + sigma_dt * Z               # (num_paths, num_steps)

    log_paths = np.empty((num_paths, num_steps + 1))
    log_paths[:, 0] = np.log(S0)
    log_paths[:, 1:] = np.log(S0) + np.cumsum(log_increments, axis=1)

    return np.exp(log_paths)


def _time_to_expiry(config: Dict[str, Any]) -> float:
    """Compute T in years from config's expiration_date."""
    exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
    T = (exp_date - datetime.now()).days / 365.0
    return max(T, 1e-6)


def run_monte_carlo(
    config: Dict[str, Any],
    num_paths: int = 10000,
    num_steps: int = 252,
    seed: Optional[int] = None,
    confidence: float = 0.95,
    antithetic: bool = False,
    use_garch: bool = False,
    historical_returns: Optional[np.ndarray] = None,
    use_jumps: bool = False,
    jump_params: Optional[Dict[str, Any]] = None,
    option_style: str = 'european',
) -> Dict[str, Any]:
    """
    Orchestrate a full Monte Carlo simulation for a single option config.

    Uses Black-Scholes price as a reference and computes P&L distribution
    assuming the option was purchased at the BS price.

    Parameters:
    -----------
    config : Dict[str, Any]
        Option configuration dict (current_price, strike_price, expiration_date,
        implied_volatility, risk_free_rate, option_type, ...)
    num_paths : int
        Number of paths to simulate
    num_steps : int
        Number of daily time steps (252 = 1 trading year)
    seed : int, optional
        Random seed
    confidence : float
        Confidence level for VaR/CVaR
    antithetic : bool
        Enable antithetic variates
    use_garch : bool
        If True, fit GARCH(1,1) to historical_returns and use time-varying vol.
        Falls back to constant vol if historical_returns is None.
        Ignored when use_jumps=True (jump diffusion takes priority).
    historical_returns : np.ndarray, optional
        Array of daily returns for GARCH calibration (required when use_garch=True).
    use_jumps : bool
        If True, simulate with Merton jump-diffusion.  Takes priority over
        use_garch.  Falls back to GBM if jump_params cannot be resolved.
    jump_params : dict, optional
        Jump-diffusion parameters: {'lam', 'mu_J', 'sigma_J'}.
        If None, read from config['jump'] if present.
    option_style : str
        'european' (default) or 'american'.  When 'american', price is also
        computed via Longstaff-Schwartz LSMC on the simulated paths.

    Returns:
    --------
    Dict[str, Any]
        {mc_price, bs_price, std_error, var, cvar, percentiles, payoffs, paths,
         vol_model, garch_params, jump_params, american_price,
         early_exercise_premium}
    """
    # Import BS pricing from sibling models package
    from models.black_scholes import black_scholes_price

    S0 = config['current_price']
    K = config['strike_price']
    sigma = config['implied_volatility']
    r = config.get('risk_free_rate', 0.045)
    option_type = config.get('option_type', 'call').lower()

    # Apply MC overrides from config['monte_carlo'] if present
    mc_cfg = config.get('monte_carlo', {})
    num_paths = mc_cfg.get('num_paths', num_paths)
    num_steps = mc_cfg.get('num_steps', num_steps)
    if seed is None:
        seed = mc_cfg.get('seed', None)
    confidence = mc_cfg.get('confidence_level', confidence)
    antithetic = mc_cfg.get('antithetic', antithetic)

    # Pull historical_returns from config runtime field if not passed explicitly
    if historical_returns is None and '_historical_returns' in config:
        historical_returns = config['_historical_returns']

    T = _time_to_expiry(config)

    # Black-Scholes reference price
    bs_price = black_scholes_price(S0, K, T, r, sigma, option_type)

    # --- Simulate paths ---
    garch_params_result = None
    resolved_jump_params = None

    if use_jumps:
        # Resolve jump params: explicit arg > config['jump'] > fallback
        resolved_jump_params = jump_params
        if resolved_jump_params is None:
            resolved_jump_params = config.get('jump', None)

        if resolved_jump_params is not None:
            from .jump_diffusion import simulate_jump_paths
            paths = simulate_jump_paths(
                S0, r, sigma,
                resolved_jump_params['lam'],
                resolved_jump_params['mu_J'],
                resolved_jump_params['sigma_J'],
                T, num_paths, num_steps, seed, antithetic,
            )
            vol_model = 'jump'
        else:
            warnings.warn(
                "use_jumps=True but no jump_params provided and config has no "
                "'jump' key.  Falling back to constant-vol GBM.",
                UserWarning,
                stacklevel=2,
            )
            paths = simulate_gbm_paths(S0, r, sigma, T, num_paths, num_steps, seed, antithetic)
            vol_model = 'constant'

    elif use_garch:
        if historical_returns is None or len(historical_returns) < 30:
            warnings.warn(
                "use_garch=True but no sufficient historical_returns provided. "
                "Falling back to constant-vol GBM.",
                UserWarning,
                stacklevel=2,
            )
            paths = simulate_gbm_paths(S0, r, sigma, T, num_paths, num_steps, seed, antithetic)
            vol_model = 'constant'
        else:
            from .garch_vol import fit_garch11
            garch_params_result = fit_garch11(historical_returns)
            paths = simulate_garch_paths(
                S0, r,
                garch_params_result['omega'], garch_params_result['alpha'],
                garch_params_result['beta'], garch_params_result['sigma0'],
                T, num_paths, num_steps, seed, antithetic,
            )
            vol_model = 'garch'
    else:
        paths = simulate_gbm_paths(S0, r, sigma, T, num_paths, num_steps, seed, antithetic)
        vol_model = 'constant'

    # --- Price European option on terminal prices ---
    payoffs = price_option_on_paths(paths, K, r, T, option_type)

    mc_price = float(np.mean(payoffs))
    std_error = float(np.std(payoffs) / np.sqrt(num_paths))

    # --- American option pricing via Longstaff-Schwartz (if requested) ---
    american_price = None
    early_exercise_premium = None
    if option_style.lower() == 'american':
        from .american_mc import price_american_lsmc
        american_price, _ = price_american_lsmc(paths, K, r, T, option_type)
        early_exercise_premium = american_price - mc_price

    # P&L = payoff - entry cost (BS price as entry proxy)
    pnl = payoffs - bs_price

    var = compute_var(pnl, confidence)
    cvar = compute_cvar(pnl, confidence)
    percentiles = compute_distribution_stats(pnl)

    return {
        'mc_price': mc_price,
        'bs_price': bs_price,
        'std_error': std_error,
        'var': var,
        'cvar': cvar,
        'confidence': confidence,
        'percentiles': percentiles,
        'payoffs': payoffs,
        'paths': paths,
        'num_paths': num_paths,
        'num_steps': num_steps,
        'T': T,
        'vol_model': vol_model,
        'garch_params': garch_params_result,
        'jump_params': resolved_jump_params,
        'american_price': american_price,
        'early_exercise_premium': early_exercise_premium,
    }
