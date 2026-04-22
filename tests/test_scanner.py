"""
Unit tests for the options chain scanner (Phase A).

All yfinance calls are mocked — no network dependency.
Covers: provider base, cached provider, IV rank, contract filter,
edge calculator, scorer, and end-to-end scanner pipeline.

Options Analytics Team — 2026-04-02
"""

import math
import sys
import os
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from scanner.providers.base import (
    ChainProvider, ChainSnapshot, HistoryData, OptionContract,
)
from scanner.providers.cached_provider import CachedProvider
from scanner.iv_rank import compute_iv_metrics
from scanner.contract_filter import filter_contracts
from scanner.edge import compute_edge
from scanner.scorer import score_signal, rank_signals
from scanner import OptionSignal
from scanner.scanner import OptionsScanner


# ======================================================================
# Helpers — reusable fixtures
# ======================================================================

def _make_contract(**overrides) -> OptionContract:
    """Build an OptionContract with sensible defaults."""
    exp = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
    defaults = dict(
        ticker='AAPL', strike=175.0, expiry=exp, option_type='call',
        bid=5.0, ask=5.50, mid=5.25, last=5.20,
        volume=500, open_interest=2000, implied_volatility=0.28,
    )
    defaults.update(overrides)
    return OptionContract(**defaults)


def _make_history(n_days=252, ticker='AAPL', base_price=175.0,
                  annual_vol=0.25) -> HistoryData:
    """Build synthetic HistoryData."""
    np.random.seed(42)
    daily_vol = annual_vol / np.sqrt(252)
    returns = np.random.normal(0.0003, daily_vol, n_days)
    prices = base_price * np.cumprod(1 + returns)
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
    closes = pd.Series(prices, index=dates)
    rv30 = float(np.std(returns[-30:]) * np.sqrt(252))
    rv60 = float(np.std(returns[-60:]) * np.sqrt(252))
    return HistoryData(ticker=ticker, closes=closes, returns=returns,
                       realized_vol_30d=rv30, realized_vol_60d=rv60)


def _make_snapshot(spot=175.0, n_contracts=5) -> ChainSnapshot:
    """Build a ChainSnapshot with a range of strikes."""
    exp = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
    contracts = []
    for i in range(n_contracts):
        strike = spot - 10 + i * 5
        contracts.append(_make_contract(strike=strike, expiry=exp))
        contracts.append(_make_contract(strike=strike, expiry=exp,
                                        option_type='put',
                                        bid=3.0, ask=3.40, mid=3.20))
    return ChainSnapshot(
        ticker='AAPL', spot=spot, fetched_at=datetime.now(),
        contracts=contracts, expiries=[exp],
    )


class MockProvider(ChainProvider):
    """Deterministic mock provider for testing."""

    def __init__(self, spot=175.0, n_contracts=5):
        self._spot = spot
        self._n_contracts = n_contracts

    def get_spot(self, ticker):
        return self._spot

    def get_chain(self, ticker, min_dte=7, max_dte=90):
        return _make_snapshot(self._spot, self._n_contracts)

    def get_history(self, ticker, days=365):
        return _make_history()

    def get_risk_free_rate(self):
        return 0.045


# ======================================================================
# TestProviderBase — dataclass construction, ABC enforcement
# ======================================================================

