"""
Tests for backtest module (Phase 3).

All tests use synthetic data — no network dependency.
"""

import sys
import os
import tempfile
from datetime import date

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from backtest.models import BacktestRequest, BacktestTrade, BacktestResult, BacktestStats
from backtest.analyzer import (
    analyze_results, compute_regime_breakdown,
    _compute_equity_curve, _compute_max_drawdown, _compute_sharpe,
)
from backtest.cache import _cache_key, get_cached, store_cached


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_trade(pnl=50.0, win=True, regime="LOW_VOL_RANGING", days=15):
    return BacktestTrade(
        entry_date=date(2024, 1, 1),
        exit_date=date(2024, 1, 1 + days) if days < 28 else date(2024, 2, 1),
        entry_price=1.50,
        exit_price=0.75 if win else 3.00,
        pnl=pnl,
        pnl_pct=pnl / 1.50 * 100,
        dte_at_entry=30,
        dte_at_exit=15,
        regime=regime,
        win=win,
        exit_reason="profit_target" if win else "stop_loss",
    )


def _make_request(**overrides):
    defaults = dict(
        strategy="iron_condor",
        symbol="SPY",
        start_date=date(2023, 1, 1),
        end_date=date(2024, 1, 1),
    )
    defaults.update(overrides)
    return BacktestRequest(**defaults)


# ── Analyzer ──────────────────────────────────────────────────────────────────

class TestAnalyzer:
    def test_empty_trades(self):
        stats = analyze_results([])
        assert stats.total_trades == 0
        assert stats.win_rate == 0.0

    def test_all_winners(self):
        trades = [_make_trade(pnl=50, win=True) for _ in range(10)]
        stats = analyze_results(trades)
        assert stats.total_trades == 10
        assert stats.wins == 10
        assert stats.win_rate == 100.0
        assert stats.avg_win == 50.0

    def test_all_losers(self):
        trades = [_make_trade(pnl=-100, win=False) for _ in range(5)]
        stats = analyze_results(trades)
        assert stats.wins == 0
        assert stats.losses == 5
        assert stats.win_rate == 0.0
        assert stats.avg_loss == -100.0

    def test_mixed_trades(self):
        trades = [
            _make_trade(pnl=50, win=True),
            _make_trade(pnl=75, win=True),
            _make_trade(pnl=-100, win=False),
        ]
        stats = analyze_results(trades)
        assert stats.total_trades == 3
        assert stats.wins == 2
        assert stats.losses == 1
        assert stats.total_pnl == 25.0
        assert stats.profit_factor == 1.25

    def test_sharpe_positive(self):
        trades = [_make_trade(pnl=p, win=p > 0) for p in [50, 60, 40, 55, 45]]
        stats = analyze_results(trades)
        assert stats.sharpe_ratio > 0

    def test_max_drawdown(self):
        pnls = [100, -50, -50, 200, -150]
        equity = _compute_equity_curve(pnls)
        dd, dd_pct = _compute_max_drawdown(equity)
        assert dd > 0

    def test_equity_curve_length(self):
        pnls = [10, 20, -5, 15]
        curve = _compute_equity_curve(pnls)
        assert len(curve) == len(pnls) + 1
        assert curve[0] == 0.0
        assert curve[-1] == 40.0

    def test_regime_breakdown(self):
        trades = [
            _make_trade(pnl=50, win=True, regime="LOW_VOL_RANGING"),
            _make_trade(pnl=-30, win=False, regime="LOW_VOL_RANGING"),
            _make_trade(pnl=80, win=True, regime="HIGH_VOL_TRENDING"),
        ]
        breakdown = compute_regime_breakdown(trades)
        assert "LOW_VOL_RANGING" in breakdown
        assert "HIGH_VOL_TRENDING" in breakdown
        assert breakdown["LOW_VOL_RANGING"]["count"] == 2
        assert breakdown["HIGH_VOL_TRENDING"]["count"] == 1


# ── Models ────────────────────────────────────────────────────────────────────

class TestModels:
    def test_request_defaults(self):
        req = BacktestRequest(
            strategy="iron_condor", symbol="SPY",
            start_date=date(2023, 1, 1), end_date=date(2024, 1, 1),
        )
        assert req.entry_delta == 0.20
        assert req.exit_profit_pct == 50.0

    def test_trade_creation(self):
        trade = _make_trade()
        assert trade.win is True
        assert trade.pnl == 50.0

    def test_result_creation(self):
        req = _make_request()
        result = BacktestResult(
            request=req,
            stats=BacktestStats(),
            source="local",
        )
        assert result.source == "local"
        assert result.cached is False

    def test_result_serialization(self):
        req = _make_request()
        result = BacktestResult(
            request=req,
            stats=BacktestStats(total_trades=5, win_rate=60.0),
            trades=[_make_trade()],
            source="local",
        )
        json_str = result.model_dump_json()
        restored = BacktestResult.model_validate_json(json_str)
        assert restored.stats.total_trades == 5
        assert len(restored.trades) == 1


# ── Cache ─────────────────────────────────────────────────────────────────────

class TestCache:
    def test_cache_key_deterministic(self):
        req1 = _make_request()
        req2 = _make_request()
        assert _cache_key(req1) == _cache_key(req2)

    def test_cache_key_varies(self):
        req1 = _make_request(symbol="SPY")
        req2 = _make_request(symbol="QQQ")
        assert _cache_key(req1) != _cache_key(req2)

    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_cache.db")
            os.environ["BACKTEST_CACHE_DB"] = db_path

            req = _make_request()
            result = BacktestResult(
                request=req,
                stats=BacktestStats(total_trades=10, win_rate=70.0),
                trades=[_make_trade()],
                source="local",
            )

            store_cached(req, result)
            cached = get_cached(req)

            assert cached is not None
            assert cached.cached is True
            assert cached.stats.total_trades == 10

            del os.environ["BACKTEST_CACHE_DB"]

    def test_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "empty_cache.db")
            os.environ["BACKTEST_CACHE_DB"] = db_path

            req = _make_request(symbol="NONEXISTENT")
            cached = get_cached(req)
            assert cached is None

            del os.environ["BACKTEST_CACHE_DB"]
