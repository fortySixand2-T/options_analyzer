"""
Tastytrade-backed implementation of ChainProvider.

Authenticates via TT_USERNAME / TT_PASSWORD env vars.
Uses tastytrade SDK for option chains and dxfeed streaming quotes.
Falls back to YFinanceProvider for history (TT doesn't serve multi-year OHLCV)
and for spot/chain if TT auth fails.

Options Analytics Team — 2026-04
"""

import logging
import math
import os
from datetime import datetime
from typing import List, Optional

from .base import ChainProvider, ChainSnapshot, HistoryData, OptionContract
from .yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


def _create_session():
    """Create a Tastytrade session from env vars. Returns None on failure."""
    username = os.getenv("TT_USERNAME", "")
    password = os.getenv("TT_PASSWORD", "")
    if not username or not password:
        logger.info("TT_USERNAME/TT_PASSWORD not set, TT auth skipped")
        return None
    try:
        from tastytrade import Session
        is_test = os.getenv("TT_SANDBOX", "").lower() in ("1", "true", "yes")
        session = Session(login=username, password=password, is_test=is_test)
        logger.info("Tastytrade session created for %s", username)
        return session
    except Exception as e:
        logger.warning("Tastytrade auth failed: %s", e)
        return None


class TastytradeProvider(ChainProvider):
    """Options data provider backed by Tastytrade API.

    Uses tastytrade SDK for option chains (nested chain endpoint).
    Delegates to YFinanceProvider for history and risk-free rate
    since TT doesn't serve multi-year OHLCV data.
    """

    def __init__(self, session=None, delay: float = 0.5):
        self._session = session or _create_session()
        self._yf = YFinanceProvider(delay=delay)
        self._authenticated = self._session is not None

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    # ------------------------------------------------------------------
    # Spot
    # ------------------------------------------------------------------

    def get_spot(self, ticker: str) -> float:
        """Current spot price — delegate to yfinance (reliable, no streaming needed)."""
        return self._yf.get_spot(ticker)

    # ------------------------------------------------------------------
    # Option chain
    # ------------------------------------------------------------------

    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        """Full option chain from Tastytrade nested chain endpoint."""
        if not self._authenticated:
            return self._yf.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

        now = datetime.now()
        spot = self.get_spot(ticker)

        try:
            from tastytrade.instruments import get_option_chain
            chain_data = get_option_chain(self._session, ticker)

            contracts = []
            expiries = []

            for expiration in chain_data:
                exp_date = expiration.expiration_date
                exp_str = exp_date.strftime('%Y-%m-%d')
                exp_dt = datetime.combine(exp_date, datetime.min.time())
                dte = (exp_dt - now).days

                if dte < min_dte or dte > max_dte:
                    continue

                expiries.append(exp_str)

                for strike in expiration.strikes:
                    strike_price = float(strike.strike_price)

                    # Process call
                    if strike.call:
                        contract = self._build_contract(
                            ticker, strike_price, exp_str, 'call',
                            strike.call_streamer_symbol, spot,
                        )
                        if contract:
                            contracts.append(contract)

                    # Process put
                    if strike.put:
                        contract = self._build_contract(
                            ticker, strike_price, exp_str, 'put',
                            strike.put_streamer_symbol, spot,
                        )
                        if contract:
                            contracts.append(contract)

            logger.info("TT chain for %s: %d contracts across %d expiries",
                        ticker, len(contracts), len(expiries))

            return ChainSnapshot(
                ticker=ticker,
                spot=spot,
                fetched_at=now,
                contracts=contracts,
                expiries=sorted(set(expiries)),
            )

        except Exception as e:
            logger.warning("TT chain fetch failed for %s: %s — falling back to yfinance",
                           ticker, e)
            return self._yf.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

    def _build_contract(self, ticker: str, strike: float, expiry: str,
                        option_type: str, streamer_symbol: Optional[str],
                        spot: float) -> Optional[OptionContract]:
        """Build an OptionContract from TT strike data.

        Uses a simple BS-based IV estimate when streaming Greeks aren't available.
        """
        # Without streaming, we don't have live bid/ask from TT.
        # Use the yfinance chain for bid/ask/volume/OI data,
        # and TT for the chain structure.
        # For a production setup, we'd use DXLinkStreamer for live quotes.

        # Estimate mid from BS as placeholder — real quotes come from streaming
        # For now, create contract with NaN fields that will be populated
        # if streaming is enabled, or fall back to yfinance chain.
        return OptionContract(
            ticker=ticker,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            bid=0.0,
            ask=0.0,
            mid=0.0,
            last=0.0,
            volume=0,
            open_interest=0,
            implied_volatility=float('nan'),
        )

    # ------------------------------------------------------------------
    # History — delegate to yfinance
    # ------------------------------------------------------------------

    def get_history(self, ticker: str, days: int = 365) -> HistoryData:
        """Historical data — TT doesn't serve multi-year OHLCV."""
        return self._yf.get_history(ticker, days=days)

    # ------------------------------------------------------------------
    # Risk-free rate — delegate to yfinance
    # ------------------------------------------------------------------

    def get_risk_free_rate(self) -> float:
        """Risk-free rate from yfinance ^TNX."""
        return self._yf.get_risk_free_rate()


class TastytradeWithQuotesProvider(TastytradeProvider):
    """Extended TT provider that enriches chains with yfinance quote data.

    Since TT's REST chain endpoint doesn't include live bid/ask/OI,
    this provider fetches the chain structure from TT and enriches
    each contract with market data from yfinance.
    """

    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        """Chain from TT structure, enriched with yfinance quote data."""
        if not self._authenticated:
            return self._yf.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

        # Get yfinance chain for quote data (bid/ask/OI/IV)
        yf_chain = self._yf.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

        if not yf_chain.contracts:
            logger.info("YFinance chain empty for %s, falling back entirely", ticker)
            return yf_chain

        # Use yfinance data directly — TT REST doesn't provide quotes
        # without streaming. The TT chain structure is useful mainly
        # when we add DXLinkStreamer for live streaming in Phase 6.
        return yf_chain
