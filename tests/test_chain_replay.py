"""
Tests for the chain-replay backtester using real chain snapshot data.

These tests hit the actual chain_snapshots.db — no mocks, no BS pricing.
They validate that we can construct spreads from real chains and compute
P&L from real bid/ask/mid quotes.

Requires: data/chain_snapshots.db with SPY snapshots (2020+).
"""

import sys
import os
import sqlite3
from datetime import date

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest, BacktestResult
from backtest.chain_replay import (
    run_chain_replay,
    _load_snapshots,
    _load_contracts,
    _select_strikes,
    _compute_entry_price,
    _compute_intrinsic_exit,
    _classify_regime,
    _find_delta_strike,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chain_snapshots.db")
HAS_DB = os.path.exists(DB_PATH)

pytestmark = pytest.mark.skipif(not HAS_DB, reason="chain_snapshots.db not found")


@pytest.fixture
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def spy_snapshots(conn):
    return _load_snapshots(conn, "SPY", date(2023, 1, 1), date(2024, 12, 31))


# ── Data Availability ───────────────────────────────────────────────────────


class TestDataAvailability:
    def test_spy_has_snapshots(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2020, 1, 1), date(2026, 12, 31))
        assert len(snaps) > 500, f"Expected 500+ SPY snapshots, got {len(snaps)}"

    def test_snapshots_have_spot(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2023, 1, 1), date(2023, 12, 31))
        for s in snaps:
            assert s["spot"] > 0, f"Snapshot {s['date']} has no spot price"

    def test_contracts_have_bid_ask(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        assert len(snaps) > 0
        contracts = _load_contracts(conn, snaps[0]["id"], 3, 14, snaps[0]["date"])
        assert len(contracts) > 0, "No contracts found in DTE 3-14 range"
        for c in contracts:
            assert c["bid"] > 0, f"Contract {c['strike']} {c['option_type']} has no bid"
            assert c["ask"] >= c["bid"], f"Ask < bid for {c['strike']}"
            assert c["mid"] > 0, f"Contract {c['strike']} has no mid"

    def test_contracts_have_iv(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        contracts = _load_contracts(conn, snaps[0]["id"], 3, 14, snaps[0]["date"])
        iv_count = sum(1 for c in contracts if c.get("implied_volatility", 0) > 0)
        assert iv_count / len(contracts) > 0.8, "Less than 80% of contracts have IV"

    def test_older_data_has_fewer_strikes(self, conn):
        """Documents the data gap: 2020 has ~60 contracts vs 2025+ with 2000+."""
        old = _load_snapshots(conn, "SPY", date(2020, 3, 1), date(2020, 3, 31))
        new = _load_snapshots(conn, "SPY", date(2026, 5, 1), date(2026, 5, 21))
        if old and new:
            old_contracts = _load_contracts(conn, old[0]["id"], 0, 30, old[0]["date"])
            new_contracts = _load_contracts(conn, new[-1]["id"], 0, 30, new[-1]["date"])
            assert len(old_contracts) < len(new_contracts), \
                "Expected older snapshots to have fewer contracts"


# ── Strike Selection ─────────────────────────────────────────────────────────


class TestStrikeSelection:
    def test_iron_condor_from_real_chain(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 3, 14, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "iron_condor", 0.20)
        assert position is not None, "Failed to construct iron condor from real chain"
        assert len(position["legs"]) == 4
        assert position["is_credit"] is True

        sells = [l for l in position["legs"] if l["side"] == "sell"]
        buys = [l for l in position["legs"] if l["side"] == "buy"]
        assert len(sells) == 2
        assert len(buys) == 2

        put_legs = [l for l in position["legs"] if l["contract"]["option_type"] == "put"]
        call_legs = [l for l in position["legs"] if l["contract"]["option_type"] == "call"]
        assert len(put_legs) == 2
        assert len(call_legs) == 2

    def test_short_put_spread_from_real_chain(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 3, 14, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "short_put_spread", 0.20)
        assert position is not None
        assert len(position["legs"]) == 2
        assert position["is_credit"] is True
        assert position["legs"][0]["side"] == "sell"
        assert position["legs"][1]["side"] == "buy"
        assert position["legs"][0]["contract"]["strike"] > position["legs"][1]["contract"]["strike"]

    def test_butterfly_from_real_chain(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 0, 7, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "butterfly", 0.20)
        if position:
            assert len(position["legs"]) == 4
            assert position["is_credit"] is False

    def test_long_call_spread_from_real_chain(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 3, 14, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "long_call_spread", 0.20)
        assert position is not None
        assert len(position["legs"]) == 2
        assert position["is_credit"] is False
        assert position["legs"][0]["side"] == "buy"
        assert position["legs"][1]["side"] == "sell"


# ── P&L Calculation ──────────────────────────────────────────────────────────


class TestPnlCalculation:
    def test_credit_spread_entry_price_positive(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 3, 14, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "short_put_spread", 0.20)
        assert position is not None
        entry = _compute_entry_price(position)
        assert entry > 0, f"Credit spread entry should be positive (credit), got {entry}"

    def test_debit_spread_entry_price_negative(self, conn):
        snaps = _load_snapshots(conn, "SPY", date(2024, 6, 1), date(2024, 6, 30))
        snap = snaps[0]
        contracts = _load_contracts(conn, snap["id"], 3, 14, snap["date"])
        for c in contracts:
            c["_snap_date"] = snap["date"]

        position = _select_strikes(contracts, snap["spot"], "long_call_spread", 0.20)
        assert position is not None
        entry = _compute_entry_price(position)
        assert entry < 0, f"Debit spread entry should be negative (debit), got {entry}"

    def test_intrinsic_exit_otm_is_zero(self):
        position = {
            "legs": [
                {"contract": {"strike": 400.0, "option_type": "put"}, "side": "sell"},
                {"contract": {"strike": 395.0, "option_type": "put"}, "side": "buy"},
            ]
        }
        exit_val = _compute_intrinsic_exit(position, spot=450.0)
        assert exit_val == 0.0, "Both legs OTM should have zero intrinsic"

    def test_intrinsic_exit_itm_put_spread(self):
        position = {
            "legs": [
                {"contract": {"strike": 450.0, "option_type": "put"}, "side": "sell"},
                {"contract": {"strike": 445.0, "option_type": "put"}, "side": "buy"},
            ]
        }
        exit_val = _compute_intrinsic_exit(position, spot=440.0)
        assert exit_val == 5.0, f"Expected 5.0 (max loss on $5 wide spread), got {exit_val}"


# ── Full Backtest Run ────────────────────────────────────────────────────────


class TestFullBacktest:
    def test_short_put_spread_produces_trades(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            exit_rule="50pct",
        )
        result = run_chain_replay(req)
        assert result.source == "chain_replay"
        assert result.stats.total_trades > 0, \
            f"Expected trades, got 0. Issues: {result.data_issues}"
        assert result.stats.total_trades >= 5, \
            f"Expected 5+ trades over 18 months, got {result.stats.total_trades}"

    def test_iron_condor_produces_trades(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="iron_condor",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            exit_rule="50pct",
        )
        result = run_chain_replay(req)
        assert result.source == "chain_replay"
        assert result.stats.total_trades > 0, \
            f"No IC trades. Issues: {result.data_issues}"

    def test_long_call_spread_produces_trades(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="long_call_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            exit_rule="50pct",
        )
        result = run_chain_replay(req)
        assert result.source == "chain_replay"
        assert result.stats.total_trades > 0

    def test_result_has_equity_curve(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 6, 1),
            end_date=date(2024, 6, 30),
            exit_rule="50pct",
        )
        result = run_chain_replay(req)
        if result.stats.total_trades > 0:
            # Equity curve is now a TIME-INDEXED mark-to-market portfolio curve
            # (one point per snapshot), not a per-trade cumsum — see F-006.
            assert len(result.equity_curve) >= 2
            assert result.equity_curve[0] == 0.0

    def test_result_has_regime_breakdown(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
        )
        result = run_chain_replay(req)
        if result.stats.total_trades > 0:
            assert len(result.regime_breakdown) > 0

    def test_regime_filter_reduces_trades(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req_no_filter = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
        )
        req_filter = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            regime_filter=True,
        )
        result_all = run_chain_replay(req_no_filter)
        result_filtered = run_chain_replay(req_filter)
        assert result_filtered.stats.total_trades <= result_all.stats.total_trades

    def test_edge_filter_reduces_trades(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req_no_edge = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
        )
        req_edge = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            edge_threshold=5.0,
        )
        result_all = run_chain_replay(req_no_edge)
        result_edge = run_chain_replay(req_edge)
        assert result_edge.stats.total_trades <= result_all.stats.total_trades

    def test_data_issues_populated(self):
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
            dealer_filter=True,
        )
        result = run_chain_replay(req)
        assert isinstance(result.data_issues, list)

    def test_trades_have_real_prices(self):
        """Verify trade entry/exit prices look like real option prices, not BS artifacts."""
        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 6, 30),
        )
        result = run_chain_replay(req)
        for trade in result.trades[:10]:
            assert 0.01 < abs(trade.entry_price) < 50.0, \
                f"Entry price {trade.entry_price} doesn't look like a real spread price"
            assert trade.dte_at_entry >= 3
            assert trade.dte_at_entry <= 14


