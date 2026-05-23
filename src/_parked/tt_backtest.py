"""
Tastytrade Backtester API wrapper.

Uses TT's /backtests REST API (13 years of data, 137+ symbols).
Limited to 5 calls/day on free tier — results are cached in SQLite.

Options Analytics Team — 2026-04
"""

import logging
import os
import time
from datetime import date
from typing import Optional

from .models import BacktestRequest, BacktestResult, BacktestTrade, BacktestStats
from .analyzer import analyze_results
from .cache import get_cached, store_cached

logger = logging.getLogger(__name__)

# Strategy type mapping for TT API
_TT_STRATEGY_MAP = {
    "iron_condor": "Iron Condor",
    "short_put_spread": "Short Put Vertical",
    "short_call_spread": "Short Call Vertical",
    "short_strangle": "Short Strangle",
    "naked_put_1dte": "Short Put",
}


def run_tt_backtest(request: BacktestRequest) -> Optional[BacktestResult]:
    """Run a backtest via Tastytrade API.

    Returns None if TT credentials are not available or API call fails.
    Results are cached in SQLite.
    """
    # Check cache first
    cached = get_cached(request)
    if cached:
        return cached

    # Check credentials
    username = os.getenv("TT_USERNAME", "")
    password = os.getenv("TT_PASSWORD", "")
    if not username or not password:
        logger.info("TT credentials not set, skipping TT backtest")
        return None

    tt_strategy = _TT_STRATEGY_MAP.get(request.strategy)
    if not tt_strategy:
        logger.info("Strategy %s not supported by TT backtester", request.strategy)
        return None

    try:
        from tastytrade import Session
        is_test = os.getenv("TT_SANDBOX", "").lower() in ("1", "true", "yes")
        session = Session(login=username, password=password, is_test=is_test)

        # Build backtest request payload
        payload = {
            "symbol": request.symbol,
            "strategy-type": tt_strategy,
            "start-date": request.start_date.isoformat(),
            "end-date": request.end_date.isoformat(),
            "entry-conditions": {
                "target-delta": request.entry_delta,
                "min-dte": request.entry_dte_min,
                "max-dte": request.entry_dte_max,
            },
            "exit-conditions": {
                "profit-target-percent": request.exit_profit_pct,
                "stop-loss-percent": request.exit_loss_pct,
                "close-at-dte": request.exit_dte,
            },
        }

        # Submit backtest
        response = session._request(
            "POST",
            f"/backtests",
            json=payload,
        )

        if not response or "data" not in response:
            logger.warning("TT backtest returned no data")
            return None

        # Parse response into trades
        trades = _parse_tt_response(response["data"])
        stats = analyze_results(trades)
        equity = _build_equity([t.pnl for t in trades])

        result = BacktestResult(
            request=request,
            stats=stats,
            trades=trades,
            equity_curve=equity,
            source="tastytrade",
        )

        # Cache result
        store_cached(request, result)

        return result

    except Exception as e:
        logger.warning("TT backtest failed: %s", e)
        return None


def _parse_tt_response(data: dict) -> list:
    """Parse TT backtest API response into BacktestTrade list."""
    trades = []
    for entry in data.get("trades", []):
        try:
            trade = BacktestTrade(
                entry_date=date.fromisoformat(entry.get("entry-date", "2020-01-01")),
                exit_date=date.fromisoformat(entry.get("exit-date", "2020-01-01")),
                entry_price=float(entry.get("entry-price", 0)),
                exit_price=float(entry.get("exit-price", 0)),
                pnl=float(entry.get("pnl", 0)),
                pnl_pct=float(entry.get("pnl-pct", 0)),
                dte_at_entry=int(entry.get("dte-at-entry", 0)),
                dte_at_exit=int(entry.get("dte-at-exit", 0)),
                win=float(entry.get("pnl", 0)) > 0,
                exit_reason=entry.get("exit-reason", "unknown"),
            )
            trades.append(trade)
        except Exception as e:
            logger.debug("Failed to parse TT trade: %s", e)
    return trades


def _build_equity(pnls: list) -> list:
    curve = [0.0]
    for p in pnls:
        curve.append(curve[-1] + p)
    return curve
