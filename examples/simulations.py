#!/usr/bin/env python3
"""
Option Analytics and Simulations
================================

Provides simulation functions for analyzing option price behavior
over time and across different underlying price scenarios.

Author: Restructured Options Pricing System
Date: October 2025
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Union, Tuple

from models.black_scholes import black_scholes_price, calculate_greeks, intrinsic_value


def simulate_price_over_time(config: Dict, time_points: Union[int, List[datetime]] = 20) -> pd.DataFrame:
    """
    Simulate option price evolution from current date to expiration.
    
    Parameters:
    -----------
    config : Dict
        Option configuration containing all parameters
    time_points : Union[int, List[datetime]]
        Number of time points to simulate or specific dates
    
    Returns:
    --------
    pd.DataFrame
        Time simulation results with prices and Greeks
    """
    # Extract parameters
    S = config['current_price']
    K = config['strike_price']
    option_type = config.get('option_type', 'call')
    sigma = config.get('implied_volatility', config.get('volatility', 0.25))
    r = config.get('risk_free_rate', 0.05)
    
    # Parse expiration date
    if isinstance(config['expiration_date'], str):
        exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
    else:
        exp_date = config['expiration_date']
    
    # Generate time points
    if isinstance(time_points, int):
        current_date = datetime.now()
        dates = pd.date_range(start=current_date, end=exp_date, periods=time_points)
    else:
        dates = time_points
    
    results = []
    
    for date in dates:
        if isinstance(date, pd.Timestamp):
            date = date.to_pydatetime()
        
        # Calculate time to expiration
        T = max((exp_date - date).days / 365.0, 0)
        
        # Calculate metrics
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        greeks = calculate_greeks(S, K, T, r, sigma, option_type)
        intrinsic = intrinsic_value(S, K, option_type)
        time_value = price - intrinsic
        
        result = {
            'Date': date,
            'Days_to_Expiration': (exp_date - date).days,
            'Time_to_Expiration_Years': T,
            'Option_Price': price,
            'Intrinsic_Value': intrinsic,
            'Time_Value': time_value,
            **greeks
        }
        results.append(result)
    
    return pd.DataFrame(results)


def simulate_price_scenarios(config: Dict, price_range: Tuple[float, float] = None,
                           num_prices: int = 20) -> pd.DataFrame:
    """
    Simulate option prices across different underlying stock prices.
    
    Parameters:
    -----------
    config : Dict
        Option configuration containing all parameters
    price_range : Tuple[float, float] or None
        (min_price, max_price) or None for auto-generated range
    num_prices : int
        Number of price points to simulate
    
    Returns:
    --------
    pd.DataFrame
        Price scenario simulation results
    """
    S_current = config['current_price']
    K = config['strike_price']
    option_type = config.get('option_type', 'call')
    sigma = config.get('implied_volatility', config.get('volatility', 0.25))
    r = config.get('risk_free_rate', 0.05)
    
    # Parse expiration and calculate time to expiration
    if isinstance(config['expiration_date'], str):
        exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
    else:
        exp_date = config['expiration_date']
    
    current_date = datetime.now()
    T = max((exp_date - current_date).days / 365.0, 0)
    
    # Generate price range
    if price_range is None:
        price_range = (S_current * 0.7, S_current * 1.3)
    
    prices = np.linspace(price_range[0], price_range[1], num_prices)
    
    results = []
    
    for S in prices:
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        greeks = calculate_greeks(S, K, T, r, sigma, option_type)
        intrinsic = intrinsic_value(S, K, option_type)
        
        result = {
            'Underlying_Price': S,
            'Option_Price': price,
            'Moneyness': S / K,
            'Intrinsic_Value': intrinsic,
            'Time_Value': price - intrinsic,
            **greeks
        }
        results.append(result)
    
    return pd.DataFrame(results)


def simulate_volatility_scenarios(config: Dict, vol_range: Tuple[float, float] = (0.1, 0.8),
                                 num_vols: int = 10) -> pd.DataFrame:
    """
    Simulate option prices across different implied volatility levels.
    
    Parameters:
    -----------
    config : Dict
        Option configuration containing all parameters
    vol_range : Tuple[float, float]
        (min_vol, max_vol) range for volatility simulation
    num_vols : int
        Number of volatility points to simulate
    
    Returns:
    --------
    pd.DataFrame
        Volatility scenario simulation results
    """
    S = config['current_price']
    K = config['strike_price']
    option_type = config.get('option_type', 'call')
    r = config.get('risk_free_rate', 0.05)
    
    # Parse expiration and calculate time to expiration
    if isinstance(config['expiration_date'], str):
        exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
    else:
        exp_date = config['expiration_date']
    
    current_date = datetime.now()
    T = max((exp_date - current_date).days / 365.0, 0)
    
    # Generate volatility range
    volatilities = np.linspace(vol_range[0], vol_range[1], num_vols)
    
    results = []
    
    for sigma in volatilities:
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        greeks = calculate_greeks(S, K, T, r, sigma, option_type)
        intrinsic = intrinsic_value(S, K, option_type)
        
        result = {
            'Implied_Volatility': sigma,
            'IV_Percentage': sigma * 100,
            'Option_Price': price,
            'Intrinsic_Value': intrinsic,
            'Time_Value': price - intrinsic,
            **greeks
        }
        results.append(result)
    
    return pd.DataFrame(results)


def compare_option_strategies(configs: List[Dict], scenario_type: str = 'price') -> pd.DataFrame:
    """
    Compare multiple option configurations side by side.
    
    Parameters:
    -----------
    configs : List[Dict]
        List of option configurations to compare
    scenario_type : str
        Type of comparison: 'price', 'time', or 'volatility'
    
    Returns:
    --------
    pd.DataFrame
        Comparison results for all configurations
    """
    if scenario_type == 'price':
        results = []
        for i, config in enumerate(configs):
            scenario_df = simulate_price_scenarios(config)
            scenario_df['Strategy'] = config.get('name', f'Strategy_{i+1}')
            results.append(scenario_df)
        return pd.concat(results, ignore_index=True)
    
    elif scenario_type == 'time':
        results = []
        for i, config in enumerate(configs):
            time_df = simulate_price_over_time(config)
            time_df['Strategy'] = config.get('name', f'Strategy_{i+1}')
            results.append(time_df)
        return pd.concat(results, ignore_index=True)
    
    elif scenario_type == 'volatility':
        results = []
        for i, config in enumerate(configs):
            vol_df = simulate_volatility_scenarios(config)
            vol_df['Strategy'] = config.get('name', f'Strategy_{i+1}')
            results.append(vol_df)
        return pd.concat(results, ignore_index=True)
    
    else:
        raise ValueError("scenario_type must be 'price', 'time', or 'volatility'")
