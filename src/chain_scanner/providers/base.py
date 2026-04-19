"""
Base data structures and abstract provider interface for the options chain scanner.

Defines OptionContract, ChainSnapshot, HistoryData dataclasses and the
ChainProvider ABC that all data providers must implement.

Options Analytics Team — 2026-04-02
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class OptionContract:
    """Single option contract from the chain."""
    ticker: str
    strike: float
    expiry: str                    # YYYY-MM-DD
    option_type: str               # 'call' or 'put'
    bid: float
    ask: float
    mid: float                     # (bid + ask) / 2
    last: float
    volume: int
    open_interest: int
    implied_volatility: float      # from chain data (may be NaN)


@dataclass
class ChainSnapshot:
    """Full chain snapshot for one ticker."""
    ticker: str
    spot: float
    fetched_at: datetime
    contracts: List[OptionContract]
    expiries: List[str]            # available expiry dates


@dataclass
class HistoryData:
    """Historical price data for one ticker."""
    ticker: str
    closes: pd.Series              # DatetimeIndex -> float
    returns: np.ndarray            # daily simple returns
    realized_vol_30d: float        # annualized 30-day realized vol
    realized_vol_60d: float        # annualized 60-day realized vol


class ChainProvider(ABC):
    """Abstract interface for options data providers."""

    @abstractmethod
    def get_spot(self, ticker: str) -> float:
        """Current spot price."""
        ...

    @abstractmethod
    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        """Full option chain filtered by DTE range."""
        ...

    @abstractmethod
    def get_history(self, ticker: str,
                    days: int = 365) -> HistoryData:
        """Historical daily closes and derived vol metrics."""
        ...

    @abstractmethod
    def get_risk_free_rate(self) -> float:
        """Current risk-free rate (annualized)."""
        ...
