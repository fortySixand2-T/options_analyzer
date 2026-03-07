#!/usr/bin/env python3
"""
Monte Carlo Options Simulation Package
=======================================

Provides GBM path simulation, option pricing on simulated paths,
and tail-risk metrics (VaR, CVaR).

Public API:
-----------
    simulate_gbm_paths  - Generate GBM stock price paths
    price_option_on_paths - Price European option on path terminals
    run_monte_carlo     - Full simulation orchestrator
    compute_var         - Value at Risk
    compute_cvar        - Conditional Value at Risk / Expected Shortfall
    compute_distribution_stats - Descriptive statistics dict
"""

from .gbm_simulator import simulate_gbm_paths, simulate_garch_paths, price_option_on_paths, run_monte_carlo
from .risk_metrics import compute_var, compute_cvar, compute_distribution_stats
from .garch_vol import fit_garch11, simulate_garch_vol_paths
from .jump_diffusion import simulate_jump_paths
from .mc_greeks import compute_mc_greeks
from .american_mc import price_american_lsmc

__all__ = [
    'simulate_gbm_paths',
    'simulate_garch_paths',
    'simulate_jump_paths',
    'price_option_on_paths',
    'price_american_lsmc',
    'run_monte_carlo',
    'compute_var',
    'compute_cvar',
    'compute_distribution_stats',
    'fit_garch11',
    'simulate_garch_vol_paths',
    'compute_mc_greeks',
]
