"""Tests for data pipeline: per-expiry IV storage and retrieval."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestIvByExpiry:

    def test_store_and_retrieve(self, tmp_path):
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_iv_by_expiry, get_iv_by_expiry

        rows = [
            {"expiry_date": "2026-05-10", "dte": 7, "atm_iv": 0.22,
             "mean_spread_pct": 3.5, "sample_size": 20},
            {"expiry_date": "2026-05-24", "dte": 21, "atm_iv": 0.25,
             "mean_spread_pct": 4.2, "sample_size": 30},
        ]
        store_iv_by_expiry("SPY", "2026-05-03", rows)

        result = get_iv_by_expiry("SPY")
        assert len(result) == 2
        assert result[0]["expiry_date"] == "2026-05-10"
        assert result[0]["atm_iv"] == pytest.approx(0.22)
        assert result[1]["mean_spread_pct"] == pytest.approx(4.2)

        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_upsert_overwrites(self, tmp_path):
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_iv_by_expiry, get_iv_by_expiry

        store_iv_by_expiry("SPY", "2026-05-03", [
            {"expiry_date": "2026-05-10", "dte": 7, "atm_iv": 0.22,
             "mean_spread_pct": 3.5, "sample_size": 20},
        ])
        store_iv_by_expiry("SPY", "2026-05-03", [
            {"expiry_date": "2026-05-10", "dte": 7, "atm_iv": 0.28,
             "mean_spread_pct": 5.0, "sample_size": 25},
        ])

        result = get_iv_by_expiry("SPY")
        assert len(result) == 1
        assert result[0]["atm_iv"] == pytest.approx(0.28)

        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_date_range_filter(self, tmp_path):
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_iv_by_expiry, get_iv_by_expiry

        for d in ["2026-05-01", "2026-05-02", "2026-05-03"]:
            store_iv_by_expiry("SPY", d, [
                {"expiry_date": "2026-05-15", "dte": 14, "atm_iv": 0.22},
            ])

        result = get_iv_by_expiry("SPY", start_date="2026-05-02")
        assert len(result) == 2

        result = get_iv_by_expiry("SPY", start_date="2026-05-01", end_date="2026-05-02")
        assert len(result) == 2

        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_multiple_tickers(self, tmp_path):
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_iv_by_expiry, get_iv_by_expiry

        store_iv_by_expiry("SPY", "2026-05-03", [
            {"expiry_date": "2026-05-10", "dte": 7, "atm_iv": 0.22},
        ])
        store_iv_by_expiry("QQQ", "2026-05-03", [
            {"expiry_date": "2026-05-10", "dte": 7, "atm_iv": 0.28},
        ])

        assert len(get_iv_by_expiry("SPY")) == 1
        assert len(get_iv_by_expiry("QQQ")) == 1
        assert get_iv_by_expiry("IWM") == []

        del os.environ["CHAIN_SNAPSHOTS_DB"]

    def test_empty_rows(self, tmp_path):
        os.environ["CHAIN_SNAPSHOTS_DB"] = str(tmp_path / "test.db")

        from data.chain_store import store_iv_by_expiry, get_iv_by_expiry

        store_iv_by_expiry("SPY", "2026-05-03", [])
        assert get_iv_by_expiry("SPY") == []

        del os.environ["CHAIN_SNAPSHOTS_DB"]


class TestSafeFloat:

    def test_safe_float_valid(self):
        from scanner.providers.flashalpha_client import _safe_float
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5
        assert _safe_float(0) == 0.0

    def test_safe_float_none(self):
        from scanner.providers.flashalpha_client import _safe_float
        assert _safe_float(None) == 0.0
        assert _safe_float(None, default=42.0) == 42.0

    def test_safe_float_nan(self):
        from scanner.providers.flashalpha_client import _safe_float
        assert _safe_float(float("nan")) == 0.0

    def test_safe_float_inf(self):
        from scanner.providers.flashalpha_client import _safe_float
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf")) == 0.0

    def test_safe_float_invalid_string(self):
        from scanner.providers.flashalpha_client import _safe_float
        assert _safe_float("not_a_number") == 0.0


class TestSafeRound:

    def test_safe_round_valid(self):
        from market_state import _safe_round
        assert _safe_round(3.14159, 2) == 3.14

    def test_safe_round_nan(self):
        from market_state import _safe_round
        assert _safe_round(float("nan"), 2) == 0.0

    def test_safe_round_inf(self):
        from market_state import _safe_round
        assert _safe_round(float("inf"), 2) == 0.0

    def test_safe_round_none(self):
        from market_state import _safe_round
        assert _safe_round(None, 2) == 0.0
