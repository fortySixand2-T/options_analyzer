"""
Tests for the robustness / OOS harness (src/backtest/robustness.py).

DB-backed (skip if chain_snapshots.db absent); isolated cache so a stale cache
can't mask a regression (F-005).
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chain_snapshots.db")
needs_db = pytest.mark.skipif(not os.path.exists(DB_PATH), reason="chain_snapshots.db not found")


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("CHAIN_SNAPSHOTS_DB", DB_PATH)


@pytest.fixture
def req():
    return BacktestRequest(
        strategy="short_put_spread", symbol="SPY",
        start_date=date(2022, 1, 1), end_date=date(2026, 5, 21),
        exit_rule="strategy", fill_mode="bid_ask",
    )


@needs_db
class TestRobustnessHarness:
    def test_report_shape_and_verdict(self, req, isolated_cache):
        from backtest.robustness import run_robustness
        r = run_robustness(req, n_folds=4, oos_fraction=0.3)
        assert r["verdict"] in {"robust", "fragile_or_no_edge", "insufficient_sample"}
        assert "time_folds" in r and "oos_split" in r and "perturbation" in r
        assert len(r["time_folds"]["folds"]) >= 1

    def test_perturbation_is_stable_and_monotonic(self, req, isolated_cache):
        # The harness itself must observe the F-004/F-006 guarantees.
        from backtest.robustness import perturbation_analysis
        p = perturbation_analysis(req)
        assert p["trade_count_stable"] is True      # F-004: trade set fixed under perturbation
        assert p["slippage_monotonic"] is True      # F-006: slippage is a strict cost

    def test_primary_metric_routing(self):
        # Each strategy routes to its correct metric family (no DB needed).
        from backtest.models import BacktestStats
        from backtest.robustness import primary_metrics
        s = BacktestStats(calmar_ratio=1.0, cvar_95=-100.0, max_single_loss=-200.0,
                          pnl_skew=-2.0, return_on_risk=0.1, profit_factor=1.5, win_rate=80.0)
        assert primary_metrics(s, "short_put_spread")["family"] == "tail"
        assert primary_metrics(s, "iron_condor")["family"] == "tail"
        assert primary_metrics(s, "long_call_spread")["family"] == "directional"
        assert primary_metrics(s, "butterfly")["family"] == "convex"

    def test_oos_split_returns_both_slices(self, req, isolated_cache):
        from backtest.robustness import oos_split_analysis
        o = oos_split_analysis(req, oos_fraction=0.3)
        assert "in_sample" in o and "out_of_sample" in o
        assert o["oos_verdict"] in {"holds", "degrades_oos", "no_in_sample_edge", "insufficient_sample"}
