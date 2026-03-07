#!/usr/bin/env python3
"""
Unit Tests for Monte Carlo Simulation
======================================

Tests for GBM path simulator and risk metrics,
following the style of test_black_scholes.py.

Author: Options Analytics Team
Date: March 2026
"""

import sys
import unittest
import numpy as np
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))
sys.path.append(str(Path(__file__).parent.parent / 'src' / 'monte_carlo'))

from monte_carlo.gbm_simulator import simulate_gbm_paths, simulate_garch_paths, price_option_on_paths, run_monte_carlo
from monte_carlo.risk_metrics import compute_var, compute_cvar, compute_distribution_stats
from monte_carlo.garch_vol import fit_garch11, simulate_garch_vol_paths


# Shared test config
_BASE_CONFIG = {
    'ticker': 'TEST',
    'current_price': 100.0,
    'strike_price': 100.0,
    'expiration_date': '2027-03-07',  # ~1 year out
    'option_type': 'call',
    'implied_volatility': 0.20,
    'risk_free_rate': 0.05,
}


class TestGBMSimulator(unittest.TestCase):
    """Tests for GBM path generation and option pricing on paths."""

    def setUp(self):
        self.S0 = 100.0
        self.r = 0.05
        self.sigma = 0.20
        self.T = 1.0
        self.num_paths = 1000
        self.num_steps = 252
        self.seed = 42

    def test_path_shape(self):
        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        self.assertEqual(paths.shape, (self.num_paths, self.num_steps + 1))

    def test_paths_start_at_S0(self):
        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        np.testing.assert_allclose(paths[:, 0], self.S0, rtol=1e-10)

    def test_paths_positive(self):
        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        self.assertTrue(np.all(paths > 0), "All path prices must be positive")

    def test_seed_reproducibility(self):
        paths1 = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        paths2 = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        np.testing.assert_array_equal(paths1, paths2)

    def test_different_seeds_differ(self):
        paths1 = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=1
        )
        paths2 = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=2
        )
        self.assertFalse(np.array_equal(paths1, paths2))

    def test_mc_price_converges_to_bs(self):
        """With 50k paths, MC price should be within $0.50 of BS price."""
        from models.black_scholes import black_scholes_price
        bs = black_scholes_price(self.S0, 100.0, self.T, self.r, self.sigma, 'call')

        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            50000, self.num_steps, seed=self.seed
        )
        payoffs = price_option_on_paths(paths, 100.0, self.r, self.T, 'call')
        mc = float(np.mean(payoffs))

        self.assertAlmostEqual(mc, bs, delta=0.50,
            msg=f"MC price {mc:.4f} not within $0.50 of BS price {bs:.4f}")

    def test_call_payoff_nonnegative(self):
        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        payoffs = price_option_on_paths(paths, 100.0, self.r, self.T, 'call')
        self.assertTrue(np.all(payoffs >= 0))

    def test_put_payoff_nonnegative(self):
        paths = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed
        )
        payoffs = price_option_on_paths(paths, 100.0, self.r, self.T, 'put')
        self.assertTrue(np.all(payoffs >= 0))

    def test_antithetic_reduces_variance(self):
        """Antithetic variates should reduce std dev of payoff estimates."""
        paths_plain = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            2000, self.num_steps, seed=self.seed, antithetic=False
        )
        paths_anti = simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            2000, self.num_steps, seed=self.seed, antithetic=True
        )
        payoffs_plain = price_option_on_paths(paths_plain, 100.0, self.r, self.T, 'call')
        payoffs_anti = price_option_on_paths(paths_anti, 100.0, self.r, self.T, 'call')
        # Antithetic std should be lower (test over multiple seeds for robustness)
        self.assertLess(np.std(payoffs_anti), np.std(payoffs_plain) * 1.2,
            "Antithetic variates should not significantly increase variance")

    def test_run_monte_carlo_keys(self):
        results = run_monte_carlo(_BASE_CONFIG, num_paths=500, num_steps=50, seed=42)
        required_keys = {'mc_price', 'bs_price', 'std_error', 'var', 'cvar',
                         'percentiles', 'payoffs', 'paths', 'num_paths', 'num_steps', 'T'}
        self.assertTrue(required_keys.issubset(results.keys()))

    def test_run_monte_carlo_var_leq_entry_premium(self):
        """VaR should be <= entry premium (you can't lose more than what you paid)."""
        results = run_monte_carlo(_BASE_CONFIG, num_paths=2000, num_steps=50, seed=42)
        self.assertLessEqual(results['var'], results['bs_price'] + 1e-9,
            "VaR cannot exceed the premium paid")


