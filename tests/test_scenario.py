#!/usr/bin/env python3
"""
Tests for analytics/scenario.py — Scenario P&L Matrix
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from analytics.scenario import run_scenario_matrix, _compute_greek_pnl


# ---------------------------------------------------------------------------
# Shared fixture — 1-year ATM call, well within expiry
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    'ticker': 'TEST',
    'current_price': 100.0,
    'strike_price': 100.0,
    'expiration_date': '2027-03-07',   # ~1 year out
    'option_type': 'call',
    'implied_volatility': 0.20,
    'risk_free_rate': 0.05,
}


def _run(s_shocks=(-10, 0, 10), vol_shocks=(-5, 0, 5), day_shocks=(0, 5),
         reprice=False, **kwargs):
    return run_scenario_matrix(
        _BASE_CONFIG,
        s_shocks=s_shocks,
        vol_shocks=vol_shocks,
        day_shocks=day_shocks,
        reprice=reprice,
        num_paths=500,   # small for test speed
        seed=42,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test 1: zero shock → zero greek P&L
# ---------------------------------------------------------------------------

def test_zero_shock_zero_pnl():
    results = _run()
    pnl = results['greek_pnl'][(0, 0, 0)]
    assert pnl == pytest.approx(0.0, abs=1e-12), (
        f"Expected 0.0 at zero shock, got {pnl}"
    )


# ---------------------------------------------------------------------------
# Test 2: positive stock move → positive call P&L
# ---------------------------------------------------------------------------

def test_positive_s_positive_call_pnl():
    results = _run(s_shocks=(10,), vol_shocks=(0,), day_shocks=(0,))
    pnl = results['greek_pnl'][(10, 0, 0)]
    assert pnl > 0, f"Expected pnl > 0 for +10% stock, got {pnl}"


# ---------------------------------------------------------------------------
# Test 3: negative stock move → negative call P&L
# ---------------------------------------------------------------------------

def test_negative_s_negative_call_pnl():
    results = _run(s_shocks=(-10,), vol_shocks=(0,), day_shocks=(0,))
    pnl = results['greek_pnl'][(-10, 0, 0)]
    assert pnl < 0, f"Expected pnl < 0 for -10% stock, got {pnl}"


# ---------------------------------------------------------------------------
# Test 4: theta decay — time passing hurts long call
# ---------------------------------------------------------------------------

def test_theta_decay():
    results = _run(s_shocks=(0,), vol_shocks=(0,), day_shocks=(5,))
    pnl = results['greek_pnl'][(0, 0, 5)]
    assert pnl < 0, f"Expected pnl < 0 after 5 days (theta decay), got {pnl}"


# ---------------------------------------------------------------------------
# Test 5: result dict has all required keys
# ---------------------------------------------------------------------------

def test_result_keys():
    results = _run()
    required = {
        'base_price', 'greeks', 's_shocks', 'vol_shocks', 'day_shocks',
        'greek_pnl', 'mc_pnl', 'ticker', 'option_type', 'K', 'S0',
    }
    missing = required - set(results.keys())
    assert not missing, f"Missing keys in results: {missing}"

    # greek_pnl is a dict of tuples
    assert isinstance(results['greek_pnl'], dict)

    # greeks has core keys
    greeks = results['greeks']
    for key in ('delta', 'gamma', 'vega', 'theta', 'rho'):
        assert key in greeks, f"Missing greek: {key}"

    # ticker / option_type
    assert results['ticker'] == 'TEST'
    assert results['option_type'] == 'call'


# ---------------------------------------------------------------------------
# Test 6: reprice=True → (0,0,0) mc_pnl is exactly 0.0
# ---------------------------------------------------------------------------

def test_reprice_zero_shock():
    results = _run(
        s_shocks=(0,), vol_shocks=(0,), day_shocks=(0,),
        reprice=True,
    )
    mc_val = results['mc_pnl'].get((0, 0, 0))
    assert mc_val is not None, "mc_pnl[(0,0,0)] should not be None with reprice=True"
    assert mc_val == pytest.approx(0.0, abs=1e-12), (
        f"Expected mc_pnl[(0,0,0)] == 0.0, got {mc_val}"
    )
