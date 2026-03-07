#!/usr/bin/env python3
"""
Unit Tests for Implied Volatility Surface
==========================================

Tests for compute_implied_vol().  All tests are offline (no live data).

Author: Options Analytics Team
Date: March 2026
"""

import sys
import unittest
import numpy as np
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))

from analytics.vol_surface import compute_implied_vol
from models.black_scholes import black_scholes_price


class TestImpliedVol(unittest.TestCase):
    """Offline tests for compute_implied_vol."""

    # Standard parameters used across several tests
    S = 100.0
    K = 100.0
    T = 1.0
    r = 0.05

    def test_iv_roundtrip(self):
        """BS(sigma=0.25) → back-solves to IV ≈ 0.25."""
        sigma_true = 0.25
        price = black_scholes_price(self.S, self.K, self.T, self.r, sigma_true, 'call')
        iv = compute_implied_vol(price, self.S, self.K, self.T, self.r, 'call')
        self.assertAlmostEqual(iv, sigma_true, delta=1e-4,
            msg=f"Roundtrip IV {iv:.6f} != sigma {sigma_true}")

    def test_iv_nan_on_zero_price(self):
        """A price of 0.0 is below the arbitrage lower bound → nan."""
        iv = compute_implied_vol(0.0, self.S, self.K, self.T, self.r, 'call')
        self.assertTrue(np.isnan(iv),
            f"Expected nan for zero price, got {iv}")

    def test_iv_in_bounds(self):
        """IV for a realistic market price should be in (0.01, 5.0)."""
        # ATM 1yr call with sigma=0.30 gives a sensible market price
        price = black_scholes_price(self.S, self.K, self.T, self.r, 0.30, 'call')
        iv = compute_implied_vol(price, self.S, self.K, self.T, self.r, 'call')
        self.assertFalse(np.isnan(iv), "IV should not be nan for valid input")
        self.assertGreater(iv, 0.01)
        self.assertLess(iv, 5.0)

    def test_iv_call_put_parity(self):
        """Same sigma should give same IV for call and put (put-call parity)."""
        sigma = 0.30
        call_price = black_scholes_price(self.S, self.K, self.T, self.r, sigma, 'call')
        put_price  = black_scholes_price(self.S, self.K, self.T, self.r, sigma, 'put')

        iv_call = compute_implied_vol(call_price, self.S, self.K, self.T, self.r, 'call')
        iv_put  = compute_implied_vol(put_price,  self.S, self.K, self.T, self.r, 'put')

        self.assertFalse(np.isnan(iv_call), "Call IV should not be nan")
        self.assertFalse(np.isnan(iv_put),  "Put IV should not be nan")
        self.assertAlmostEqual(iv_call, iv_put, delta=1e-4,
            msg=f"Call IV {iv_call:.6f} != Put IV {iv_put:.6f}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
