"""
SQLite cache for backtest results.

Stores serialized BacktestResult objects keyed by
(strategy, symbol, date_range, entry_params) to avoid
re-running expensive backtests.

Options Analytics Team — 2026-04
"""

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

from .models import BacktestRequest, BacktestResult

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "backtest_cache.db"
)


def _get_db_path() -> str:
    path = os.getenv("BACKTEST_CACHE_DB", _DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _cache_key(request: BacktestRequest) -> str:
    """Deterministic cache key from request parameters."""
    key_data = {
        "strategy": request.strategy,
        "symbol": request.symbol,
        "start": request.start_date.isoformat(),
        "end": request.end_date.isoformat(),
        "delta": request.entry_delta,
        "dte_min": request.entry_dte_min,
        "dte_max": request.entry_dte_max,
        "exit_profit": request.exit_profit_pct,
        "exit_loss": request.exit_loss_pct,
        "exit_dte": request.exit_dte,
        "exit_rule": request.exit_rule,
        "regime_filter": request.regime_filter,
        "bias_filter": request.bias_filter,
        "dealer_filter": request.dealer_filter,
        "edge_threshold": request.edge_threshold,
        "slippage_pct": request.slippage_pct,
    }
    raw = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_cache (
            cache_key TEXT PRIMARY KEY,
            strategy TEXT,
            symbol TEXT,
            created_at TEXT,
            result_json TEXT
        )
    """)
    conn.commit()


def get_cached(request: BacktestRequest) -> Optional[BacktestResult]:
    """Look up cached backtest result. Returns None if not found."""
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        _init_db(conn)

        key = _cache_key(request)
        row = conn.execute(
            "SELECT result_json FROM backtest_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        conn.close()

        if row:
            result = BacktestResult.model_validate_json(row[0])
            result.cached = True
            logger.info("Cache hit for %s/%s", request.strategy, request.symbol)
            return result
        return None
    except Exception as e:
        logger.warning("Cache lookup failed: %s", e)
        return None


def store_cached(request: BacktestRequest, result: BacktestResult):
    """Store backtest result in cache."""
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        _init_db(conn)

        key = _cache_key(request)
        conn.execute(
            """INSERT OR REPLACE INTO backtest_cache
               (cache_key, strategy, symbol, created_at, result_json)
               VALUES (?, ?, ?, ?, ?)""",
            (key, request.strategy, request.symbol,
             datetime.now().isoformat(), result.model_dump_json()),
        )
        conn.commit()
        conn.close()
        logger.info("Cached result for %s/%s", request.strategy, request.symbol)
    except Exception as e:
        logger.warning("Cache store failed: %s", e)
