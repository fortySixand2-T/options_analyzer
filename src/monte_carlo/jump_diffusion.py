#!/usr/bin/env python3
"""
Merton Jump-Diffusion Path Simulator
=====================================

Implements the Merton (1976) jump-diffusion model.  Stock price follows GBM
with an additional compound Poisson jump component:

    S(t+dt) = S(t) * exp((r - λκ - ½σ²)dt + σ√dt·Z + J_t)

where
    κ = exp(μ_J + ½σ_J²) - 1          (drift compensator, risk-neutral)
    N ~ Poisson(λ·dt)                  (number of jumps per step)
    J_t = N*μ_J + √N*σ_J*ε            (compound log-jump, ε ~ N(0,1))

The drift compensator λκ ensures the discounted stock price remains a
martingale under the risk-neutral measure.

Author: Options Analytics Team
Date: March 2026
"""

import numpy as np
from typing import Optional


def simulate_jump_paths(
    S0: float,
    r: float,
    sigma: float,
    lam: float,
    mu_J: float,
    sigma_J: float,
    T: float,
    num_paths: int,
    num_steps: int,
    seed: Optional[int] = None,
    antithetic: bool = False,
) -> np.ndarray:
    """
    Simulate stock price paths under Merton jump-diffusion.

    Parameters
    ----------
    S0 : float
        Initial stock price.
    r : float
        Risk-free rate (annual).
    sigma : float
        Diffusion volatility (annual), excluding jump component.
    lam : float
        Jump intensity — expected number of jumps per year (λ ≥ 0).
    mu_J : float
        Mean log-jump size (log-normal mean of each jump).
    sigma_J : float
        Std-dev of log-jump size (log-normal vol of each jump).
    T : float
        Time to expiration (years).
    num_paths : int
        Number of simulation paths.
    num_steps : int
        Number of time steps.
    seed : int, optional
        Random seed for reproducibility.
    antithetic : bool
        If True, mirror half the diffusion Z draws for variance reduction.
        Jump draws are NOT mirrored (they reduce variance independently).

    Returns
    -------
    np.ndarray
        Shape (num_paths, num_steps + 1); paths[:, 0] == S0.
    """
    rng = np.random.default_rng(seed)
    dt = T / num_steps

    # Risk-neutral drift compensator: κ = E[e^J] - 1
    kappa = np.exp(mu_J + 0.5 * sigma_J ** 2) - 1
    drift = (r - lam * kappa - 0.5 * sigma ** 2) * dt

    # --- Diffusion component (antithetic on Z only) ---
    if antithetic:
        half = num_paths // 2
        Z_half = rng.standard_normal((half, num_steps))
        Z = np.concatenate([Z_half, -Z_half], axis=0)
        if num_paths % 2 == 1:
            Z = np.concatenate([Z, rng.standard_normal((1, num_steps))], axis=0)
    else:
        Z = rng.standard_normal((num_paths, num_steps))

    # --- Jump component ---
    # Number of jumps per (path, step): N ~ Poisson(λ·dt)
    N = rng.poisson(lam * dt, size=(num_paths, num_steps))
    # Compound log-jump: sum of N iid N(μ_J, σ_J²) given N
    #   = N*μ_J + √N*σ_J*ε   (works at N=0 because √0 = 0)
    eps_J = rng.standard_normal((num_paths, num_steps))
    jump_log_rets = N * mu_J + np.sqrt(N) * sigma_J * eps_J

    # --- Assemble log-increments ---
    log_increments = drift + sigma * np.sqrt(dt) * Z + jump_log_rets

    # Build log-paths via cumsum, then exponentiate
    log_paths = np.empty((num_paths, num_steps + 1))
    log_paths[:, 0] = np.log(S0)
    log_paths[:, 1:] = np.log(S0) + np.cumsum(log_increments, axis=1)

    return np.exp(log_paths)
