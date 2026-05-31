"""
Unit tests for AlpacaOptionsClient.get_option_quotes (F-007).

These mock the HTTP layer, so they validate parsing / EOD-selection / graceful
degradation independently of live entitlement. (Historical option quotes need
an OPRA subscription this account lacks — verified 2026-05-30: bars/trades 200,
quotes 404 — so the live path yields no data; see FINDINGS.md F-007.)
"""

import os
import sys
from unittest import mock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data.alpaca_client import AlpacaOptionsClient, QUOTES_URL


@pytest.fixture
def client():
    # Explicit keys so __init__ doesn't require env vars.
    return AlpacaOptionsClient(api_key="test", secret_key="test")


class TestGetOptionQuotes:
    def test_parses_latest_quote_per_symbol(self, client):
        # sort=desc → first row per symbol is the most recent (EOD) quote.
        payload = {
            "quotes": {
                "SPY260511P00640000": [
                    {"t": "2026-05-08T19:59:00Z", "bp": 1.20, "ap": 1.30},
                    {"t": "2026-05-08T15:00:00Z", "bp": 0.90, "ap": 1.00},
                ]
            }
        }
        with mock.patch.object(client, "_request", return_value=payload) as req:
            out = client.get_option_quotes(["SPY260511P00640000"], "2026-05-08")

        # Hit the quotes endpoint with desc sort.
        called_url = req.call_args[0][0]
        called_params = req.call_args[0][1]
        assert called_url == QUOTES_URL
        assert called_params["sort"] == "desc"

        q = out["SPY260511P00640000"]
        assert q["bid"] == 1.20 and q["ask"] == 1.30
        assert q["mid"] == 1.25            # (1.20 + 1.30) / 2
        assert q["ts"] == "2026-05-08T19:59:00Z"

    def test_skips_zero_and_one_sided_quotes(self, client):
        payload = {
            "quotes": {
                "A": [{"t": "t", "bp": 0, "ap": 0}],        # no market → dropped
                "B": [{"t": "t", "bp": 0, "ap": 2.0}],      # one-sided → mid = ask
            }
        }
        with mock.patch.object(client, "_request", return_value=payload):
            out = client.get_option_quotes(["A", "B"], "2026-05-08")

        assert "A" not in out
        assert out["B"]["mid"] == 2.0

    def test_not_entitled_404_yields_empty(self, client):
        # Simulate Alpaca's 404 for un-entitled historical quotes: _request must
        # map it to {} (no raise), so get_option_quotes returns {}.
        resp = mock.Mock()
        resp.status_code = 404
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
        with mock.patch.object(client._session, "get", return_value=resp):
            out = client.get_option_quotes(["SPY260511P00640000"], "2026-05-08")
        assert out == {}
