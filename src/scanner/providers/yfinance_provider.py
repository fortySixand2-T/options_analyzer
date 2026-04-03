"""
YFinance-backed implementation of ChainProvider.

Fetches spot prices, option chains, and historical data via the yfinance library.
All yfinance calls are wrapped in try/except so a single API failure never
crashes the scanner.

Options Analytics Team — 2026-04-02
"""

import logging
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from .base import ChainProvider, ChainSnapshot, HistoryData, OptionContract

logger = logging.getLogger(__name__)


class YFinanceProvider(ChainProvider):
    """Options data provider backed by yfinance."""

    # ------------------------------------------------------------------
    # Spot
    # ------------------------------------------------------------------

    def get_spot(self, ticker: str) -> float:
        """Current spot price."""
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.get('lastPrice')
            if price and price > 0:
                return float(price)
            # Fallback: last close from 1-day history
            hist = t.history(period='1d')
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
        except Exception as e:
            logger.warning("Failed to fetch spot for %s: %s", ticker, e)
        return float('nan')

    # ------------------------------------------------------------------
    # Option chain
    # ------------------------------------------------------------------

    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        """Full option chain filtered by DTE range."""
        now = datetime.now()
        spot = self.get_spot(ticker)
        contracts: list[OptionContract] = []
        valid_expiries: list[str] = []

        try:
            t = yf.Ticker(ticker)
            all_expiries = t.options  # tuple of 'YYYY-MM-DD' strings
        except Exception as e:
            logger.warning("Failed to fetch expiries for %s: %s", ticker, e)
            return ChainSnapshot(
                ticker=ticker, spot=spot, fetched_at=now,
                contracts=[], expiries=[],
            )

        for exp_str in all_expiries:
            exp_dt = datetime.strptime(exp_str, '%Y-%m-%d')
            dte = (exp_dt - now).days
            if dte < min_dte or dte > max_dte:
                continue
            valid_expiries.append(exp_str)

            try:
                chain = t.option_chain(exp_str)
            except Exception as e:
                logger.warning("Failed to fetch chain for %s %s: %s",
                               ticker, exp_str, e)
                continue

            for opt_type, df in [('call', chain.calls), ('put', chain.puts)]:
                for _, row in df.iterrows():
                    bid = float(row.get('bid', 0))
                    ask = float(row.get('ask', 0))
                    if bid <= 0 or ask <= 0:
                        continue
                    mid = (bid + ask) / 2.0
                    iv = float(row.get('impliedVolatility', float('nan')))
                    contracts.append(OptionContract(
                        ticker=ticker,
                        strike=float(row['strike']),
                        expiry=exp_str,
                        option_type=opt_type,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        last=float(row.get('lastPrice', 0)),
                        volume=int(row.get('volume', 0) or 0),
                        open_interest=int(row.get('openInterest', 0) or 0),
                        implied_volatility=iv,
                    ))

        return ChainSnapshot(
            ticker=ticker,
            spot=spot,
            fetched_at=now,
            contracts=contracts,
            expiries=valid_expiries,
        )

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    def get_history(self, ticker: str, days: int = 365) -> HistoryData:
        """Historical daily closes and derived vol metrics."""
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=f'{days}d')
            if hist.empty:
                raise ValueError(f"No history returned for {ticker}")

            closes = hist['Close']
            returns = closes.pct_change().dropna().values

            rv_30 = float(np.std(returns[-30:]) * np.sqrt(252)) if len(returns) >= 30 else float('nan')
            rv_60 = float(np.std(returns[-60:]) * np.sqrt(252)) if len(returns) >= 60 else float('nan')

            return HistoryData(
                ticker=ticker,
                closes=closes,
                returns=returns,
                realized_vol_30d=rv_30,
                realized_vol_60d=rv_60,
            )
        except Exception as e:
            logger.warning("Failed to fetch history for %s: %s", ticker, e)
            return HistoryData(
                ticker=ticker,
                closes=pd.Series(dtype=float),
                returns=np.array([]),
                realized_vol_30d=float('nan'),
                realized_vol_60d=float('nan'),
            )

    # ------------------------------------------------------------------
    # Risk-free rate
    # ------------------------------------------------------------------

    def get_risk_free_rate(self) -> float:
        """13-week T-bill yield as risk-free rate proxy."""
        try:
            t = yf.Ticker('^IRX')
            rate = t.fast_info.get('lastPrice')
            if rate and rate > 0:
                return float(rate) / 100.0
        except Exception as e:
            logger.warning("Failed to fetch risk-free rate: %s", e)
        return 0.045  # fallback
