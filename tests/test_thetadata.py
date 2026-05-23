"""
Tests for ThetaData client, backfill pipeline, and greeks storage.

Uses mocked HTTP responses — no Theta Terminal needed to run these.
"""

import sys
import os
import json
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data.thetadata_client import (
    ThetaDataClient,
    _date_to_int,
    _int_to_date,
    _parse_strike,
    _normalize_contract,
    _parse_response,
)


SAMPLE_EOD_RESPONSE = {
    "header": {"format": "json"},
    "response": [
        {
            "symbol": "SPY",
            "expiration": 20240628,
            "strike": 543000,
            "right": "P",
            "bid": 4.68,
            "ask": 4.71,
            "mid_price": 4.695,
            "open": 4.50,
            "high": 4.80,
            "low": 4.40,
            "close": 4.70,
            "volume": 1234,
            "open_interest": 5678,
            "implied_volatility": 0.0949,
            "delta": -0.25,
            "gamma": 0.015,
            "theta": -0.12,
            "vega": 0.35,
            "rho": -0.08,
            "underlying_price": 543.50,
        },
        {
            "symbol": "SPY",
            "expiration": 20240628,
            "strike": 554000,
            "right": "C",
            "bid": 2.10,
            "ask": 2.15,
            "mid_price": 2.125,
            "open": 2.00,
            "high": 2.20,
            "low": 1.95,
            "close": 2.12,
            "volume": 890,
            "open_interest": 3456,
            "implied_volatility": 0.1001,
            "delta": 0.30,
            "gamma": 0.018,
            "theta": -0.10,
            "vega": 0.28,
            "rho": 0.05,
            "underlying_price": 543.50,
        },
    ],
}

SAMPLE_STOCK_EOD_RESPONSE = {
    "response": [
        {"close": 543.50, "open": 540.0, "high": 545.0, "low": 539.0, "volume": 50000000}
    ]
}


# ── Client Unit Tests ────────────────────────────────────────────────────────


class TestConversions:
    def test_date_to_int(self):
        assert _date_to_int("2024-06-28") == 20240628

    def test_int_to_date(self):
        assert _int_to_date(20240628) == "2024-06-28"

    def test_parse_strike_standard(self):
        assert _parse_strike(543000) == 543.0

    def test_parse_strike_with_cents(self):
        assert _parse_strike(543500) == 543.5

    def test_normalize_contract_put(self):
        row = SAMPLE_EOD_RESPONSE["response"][0]
        contract = _normalize_contract(row)
        assert contract is not None
        assert contract["strike"] == 543.0
        assert contract["option_type"] == "put"
        assert contract["expiry"] == "2024-06-28"
        assert contract["bid"] == 4.68
        assert contract["ask"] == 4.71
        assert contract["mid"] == 4.695
        assert contract["delta"] == -0.25
        assert contract["gamma"] == 0.015
        assert contract["open_interest"] == 5678

    def test_normalize_contract_call(self):
        row = SAMPLE_EOD_RESPONSE["response"][1]
        contract = _normalize_contract(row)
        assert contract is not None
        assert contract["option_type"] == "call"
        assert contract["delta"] == 0.30

    def test_normalize_contract_missing_fields(self):
        result = _normalize_contract({})
        assert result is None

    def test_parse_response_dict(self):
        rows = _parse_response(SAMPLE_EOD_RESPONSE)
        assert len(rows) == 2

    def test_parse_response_list(self):
        rows = _parse_response([{"a": 1}, {"b": 2}])
        assert len(rows) == 2

    def test_parse_response_empty(self):
        assert _parse_response({}) == []
        assert _parse_response({"response": "not a list"}) == []


