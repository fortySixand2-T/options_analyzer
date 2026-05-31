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


def _compute_logic_version() -> str:
    """Hash the backtester source so any logic change invalidates cached results.

    F-005: the cache previously keyed only on request params, so after a
    backtester code change identical params returned STALE pre-change results
    (this masked the F-004 path-stability fix for a turn). Folding a hash of the
    engine source into the key makes the cache self-invalidate on any edit to
    these modules — no manual version bumping.
    """
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for fname in ("chain_replay.py", "local_backtest.py", "analyzer.py"):
        try:
            with open(os.path.join(here, fname), "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest()[:12]


# Computed once at import; the Docker image bakes source at build time.
_LOGIC_VERSION = _compute_logic_version()


def _cache_key(request: BacktestRequest) -> str:
    """Deterministic cache key from ALL result-affecting request parameters.

    Every field on BacktestRequest that can change the backtest outcome MUST
    appear here. If a new result-affecting field is added to BacktestRequest
    but omitted here, two runs with different filter configs silently return
    the same cached result — the exact F-005/F-019 failure mode.

    The sentinel test `test_cache_key_covers_all_result_affecting_fields` in
    tests/test_signal_lib.py will fail if a field in the RESULT_AFFECTING_FIELDS
    allow-list is missing, ensuring this never regresses silently.

    Phase-3 additions (2026-05-31): vrp_filter, vrp_threshold, swing_bias_filter,
    option_style, min_score — all were result-affecting but absent from the key.
    """
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
        "min_score": request.min_score,            # Phase 3: was missing
        "regime_filter": request.regime_filter,
        "bias_filter": request.bias_filter,
        "signal_filter": request.signal_filter,    # F-019: gated vs unconditional differ
        "signal_gate": request.signal_gate,
        "dealer_filter": request.dealer_filter,
        "edge_threshold": request.edge_threshold,
        "slippage_pct": request.slippage_pct,
        "fill_mode": request.fill_mode,            # bid/ask vs mid fills produce different P&L
        "vrp_filter": request.vrp_filter,          # Phase 3: was missing (F-005-class latent bug)
        "vrp_threshold": request.vrp_threshold,    # Phase 3: companion to vrp_filter
        "swing_bias_filter": request.swing_bias_filter,  # Phase 3: was missing
        "option_style": request.option_style,      # Phase 3: european/american → different P&L
        "logic_version": _LOGIC_VERSION,           # invalidate cache when engine source changes (F-005)
    }
    raw = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# Allow-list of every result-affecting BacktestRequest field name. Used by the
# sentinel test to catch future omissions before they silently corrupt results.
# When you add a new result-affecting field to BacktestRequest, add it here too.
RESULT_AFFECTING_FIELDS = frozenset({
    "strategy", "symbol", "start_date", "end_date",
    "entry_delta", "entry_dte_min", "entry_dte_max",
    "exit_profit_pct", "exit_loss_pct", "exit_dte", "exit_rule",
    "min_score",
    "regime_filter", "bias_filter",
    "signal_filter", "signal_gate",
    "dealer_filter", "edge_threshold",
    "slippage_pct", "fill_mode",
    "vrp_filter", "vrp_threshold", "swing_bias_filter",
    "option_style",
})


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


def get_cached(request: BacktestRequest, key_suffix: str = "") -> Optional[BacktestResult]:
    """Look up cached backtest result. Returns None if not found."""
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        _init_db(conn)

        key = _cache_key(request) + key_suffix
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


def store_cached(request: BacktestRequest, result: BacktestResult, key_suffix: str = ""):
    """Store backtest result in cache."""
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        _init_db(conn)

        key = _cache_key(request) + key_suffix
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