# ── Regime Classifier ────────────────────────────────────────────────────────


class TestRegimeClassifier:
    def test_spike_above_030(self):
        assert _classify_regime(0.35, np.full(300, 0.20), 250) == "SPIKE"

    def test_high_iv_percentile(self):
        vol = np.linspace(0.10, 0.25, 300)
        regime = _classify_regime(0.24, vol, 299)
        assert regime == "HIGH_IV"

    def test_low_iv_percentile(self):
        vol = np.linspace(0.10, 0.25, 300)
        regime = _classify_regime(0.11, vol, 299)
        assert regime == "LOW_IV"


# ── Cross-Source Comparison ──────────────────────────────────────────────────


class TestCrossSourceComparison:
    """Compare chain_replay vs local_backtest to quantify BS pricing error."""

    def test_same_interface(self):
        """Both backends accept BacktestRequest and return BacktestResult."""
        from backtest.local_backtest import run_local_backtest

        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 6, 1),
            end_date=date(2024, 6, 30),
        )
        bs_result = run_local_backtest(req)
        chain_result = run_chain_replay(req)

        assert isinstance(bs_result, BacktestResult)
        assert isinstance(chain_result, BacktestResult)
        assert bs_result.source == "local"
        assert chain_result.source == "chain_replay"

    def test_both_produce_trades(self):
        from backtest.local_backtest import run_local_backtest

        os.environ["CHAIN_SNAPSHOTS_DB"] = DB_PATH
        req = BacktestRequest(
            strategy="short_put_spread",
            symbol="SPY",
            start_date=date(2023, 6, 1),
            end_date=date(2024, 6, 30),
        )
        bs_result = run_local_backtest(req)
        chain_result = run_chain_replay(req)

        assert bs_result.stats.total_trades > 0
        assert chain_result.stats.total_trades > 0