class TestThetaDataClient:
    def test_health_check_success(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client._session, "get", return_value=mock_resp):
            assert client.health_check() is True

    def test_health_check_failure(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        with patch.object(client._session, "get", side_effect=requests.exceptions.ConnectionError):
            assert client.health_check() is False

    def test_get_spot_eod(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_STOCK_EOD_RESPONSE
        with patch.object(client._session, "get", return_value=mock_resp):
            spot = client.get_spot_eod("SPY", "2024-06-28")
            assert spot == 543.50

    def test_get_options_greeks_eod(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_EOD_RESPONSE
        with patch.object(client._session, "get", return_value=mock_resp):
            contracts = client.get_options_greeks_eod("SPY", "2024-06-28", max_dte=14)
            assert len(contracts) == 2
            assert contracts[0]["option_type"] == "put"
            assert contracts[1]["option_type"] == "call"
            assert contracts[0]["delta"] == -0.25

    def test_get_options_intraday_not_implemented(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        with pytest.raises(NotImplementedError):
            client.get_options_greeks_intraday("SPY", "2024-06-28")

    def test_request_retry_on_connection_error(self):
        client = ThetaDataClient(base_url="http://localhost:25503", max_retries=2)
        with patch.object(client._session, "get", side_effect=requests.exceptions.ConnectionError):
            result = client._request("/v3/test", {})
            assert result is None

    def test_request_404_returns_none(self):
        client = ThetaDataClient(base_url="http://localhost:25503")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client._request("/v3/test", {})
            assert result is None

    def test_env_url_override(self):
        with patch.dict(os.environ, {"THETADATA_URL": "http://custom:9999"}):
            client = ThetaDataClient()
            assert client.base_url == "http://custom:9999"


# ── Schema & Greeks Storage Tests ────────────────────────────────────────────


class TestSchemaGreeks:
    @pytest.fixture
    def tmp_db(self, tmp_path):
        db_path = str(tmp_path / "test_chain.db")
        old_env = os.environ.get("CHAIN_SNAPSHOTS_DB")
        os.environ["CHAIN_SNAPSHOTS_DB"] = db_path
        yield db_path
        if old_env is not None:
            os.environ["CHAIN_SNAPSHOTS_DB"] = old_env
        else:
            os.environ.pop("CHAIN_SNAPSHOTS_DB", None)

    def test_migration_adds_greek_columns(self, tmp_db):
        from data.chain_store import _get_conn
        conn = _get_conn()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(chain_contracts)").fetchall()]
        conn.close()
        assert "delta" in cols
        assert "gamma" in cols
        assert "theta" in cols
        assert "vega" in cols
        assert "rho" in cols

    def test_store_snapshot_with_greeks(self, tmp_db):
        from data.chain_store import store_snapshot_with_greeks, _get_conn
        from scanner.providers.base import ChainSnapshot, OptionContract

        chain = ChainSnapshot(
            ticker="SPY",
            spot=543.50,
            fetched_at=datetime(2024, 6, 28),
            contracts=[
                OptionContract(
                    ticker="SPY", strike=540.0, expiry="2024-07-05",
                    option_type="put", bid=3.0, ask=3.2, mid=3.1,
                    last=3.1, volume=100, open_interest=500,
                    implied_volatility=0.15,
                ),
            ],
            expiries=["2024-07-05"],
        )
        greeks_map = {
            (540.0, "2024-07-05", "put"): {
                "delta": -0.30, "gamma": 0.02, "theta": -0.15,
                "vega": 0.40, "rho": -0.05,
            }
        }

        snap_id = store_snapshot_with_greeks(chain, greeks_map, label="thetadata")
        assert snap_id > 0

        conn = _get_conn()
        row = conn.execute(
            "SELECT delta, gamma, theta, vega, rho FROM chain_contracts WHERE snapshot_id = ?",
            (snap_id,),
        ).fetchone()
        conn.close()

        assert row["delta"] == -0.30
        assert row["gamma"] == 0.02
        assert row["theta"] == -0.15
        assert row["vega"] == 0.40
        assert row["rho"] == -0.05

    def test_existing_store_snapshot_unaffected(self, tmp_db):
        from data.chain_store import store_snapshot, _get_conn
        from scanner.providers.base import ChainSnapshot, OptionContract

        chain = ChainSnapshot(
            ticker="SPY",
            spot=543.50,
            fetched_at=datetime(2024, 6, 28),
            contracts=[
                OptionContract(
                    ticker="SPY", strike=540.0, expiry="2024-07-05",
                    option_type="put", bid=3.0, ask=3.2, mid=3.1,
                    last=3.1, volume=100, open_interest=500,
                    implied_volatility=0.15,
                ),
            ],
            expiries=["2024-07-05"],
        )

        snap_id = store_snapshot(chain, label="eod")

        conn = _get_conn()
        row = conn.execute(
            "SELECT delta, gamma, theta, vega, rho FROM chain_contracts WHERE snapshot_id = ?",
            (snap_id,),
        ).fetchone()
        conn.close()

        assert row["delta"] is None
        assert row["gamma"] is None

    def test_greeks_map_key_mismatch_gives_null(self, tmp_db):
        from data.chain_store import store_snapshot_with_greeks, _get_conn
        from scanner.providers.base import ChainSnapshot, OptionContract

        chain = ChainSnapshot(
            ticker="SPY", spot=543.50,
            fetched_at=datetime(2024, 6, 28),
            contracts=[
                OptionContract(
                    ticker="SPY", strike=540.0, expiry="2024-07-05",
                    option_type="put", bid=3.0, ask=3.2, mid=3.1,
                    last=3.1, volume=100, open_interest=500,
                    implied_volatility=0.15,
                ),
            ],
            expiries=["2024-07-05"],
        )
        greeks_map = {
            (999.0, "2099-01-01", "call"): {"delta": 0.99}
        }

        snap_id = store_snapshot_with_greeks(chain, greeks_map, label="thetadata")
        conn = _get_conn()
        row = conn.execute(
            "SELECT delta FROM chain_contracts WHERE snapshot_id = ?",
            (snap_id,),
        ).fetchone()
        conn.close()
        assert row["delta"] is None


# ── Backfill Pipeline Tests ──────────────────────────────────────────────────


class TestThetaDataBackfill:
    def test_backfill_date_builds_snapshot(self):
        from data.thetadata_backfill import backfill_date

        mock_client = MagicMock()
        mock_client.get_options_greeks_eod.return_value = [
            {
                "strike": 540.0, "expiry": "2024-07-05", "option_type": "put",
                "bid": 3.0, "ask": 3.2, "mid": 3.1, "last": 3.1,
                "volume": 100, "open_interest": 500,
                "implied_volatility": 0.15,
                "delta": -0.30, "gamma": 0.02, "theta": -0.15,
                "vega": 0.40, "rho": -0.05,
                "underlying_price": 543.50,
            },
        ]

        with patch("data.thetadata_backfill.store_snapshot_with_greeks") as mock_store, \
             patch("data.thetadata_backfill.store_iv_snapshot"):
            mock_store.return_value = 1
            result = backfill_date(mock_client, "SPY", "2024-06-28", max_dte=14)

        assert result["stored"] is True
        assert result["contracts"] == 1
        assert result["greeks_stored"] == 1
        assert result["spot"] == 543.50

        mock_store.assert_called_once()
        call_args = mock_store.call_args
        chain = call_args[0][0]
        greeks_map = call_args[0][1]
        assert chain.ticker == "SPY"
        assert len(chain.contracts) == 1
        assert (540.0, "2024-07-05", "put") in greeks_map

    def test_backfill_date_no_data(self):
        from data.thetadata_backfill import backfill_date

        mock_client = MagicMock()
        mock_client.get_options_greeks_eod.return_value = []

        result = backfill_date(mock_client, "SPY", "2024-06-28")
        assert result["stored"] is False
        assert "No option data" in result["error"]

    def test_backfill_date_intraday_raises(self):
        from data.thetadata_backfill import backfill_date
        mock_client = MagicMock()
        with pytest.raises(NotImplementedError):
            backfill_date(mock_client, "SPY", "2024-06-28", granularity="5min")

    def test_backfill_range_with_progress(self, tmp_path):
        from data.thetadata_backfill import backfill_range

        progress_file = str(tmp_path / "progress.json")
        with open(progress_file, "w") as f:
            json.dump({"completed": ["SPY:2024-06-28"]}, f)

        mock_client_cls = MagicMock()
        mock_client_cls.return_value.health_check.return_value = True

        with patch("data.thetadata_backfill.ThetaDataClient", mock_client_cls), \
             patch("data.thetadata_backfill.backfill_date") as mock_bd:
            mock_bd.return_value = {"contracts": 10, "greeks_stored": 10, "error": None}
            result = backfill_range(
                ["SPY"], "2024-06-28", "2024-06-28",
                progress_file=progress_file,
            )

        assert result["dates_skipped"] == 1
        mock_bd.assert_not_called()
