"""Tests for edge measurement modules: VRP, term structure, earnings, skew."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, datetime
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


# ── VRP Tests ─────────────────────────────────────────────────────────────────

class TestVRP:
    def test_compute_vrp_curve_basic(self):
        from edge.vrp import compute_vrp_curve

        chain_iv_by_dte = {
            3: [0.20, 0.22, 0.21],
            5: [0.19, 0.20],
            10: [0.25, 0.26, 0.24],
            35: [0.28, 0.30, 0.29],
        }
        rv = 0.18

        result = compute_vrp_curve(chain_iv_by_dte, rv)

        assert len(result.buckets) >= 2
        assert result.overall_vrp > 0  # IV > RV → positive VRP
        assert result.richest_bucket is not None

    def test_vrp_positive_when_iv_rich(self):
        from edge.vrp import compute_vrp_curve

        chain_iv_by_dte = {5: [0.30, 0.32]}
        result = compute_vrp_curve(chain_iv_by_dte, realized_vol=0.15)

        bucket = result.buckets[0]
        assert bucket.vrp > 0
        assert bucket.vrp_pct > 0

    def test_vrp_negative_when_iv_cheap(self):
        from edge.vrp import compute_vrp_curve

        chain_iv_by_dte = {5: [0.10, 0.12]}
        result = compute_vrp_curve(chain_iv_by_dte, realized_vol=0.25)

        bucket = result.buckets[0]
        assert bucket.vrp < 0

    def test_vrp_empty_chain(self):
        from edge.vrp import compute_vrp_curve

        result = compute_vrp_curve({}, 0.20)
        assert len(result.buckets) == 0
        assert result.overall_vrp == 0.0

    def test_vrp_to_dict(self):
        from edge.vrp import compute_vrp_curve

        chain_iv_by_dte = {5: [0.25], 30: [0.28]}
        result = compute_vrp_curve(chain_iv_by_dte, 0.20)
        d = result.to_dict()

        assert "buckets" in d
        assert "overall_vrp" in d
        assert "richest_bucket" in d
        assert isinstance(d["buckets"], list)

    def test_vrp_simple(self):
        from edge.vrp import compute_vrp_simple

        result = compute_vrp_simple(chain_iv=0.25, realized_vol=0.18)
        assert result["vrp"] == round(0.25 - 0.18, 4)
        assert result["rich"] is True

        result2 = compute_vrp_simple(chain_iv=0.12, realized_vol=0.18)
        assert result2["rich"] is False

    def test_extract_chain_iv_by_dte(self):
        from edge.vrp import extract_chain_iv_by_dte

        @dataclass
        class MockContract:
            expiry: str
            implied_volatility: float
            option_type: str = "call"
            strike: float = 100.0

        @dataclass
        class MockChain:
            contracts: list

        today = date.today()
        expiry_5d = (datetime(today.year, today.month, today.day) +
                     __import__('datetime').timedelta(days=5)).strftime("%Y-%m-%d")

        chain = MockChain(contracts=[
            MockContract(expiry=expiry_5d, implied_volatility=0.22),
            MockContract(expiry=expiry_5d, implied_volatility=0.24),
            MockContract(expiry=expiry_5d, implied_volatility=float('nan')),
            MockContract(expiry=expiry_5d, implied_volatility=-0.1),
        ])

        result = extract_chain_iv_by_dte(chain)
        assert 5 in result
        assert len(result[5]) == 2  # nan and negative filtered out

    def test_vrp_multiple_buckets(self):
        from edge.vrp import compute_vrp_curve

        chain_iv_by_dte = {
            2: [0.20],     # 0-7 bucket
            10: [0.22],    # 7-14 bucket
            20: [0.25],    # 14-30 bucket
            45: [0.28],    # 30-60 bucket
        }
        result = compute_vrp_curve(chain_iv_by_dte, 0.18)
        assert len(result.buckets) == 4

    def test_compute_vrp_by_dte_basic(self):
        from edge.vrp import compute_vrp_by_dte

        prices = np.array([100 * (1 + 0.001 * np.sin(i / 5)) for i in range(60)])
        chain_iv_by_dte = {
            3: [0.25, 0.26],
            10: [0.24, 0.25],
            25: [0.23, 0.24],
            40: [0.22, 0.23],
        }
        result = compute_vrp_by_dte(chain_iv_by_dte, prices)
        assert len(result.buckets) >= 2
        assert result.overall_vrp != 0

    def test_compute_vrp_by_dte_different_rv_per_bucket(self):
        from edge.vrp import compute_vrp_by_dte

        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(60) * 0.5)
        chain_iv_by_dte = {3: [0.30], 40: [0.30]}
        result = compute_vrp_by_dte(chain_iv_by_dte, prices)
        if len(result.buckets) == 2:
            assert result.buckets[0].realized_vol != result.buckets[1].realized_vol

    def test_compute_vrp_by_dte_insufficient_history(self):
        from edge.vrp import compute_vrp_by_dte

        prices = np.array([100.0, 101.0, 102.0])
        chain_iv_by_dte = {3: [0.25], 40: [0.28]}
        result = compute_vrp_by_dte(chain_iv_by_dte, prices)
        assert len(result.buckets) == 0

    def test_realized_vol_helper(self):
        from edge.vrp import _realized_vol

        prices = np.array([100 + i * 0.5 for i in range(30)])
        rv = _realized_vol(prices, 20)
        assert rv is not None
        assert rv > 0

        assert _realized_vol(np.array([100.0]), 5) is None


# ── Term Structure Tests ──────────────────────────────────────────────────────

class TestTermStructure:
    def _make_chain(self, expiry_iv_pairs):
        """Build a mock chain with contracts at given expiries and IVs."""
        @dataclass
        class MockContract:
            expiry: str
            strike: float
            implied_volatility: float
            option_type: str = "call"

        @dataclass
        class MockChain:
            contracts: list

        contracts = []
        for expiry, ivs in expiry_iv_pairs:
            for i, iv in enumerate(ivs):
                # Create contracts near ATM (spot=100) and wings
                contracts.append(MockContract(expiry=expiry, strike=95 + i * 2, implied_volatility=iv))
                contracts.append(MockContract(expiry=expiry, strike=95 + i * 2, implied_volatility=iv, option_type="put"))
        return MockChain(contracts=contracts)

    def test_basic_term_structure(self):
        from edge.term_structure import compute_iv_term_structure

        today = date.today()
        exp1 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=5)).strftime("%Y-%m-%d")
        exp2 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=30)).strftime("%Y-%m-%d")

        chain = self._make_chain([
            (exp1, [0.22, 0.24, 0.23, 0.25]),
            (exp2, [0.18, 0.19, 0.20, 0.21]),
        ])

        ts = compute_iv_term_structure(chain, spot=100.0)

        assert len(ts.expiries) == 2
        assert ts.front_iv > 0
        assert ts.back_iv > 0

    def test_contango_detection(self):
        from edge.term_structure import compute_iv_term_structure

        today = date.today()
        exp1 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=5)).strftime("%Y-%m-%d")
        exp2 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=30)).strftime("%Y-%m-%d")

        # Contango: back > front
        chain = self._make_chain([
            (exp1, [0.18, 0.18, 0.18, 0.18]),
            (exp2, [0.25, 0.25, 0.25, 0.25]),
        ])
        ts = compute_iv_term_structure(chain, spot=100.0)
        assert ts.contango is True
        assert ts.slope > 0

    def test_backwardation_detection(self):
        from edge.term_structure import compute_iv_term_structure

        today = date.today()
        exp1 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=5)).strftime("%Y-%m-%d")
        exp2 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=30)).strftime("%Y-%m-%d")

        # Backwardation: front > back
        chain = self._make_chain([
            (exp1, [0.30, 0.30, 0.30, 0.30]),
            (exp2, [0.20, 0.20, 0.20, 0.20]),
        ])
        ts = compute_iv_term_structure(chain, spot=100.0)
        assert ts.contango is False
        assert ts.slope < 0

    def test_empty_chain(self):
        from edge.term_structure import compute_iv_term_structure

        @dataclass
        class MockChain:
            contracts: list

        ts = compute_iv_term_structure(MockChain(contracts=[]), spot=100.0)
        assert len(ts.expiries) == 0
        assert ts.front_iv == 0.0

    def test_calendar_signal_backwardation(self):
        from edge.term_structure import _compute_calendar_signal

        signal = _compute_calendar_signal(slope=-8.0, kink_magnitude=0.0, contango=False)
        assert signal > 0  # backwardation = good for calendars

    def test_calendar_signal_strong_contango(self):
        from edge.term_structure import _compute_calendar_signal

        signal = _compute_calendar_signal(slope=15.0, kink_magnitude=0.0, contango=True)
        assert signal < 0  # strong contango = bad for calendars

    def test_to_dict(self):
        from edge.term_structure import compute_iv_term_structure

        today = date.today()
        exp1 = (datetime(today.year, today.month, today.day) +
                __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")

        chain = self._make_chain([(exp1, [0.20, 0.22, 0.21, 0.23])])
        ts = compute_iv_term_structure(chain, spot=100.0)
        d = ts.to_dict()

        assert "expiries" in d
        assert "slope" in d
        assert "calendar_signal" in d

    def test_term_structure_slope_func(self):
        from edge.term_structure import term_structure_slope

        assert term_structure_slope(0.20, 0.25) == pytest.approx(25.0)
        assert term_structure_slope(0.20, 0.20) == pytest.approx(0.0)
        assert term_structure_slope(0.0, 0.20) == 0.0


# ── Earnings Tests ────────────────────────────────────────────────────────────

class TestEarnings:
    def test_iv_inflation_score(self):
        from edge.earnings import compute_iv_inflation

        assert compute_iv_inflation(0.25, 0.20) == pytest.approx(0.5)
        assert compute_iv_inflation(0.30, 0.20) == pytest.approx(1.0)
        assert compute_iv_inflation(0.20, 0.20) == 0.0
        assert compute_iv_inflation(0.15, 0.20) == 0.0  # below baseline

    def test_iv_inflation_edge_cases(self):
        from edge.earnings import compute_iv_inflation

        assert compute_iv_inflation(0.0, 0.20) == 0.0
        assert compute_iv_inflation(0.25, 0.0) == 0.0

    def test_expected_move(self):
        from edge.earnings import expected_move_from_straddle

        move = expected_move_from_straddle(straddle_price=10.0, spot=200.0)
        assert move == pytest.approx(5.0)

        assert expected_move_from_straddle(10.0, 0.0) == 0.0

    def test_compute_earnings_info_no_earnings(self):
        from edge.earnings import compute_earnings_info

        result = compute_earnings_info(
            ticker="SPY", current_iv=0.20, baseline_iv=0.18,
            earnings_date_str=None,
        )
        assert result.has_earnings is False

    def test_compute_earnings_info_with_date(self):
        from edge.earnings import compute_earnings_info

        # 5 days from now
        future = date.today() + __import__('datetime').timedelta(days=5)
        result = compute_earnings_info(
            ticker="AAPL",
            current_iv=0.30,
            baseline_iv=0.20,
            spot=150.0,
            earnings_date_str=future.strftime("%Y-%m-%d"),
        )
        assert result.has_earnings is True
        assert result.days_to_earnings == 5
        assert result.in_earnings_window is True
        assert result.iv_inflation > 0

    def test_compute_earnings_info_post_earnings(self):
        from edge.earnings import compute_earnings_info

        past = date.today() - __import__('datetime').timedelta(days=1)
        result = compute_earnings_info(
            ticker="AAPL",
            current_iv=0.15,
            baseline_iv=0.20,
            earnings_date_str=past.strftime("%Y-%m-%d"),
        )
        assert result.has_earnings is True
        assert result.post_earnings is True
        assert result.iv_inflation == 0.0  # IV is below baseline post-crush

    def test_compute_earnings_info_far_out(self):
        from edge.earnings import compute_earnings_info

        future = date.today() + __import__('datetime').timedelta(days=30)
        result = compute_earnings_info(
            ticker="AAPL",
            current_iv=0.22,
            baseline_iv=0.20,
            earnings_date_str=future.strftime("%Y-%m-%d"),
        )
        assert result.in_earnings_window is False

    def test_index_tickers_skip_earnings(self):
        from edge.earnings import get_earnings_date

        assert get_earnings_date("SPY") is None
        assert get_earnings_date("^SPX") is None
        assert get_earnings_date("QQQ") is None

    def test_earnings_info_to_dict(self):
        from edge.earnings import EarningsInfo

        info = EarningsInfo(
            has_earnings=True, earnings_date="2026-05-15",
            days_to_earnings=12, iv_inflation=0.5,
            expected_move_pct=3.2, in_earnings_window=False,
        )
        d = info.to_dict()
        assert d["has_earnings"] is True
        assert d["iv_inflation"] == 0.5


# ── Skew Z-Score Tests ────────────────────────────────────────────────────────

class TestSkewZScore:
    @patch("data.chain_store.get_iv_history")
    def test_skew_zscore_computation(self, mock_history):
        from market_state import _compute_skew_zscore

        # 20 days of skew data with mean ~0.05, std ~0.01
        skew_history = [
            {"skew_25d": 0.04 + i * 0.001} for i in range(25)
        ]
        mock_history.return_value = skew_history

        zscore = _compute_skew_zscore("SPY", current_skew=0.08)
        assert zscore > 1.0  # well above mean

    @patch("data.chain_store.get_iv_history")
    def test_skew_zscore_insufficient_history(self, mock_history):
        from market_state import _compute_skew_zscore

        mock_history.return_value = [{"skew_25d": 0.05}] * 5  # only 5 rows
        zscore = _compute_skew_zscore("SPY", current_skew=0.08)
        assert zscore == 0.0  # not enough data

    @patch("data.chain_store.get_iv_history")
    def test_skew_zscore_no_skew_data(self, mock_history):
        from market_state import _compute_skew_zscore

        mock_history.return_value = [{"skew_25d": None}] * 25
        zscore = _compute_skew_zscore("SPY", current_skew=0.05)
        assert zscore == 0.0

    def test_vol_surface_has_skew_zscore(self):
        from market_state import VolSurface

        vs = VolSurface(atm_iv=0.20, skew_zscore=1.5)
        assert vs.skew_zscore == 1.5
