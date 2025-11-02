#!/usr/bin/env python3
"""
Analytics package for options pricing simulations and visualizations.
"""

from analytics.simulations import (
    simulate_price_over_time,
    simulate_price_scenarios,
    simulate_volatility_scenarios,
    compare_option_strategies
)

from analytics.visualization import (
    plot_price_evolution,
    plot_price_scenarios,
    plot_volatility_surface,
    plot_strategy_comparison,
    plot_greeks_heatmap
)

__all__ = [
    'simulate_price_over_time',
    'simulate_price_scenarios', 
    'simulate_volatility_scenarios',
    'compare_option_strategies',
    'plot_price_evolution',
    'plot_price_scenarios',
    'plot_volatility_surface',
    'plot_strategy_comparison',
    'plot_greeks_heatmap'
]
