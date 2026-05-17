"""
Dolt options data provider for backtesting.

Reads from a local clone of dolthub.com/post-no-preference/options.
Produces ChainSnapshot objects compatible with the existing backtest pipeline.

Tables used:
    option_chain       — per-contract bid/ask/IV/greeks by date
    volatility_history — daily HV/IV summary per ticker
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from scanner.providers.base import ChainSnapshot, OptionContract

logger = logging.getLogger(__name__)

_DEFAULT_DOLT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "dolt_options",
)


def _get_db_path() -> str:
    path = os.getenv("DOLT_OPTIONS_DB", _DEFAULT_DOLT_PATH)
    db_file = os.path.join(path, ".dolt", "noms", "manifest")
    if not os.path.exists(db_file):
        raise FileNotFoundError(
            f"Dolt database not found at {path}. "
            "Clone it with: cd data && dolt clone post-no-preference/options dolt_options"
        )
    return path


def _get_conn(dolt_path: Optional[str] = None) -> sqlite3.Connection:
    path = dolt_path or _get_db_path()
    db_file = os.path.join(path, ".dolt", "noms", "vvvv")
    # Dolt stores data internally; we query via dolt sql-server or the Python interface.
    # For simplicity, use dolt's built-in SQLite-compatible interface via subprocess.
    raise NotImplementedError("Use query functions instead")


def _dolt_query(sql: str, dolt_path: Optional[str] = None) -> List[Dict]:
    """Execute a SQL query against the local Dolt database."""
    import json
    import subprocess

    path = dolt_path or _get_db_path()
    result = subprocess.run(
        ["dolt", "sql", "-q", sql, "-r", "json"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        logger.error("Dolt query failed: %s", result.stderr.strip())
        return []

    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        logger.error("Failed to parse Dolt JSON output")
        return []


def get_available_dates(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    dolt_path: Optional[str] = None,
) -> List[str]:
    """List all dates with option chain data for a ticker."""
    clauses = ["act_symbol = '{}'".format(ticker.replace("'", ""))]
    if start_date:
        clauses.append(f"date >= '{start_date}'")
    if end_date:
        clauses.append(f"date <= '{end_date}'")

    where = " AND ".join(clauses)
    sql = f"SELECT DISTINCT date FROM option_chain WHERE {where} ORDER BY date"

    rows = _dolt_query(sql, dolt_path)
    return [str(r.get("date", "")) for r in rows]


def get_volatility(
    ticker: str, date: str, dolt_path: Optional[str] = None,
) -> Optional[Dict]:
    """Get volatility history for a ticker on a given date."""
    sql = (
        f"SELECT * FROM volatility_history "
        f"WHERE act_symbol = '{ticker}' AND date = '{date}' LIMIT 1"
    )
    rows = _dolt_query(sql, dolt_path)
    return rows[0] if rows else None


def _estimate_spot(contracts: List[Dict]) -> float:
    """Estimate spot price from deep ITM call with delta closest to 1.0."""
    best_call = None
    best_delta = 0.0

    for c in contracts:
        if c.get("call_put") != "call":
            continue
        delta = float(c.get("delta") or 0)
        if delta > best_delta:
            best_delta = delta
            best_call = c

    if best_call and best_delta > 0.95:
        strike = float(best_call["strike"])
        mid = (float(best_call.get("bid") or 0) + float(best_call.get("ask") or 0)) / 2
        return strike + mid

    # Fallback: average of highest-delta call strike + mid and lowest put
    calls = [c for c in contracts if c.get("call_put") == "call"]
    puts = [c for c in contracts if c.get("call_put") == "put"]

    if calls:
        atm_calls = sorted(calls, key=lambda c: abs(float(c.get("delta") or 0) - 0.5))
        if atm_calls:
            return float(atm_calls[0]["strike"])

    if puts:
        atm_puts = sorted(puts, key=lambda c: abs(float(c.get("delta") or 0) + 0.5))
        if atm_puts:
            return float(atm_puts[0]["strike"])

    # Last resort: median strike
    strikes = [float(c["strike"]) for c in contracts if c.get("strike")]
    if strikes:
        strikes.sort()
        return strikes[len(strikes) // 2]

    return 0.0


def get_snapshot(
    ticker: str,
    date: str,
    max_dte: int = 60,
    dolt_path: Optional[str] = None,
) -> Optional[ChainSnapshot]:
    """Build a ChainSnapshot from Dolt option_chain data.

    Args:
        ticker: Symbol (e.g., 'SPY').
        date: Date string 'YYYY-MM-DD'.
        max_dte: Maximum DTE to include.
        dolt_path: Override Dolt repo path.

    Returns:
        ChainSnapshot compatible with the backtest pipeline.
    """
    safe_ticker = ticker.replace("'", "")
    sql = (
        f"SELECT date, act_symbol, expiration, strike, call_put, "
        f"bid, ask, vol, delta, gamma, theta, vega, rho "
        f"FROM option_chain "
        f"WHERE act_symbol = '{safe_ticker}' AND date = '{date}' "
        f"AND expiration <= DATE_ADD('{date}', INTERVAL {max_dte} DAY) "
        f"ORDER BY expiration, strike, call_put"
    )

    rows = _dolt_query(sql, dolt_path)
    if not rows:
        return None

    spot = _estimate_spot(rows)
    if spot <= 0:
        logger.warning("Could not estimate spot for %s on %s", ticker, date)
        return None

    contracts = []
    expiries = set()

    for r in rows:
        bid = float(r.get("bid") or 0)
        ask = float(r.get("ask") or 0)
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
        iv = float(r.get("vol") or 0)
        expiry = str(r.get("expiration", ""))

        contracts.append(OptionContract(
            ticker=ticker,
            strike=float(r["strike"]),
            expiry=expiry,
            option_type=str(r["call_put"]).lower(),
            bid=bid,
            ask=ask,
            mid=mid,
            last=mid,
            volume=0,
            open_interest=0,
            implied_volatility=iv,
        ))
        expiries.add(expiry)

    return ChainSnapshot(
        ticker=ticker,
        spot=spot,
        fetched_at=datetime.strptime(date, "%Y-%m-%d"),
        contracts=contracts,
        expiries=sorted(expiries),
    )


def get_date_range(
    ticker: str, dolt_path: Optional[str] = None,
) -> Tuple[str, str]:
    """Get the first and last dates available for a ticker."""
    sql = (
        f"SELECT MIN(date) as min_d, MAX(date) as max_d "
        f"FROM option_chain WHERE act_symbol = '{ticker}'"
    )
    rows = _dolt_query(sql, dolt_path)
    if rows:
        return str(rows[0].get("min_d", "")), str(rows[0].get("max_d", ""))
    return "", ""


def get_available_tickers(dolt_path: Optional[str] = None) -> List[str]:
    """List all tickers in the Dolt options database."""
    sql = "SELECT DISTINCT act_symbol FROM option_chain ORDER BY act_symbol"
    rows = _dolt_query(sql, dolt_path)
    return [str(r.get("act_symbol", "")) for r in rows]