class TestProviderBase:
    def test_option_contract_construction(self):
        c = _make_contract()
        assert c.ticker == 'AAPL'
        assert c.mid == 5.25
        assert c.option_type == 'call'

    def test_chain_snapshot_construction(self):
        snap = _make_snapshot()
        assert snap.ticker == 'AAPL'
        assert snap.spot == 175.0
        assert len(snap.contracts) == 10  # 5 calls + 5 puts

    def test_history_data_construction(self):
        h = _make_history()
        assert h.ticker == 'AAPL'
        assert len(h.returns) == 252
        assert h.realized_vol_30d > 0

    def test_abc_enforcement(self):
        """ChainProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ChainProvider()


# ======================================================================
# TestCachedProvider — cache hit/miss, TTL expiry
# ======================================================================

class TestCachedProvider:
    def test_cache_hit(self):
        mock = MockProvider()
        cached = CachedProvider(mock, chain_ttl=300, history_ttl=300)
        s1 = cached.get_spot('AAPL')
        s2 = cached.get_spot('AAPL')
        assert s1 == s2 == 175.0

    def test_cache_stores_result(self):
        mock = MockProvider()
        cached = CachedProvider(mock, chain_ttl=300, history_ttl=300)
        cached.get_spot('AAPL')
        # Check cache key exists
        assert ('spot', 'AAPL') in cached._cache

    def test_cache_ttl_expiry(self):
        mock = MockProvider()
        cached = CachedProvider(mock, chain_ttl=0, history_ttl=0)  # instant expiry
        cached.get_spot('AAPL')
        # With TTL=0, cache should always miss
        time.sleep(0.01)
        result = cached._get_cached(('spot', 'AAPL'), 0)
        assert result is None

    def test_rfr_cached(self):
        mock = MockProvider()
        cached = CachedProvider(mock, chain_ttl=300, history_ttl=3600)
        r1 = cached.get_risk_free_rate()
        r2 = cached.get_risk_free_rate()
        assert r1 == r2 == 0.045


# ======================================================================
# TestIVRank — known inputs → expected rank/percentile/regime
# ======================================================================

class TestIVRank:
    def test_iv_rank_bounds(self):
        h = _make_history()
        result = compute_iv_metrics(0.25, h)
        assert 0 <= result['iv_rank'] <= 100
        assert 0 <= result['iv_percentile'] <= 100

    def test_iv_rank_at_min(self):
        h = _make_history()
        # IV equal to the minimum rolling RV should yield rank ≈ 0
        result = compute_iv_metrics(result['rv_low'] if (result := compute_iv_metrics(0.01, h)) else 0.01, h)
        # With a very low IV, rank should be near 0
        assert result['iv_rank'] <= 5  # may not be exactly 0 due to discretization

    def test_iv_rank_at_max(self):
        h = _make_history()
        # IV well above the max rolling RV should yield rank = 100
        result = compute_iv_metrics(5.0, h)
        assert result['iv_rank'] == 100

    def test_regime_low(self):
        h = _make_history()
        result = compute_iv_metrics(0.01, h)
        assert result['iv_regime'] == 'LOW_IV'

    def test_regime_high(self):
        h = _make_history()
        result = compute_iv_metrics(5.0, h)
        assert result['iv_regime'] == 'HIGH_IV'

    def test_insufficient_history(self):
        """With <30 days of data, should return defaults."""
        h = HistoryData(ticker='X', closes=pd.Series(dtype=float),
                        returns=np.random.randn(10),
                        realized_vol_30d=float('nan'),
                        realized_vol_60d=float('nan'))
        result = compute_iv_metrics(0.30, h)
        assert result['iv_rank'] == 50.0
        assert result['iv_percentile'] == 50.0
        assert result['iv_regime'] == 'MODERATE_IV'


# ======================================================================
# TestContractFilter — each filter criterion independently
# ======================================================================

class TestContractFilter:
    def test_nan_iv_excluded(self):
        c = _make_contract(implied_volatility=float('nan'))
        result = filter_contracts([c], spot=175.0, risk_free_rate=0.045)
        assert len(result) == 0

    def test_low_oi_excluded(self):
        c = _make_contract(open_interest=5)
        result = filter_contracts([c], spot=175.0, risk_free_rate=0.045,
                                  min_oi=100)
        assert len(result) == 0

    def test_wide_spread_excluded(self):
        c = _make_contract(bid=2.0, ask=5.0, mid=3.5)  # spread ~85%
        result = filter_contracts([c], spot=175.0, risk_free_rate=0.045,
                                  max_spread_pct=15.0)
        assert len(result) == 0

    def test_moneyness_out_of_range(self):
        c = _make_contract(strike=300.0)  # way OTM
        result = filter_contracts([c], spot=175.0, risk_free_rate=0.045,
                                  moneyness_range=(0.85, 1.15))
        assert len(result) == 0

    def test_valid_contract_passes(self):
        c = _make_contract(strike=182.0)  # slightly OTM, delta ~0.35
        result = filter_contracts([c], spot=175.0, risk_free_rate=0.045)
        assert len(result) == 1

    def test_empty_input(self):
        result = filter_contracts([], spot=175.0, risk_free_rate=0.045)
        assert result == []


# ======================================================================
# TestEdge — known BS price → expected edge_pct and direction
# ======================================================================

class TestEdge:
    def test_positive_edge(self):
        """When GARCH vol > chain IV, theo > mid → BUY."""
        c = _make_contract(implied_volatility=0.20, mid=4.0)
        result = compute_edge(c, spot=175.0, garch_vol=0.35,
                              risk_free_rate=0.045, dte=30)
        assert result['edge_pct'] > 0
        assert result['direction'] == 'BUY'

    def test_negative_edge(self):
        """When GARCH vol < chain IV, theo < mid → SELL."""
        c = _make_contract(implied_volatility=0.40, mid=10.0)
        result = compute_edge(c, spot=175.0, garch_vol=0.15,
                              risk_free_rate=0.045, dte=30)
        assert result['edge_pct'] < 0
        assert result['direction'] == 'SELL'

    def test_greeks_present(self):
        c = _make_contract()
        result = compute_edge(c, spot=175.0, garch_vol=0.28,
                              risk_free_rate=0.045, dte=30)
        for key in ['delta', 'gamma', 'theta', 'vega', 'rho']:
            assert key in result

    def test_edge_pct_type(self):
        c = _make_contract()
        result = compute_edge(c, spot=175.0, garch_vol=0.28,
                              risk_free_rate=0.045, dte=30)
        assert isinstance(result['edge_pct'], float)


# ======================================================================
# TestScorer — weight application, ranking order
# ======================================================================

class TestScorer:
    def test_conviction_bounds(self):
        score = score_signal(
            edge_pct=10.0, iv_rank=60.0, spread_pct=5.0,
            open_interest=1000, theta=-0.05, vega=0.30,
            direction='SELL',
        )
        assert 0 <= score <= 100

    def test_higher_edge_higher_score(self):
        base = dict(iv_rank=50.0, spread_pct=5.0, open_interest=1000,
                    theta=-0.05, vega=0.30, direction='BUY')
        s_low = score_signal(edge_pct=2.0, **base)
        s_high = score_signal(edge_pct=15.0, **base)
        assert s_high > s_low

    def test_iv_rank_alignment_sell(self):
        """SELL + HIGH iv_rank should score higher than SELL + LOW iv_rank."""
        base = dict(edge_pct=5.0, spread_pct=5.0, open_interest=1000,
                    theta=-0.05, vega=0.30, direction='SELL')
        s_high_rank = score_signal(iv_rank=90.0, **base)
        s_low_rank = score_signal(iv_rank=10.0, **base)
        assert s_high_rank > s_low_rank

    def test_rank_signals_order(self):
        sig_a = OptionSignal(
            ticker='A', strike=100, expiry='2026-05-01', option_type='call',
            dte=30, spot=100, bid=5, ask=5.5, mid=5.25, open_interest=1000,
            bid_ask_spread_pct=9.5, chain_iv=0.25, iv_rank=50, iv_percentile=50,
            iv_regime='MODERATE_IV', garch_vol=0.25, theo_price=5.3, edge_pct=1.0,
            direction='BUY', delta=0.5, gamma=0.02, theta=-0.05, vega=0.3,
            conviction=40.0,
        )
        sig_b = OptionSignal(
            ticker='B', strike=100, expiry='2026-05-01', option_type='call',
            dte=30, spot=100, bid=5, ask=5.5, mid=5.25, open_interest=1000,
            bid_ask_spread_pct=9.5, chain_iv=0.25, iv_rank=50, iv_percentile=50,
            iv_regime='MODERATE_IV', garch_vol=0.25, theo_price=5.3, edge_pct=5.0,
            direction='BUY', delta=0.5, gamma=0.02, theta=-0.05, vega=0.3,
            conviction=80.0,
        )
        ranked = rank_signals([sig_a, sig_b])
        assert ranked[0].ticker == 'B'
        assert ranked[1].ticker == 'A'


# ======================================================================
# TestScanner — mock provider, end-to-end pipeline
# ======================================================================

class TestScanner:
    def test_scan_ticker_returns_signals(self):
        provider = MockProvider()
        scanner = OptionsScanner(provider=provider)
        signals = scanner.scan_ticker('AAPL')
        assert isinstance(signals, list)
        # Should have some signals (our mock has valid contracts)
        assert len(signals) > 0
        assert all(isinstance(s, OptionSignal) for s in signals)

    def test_scan_watchlist_returns_ranked(self):
        provider = MockProvider()
        scanner = OptionsScanner(provider=provider)
        signals = scanner.scan_watchlist(['AAPL'])
        assert isinstance(signals, list)
        if len(signals) > 1:
            # Conviction should be non-increasing
            convictions = [s.conviction for s in signals]
            assert convictions == sorted(convictions, reverse=True)

    def test_scan_watchlist_handles_failure(self):
        """A failing ticker should be skipped, not crash the whole scan."""
        class FailProvider(MockProvider):
            def get_chain(self, ticker, min_dte=7, max_dte=90):
                if ticker == 'BAD':
                    raise RuntimeError("API error")
                return super().get_chain(ticker, min_dte, max_dte)

        provider = FailProvider()
        scanner = OptionsScanner(provider=provider)
        signals = scanner.scan_watchlist(['BAD', 'AAPL'])
        # Should still get AAPL signals
        assert any(s.ticker == 'AAPL' for s in signals)

    def test_signal_fields_populated(self):
        provider = MockProvider()
        scanner = OptionsScanner(provider=provider)
        signals = scanner.scan_ticker('AAPL')
        if signals:
            s = signals[0]
            assert s.ticker == 'AAPL'
            assert s.spot == 175.0
            assert s.dte > 0
            assert s.iv_regime in ('LOW_IV', 'MODERATE_IV', 'HIGH_IV')
            assert s.direction in ('BUY', 'SELL')
            assert 0 <= s.conviction <= 100

    def test_empty_chain(self):
        """Provider returning empty chain should yield no signals."""
        class EmptyProvider(MockProvider):
            def get_chain(self, ticker, min_dte=7, max_dte=90):
                return ChainSnapshot(
                    ticker=ticker, spot=175.0, fetched_at=datetime.now(),
                    contracts=[], expiries=[],
                )

        provider = EmptyProvider()
        scanner = OptionsScanner(provider=provider)
        signals = scanner.scan_ticker('AAPL')
        assert signals == []
