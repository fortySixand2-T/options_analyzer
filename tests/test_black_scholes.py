#!/usr/bin/env python3
"""
Unit Tests for Black-Scholes Model
==================================

Basic tests to ensure the pricing model works correctly.

Author: Restructured Options Pricing System
Date: October 2025
"""

import sys
import unittest
import numpy as np
from pathlib import Path

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / 'src'))

from models.black_scholes import (
    black_scholes_price,
    calculate_greeks,
    calculate_d1_d2,
    intrinsic_value
)


class TestBlackScholes(unittest.TestCase):
    """Test cases for Black-Scholes pricing functions."""
    
    def setUp(self):
        """Set up test parameters."""
        self.S = 100.0  # Current stock price
        self.K = 100.0  # Strike price (ATM)
        self.T = 0.25   # Time to expiration (3 months)
        self.r = 0.05   # Risk-free rate (5%)
        self.sigma = 0.20  # Volatility (20%)
    
    def test_call_price_reasonable(self):
        """Test that call price is reasonable for ATM option."""
        price = black_scholes_price(self.S, self.K, self.T, self.r, self.sigma, 'call')
        
        # ATM call with 3 months should be worth several dollars
        self.assertGreater(price, 2.0)
        self.assertLess(price, 15.0)
    
    def test_put_call_parity(self):
        """Test put-call parity: C - P = S - K*e^(-rT)."""
        call_price = black_scholes_price(self.S, self.K, self.T, self.r, self.sigma, 'call')
        put_price = black_scholes_price(self.S, self.K, self.T, self.r, self.sigma, 'put')
        
        # Calculate theoretical difference
        theoretical_diff = self.S - self.K * np.exp(-self.r * self.T)
        actual_diff = call_price - put_price
        
        # Should be equal within small tolerance
        self.assertAlmostEqual(actual_diff, theoretical_diff, places=6)
    
    def test_expiration_intrinsic_value(self):
        """Test that at expiration, option price equals intrinsic value."""
        # ITM call at expiration
        call_price = black_scholes_price(110, 100, 0, self.r, self.sigma, 'call')
        self.assertEqual(call_price, 10.0)
        
        # OTM call at expiration
        call_price = black_scholes_price(90, 100, 0, self.r, self.sigma, 'call')
        self.assertEqual(call_price, 0.0)
        
        # ITM put at expiration
        put_price = black_scholes_price(90, 100, 0, self.r, self.sigma, 'put')
        self.assertEqual(put_price, 10.0)
    
    def test_delta_range(self):
        """Test that Delta is within expected range."""
        greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'call')
        
        # Call delta should be between 0 and 1
        self.assertGreaterEqual(greeks['Delta'], 0)
        self.assertLessEqual(greeks['Delta'], 1)
        
        # ATM call delta should be around 0.5
        self.assertGreater(greeks['Delta'], 0.4)
        self.assertLess(greeks['Delta'], 0.6)
    
    def test_gamma_positive(self):
        """Test that Gamma is positive for long options."""
        call_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'call')
        put_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'put')
        
        # Gamma should be positive for both calls and puts
        self.assertGreater(call_greeks['Gamma'], 0)
        self.assertGreater(put_greeks['Gamma'], 0)
        
        # Gamma should be the same for calls and puts with same parameters
        self.assertAlmostEqual(call_greeks['Gamma'], put_greeks['Gamma'], places=6)
    
    def test_theta_negative(self):
        """Test that Theta is negative for long options (time decay)."""
        call_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'call')
        put_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'put')
        
        # Theta should be negative (options lose value over time)
        self.assertLess(call_greeks['Theta'], 0)
        self.assertLess(put_greeks['Theta'], 0)
    
    def test_vega_positive(self):
        """Test that Vega is positive (options gain value with higher volatility)."""
        call_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'call')
        put_greeks = calculate_greeks(self.S, self.K, self.T, self.r, self.sigma, 'put')
        
        # Vega should be positive for both calls and puts
        self.assertGreater(call_greeks['Vega'], 0)
        self.assertGreater(put_greeks['Vega'], 0)
        
        # Vega should be the same for calls and puts
        self.assertAlmostEqual(call_greeks['Vega'], put_greeks['Vega'], places=6)
    
    def test_intrinsic_value_calculation(self):
        """Test intrinsic value calculations."""
        # ITM call
        intrinsic = intrinsic_value(110, 100, 'call')
        self.assertEqual(intrinsic, 10)
        
        # OTM call
        intrinsic = intrinsic_value(90, 100, 'call')
        self.assertEqual(intrinsic, 0)
        
        # ITM put
        intrinsic = intrinsic_value(90, 100, 'put')
        self.assertEqual(intrinsic, 10)
        
        # OTM put
        intrinsic = intrinsic_value(110, 100, 'put')
        self.assertEqual(intrinsic, 0)
    
    def test_volatility_sensitivity(self):
        """Test that higher volatility increases option prices."""
        low_vol_price = black_scholes_price(self.S, self.K, self.T, self.r, 0.10, 'call')
        high_vol_price = black_scholes_price(self.S, self.K, self.T, self.r, 0.40, 'call')
        
        # Higher volatility should increase option price
        self.assertGreater(high_vol_price, low_vol_price)
    
    def test_time_decay_effect(self):
        """Test that longer time to expiration increases option prices."""
        short_time_price = black_scholes_price(self.S, self.K, 0.1, self.r, self.sigma, 'call')
        long_time_price = black_scholes_price(self.S, self.K, 0.5, self.r, self.sigma, 'call')
        
        # Longer time should increase option price
        self.assertGreater(long_time_price, short_time_price)


if __name__ == '__main__':
    unittest.main()
