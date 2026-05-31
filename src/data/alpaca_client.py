"""
Alpaca historical options data client.

Fetches daily option bars and underlying prices via Alpaca's REST API.
Handles pagination, rate limiting, and OCC symbol construction.

API docs: https://docs.alpaca.markets/docs/historical-option-data
Data available since Feb 2024.

Options Analytics Team — 2026-05
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.alpaca.markets"
BARS_URL = f"{BASE_URL}/v1beta1/options/bars"
QUOTES_URL = f"{BASE_URL}/v1beta1/options/quotes"
STOCK_BARS_URL = f"{BASE_URL}/v2/stocks/bars"

MAX_SYMBOLS_PER_REQUEST = 100
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 1.0


class AlpacaOptionsClient:
    """REST client for Alpaca historical options data."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: str = "indicative",
    ):
        self.api_key = api_key or os.getenv("APCA_API_KEY_ID", "")
        self.secret_key = secret_key or os.getenv("APCA_API_SECRET_KEY", "")
        self.feed = feed
        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        })

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "Alpaca API keys required. Set APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY in .env"
            )

    def _request(self, url: str, params: dict) -> dict:
        """Make an authenticated GET request with retry and rate limit handling."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.get(url, params=params, timeout=30)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning("Rate limited, sleeping %ds", retry_after)
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                # 400/422 = bad/empty request; 403/404 = endpoint not entitled
                # on this plan (e.g. historical option quotes need an OPRA
                # subscription — see FINDINGS.md F-007). Treat all as "no data"
                # rather than raising, so callers degrade gracefully.
                if resp.status_code in (400, 403, 404, 422):
                    logger.debug("No data (HTTP %d): %s", resp.status_code, e)
                    return {}
                logger.error("HTTP %d: %s", resp.status_code, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.exceptions.RequestException as e:
                logger.error("Request failed: %s", e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

        return {}

    def _paginate(self, url: str, params: dict, result_key: str) -> dict:
        """Fetch all pages and merge results."""
        all_results = {}
        page = 0

        while True:
            data = self._request(url, params)
            if not data:
                break

            results = data.get(result_key, {})
            if isinstance(results, dict):
                all_results.update(results)
            elif isinstance(results, list):
                all_results.update({item.get("S", str(page)): item for item in results})

            next_token = data.get("next_page_token")
            if not next_token:
                break

            params["page_token"] = next_token
            page += 1
            time.sleep(RATE_LIMIT_DELAY)

        return all_results

    def get_spot_price(self, underlying: str, date: str) -> Optional[float]:
        """Fetch underlying close price for a given date."""
        params = {
            "symbols": underlying,
            "timeframe": "1Day",
            "start": date,
            "end": date,
            "limit": 1,
        }

        data = self._request(STOCK_BARS_URL, params)
        bars = data.get("bars", {})

        ticker_bars = bars.get(underlying, [])
        if not ticker_bars:
            logger.warning("No spot data for %s on %s", underlying, date)
            return None

        bar = ticker_bars[0] if isinstance(ticker_bars, list) else ticker_bars
        return float(bar.get("c", 0))

    def get_daily_bars(
        self,
        symbols: List[str],
        date: str,
    ) -> Dict[str, dict]:
        """Fetch 1Day bars for OCC option symbols on a specific date.

        Args:
            symbols: List of OCC symbols (e.g., ["SPY250509C00560000"]).
            date: Date string "YYYY-MM-DD".

        Returns:
            Dict mapping OCC symbol to bar data:
            {symbol: {"open": float, "high": float, "low": float,
                      "close": float, "volume": int, "trade_count": int}}
        """
        all_bars = {}

        for i in range(0, len(symbols), MAX_SYMBOLS_PER_REQUEST):
            batch = symbols[i:i + MAX_SYMBOLS_PER_REQUEST]
            params = {
                "symbols": ",".join(batch),
                "timeframe": "1Day",
                "start": date,
                "end": date,
                "limit": 10000,
            }

            bars_data = self._paginate(BARS_URL, params, "bars")

            for sym, bar_list in bars_data.items():
                if isinstance(bar_list, list) and bar_list:
                    bar = bar_list[0]
                elif isinstance(bar_list, dict):
                    bar = bar_list
                else:
                    continue

                all_bars[sym] = {
                    "open": float(bar.get("o", 0)),
                    "high": float(bar.get("h", 0)),
                    "low": float(bar.get("l", 0)),
                    "close": float(bar.get("c", 0)),
                    "volume": int(bar.get("v", 0)),
                    "trade_count": int(bar.get("n", 0)),
                }

            if i + MAX_SYMBOLS_PER_REQUEST < len(symbols):
                time.sleep(RATE_LIMIT_DELAY)

        return all_bars

    def get_option_quotes(
        self,
        symbols: List[str],
        date: str,
        window_start: str = "13:30:00",
        window_end: str = "20:00:00",
    ) -> Dict[str, dict]:
        """Fetch end-of-day NBBO quotes for OCC option symbols on a date.

        This is the data source that fixes F-007 (sparse intra-hold marks):
        unlike bars/trades — which exist only on days a contract actually traded
        — quotes are continuously posted during market hours, so a position can
        be marked on the in-between days too, giving a true mark-to-market
        equity curve (and an honest drawdown).

        Returns ``{occ: {"bid", "ask", "mid", "ts"}}`` using the LATEST quote
        within [window_start, window_end] UTC on ``date`` (``sort=desc`` →
        first row per symbol is the most recent). Symbols with no usable quote
        are simply absent.

        IMPORTANT — entitlement: historical option quotes require an OPRA data
        subscription. On plans without it Alpaca returns HTTP 404, which
        ``_request`` maps to an empty result, so this method yields ``{}`` (no
        marks) rather than erroring. Verified 2026-05-30: this account is NOT
        entitled (bars/trades 200, quotes 404). See FINDINGS.md F-007.

        Args:
            symbols: OCC symbols (e.g. ["SPY260511P00640000"]).
            date: "YYYY-MM-DD".
            window_start/window_end: UTC time-of-day bounds for the EOD quote.

        Returns:
            Dict mapping OCC symbol to {bid, ask, mid, ts}.
        """
        result: Dict[str, dict] = {}
        start = f"{date}T{window_start}Z"
        end = f"{date}T{window_end}Z"

        for i in range(0, len(symbols), MAX_SYMBOLS_PER_REQUEST):
            batch = symbols[i:i + MAX_SYMBOLS_PER_REQUEST]
            params = {
                "symbols": ",".join(batch),
                "start": start,
                "end": end,
                "limit": 1000,
                "sort": "desc",  # newest first → first row per symbol is EOD
            }

            data = self._request(QUOTES_URL, params)
            quotes = data.get("quotes", {}) if data else {}

            for sym, q_list in quotes.items():
                if sym in result:
                    continue
                if isinstance(q_list, list):
                    q = q_list[0] if q_list else None
                elif isinstance(q_list, dict):
                    q = q_list
                else:
                    q = None
                if not q:
                    continue

                bid = float(q.get("bp", 0) or 0)   # bid price
                ask = float(q.get("ap", 0) or 0)   # ask price
                if bid <= 0 and ask <= 0:
                    continue
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                else:
                    mid = bid or ask

                result[sym] = {
                    "bid": round(bid, 4),
                    "ask": round(ask, 4),
                    "mid": round(mid, 4),
                    "ts": q.get("t", ""),
                }

            if i + MAX_SYMBOLS_PER_REQUEST < len(symbols):
                time.sleep(RATE_LIMIT_DELAY)

        return result

    def discover_contracts(
        self,
        underlying: str,
        date: str,
        spot: float,
        max_dte: int = 60,
        strike_range_pct: float = 0.15,
        strike_step: float = 1.0,
    ) -> List[str]:
        """Generate OCC symbols for contracts that likely existed on a date.

        Builds symbols for weekly/monthly expiries within max_dte,
        for strikes within strike_range_pct of spot.

        Args:
            underlying: Root symbol (e.g., "SPY").
            date: Date string "YYYY-MM-DD".
            spot: Underlying close price on that date.
            max_dte: Maximum days to expiration.
            strike_range_pct: Fraction of spot for strike range (0.15 = 15%).
            strike_step: Strike increment ($1 for ETFs, $5 for indices).

        Returns:
            List of OCC-formatted symbol strings.
        """
        base_dt = datetime.strptime(date, "%Y-%m-%d")

        if underlying in ("SPY", "QQQ", "IWM"):
            strike_step = 1.0
        elif underlying in ("^SPX", "^NDX"):
            strike_step = 5.0
            underlying = underlying.lstrip("^")
        else:
            strike_step = strike_step

        expiries = self._generate_expiries(base_dt, max_dte, underlying)

        min_strike = int(spot * (1 - strike_range_pct))
        max_strike = int(spot * (1 + strike_range_pct))

        strikes = []
        s = float(min_strike)
        while s <= max_strike:
            strikes.append(s)
            s += strike_step

        symbols = []
        for expiry in expiries:
            for strike in strikes:
                for opt_type in ("C", "P"):
                    occ = self._build_occ_symbol(underlying, expiry, opt_type, strike)
                    symbols.append(occ)

        logger.info(
            "Discovered %d candidate symbols for %s on %s "
            "(spot=%.2f, %d expiries, %d strikes)",
            len(symbols), underlying, date, spot,
            len(expiries), len(strikes),
        )
        return symbols

    def _generate_expiries(
        self,
        base_dt: datetime,
        max_dte: int,
        underlying: str,
    ) -> List[datetime]:
        """Generate likely expiry dates (Fridays) within max_dte of base_dt.

        SPY/QQQ/IWM have Mon/Wed/Fri weeklies.
        Other underlyings: Fridays only.
        """
        expiries = []
        has_daily_expiries = underlying in ("SPY", "QQQ", "IWM", "SPX")

        for offset in range(0, max_dte + 1):
            dt = base_dt + timedelta(days=offset)
            weekday = dt.weekday()

            if has_daily_expiries:
                if weekday in (0, 2, 4):  # Mon, Wed, Fri
                    expiries.append(dt)
            else:
                if weekday == 4:  # Friday only
                    expiries.append(dt)

        return expiries

    @staticmethod
    def _build_occ_symbol(
        underlying: str,
        expiry: datetime,
        option_type: str,
        strike: float,
    ) -> str:
        """Build OCC option symbol.

        Format: ROOT + YYMMDD + C/P + strike*1000 (8 digits, zero-padded)
        Example: SPY250509C00560000
        """
        root = underlying.ljust(6)[:6].rstrip()
        date_str = expiry.strftime("%y%m%d")
        strike_int = int(strike * 1000)
        return f"{root}{date_str}{option_type}{strike_int:08d}"

    @staticmethod
    def parse_occ_symbol(occ: str) -> dict:
        """Parse OCC symbol into components.

        Returns:
            {"underlying": str, "expiry": str, "option_type": str, "strike": float}
        """
        cp_idx = None
        for i in range(len(occ) - 9, 0, -1):
            if occ[i] in ("C", "P"):
                cp_idx = i
                break

        if cp_idx is None:
            raise ValueError(f"Cannot parse OCC symbol: {occ}")

        date_str = occ[cp_idx - 6:cp_idx]
        underlying = occ[:cp_idx - 6].rstrip()
        option_type = "call" if occ[cp_idx] == "C" else "put"
        strike = int(occ[cp_idx + 1:]) / 1000.0

        expiry_dt = datetime.strptime(date_str, "%y%m%d")

        return {
            "underlying": underlying,
            "expiry": expiry_dt.strftime("%Y-%m-%d"),
            "option_type": option_type,
            "strike": strike,
        }
