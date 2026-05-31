"""
Economic-invariant tests for the backtest engines (F-011).

The pre-existing suite checked that the pipeline RUNS and produces plausibly-
shaped output — so every silent wrong-number bug this session passed it:
F-002 (P&L sign), F-003 (fabricated spread), F-004 (path dependence),
F-006 (return-series), F-008 (cross-expiry legs), F-009 (butterfly priced as a
call). These tests instead assert ECONOMIC INVARIANTS and per-strategy
known-answers, converting each past bug into a permanent guard. Every test
names the finding (F-0NN) it protects.

Unit invariants need no data. DB-backed invariants skip if chain_snapshots.db
is absent and use an ISOLATED cache (BACKTEST_CACHE_DB → tmp) so a stale cache
can never mask a regression (F-005).
"""

import math
import os
import sqlite3
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest
from backtest.chain_replay import (
    run_chain_replay, _load_snapshots, _load_contracts, _select_strikes,
    _compute_entry_price, _compute_exit_price,
)
from backtest.local_backtest import _price_strategy
from models.black_scholes import black_scholes_price

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chain_snapshots.db")
HAS_DB = os.path.exists(DB_PATH)
needs_db = pytest.mark.skipif(not HAS_DB, reason="chain_snapshots.db not found")

SPREADS = ["short_put_spread", "short_call_spread", "long_call_spread",
           "long_put_spread", "iron_condor", "butterfly"]
INC = 5.0  # local_backtest strike increment for spot >= 100


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point the backtest cache at a throwaway DB so stale entries can't mask
    a regression (F-005) and we never clobber the real cache."""
    monkeypatch.setenv("BACKTEST_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("CHAIN_SNAPSHOTS_DB", DB_PATH)


# ── Unit invariants (no DB) ──────────────────────────────────────────────────

class TestPnLSignInvariants:
    """F-002: pnl = entry_net - current_value must be correct for credit AND debit."""

    def test_credit_spread_that_shrinks_is_a_profit(self):
        pos = {"is_credit": True, "legs": [
            {"side": "sell", "contract": {"strike": 95.0, "option_type": "put", "bid": 0.95, "ask": 1.05, "mid": 1.0}},
            {"side": "buy",  "contract": {"strike": 90.0, "option_type": "put", "bid": 0.35, "ask": 0.45, "mid": 0.4}}]}
        exit_c = {(95.0, "put"): {"bid": 0.05, "ask": 0.15, "mid": 0.10},
                  (90.0, "put"): {"bid": 0.00, "ask": 0.05, "mid": 0.02}}
        en = _compute_entry_price(pos, "mid")
        cv = _compute_exit_price(pos, exit_c, "mid")
        assert en > 0                       # collected a credit
        assert en - cv > 0                  # spread shrank → profit

    def test_debit_spread_that_appreciates_is_a_profit(self):
        pos = {"is_credit": False, "legs": [
            {"side": "buy",  "contract": {"strike": 100.0, "option_type": "call", "bid": 2.95, "ask": 3.05, "mid": 3.0}},
            {"side": "sell", "contract": {"strike": 105.0, "option_type": "call", "bid": 0.95, "ask": 1.05, "mid": 1.0}}]}
        exit_c = {(100.0, "call"): {"bid": 3.95, "ask": 4.05, "mid": 4.0},
                  (105.0, "call"): {"bid": 1.45, "ask": 1.55, "mid": 1.5}}
        en = _compute_entry_price(pos, "mid")
        cv = _compute_exit_price(pos, exit_c, "mid")
        assert en < 0                       # paid a debit
        assert en - cv > 0                  # spread appreciated → profit (unified formula)


class TestStrategyPayoffInvariants:
    """F-009: each strategy must be priced as its real structure, not something else."""

    def test_butterfly_is_bounded_and_not_a_call(self):
        T, iv, r = 14 / 365, 0.20, 0.04
        bf = _price_strategy(500, 500, iv, T, r, "butterfly", False)
        atm_call = black_scholes_price(500, 500, T, r, iv, "call")
        assert 0 <= bf <= INC * 1.5         # bounded by ~wing width...
        assert bf < atm_call * 0.5          # ...and nowhere near the ATM call it used to be priced as

    def test_butterfly_peaks_at_center(self):
        T, iv, r = 2 / 365, 0.20, 0.04
        at_center = _price_strategy(500, 500, iv, T, r, "butterfly", False)
        far = _price_strategy(530, 500, iv, T, r, "butterfly", False)
        assert at_center > far              # pin payoff

    def test_credit_spread_value_bounded_by_width(self):
        T, iv, r = 7 / 365, 0.20, 0.04
        v = _price_strategy(500, 500, iv, T, r, "short_put_spread", True)
        assert 0 <= v <= INC * 1.05         # a 1-wide credit spread can't exceed its width


class TestMaxPainAndSkewMetrics:
    """F-013: max-pain centering + skew-aware metrics."""

    def test_max_pain_known_answer(self):
        from backtest.chain_replay import _compute_max_pain
        exp = "2026-06-19"
        contracts = [
            {"strike": 90.0, "option_type": "call", "open_interest": 200, "expiry": exp},
            {"strike": 100.0, "option_type": "call", "open_interest": 50, "expiry": exp},
            {"strike": 100.0, "option_type": "put", "open_interest": 50, "expiry": exp},
            {"strike": 110.0, "option_type": "put", "open_interest": 100, "expiry": exp},
        ]
        # Heavy call OI at 90 pulls max pain down to 90 (those calls expire worthless there).
        assert _compute_max_pain(contracts, exp) == 90.0

    def test_max_pain_none_without_oi(self):
        from backtest.chain_replay import _compute_max_pain
        exp = "2026-06-19"
        contracts = [{"strike": k, "option_type": "call", "open_interest": 0, "expiry": exp}
                     for k in (90.0, 100.0, 110.0)]
        assert _compute_max_pain(contracts, exp) is None  # no OI → caller falls back to ATM

    def test_positive_skew_payoff_reads_positive(self):
        # Many small losses + a few large wins (the butterfly/convex profile) → skew > 0.
        from backtest.analyzer import analyze_results
        from backtest.models import BacktestTrade
        pnls = [-10.0] * 18 + [200.0, 220.0]
        trades = [BacktestTrade(entry_date=date(2024, 1, 1), exit_date=date(2024, 1, 3),
                                entry_price=1.0, exit_price=0.5, pnl=p, pnl_pct=1.0,
                                dte_at_entry=7, dte_at_exit=1, win=p > 0) for p in pnls]
        stats = analyze_results(trades)
        assert stats.pnl_skew > 0


class TestStatSanity:
    """F-011/F-005: stats must be sane and serializable."""

    def test_profit_factor_is_finite(self):
        # Even with zero losses, PF must be finite/JSON-serializable (not inf).
        from backtest.analyzer import analyze_results
        from backtest.models import BacktestTrade
        winners = [BacktestTrade(entry_date=date(2024, 1, 1), exit_date=date(2024, 1, 2),
                                 entry_price=1.0, exit_price=0.0, pnl=50.0, pnl_pct=10.0,
                                 dte_at_entry=7, dte_at_exit=1, win=True) for _ in range(5)]
        stats = analyze_results(winners)
        assert math.isfinite(stats.profit_factor)
        assert 0 <= stats.win_rate <= 100


# ── DB-backed invariants (isolated cache) ────────────────────────────────────

@needs_db
class TestDefinedRiskInvariants:
    """F-008: spread legs share an expiry and premium can't exceed the strike span."""

    @pytest.mark.parametrize("strat", SPREADS)
    def test_single_expiry_and_premium_within_span(self, strat):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        snaps = _load_snapshots(conn, "SPY", date(2024, 1, 1), date(2026, 5, 21))
        checked = 0
        for idx in range(0, len(snaps), 5):
            s = snaps[idx]
            cons = _load_contracts(conn, s["id"], 3, 14, s["date"])
            if len(cons) < 4:
                continue
            for c in cons:
                c["_snap_date"] = s["date"]
            pos = _select_strikes(cons, s["spot"], strat, 0.20)
            if not pos:
                continue
            expiries = {leg["contract"]["expiry"] for leg in pos["legs"]}
            assert len(expiries) == 1, f"{strat}: legs span expiries {expiries}"
            strikes = [leg["contract"]["strike"] for leg in pos["legs"]]
            span = max(strikes) - min(strikes)
            en = _compute_entry_price(pos, "bid_ask")
            assert abs(en) <= span * 1.10 + 0.01, f"{strat}: premium {en:.2f} exceeds span {span}"
            checked += 1
            if checked >= 30:
                break
        conn.close()
        assert checked > 0, f"{strat}: no positions constructed to check"


