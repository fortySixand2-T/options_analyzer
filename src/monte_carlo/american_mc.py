#!/usr/bin/env python3
"""
American Option Pricing via Longstaff-Schwartz Monte Carlo
===========================================================

Implements the Longstaff-Schwartz (2001) least-squares Monte Carlo (LSMC)
algorithm for pricing American options with early-exercise features.

The algorithm works by backward induction on already-simulated paths:
  1.  Assign terminal payoffs at t = T.
  2.  For each time step t = T−dt … dt (backward):
        a. Discount the continuation cash-flows one step.
        b. Identify in-the-money paths at t.
        c. Regress discounted continuation values on polynomial basis in S(t).
        d. Where intrinsic > fitted continuation → early exercise.
  3.  Discount from t = dt back to t = 0 and take the mean.

Basis functions are (S/K)^1, (S/K)^2, …, (S/K)^degree — normalised by K
for numerical stability.

Reference:
    Longstaff & Schwartz, "Valuing American Options by Simulation:
    A Simple Least-Squares Approach", RFS 14(1), 2001.

Author: Options Analytics Team
Date: March 2026
"""

import numpy as np
from typing import Tuple


def price_american_lsmc(
    paths: np.ndarray,
    K: float,
    r: float,
    T: float,
    option_type: str = 'put',
    degree: int = 3,
) -> Tuple[float, float]:
    """
    Price an American option on pre-simulated paths via Longstaff-Schwartz.

    Parameters
    ----------
    paths : np.ndarray
        Shape (num_paths, num_steps + 1) from any simulator.
        paths[:, 0] must equal S0 for all paths.
    K : float
        Strike price.
    r : float
        Annual risk-free rate.
    T : float
        Time to expiration in years.
    option_type : str
        'put' or 'call'.
    degree : int
        Polynomial degree for the continuation-value regression basis.

    Returns
    -------
    (price, std_error) : (float, float)
        price     : American option price estimate.
        std_error : Standard error of the mean (MC noise).
    """
    num_paths, num_steps_plus1 = paths.shape
    num_steps = num_steps_plus1 - 1
    dt = T / num_steps
    discount = np.exp(-r * dt)

    is_put = option_type.lower() == 'put'

    def _payoff(S: np.ndarray) -> np.ndarray:
        if is_put:
            return np.maximum(K - S, 0.0)
        else:
            return np.maximum(S - K, 0.0)

    # --- Initialise with terminal payoffs ---
    cash_flows = _payoff(paths[:, -1]).copy()

    # --- Backward induction: t = num_steps-1 … 1 ---
    for t_idx in range(num_steps - 1, 0, -1):
        # Discount continuation one step back to time t_idx * dt
        cash_flows *= discount

        S_t = paths[:, t_idx]
        intrinsic = _payoff(S_t)

        # Only regress on in-the-money paths
        itm = intrinsic > 0.0
        n_itm = np.sum(itm)
        if n_itm < degree + 1:
            # Too few ITM paths to fit — skip this step (keep continuation)
            continue

        # Polynomial basis normalised by K for numerical stability
        S_norm = S_t[itm] / K
        X = np.column_stack([S_norm ** i for i in range(1, degree + 1)])

        # Least-squares regression: continuation ~ basis
        coef, _, _, _ = np.linalg.lstsq(X, cash_flows[itm], rcond=None)
        continuation = X @ coef

        # Early-exercise decision: replace cash_flow where intrinsic > continuation
        exercise_mask = intrinsic[itm] > continuation
        itm_indices = np.where(itm)[0]
        exercise_indices = itm_indices[exercise_mask]
        cash_flows[exercise_indices] = intrinsic[exercise_indices]

    # --- Discount from t = dt back to t = 0 ---
    cash_flows *= discount

    price = float(np.mean(cash_flows))
    std_error = float(np.std(cash_flows) / np.sqrt(num_paths))

    return price, std_error
