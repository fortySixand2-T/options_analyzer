#!/usr/bin/env python3
"""
Analytics package for options pricing simulations and visualizations.
"""

from .simulations import (
    simulate_price_over_time,
    simulate_price_scenarios,
    simulate_volatility_scenarios,
    compare_option_strategies
)

from .visualization import (
    plot_price_evolution,
    plot_price_scenarios,
    plot_volatility_surface,
    plot_strategy_comparison,
    plot_greeks_heatmap
)

from .vol_surface import compute_implied_vol, fetch_vol_surface, plot_vol_surface
from .scenario import run_scenario_matrix, plot_scenario_matrix

__all__ = [
    'simulate_price_over_time',
    'simulate_price_scenarios',
    'simulate_volatility_scenarios',
    'compare_option_strategies',
    'plot_price_evolution',
    'plot_price_scenarios',
    'plot_volatility_surface',
    'plot_strategy_comparison',
    'plot_greeks_heatmap',
    'compute_implied_vol',
    'fetch_vol_surface',
    'plot_vol_surface',
    'run_scenario_matrix',
    'plot_scenario_matrix',
]
