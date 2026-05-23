"""
ThetaData REST client for Theta Terminal (localhost proxy).

Theta Terminal is a Java application that runs on the host machine and
exposes a REST API on port 25503. All ThetaData queries go through it.

Setup: https://docs.thetadata.us/Articles/Getting-Started/Getting-Started.html
Requires Java 21+ on the host.

When running from Docker, the container reaches the host via
host.docker.internal:25503 (configurable via THETADATA_URL env var).
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


class ThetaDataClient:
    """REST client for ThetaData Theta Terminal."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        max_retries: int = MAX_RETRIES,
    ):
        self.base_url = (
            base_url
            or os.getenv("THETADATA_URL", "http://host.docker.internal:25503")
        ).rstrip("/")
        self.max_retries = max_retries
        self._session = requests.Session()

    def health_check(self) -> bool:
        """Verify Theta Terminal is running and reachable."""
        try:
            resp = self._session.get(
                f"{self.base_url}/v3/stock/history/eod",
                params={"symbol": "SPY", "start_date": "20240101", "end_date": "20240102"},
                timeout=10,
            )
            return resp.status_code == 200
        except requests.exceptions.ConnectionError:
            return False

    def get_spot_eod(self, symbol: str, date: str) -> Optional[float]:
        """Get EOD close price for an underlying on a specific date.

        Args:
            symbol: e.g. "SPY"
            date: "YYYY-MM-DD" format

        Returns:
            Close price as float, or None if not available.
        """
        date_int = _date_to_int(date)
        data = self._request("/v3/stock/history/eod", {
            "symbol": symbol,
            "start_date": str(date_int),
            "end_date": str(date_int),
        })
        if not data:
            return None

        rows = _parse_response(data)
        if rows:
            close = rows[0].get("close")
            if close and close > 0:
                return float(close)
        return None

    def get_options_greeks_eod(
        self,
        symbol: str,
        date: str,
        max_dte: int = 14,
    ) -> List[dict]:
        """Get EOD option chain with greeks for all strikes/expiries.

        One call returns every contract within max_dte for the given date.

        Args:
            symbol: Underlying (e.g. "SPY")
            date: "YYYY-MM-DD"
            max_dte: Maximum days to expiry filter

        Returns:
            List of normalized dicts with fields:
                strike (float $), expiry (YYYY-MM-DD str),
                option_type (call/put), bid, ask, mid, last,
                volume, open_interest, implied_volatility,
                delta, gamma, theta, vega, rho, underlying_price
        """
        date_int = _date_to_int(date)
        data = self._request("/v3/option/history/greeks/eod", {
            "symbol": symbol,
            "start_date": str(date_int),
            "end_date": str(date_int),
            "expiration": "*",
            "max_dte": str(max_dte),
            "right": "both",
            "format": "json",
        })
        if not data:
            return []

        rows = _parse_response(data)
        contracts = []
        for row in rows:
            try:
                contract = _normalize_contract(row)
                if contract:
                    contracts.append(contract)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug("Skipping malformed contract row: %s", e)
                continue

        return contracts

    def get_options_greeks_intraday(
        self,
        symbol: str,
        date: str,
        interval: str = "5min",
        max_dte: int = 3,
    ) -> List[dict]:
        """Placeholder for future intraday backfill."""
        raise NotImplementedError("Intraday backfill not yet supported")

    def _request(self, path: str, params: dict) -> Optional[dict]:
        """Make a GET request to Theta Terminal with retry."""
        url = f"{self.base_url}{path}"

        for attempt in range(self.max_retries):
            try:
                resp = self._session.get(url, params=params, timeout=60)

                if resp.status_code == 429:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Rate limited, waiting %ds", wait)
                    time.sleep(wait)
                    continue

                if resp.status_code == 404:
                    logger.debug("No data for %s %s", path, params)
                    return None

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.ConnectionError:
                if attempt == 0:
                    logger.error(
                        "Cannot connect to Theta Terminal at %s. "
                        "Is it running? Start it with: java -jar ThetaTerminal.jar",
                        self.base_url,
                    )
                if attempt < self.max_retries - 1:
                    time.sleep(RETRY_BACKOFF_BASE ** attempt)
                    continue
                return None

            except requests.exceptions.RequestException as e:
                logger.error("Request failed: %s", e)
                if attempt < self.max_retries - 1:
                    time.sleep(RETRY_BACKOFF_BASE ** attempt)
                    continue
                return None

        return None


def _date_to_int(date_str: str) -> int:
    """Convert 'YYYY-MM-DD' to YYYYMMDD integer."""
    return int(date_str.replace("-", ""))


def _int_to_date(date_int: int) -> str:
    """Convert YYYYMMDD integer to 'YYYY-MM-DD' string."""
    s = str(date_int)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _parse_strike(raw: int) -> float:
    """Convert ThetaData strike integer to dollar float.

    ThetaData v3 stores strikes in millidollars (1/1000 of a dollar).
    Example: 543000 = $543.00, 543500 = $543.50.

    If the actual API returns a different scale, adjust STRIKE_DIVISOR.
    Run --dry-run and check that strike prices look reasonable for the underlying.
    """
    return round(raw / 1_000, 2)


def _normalize_contract(row: dict) -> Optional[dict]:
    """Normalize a ThetaData EOD greeks row to our standard format."""
    strike_raw = row.get("strike")
    expiry_raw = row.get("expiration")
    right = row.get("right")

    if strike_raw is None or expiry_raw is None or right is None:
        return None

    strike = _parse_strike(int(strike_raw))
    expiry = _int_to_date(int(expiry_raw))
    option_type = "call" if str(right).upper() == "C" else "put"

    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    mid = row.get("mid_price", 0) or 0
    if mid <= 0 and bid > 0 and ask > 0:
        mid = (bid + ask) / 2

    return {
        "strike": strike,
        "expiry": expiry,
        "option_type": option_type,
        "bid": float(bid),
        "ask": float(ask),
        "mid": round(float(mid), 4),
        "last": float(row.get("close", 0) or 0),
        "volume": int(row.get("volume", 0) or 0),
        "open_interest": int(row.get("open_interest", 0) or 0),
        "implied_volatility": float(row.get("implied_volatility", 0) or 0),
        "delta": _safe_float(row.get("delta")),
        "gamma": _safe_float(row.get("gamma")),
        "theta": _safe_float(row.get("theta")),
        "vega": _safe_float(row.get("vega")),
        "rho": _safe_float(row.get("rho")),
        "underlying_price": float(row.get("underlying_price", 0) or 0),
    }


def _safe_float(val) -> Optional[float]:
    """Convert to float, returning None for missing/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def _parse_response(data: dict) -> List[dict]:
    """Parse ThetaData JSON response into list of row dicts.

    ThetaData v3 returns either:
    - {"header": {...}, "response": [{"col1": val, ...}, ...]}
    - or a list directly
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        response = data.get("response", [])
        if isinstance(response, list):
            return response
    return []
