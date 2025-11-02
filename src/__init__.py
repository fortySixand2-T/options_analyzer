#!/usr/bin/env python3
"""
Modular Options Pricing System
==============================

A comprehensive, modular Python package for options pricing and analysis
using the Black-Scholes model.

Author: Restructured Options Pricing System  
Date: October 2025
Version: 2.0.0
"""

__version__ = "2.0.0"
__author__ = "Options Analytics Team"
__description__ = "Modular options pricing and analysis system"

# Import core functionality
from models import black_scholes_price, calculate_greeks, calculate_d1_d2, intrinsic_value
from analytics import simulate_price_over_time, simulate_price_scenarios, simulate_volatility_scenarios, compare_option_strategies, plot_price_evolution, plot_price_scenarios, plot_volatility_surface, plot_strategy_comparison, plot_greeks_heatmap
from utils import load_config_from_json, validate_option_config, create_default_config, create_strategy_configs, export_to_csv, export_summary_report, bulk_export

# Expose main classes and functions
__all__ = [
    # Core pricing functions
    'black_scholes_price',
    'calculate_greeks',
    'intrinsic_value',
    
    # Analytics and simulations
    'simulate_price_over_time',
    'simulate_price_scenarios',
    'simulate_volatility_scenarios',
    'compare_option_strategies',
    
    # Visualization
    'plot_price_evolution',
    'plot_price_scenarios', 
    'plot_volatility_surface',
    'plot_strategy_comparison',
    'plot_greeks_heatmap',
    
    # Configuration and utilities
    'load_config_from_json',
    'validate_option_config',
    'create_default_config',
    'create_strategy_configs',
    
    # Data export
    'export_to_csv',
    'export_summary_report',
    'bulk_export'
]