@needs_db
class TestSlippageMonotonic:
    """F-006: slippage is a strict cost — more slippage never improves P&L."""

    def test_pnl_non_increasing_with_slippage(self, isolated_cache):
        def pnl(slip):
            return run_chain_replay(BacktestRequest(
                strategy="short_put_spread", symbol="SPY",
                start_date=date(2024, 1, 1), end_date=date(2026, 5, 21),
                exit_rule="strategy", fill_mode="bid_ask", slippage_pct=slip,
            )).stats.total_pnl
        p0, p1, p2 = pnl(0.0), pnl(1.0), pnl(2.0)
        assert p0 >= p1 - 1e-6 >= p2 - 1e-6


@needs_db
class TestPerturbationStability:
    """F-004: the trade SET must not change under a fill/slippage perturbation."""

    def test_trade_count_stable(self, isolated_cache):
        def n(fill_mode, slip):
            return run_chain_replay(BacktestRequest(
                strategy="short_put_spread", symbol="SPY",
                start_date=date(2024, 1, 1), end_date=date(2026, 5, 21),
                exit_rule="strategy", fill_mode=fill_mode, slippage_pct=slip,
            )).stats.total_trades
        base = n("mid", 0.0)
        assert base > 0
        assert n("bid_ask", 0.0) == base
        assert n("bid_ask", 2.0) == base


@needs_db
class TestResultStatSanity:
    """F-011: a real backtest's stats stay in valid ranges and serialize."""

    def test_winrate_and_pf_sane(self, isolated_cache):
        r = run_chain_replay(BacktestRequest(
            strategy="short_put_spread", symbol="SPY",
            start_date=date(2024, 1, 1), end_date=date(2026, 5, 21),
            exit_rule="strategy"))
        assert 0 <= r.stats.win_rate <= 100
        assert math.isfinite(r.stats.profit_factor)
        # result must round-trip through Pydantic/JSON (cache path)
        r.model_dump_json()