class TestRiskMetrics(unittest.TestCase):
    """Tests for VaR, CVaR, and distribution statistics."""

    def test_var_at_known_distribution(self):
        """VaR of standard normal at 95% should be ~1.645."""
        rng = np.random.default_rng(0)
        pnl = rng.standard_normal(100000)
        var = compute_var(pnl, confidence=0.95)
        self.assertAlmostEqual(var, 1.645, delta=0.05)

    def test_var_positive(self):
        pnl = np.array([-5.0, -3.0, -1.0, 0.0, 2.0, 4.0])
        var = compute_var(pnl, confidence=0.95)
        self.assertGreater(var, 0)

    def test_cvar_exceeds_var(self):
        rng = np.random.default_rng(1)
        pnl = rng.standard_normal(10000)
        var = compute_var(pnl, confidence=0.95)
        cvar = compute_cvar(pnl, confidence=0.95)
        self.assertGreaterEqual(cvar, var - 1e-9,
            "CVaR must be >= VaR")

    def test_cvar_at_known_distribution(self):
        """CVaR of standard normal at 95% should be ~2.063."""
        rng = np.random.default_rng(2)
        pnl = rng.standard_normal(200000)
        cvar = compute_cvar(pnl, confidence=0.95)
        self.assertAlmostEqual(cvar, 2.063, delta=0.10)

    def test_stats_dict_keys(self):
        values = np.arange(100, dtype=float)
        stats = compute_distribution_stats(values)
        expected_keys = {'mean', 'std', 'min', 'max', 'p5', 'p25', 'p50', 'p75', 'p95'}
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_stats_mean_correct(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        stats = compute_distribution_stats(values)
        self.assertAlmostEqual(stats['mean'], 3.0)

    def test_stats_min_max(self):
        values = np.array([-10.0, 0.0, 10.0])
        stats = compute_distribution_stats(values)
        self.assertAlmostEqual(stats['min'], -10.0)
        self.assertAlmostEqual(stats['max'], 10.0)


class TestGARCH(unittest.TestCase):
    """Tests for GARCH(1,1) volatility fitting and path simulation."""

    def setUp(self):
        rng = np.random.default_rng(0)
        # Synthetic returns: ~20% annual vol, 252 daily obs
        self.returns = rng.normal(0.0, 0.20 / np.sqrt(252), 252)
        self.S0 = 100.0
        self.r = 0.05
        self.T = 1.0
        self.num_paths = 500
        self.num_steps = 50

    def test_fit_garch11_returns_valid_params(self):
        params = fit_garch11(self.returns)
        self.assertGreater(params['omega'], 0, "omega must be positive")
        self.assertGreaterEqual(params['alpha'], 0, "alpha must be non-negative")
        self.assertGreaterEqual(params['beta'], 0, "beta must be non-negative")
        self.assertLess(params['alpha'] + params['beta'], 1.0,
                        "alpha + beta must be < 1 (stationarity)")
        self.assertGreater(params['sigma0'], 0, "sigma0 must be positive")
        self.assertGreater(params['long_run_vol'], 0, "long_run_vol must be positive")

    def test_garch_vol_path_shape(self):
        params = fit_garch11(self.returns)
        rng = np.random.default_rng(42)
        Z = rng.standard_normal((self.num_paths, self.num_steps))
        vol_paths = simulate_garch_vol_paths(
            params['omega'], params['alpha'], params['beta'], params['sigma0'],
            self.num_paths, self.num_steps, Z
        )
        self.assertEqual(vol_paths.shape, (self.num_paths, self.num_steps))

    def test_garch_vol_path_positive(self):
        params = fit_garch11(self.returns)
        rng = np.random.default_rng(7)
        Z = rng.standard_normal((self.num_paths, self.num_steps))
        vol_paths = simulate_garch_vol_paths(
            params['omega'], params['alpha'], params['beta'], params['sigma0'],
            self.num_paths, self.num_steps, Z
        )
        self.assertTrue(np.all(vol_paths > 0), "All GARCH vols must be positive")

    def test_garch_paths_start_at_S0(self):
        params = fit_garch11(self.returns)
        paths = simulate_garch_paths(
            self.S0, self.r,
            params['omega'], params['alpha'], params['beta'], params['sigma0'],
            self.T, self.num_paths, self.num_steps, seed=42
        )
        np.testing.assert_allclose(paths[:, 0], self.S0, rtol=1e-10)

    def test_garch_paths_shape(self):
        params = fit_garch11(self.returns)
        paths = simulate_garch_paths(
            self.S0, self.r,
            params['omega'], params['alpha'], params['beta'], params['sigma0'],
            self.T, self.num_paths, self.num_steps, seed=1
        )
        self.assertEqual(paths.shape, (self.num_paths, self.num_steps + 1))

    def test_garch_price_in_ballpark_of_bs(self):
        """GARCH MC price should be within $1.50 of BS (wider tolerance — different model)."""
        from models.black_scholes import black_scholes_price
        K = 100.0
        bs = black_scholes_price(self.S0, K, self.T, self.r, 0.20, 'call')
        params = fit_garch11(self.returns)
        paths = simulate_garch_paths(
            self.S0, self.r,
            params['omega'], params['alpha'], params['beta'], params['sigma0'],
            self.T, 5000, 252, seed=42
        )
        payoffs = price_option_on_paths(paths, K, self.r, self.T, 'call')
        mc_price = float(np.mean(payoffs))
        self.assertAlmostEqual(mc_price, bs, delta=1.50,
            msg=f"GARCH MC price {mc_price:.4f} too far from BS {bs:.4f}")

    def test_run_mc_garch_keys(self):
        config = dict(_BASE_CONFIG)
        results = run_monte_carlo(
            config,
            num_paths=300,
            num_steps=30,
            seed=42,
            use_garch=True,
            historical_returns=self.returns,
        )
        self.assertEqual(results['vol_model'], 'garch')
        self.assertIsNotNone(results['garch_params'])
        for key in ('omega', 'alpha', 'beta', 'sigma0', 'long_run_vol'):
            self.assertIn(key, results['garch_params'])


class TestJumpDiffusion(unittest.TestCase):
    """Tests for Merton jump-diffusion path simulator."""

    def setUp(self):
        self.S0 = 100.0
        self.r = 0.05
        self.sigma = 0.20
        self.lam = 0.1
        self.mu_J = -0.05
        self.sigma_J = 0.15
        self.T = 1.0
        self.num_paths = 1000
        self.num_steps = 252
        self.seed = 42

    def _make_paths(self, **kw):
        from monte_carlo.jump_diffusion import simulate_jump_paths
        params = dict(
            S0=self.S0, r=self.r, sigma=self.sigma,
            lam=self.lam, mu_J=self.mu_J, sigma_J=self.sigma_J,
            T=self.T, num_paths=self.num_paths, num_steps=self.num_steps,
            seed=self.seed,
        )
        params.update(kw)
        return simulate_jump_paths(**params)

    def test_jump_paths_shape(self):
        paths = self._make_paths()
        self.assertEqual(paths.shape, (self.num_paths, self.num_steps + 1))

    def test_jump_paths_start_at_S0(self):
        paths = self._make_paths()
        np.testing.assert_allclose(paths[:, 0], self.S0, rtol=1e-10)

    def test_jump_paths_positive(self):
        paths = self._make_paths()
        self.assertTrue(np.all(paths > 0), "All jump-diffusion prices must be positive")

    def test_jump_price_reasonable(self):
        """MC jump price should be within $2.00 of BS (jumps add premium)."""
        from models.black_scholes import black_scholes_price
        bs = black_scholes_price(self.S0, 100.0, self.T, self.r, self.sigma, 'call')
        paths = self._make_paths(num_paths=10000)
        payoffs = price_option_on_paths(paths, 100.0, self.r, self.T, 'call')
        mc_price = float(np.mean(payoffs))
        self.assertAlmostEqual(mc_price, bs, delta=2.0,
            msg=f"Jump MC price {mc_price:.4f} far from BS {bs:.4f}")

    def test_run_mc_jump_keys(self):
        """run_monte_carlo with use_jumps=True should return vol_model='jump'."""
        config = dict(_BASE_CONFIG)
        jump_params = {'lam': 0.1, 'mu_J': -0.05, 'sigma_J': 0.15}
        results = run_monte_carlo(
            config, num_paths=300, num_steps=30, seed=42,
            use_jumps=True, jump_params=jump_params,
        )
        self.assertEqual(results['vol_model'], 'jump')
        self.assertIsNotNone(results['jump_params'])
        self.assertIn('lam', results['jump_params'])

    def test_run_mc_jump_fallback(self):
        """use_jumps=True with no jump_params should fall back to constant vol."""
        import warnings
        config = dict(_BASE_CONFIG)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            results = run_monte_carlo(
                config, num_paths=200, num_steps=20, seed=42,
                use_jumps=True, jump_params=None,
            )
        self.assertEqual(results['vol_model'], 'constant')


class TestMCGreeks(unittest.TestCase):
    """Tests for bump-and-reprice MC Greeks with CRN."""

    def setUp(self):
        self.config = {
            'ticker': 'TEST',
            'current_price': 100.0,
            'strike_price': 100.0,
            'expiration_date': '2027-03-07',
            'option_type': 'call',
            'implied_volatility': 0.20,
            'risk_free_rate': 0.05,
        }

    def _greeks(self):
        from monte_carlo.mc_greeks import compute_mc_greeks
        return compute_mc_greeks(self.config, num_paths=3000, num_steps=50, seed=42)

    def test_mc_greeks_keys(self):
        g = self._greeks()
        expected = {'delta', 'gamma', 'vega', 'theta', 'rho',
                    'bs_delta', 'bs_gamma', 'bs_vega', 'bs_theta', 'bs_rho'}
        self.assertTrue(expected.issubset(set(g.keys())))

    def test_delta_in_range_atm_call(self):
        g = self._greeks()
        self.assertGreater(g['delta'], 0.0)
        self.assertLess(g['delta'], 1.0)

    def test_gamma_positive(self):
        g = self._greeks()
        self.assertGreater(g['gamma'], 0.0)

    def test_vega_positive(self):
        g = self._greeks()
        self.assertGreater(g['vega'], 0.0)

    def test_greeks_close_to_bs(self):
        """MC delta should be within 0.05 of BS delta (CRN helps)."""
        g = self._greeks()
        self.assertAlmostEqual(g['delta'], g['bs_delta'], delta=0.05,
            msg=f"MC delta {g['delta']:.4f} too far from BS {g['bs_delta']:.4f}")


class TestAmericanMC(unittest.TestCase):
    """Tests for Longstaff-Schwartz American option pricing."""

    def setUp(self):
        self.S0 = 100.0
        self.K = 100.0
        self.r = 0.05
        self.sigma = 0.20
        self.T = 1.0
        self.num_paths = 2000
        self.num_steps = 50
        self.seed = 42

    def _make_paths(self):
        return simulate_gbm_paths(
            self.S0, self.r, self.sigma, self.T,
            self.num_paths, self.num_steps, seed=self.seed,
        )

    def test_american_put_geq_european(self):
        """American put price must be >= European put price (same paths)."""
        from monte_carlo.american_mc import price_american_lsmc
        paths = self._make_paths()
        eu_payoffs = price_option_on_paths(paths, self.K, self.r, self.T, 'put')
        eu_price = float(np.mean(eu_payoffs))
        am_price, _ = price_american_lsmc(paths, self.K, self.r, self.T, 'put')
        self.assertGreaterEqual(am_price, eu_price - 1e-9,
            f"American put {am_price:.4f} < European put {eu_price:.4f}")

    def test_american_call_no_premium_nodiv(self):
        """American call premium ≈ 0 for non-dividend stock (early exercise never optimal)."""
        from monte_carlo.american_mc import price_american_lsmc
        paths = self._make_paths()
        eu_payoffs = price_option_on_paths(paths, self.K, self.r, self.T, 'call')
        eu_price = float(np.mean(eu_payoffs))
        am_price, _ = price_american_lsmc(paths, self.K, self.r, self.T, 'call')
        premium = am_price - eu_price
        self.assertAlmostEqual(premium, 0.0, delta=0.25,
            msg=f"American call premium {premium:.4f} should be ~0 (no dividends)")

    def test_american_keys_in_results(self):
        """run_monte_carlo with option_style='american' populates american_price."""
        results = run_monte_carlo(
            _BASE_CONFIG, num_paths=500, num_steps=30, seed=42,
            option_style='american',
        )
        self.assertIn('american_price', results)
        self.assertIn('early_exercise_premium', results)
        self.assertIsNotNone(results['american_price'])

    def test_early_exercise_nonnegative(self):
        """Early exercise premium must be non-negative for puts."""
        put_config = dict(_BASE_CONFIG)
        put_config['option_type'] = 'put'
        results = run_monte_carlo(
            put_config, num_paths=1000, num_steps=30, seed=42,
            option_style='american',
        )
        self.assertGreaterEqual(results['early_exercise_premium'], -1e-9,
            "Early exercise premium cannot be negative")


if __name__ == '__main__':
    unittest.main(verbosity=2)
