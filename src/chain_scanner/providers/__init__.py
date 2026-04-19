"""
Options chain data providers.

Provides a pluggable abstraction for fetching spot prices, option chains,
and historical data. Currently supports yfinance; paid providers (Polygon,
Tradier) can be added by implementing ChainProvider.

Options Analytics Team — 2026-04-02
"""

from .base import ChainProvider, ChainSnapshot, HistoryData, OptionContract
from .cached_provider import CachedProvider
from .yfinance_provider import YFinanceProvider

# TODO: from .polygon_provider import PolygonProvider  # planned, not yet implemented


def create_provider(name: str = 'yfinance',
                    cache: bool = True,
                    chain_ttl: int = 900,
                    history_ttl: int = 3600,
                    delay: float = 1.0) -> ChainProvider:
    """Factory: create a data provider by name, optionally wrapped in cache.

    Parameters
    ----------
    name : str
        Provider name. Currently only 'yfinance' is supported.
    cache : bool
        Wrap in CachedProvider if True (default).
    chain_ttl : int
        Cache TTL in seconds for spot/chain data (default 900 = 15 min).
    history_ttl : int
        Cache TTL in seconds for history/risk-free rate (default 3600 = 1 hr).
    delay : float
        Seconds between yfinance API calls to avoid rate limits (default 1.0).

    Returns
    -------
    ChainProvider
    """
    if name == 'yfinance':
        provider = YFinanceProvider(delay=delay)
    else:
        raise ValueError(f"Unknown provider: {name!r}. Supported: 'yfinance'")

    if cache:
        provider = CachedProvider(provider, chain_ttl=chain_ttl,
                                  history_ttl=history_ttl)
    return provider


__all__ = [
    'ChainProvider', 'ChainSnapshot', 'HistoryData', 'OptionContract',
    'YFinanceProvider', 'CachedProvider', 'create_provider',
]
