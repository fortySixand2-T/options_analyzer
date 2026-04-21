#!/usr/bin/env python3
"""
Analytics package — vol surface and scenario analysis.
"""

from .vol_surface import compute_implied_vol, fetch_vol_surface, plot_vol_surface
from .scenario import run_scenario_matrix, plot_scenario_matrix

__all__ = [
    'compute_implied_vol',
    'fetch_vol_surface',
    'plot_vol_surface',
    'run_scenario_matrix',
    'plot_scenario_matrix',
]
