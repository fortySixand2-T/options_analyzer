#!/usr/bin/env python3
"""
GARCH(1,1) Volatility Model
============================

Fits a GARCH(1,1) model to historical returns via MLE and simulates
time-varying volatility paths for use in Monte Carlo pricing.

GARCH(1,1) dynamics:
    sigma²(t) = omega + alpha * eps²(t-1) + beta * sigma²(t-1)
    eps(t)    = sigma(t) * Z(t),  Z ~ N(0,1)

Stationarity constraint: alpha + beta < 1.

Author: Options Analytics Team
Date: March 2026
"""

import numpy as np
import warnings
from typing import Optional


def _garch_loglik(params, returns):
    """
    Negative Gaussian log-likelihood for GARCH(1,1).

    Minimise this to obtain MLE estimates.
    """
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 1.0:
        return 1e10

    n = len(returns)
    sigma2 = np.empty(n)
    sigma2[0] = np.var(returns)

    for t in range(1, n):
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]

    if np.any(sigma2 <= 0):
        return 1e10

    return 0.5 * np.sum(np.log(sigma2) + returns ** 2 / sigma2)


def fit_garch11(returns: np.ndarray) -> dict:
    """
    Fit a GARCH(1,1) model to a series of returns via MLE (Nelder-Mead).

    Parameters
    ----------
    returns : np.ndarray
        1-D array of daily log or simple returns.

    Returns
    -------
    dict with keys:
        omega       : baseline variance term (daily)
        alpha       : shock coefficient
        beta        : persistence coefficient
        sigma0      : current conditional vol (annualised)
                      — the last step of the fitted variance path
        long_run_vol: long-run (unconditional) annualised vol
        converged   : bool — optimiser convergence flag
    """
    from scipy.optimize import minimize

    returns = np.asarray(returns, dtype=float)
    var0 = np.var(returns)

    # Starting point: typical GARCH(1,1) values
    omega0 = var0 * (1.0 - 0.10 - 0.85)
    x0 = [max(omega0, 1e-8), 0.10, 0.85]

    result = minimize(
        _garch_loglik,
        x0,
        args=(returns,),
        method='Nelder-Mead',
        options={'maxiter': 10000, 'xatol': 1e-8, 'fatol': 1e-8},
    )

    omega, alpha, beta = result.x

    # Clamp to feasible region in case optimizer drifts slightly
    omega = max(omega, 1e-8)
    alpha = max(alpha, 0.0)
    beta = max(beta, 0.0)

    # Cap alpha+beta to maintain stationarity
    if alpha + beta >= 1.0:
        scale = 0.9999 / (alpha + beta)
        alpha *= scale
        beta *= scale

    # Reconstruct conditional variance path to get current (last) vol
    n = len(returns)
    sigma2 = np.empty(n)
    sigma2[0] = var0
    for t in range(1, n):
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]

    # sigma0: current (most-recent) conditional vol, annualised
    sigma0 = float(np.sqrt(sigma2[-1] * 252))

    # Long-run unconditional vol
    denom = 1.0 - alpha - beta
    if denom <= 0:
        long_run_vol = sigma0
    else:
        long_run_vol = float(np.sqrt(omega / denom * 252))

    return {
        'omega': float(omega),
        'alpha': float(alpha),
        'beta': float(beta),
        'sigma0': sigma0,
        'long_run_vol': long_run_vol,
        'converged': bool(result.success),
    }


def simulate_garch_vol_paths(
    omega: float,
    alpha: float,
    beta: float,
    sigma0: float,
    num_paths: int,
    num_steps: int,
    Z: np.ndarray,
) -> np.ndarray:
    """
    Simulate GARCH(1,1) conditional volatility paths.

    Each path receives an independent variance trajectory driven by the
    pre-drawn shocks Z (which may be antithetic).

    Parameters
    ----------
    omega, alpha, beta : float
        Fitted GARCH parameters (daily units).
    sigma0 : float
        Starting conditional vol in **annualised** units.
        Converted internally to daily variance for the recursion.
    num_paths : int
    num_steps  : int
    Z : np.ndarray, shape (num_paths, num_steps)
        Pre-drawn standard normal shocks.

    Returns
    -------
    np.ndarray, shape (num_paths, num_steps)
        Annualised conditional volatility at each step for each path.
    """
    # Convert annualised sigma0 → daily variance
    sigma2_current = np.full(num_paths, (sigma0 / np.sqrt(252)) ** 2)

    vol_paths = np.empty((num_paths, num_steps))

    for t in range(num_steps):
        # Realised shock from previous step's vol × current Z
        eps2 = sigma2_current * Z[:, t] ** 2  # shape (num_paths,)

        # GARCH recursion (all operations vectorised over paths)
        sigma2_current = omega + alpha * eps2 + beta * sigma2_current

        # Ensure positivity (numerical guard)
        sigma2_current = np.maximum(sigma2_current, 1e-12)

        # Store annualised vol
        vol_paths[:, t] = np.sqrt(sigma2_current * 252)

    return vol_paths
