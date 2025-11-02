#!/usr/bin/env python3
"""
Black-Scholes Option Pricing Model
==================================

Core implementation of the Black-Scholes formula for European options.
Provides clean, modular functions for option pricing and Greeks calculation.

Author: Restructured Options Pricing System
Date: October 2025
"""

import numpy as np
from scipy.stats import norm
from typing import Dict, Tuple


def calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> Tuple[float, float]:
    """
    Calculate d1 and d2 parameters for Black-Scholes formula.
    
    Parameters:
    -----------
    S : float
        Current stock price
    K : float
        Strike price
    T : float
        Time to expiration (in years)
    r : float
        Risk-free interest rate (annual)
    sigma : float
        Volatility (annual)
    
    Returns:
    --------
    Tuple[float, float]
        (d1, d2) parameters
    """
    if T <= 0:
        return 0.0, 0.0
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return d1, d2


def black_scholes_price(S: float, K: float, T: float, r: float, 
                        sigma: float, option_type: str = 'call') -> float:
    """
    Calculate Black-Scholes option price.
    
    Parameters:
    -----------
    S : float
        Current stock price
    K : float
        Strike price
    T : float
        Time to expiration (in years)
    r : float
        Risk-free interest rate (annual)
    sigma : float
        Volatility (annual)
    option_type : str
        'call' or 'put'
    
    Returns:
    --------
    float
        Option price
    """
    if T <= 0:
        # At expiration, return intrinsic value
        if option_type.lower() == 'call':
            return max(S - K, 0)
        else:
            return max(K - S, 0)
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    
    if option_type.lower() == 'call':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:  # put
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    
    return price


def calculate_greeks(S: float, K: float, T: float, r: float, 
                    sigma: float, option_type: str = 'call') -> Dict[str, float]:
    """
    Calculate all major Greeks for an option.
    
    Parameters:
    -----------
    S : float
        Current stock price
    K : float
        Strike price
    T : float
        Time to expiration (in years)
    r : float
        Risk-free interest rate (annual)
    sigma : float
        Volatility (annual)
    option_type : str
        'call' or 'put'
    
    Returns:
    --------
    Dict[str, float]
        Dictionary containing Delta, Gamma, Theta, Vega, and Rho
    """
    if T <= 0:
        # At expiration, Greeks have specific values
        return {
            'Delta': 1.0 if (option_type == 'call' and S > K) else 0.0,
            'Gamma': 0.0,
            'Theta': 0.0,
            'Vega': 0.0,
            'Rho': 0.0
        }
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    
    # Common calculations
    pdf_d1 = norm.pdf(d1)
    sqrt_T = np.sqrt(T)
    
    # Delta
    if option_type.lower() == 'call':
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1
    
    # Gamma (same for calls and puts)
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    
    # Vega (same for calls and puts) - per 1% change in volatility
    vega = S * pdf_d1 * sqrt_T / 100
    
    # Theta (per day)
    if option_type.lower() == 'call':
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) - 
                r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
    else:
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) + 
                r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
    
    # Rho (per 1% change in interest rate)
    if option_type.lower() == 'call':
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
    
    return {
        'Delta': delta,
        'Gamma': gamma,
        'Theta': theta,
        'Vega': vega,
        'Rho': rho
    }


def intrinsic_value(S: float, K: float, option_type: str = 'call') -> float:
    """
    Calculate the intrinsic value of an option.
    
    Parameters:
    -----------
    S : float
        Current stock price
    K : float
        Strike price
    option_type : str
        'call' or 'put'
    
    Returns:
    --------
    float
        Intrinsic value
    """
    if option_type.lower() == 'call':
        return max(S - K, 0)
    else:
        return max(K - S, 0)
