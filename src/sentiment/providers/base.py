"""
Abstract news provider interface.

Mirrors the ChainProvider pattern from scanner/providers/base.py.
All concrete providers implement this ABC.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from ..models import Headline


class NewsProvider(ABC):
    """Abstract interface for financial news providers."""

    @abstractmethod
    def fetch_headlines(
        self,
        ticker: str,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        """Fetch headlines for a ticker.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g. 'SPY') or 'MACRO' for index/macro news.
        since : datetime, optional
            Only return headlines published after this time.
            If None, fetch the most recent headlines.
        limit : int
            Max number of headlines to return.

        Returns
        -------
        List[Headline]
            Sorted by published_at descending (newest first).
        """
        ...

    @abstractmethod
    def fetch_macro_headlines(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Headline]:
        """Fetch broad market / macro headlines (Fed, CPI, etc).

        Parameters
        ----------
        since : datetime, optional
            Only return headlines after this time.
        limit : int
            Max headlines to return.

        Returns
        -------
        List[Headline]
            Macro headlines with ticker='MACRO'.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short identifier for this provider (e.g. 'newsapi', 'benzinga')."""
        ...
