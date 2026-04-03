"""
Caching decorator for any ChainProvider implementation.

Wraps an underlying provider with a TTL-based in-memory cache.
Thread-safe via threading.Lock.

Options Analytics Team — 2026-04-02
"""

import logging
import threading
import time

from .base import ChainProvider, ChainSnapshot, HistoryData

logger = logging.getLogger(__name__)


class CachedProvider(ChainProvider):
    """TTL-caching wrapper around any ChainProvider."""

    def __init__(self, provider: ChainProvider,
                 chain_ttl: int = 900,
                 history_ttl: int = 3600):
        self._provider = provider
        self._chain_ttl = chain_ttl
        self._history_ttl = history_ttl
        self._cache: dict = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_cached(self, key: tuple, ttl: int):
        with self._lock:
            if key in self._cache:
                result, ts = self._cache[key]
                if time.time() - ts < ttl:
                    logger.debug("Cache hit: %s", key)
                    return result
        return None

    def _put_cache(self, key: tuple, result):
        with self._lock:
            self._cache[key] = (result, time.time())

    # ------------------------------------------------------------------
    # ChainProvider interface
    # ------------------------------------------------------------------

    def get_spot(self, ticker: str) -> float:
        key = ('spot', ticker)
        cached = self._get_cached(key, self._chain_ttl)
        if cached is not None:
            return cached
        result = self._provider.get_spot(ticker)
        self._put_cache(key, result)
        return result

    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        key = ('chain', ticker, min_dte, max_dte)
        cached = self._get_cached(key, self._chain_ttl)
        if cached is not None:
            return cached
        result = self._provider.get_chain(ticker, min_dte, max_dte)
        self._put_cache(key, result)
        return result

    def get_history(self, ticker: str, days: int = 365) -> HistoryData:
        key = ('history', ticker, days)
        cached = self._get_cached(key, self._history_ttl)
        if cached is not None:
            return cached
        result = self._provider.get_history(ticker, days)
        self._put_cache(key, result)
        return result

    def get_risk_free_rate(self) -> float:
        key = ('rfr',)
        cached = self._get_cached(key, self._history_ttl)
        if cached is not None:
            return cached
        result = self._provider.get_risk_free_rate()
        self._put_cache(key, result)
        return result
