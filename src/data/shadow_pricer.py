"""
Price lookup for shadow paper trades.

Resolves current option prices for specific (ticker, strike, expiry, option_type)
tuples by querying the chain_contracts table from collected snapshots.
Falls back to live yfinance fetch when snapshot data is missing.

Options Analytics Team — 2026-05
"""

import logging
import math
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CHAIN_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "chain_snapshots.db",
)


def _get_chain_conn() -> sqlite3.Connection:
    path = os.getenv("CHAIN_SNAPSHOTS_DB", _CHAIN_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def lookup_leg_price(
    ticker: str,
    strike: float,
    expiry: str,
    option_type: str,
) -> Optional[Dict]:
    """Look up the most recent price for a specific contract from snapshots.

    Returns dict with {mid, bid, ask, snapshot_date, label, spot, source}
    or None if not found.
    """
    conn = _get_chain_conn()
    try:
        row = conn.execute(
            """SELECT cc.mid, cc.bid, cc.ask, cs.snapshot_date, cs.label, cs.spot
            FROM chain_contracts cc
            JOIN chain_snapshots cs ON cc.snapshot_id = cs.id
            WHERE cc.ticker = ?
              AND cc.expiry = ?
              AND cc.strike = ?
              AND cc.option_type = ?
            ORDER BY cs.snapshot_date DESC, cs.label DESC
            LIMIT 1""",
            (ticker, expiry, strike, option_type),
        ).fetchone()

        if row and row["mid"] is not None and row["mid"] > 0:
            return {
                "mid": row["mid"],
                "bid": row["bid"],
                "ask": row["ask"],
                "snapshot_date": row["snapshot_date"],
                "label": row["label"],
                "spot": row["spot"],
                "source": "snapshot",
            }

        # Try interpolation from nearby strikes
        interp = _interpolate_price(conn, ticker, strike, expiry, option_type)
        if interp:
            return interp

        return None
    finally:
        conn.close()


def _interpolate_price(
    conn: sqlite3.Connection,
    ticker: str,
    strike: float,
    expiry: str,
    option_type: str,
) -> Optional[Dict]:
    """Interpolate price from two nearest strikes in the same expiry."""
    rows = conn.execute(
        """SELECT cc.strike, cc.mid, cc.bid, cc.ask, cs.snapshot_date, cs.spot
        FROM chain_contracts cc
        JOIN chain_snapshots cs ON cc.snapshot_id = cs.id
        WHERE cc.ticker = ?
          AND cc.expiry = ?
          AND cc.option_type = ?
          AND cc.mid > 0
        ORDER BY cs.snapshot_date DESC, ABS(cc.strike - ?) ASC
        LIMIT 10""",
        (ticker, expiry, option_type, strike),
    ).fetchall()

    if len(rows) < 2:
        return None

    # Find one below and one above the target strike
    below = None
    above = None
    for r in rows:
        if r["strike"] <= strike and (below is None or r["strike"] > below["strike"]):
            below = dict(r)
        if r["strike"] >= strike and (above is None or r["strike"] < above["strike"]):
            above = dict(r)

    if below is None or above is None:
        return None
    if below["strike"] == above["strike"]:
        return {
            "mid": below["mid"], "bid": below["bid"], "ask": below["ask"],
            "snapshot_date": below["snapshot_date"], "spot": below["spot"],
            "source": "interpolated",
        }

    # Linear interpolation
    frac = (strike - below["strike"]) / (above["strike"] - below["strike"])
    mid = below["mid"] + frac * (above["mid"] - below["mid"])
    bid = (below["bid"] or 0) + frac * ((above["bid"] or 0) - (below["bid"] or 0))
    ask = (below["ask"] or 0) + frac * ((above["ask"] or 0) - (below["ask"] or 0))

    return {
        "mid": round(mid, 4),
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "snapshot_date": below["snapshot_date"],
        "spot": below["spot"],
        "source": "interpolated",
    }


def lookup_spread_price(
    ticker: str,
    legs: List[Dict],
    expiry: str,
) -> Dict:
    """Look up current prices for all legs of a spread.

    Args:
        ticker: Underlying symbol.
        legs: List of {action, option_type, strike, ...}.
        expiry: Expiry date string.

    Returns:
        {
            "leg_prices": [{strike, expiry, option_type, action, mid, bid, ask, source}, ...],
            "net_price": float,  # sell=+, buy=-
            "spot": float,
            "complete": bool,  # True if all legs priced
            "source": str,  # "snapshot", "interpolated", "live", "mixed"
        }
    """
    leg_prices = []
    sources = set()
    spot = None
    complete = True

    for leg in legs:
        price_data = lookup_leg_price(
            ticker, leg["strike"], expiry, leg["option_type"]
        )

        if price_data is None:
            # Try live fallback
            price_data = _live_fallback(ticker, leg["strike"], expiry, leg["option_type"])

        if price_data is None:
            complete = False
            leg_prices.append({
                "strike": leg["strike"],
                "expiry": expiry,
                "option_type": leg["option_type"],
                "action": leg["action"],
                "mid": None, "bid": None, "ask": None,
                "source": "missing",
            })
            continue

        if spot is None:
            spot = price_data.get("spot")
        sources.add(price_data["source"])

        leg_prices.append({
            "strike": leg["strike"],
            "expiry": expiry,
            "option_type": leg["option_type"],
            "action": leg["action"],
            "mid": price_data["mid"],
            "bid": price_data["bid"],
            "ask": price_data["ask"],
            "source": price_data["source"],
        })

    # Compute net price
    net = 0.0
    for lp in leg_prices:
        mid = lp.get("mid") or 0.0
        if lp["action"] == "sell":
            net += mid
        else:
            net -= mid

    source = "mixed" if len(sources) > 1 else (sources.pop() if sources else "missing")

    return {
        "leg_prices": leg_prices,
        "net_price": round(net, 4),
        "spot": spot,
        "complete": complete,
        "source": source,
    }


def _live_fallback(
    ticker: str,
    strike: float,
    expiry: str,
    option_type: str,
) -> Optional[Dict]:
    """Fetch a live price from yfinance as fallback."""
    try:
        from scanner.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider(delay=0.5)
        chain = provider.get_chain(ticker, min_dte=0, max_dte=90)

        for c in chain.contracts:
            if (c.strike == strike and c.expiry == expiry
                    and c.option_type == option_type):
                if c.mid and not math.isnan(c.mid) and c.mid > 0:
                    return {
                        "mid": c.mid,
                        "bid": c.bid,
                        "ask": c.ask,
                        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
                        "spot": chain.spot,
                        "source": "live",
                    }

        logger.warning("Live fallback: contract not found %s %s %s %s",
                       ticker, strike, expiry, option_type)
        return None
    except Exception as e:
        logger.error("Live fallback failed for %s: %s", ticker, e)
        return None


def compute_intrinsic_value(
    spot: float,
    strike: float,
    option_type: str,
) -> float:
    """Compute intrinsic value at expiry."""
    if option_type == "call":
        return max(0.0, spot - strike)
    else:
        return max(0.0, strike - spot)


def get_latest_spot(ticker: str) -> Optional[float]:
    """Get the most recent spot price from chain snapshots."""
    conn = _get_chain_conn()
    try:
        row = conn.execute(
            """SELECT spot FROM chain_snapshots
            WHERE ticker = ? AND spot IS NOT NULL
            ORDER BY snapshot_date DESC
            LIMIT 1""",
            (ticker,),
        ).fetchone()
        return row["spot"] if row else None
    finally:
        conn.close()
