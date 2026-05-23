"""
Lightweight shadow trade monitor.

Polls open shadow trades every 5 minutes during market hours.
Only fetches the specific expiry chain needed for each trade group,
minimizing API calls. Closes trades when exit rules fire.

Design:
    - Groups open trades by (ticker, expiry) → 1 yfinance call per group
    - yf.Ticker(sym).option_chain(expiry) returns ~200 contracts vs 3000+
    - With 3 trades across 2 tickers = 2 API calls per cycle
    - No open trades → sleep 30 min before rechecking
    - Outside market hours → exit

Options Analytics Team — 2026-05
"""

import json
import logging
import math
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, time as dtime
from typing import Dict, List, Optional, Tuple

import yfinance as yf

from data.shadow_store import close_trade, get_open_trades, record_mark
from data.shadow_checker import check_exit_rules, _compute_dte
from data.shadow_pricer import compute_intrinsic_value

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 300        # 5 minutes
IDLE_INTERVAL = 1800        # 30 minutes when no open trades
MARKET_OPEN = dtime(9, 30)  # ET
MARKET_CLOSE = dtime(16, 0) # ET

_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info("Shutdown signal received, stopping monitor...")
    _running = False


def is_market_hours() -> bool:
    """Check if US market is currently open (ET-based)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    t = dtime(now_et.hour, now_et.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def fetch_contract_prices(
    ticker: str,
    expiry: str,
    needed_contracts: List[Dict],
) -> Tuple[Dict, float]:
    """Fetch prices for specific contracts from a single expiry chain.

    Args:
        ticker: Underlying symbol (e.g., "SPY").
        expiry: Expiry date string "YYYY-MM-DD".
        needed_contracts: List of {strike, option_type} to look up.

    Returns:
        (prices_dict, spot) where prices_dict maps
        (strike, option_type) → {mid, bid, ask}.
    """
    try:
        t = yf.Ticker(ticker)
        spot = t.info.get("regularMarketPrice") or t.info.get("previousClose", 0)

        chain = t.option_chain(expiry)
        calls_df = chain.calls
        puts_df = chain.puts

        prices = {}
        for contract in needed_contracts:
            strike = contract["strike"]
            opt_type = contract["option_type"]

            df = calls_df if opt_type == "call" else puts_df
            row = df[df["strike"] == strike]

            if row.empty:
                # Try nearest strike
                if not df.empty:
                    nearest_idx = (df["strike"] - strike).abs().idxmin()
                    row = df.loc[[nearest_idx]]
                    if abs(row.iloc[0]["strike"] - strike) > strike * 0.02:
                        continue  # too far, skip

            if not row.empty:
                r = row.iloc[0]
                try:
                    bid = float(r.get("bid", 0) or 0)
                    ask = float(r.get("ask", 0) or 0)
                    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(r.get("lastPrice", 0) or 0)
                except (ValueError, TypeError):
                    continue
                if mid > 0:
                    prices[(strike, opt_type)] = {
                        "mid": round(mid, 4),
                        "bid": round(bid, 4),
                        "ask": round(ask, 4),
                    }

        return prices, spot

    except Exception as e:
        logger.error("Failed to fetch chain for %s exp=%s: %s", ticker, expiry, e)
        return {}, 0.0


def check_trade_group(
    ticker: str,
    expiry: str,
    trades: List[Dict],
) -> Dict:
    """Check exit rules for a group of trades sharing (ticker, expiry).

    One yfinance call for the whole group.
    """
    # Collect all needed contracts across trades in this group
    needed = []
    for trade in trades:
        try:
            legs = json.loads(trade["legs_json"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Malformed legs_json for trade #%d, skipping", trade["id"])
            continue
        for leg in legs:
            needed.append({
                "strike": leg["strike"],
                "option_type": leg["option_type"],
            })

    # Single API call
    prices, spot = fetch_contract_prices(ticker, expiry, needed)

    if not prices or spot <= 0:
        logger.warning("No prices for %s exp=%s, skipping %d trades",
                       ticker, expiry, len(trades))
        return {"checked": len(trades), "closed": 0, "errors": 1}

    result = {"checked": 0, "closed": 0, "errors": 0}
    today = datetime.now().strftime("%Y-%m-%d")
    dte = _compute_dte(expiry)

    for trade in trades:
        trade_id = trade["id"]
        try:
            legs = json.loads(trade["legs_json"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Malformed legs_json for trade #%d, skipping", trade_id)
            result["errors"] += 1
            continue
        result["checked"] += 1

        # Build current leg prices
        current_legs = []
        all_priced = True
        for leg in legs:
            key = (leg["strike"], leg["option_type"])
            if dte <= 0:
                # Expired — use intrinsic value
                iv = compute_intrinsic_value(spot, leg["strike"], leg["option_type"])
                current_legs.append({
                    "strike": leg["strike"], "option_type": leg["option_type"],
                    "action": leg["action"],
                    "mid": round(iv, 4), "bid": round(iv, 4), "ask": round(iv, 4),
                    "source": "settlement",
                })
            elif key in prices:
                p = prices[key]
                current_legs.append({
                    "strike": leg["strike"], "option_type": leg["option_type"],
                    "action": leg["action"],
                    "mid": p["mid"], "bid": p["bid"], "ask": p["ask"],
                    "source": "live",
                })
            else:
                all_priced = False
                current_legs.append({
                    "strike": leg["strike"], "option_type": leg["option_type"],
                    "action": leg["action"],
                    "mid": None, "bid": None, "ask": None,
                    "source": "missing",
                })

        if not all_priced:
            logger.warning("Incomplete prices for trade #%d, skipping exit check",
                           trade_id)
            continue

        # Compute current net price
        current_net = 0.0
        for lp in current_legs:
            mid = lp.get("mid", 0.0) or 0.0
            if lp["action"] == "sell":
                current_net += mid
            else:
                current_net -= mid

        # Check exit rules
        should_close, reason, unrealized_pnl = check_exit_rules(
            trade, current_net, spot, dte
        )

        # Always record a mark
        record_mark(
            trade_id=trade_id,
            mark_date=today,
            mark_leg_prices=current_legs,
            mark_spot=spot,
            unrealized_pnl=round(unrealized_pnl, 2),
            dte_remaining=dte,
            price_source="live",
        )

        if should_close:
            close_trade(trade_id, current_legs, reason, spot)
            result["closed"] += 1
            contracts = trade["contracts"]
            logger.info(
                "CLOSED #%d %s/%s: %s | P&L=$%.2f | DTE=%d",
                trade_id, ticker, trade["strategy"],
                reason, unrealized_pnl * contracts, dte,
            )
        else:
            logger.debug(
                "  #%d %s/%s: holding | uPnL=$%.2f | DTE=%d",
                trade_id, ticker, trade["strategy"],
                unrealized_pnl, dte,
            )

    return result


def run_monitor_cycle() -> Dict:
    """Run one monitoring cycle across all open trades.

    Groups trades by (ticker, expiry), makes one API call per group.
    """
    open_trades = get_open_trades()
    if not open_trades:
        return {"open_trades": 0, "checked": 0, "closed": 0, "api_calls": 0}

    # Group by (symbol, expiry)
    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for trade in open_trades:
        key = (trade["symbol"], trade["expiry"] or "unknown")
        groups[key].append(trade)

    total = {"open_trades": len(open_trades), "checked": 0, "closed": 0,
             "api_calls": len(groups), "errors": 0}

    logger.info("Monitor cycle: %d trades in %d groups",
                len(open_trades), len(groups))

    for (ticker, expiry), trades in groups.items():
        if expiry == "unknown":
            logger.warning("Trade(s) with no expiry, skipping: %s",
                           [t["id"] for t in trades])
            continue

        result = check_trade_group(ticker, expiry, trades)
        total["checked"] += result["checked"]
        total["closed"] += result["closed"]
        total["errors"] += result.get("errors", 0)

        # Rate limit between groups
        time.sleep(1.0)

    return total


def run_monitor_loop():
    """Main monitor loop. Runs during market hours, checks every 5 min."""
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("Shadow trade monitor starting (check=%ds, idle=%ds)",
                CHECK_INTERVAL, IDLE_INTERVAL)

    while _running:
        if not is_market_hours():
            logger.info("Market closed, sleeping %ds", IDLE_INTERVAL)
            _sleep(IDLE_INTERVAL)
            continue

        try:
            result = run_monitor_cycle()

            if result["open_trades"] == 0:
                logger.info("No open trades, sleeping %ds", IDLE_INTERVAL)
                _sleep(IDLE_INTERVAL)
            else:
                logger.info(
                    "Cycle done: %d checked, %d closed, %d API calls | next in %ds",
                    result["checked"], result["closed"],
                    result["api_calls"], CHECK_INTERVAL,
                )
                _sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error("Monitor cycle error: %s", e)
            _sleep(CHECK_INTERVAL)

    logger.info("Shadow trade monitor stopped")


def _sleep(seconds: int):
    """Interruptible sleep."""
    end = time.time() + seconds
    while _running and time.time() < end:
        time.sleep(min(5, end - time.time()))
