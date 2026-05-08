"""
Shadow trade exit rule checker.

Runs daily after chain collection. For each open shadow trade:
1. Look up current prices from chain_contracts snapshots
2. Compute unrealized P&L
3. Check exit rules (profit target, stop loss, time exit, expiry)
4. Close trades that hit exit conditions
5. Record mark-to-market for all open trades

Options Analytics Team — 2026-05
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from data.shadow_store import (
    close_trade,
    get_open_trades,
    record_mark,
)
from data.shadow_pricer import (
    compute_intrinsic_value,
    get_latest_spot,
    lookup_spread_price,
)

logger = logging.getLogger(__name__)


def check_exit_rules(
    trade: Dict,
    current_net_price: float,
    current_spot: float,
    dte_remaining: int,
) -> Tuple[bool, Optional[str], float]:
    """Check if a shadow trade should be closed.

    Returns:
        (should_close, exit_reason, unrealized_pnl_per_contract)
    """
    entry_net = trade["entry_net_price"]
    is_credit = trade["is_credit"]
    profit_target_pct = trade["profit_target_pct"]
    stop_loss_pct = trade["stop_loss_pct"]
    time_exit_dte = trade["time_exit_dte"]

    # Compute unrealized P&L per contract
    # For credit: entry_net > 0, current_net should decrease as spread collapses
    # P&L = (entry_net - abs(current_net)) * 100 for credit
    # For debit: entry_net < 0, current_net should increase
    # P&L = (current_net + entry_net) * 100 for debit (entry_net is negative)
    if is_credit:
        # Credit: we received entry_net, now need to pay current_net to close
        # If current spread is worth less, we profit
        unrealized_pnl = (entry_net + current_net_price) * 100
    else:
        # Debit: we paid |entry_net|, spread is now worth current_net_price
        unrealized_pnl = (current_net_price + entry_net) * 100

    # 1. Check expiry (past expiry date)
    if dte_remaining <= 0:
        return True, "expiry", unrealized_pnl

    # 2. Check time exit
    if time_exit_dte is not None and dte_remaining <= time_exit_dte:
        return True, "time_exit", unrealized_pnl

    # 3. Check profit target
    if profit_target_pct is not None:
        entry_value = abs(entry_net) * 100
        target_pnl = entry_value * profit_target_pct / 100
        if unrealized_pnl >= target_pnl:
            return True, "profit_target", unrealized_pnl

    # 4. Check stop loss
    if stop_loss_pct is not None:
        entry_value = abs(entry_net) * 100
        stop_pnl = -entry_value * stop_loss_pct / 100
        if unrealized_pnl <= stop_pnl:
            return True, "stop_loss", unrealized_pnl

    return False, None, unrealized_pnl


def _compute_dte(expiry: str) -> int:
    """Compute days to expiry from today."""
    try:
        exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
        return (exp_dt - datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)).days
    except (ValueError, TypeError):
        return 999


def _settle_at_expiry(trade: Dict, spot: float) -> List[Dict]:
    """Compute settlement prices at expiry using intrinsic values."""
    legs = json.loads(trade["legs_json"])
    settled = []
    for leg in legs:
        iv = compute_intrinsic_value(spot, leg["strike"], leg["option_type"])
        settled.append({
            "strike": leg["strike"],
            "expiry": trade["expiry"],
            "option_type": leg["option_type"],
            "action": leg["action"],
            "mid": round(iv, 4),
            "bid": round(iv, 4),
            "ask": round(iv, 4),
            "source": "settlement",
        })
    return settled


def run_daily_check(dry_run: bool = False) -> Dict:
    """Run daily exit check on all open shadow trades.

    Returns summary of actions taken.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    open_trades = get_open_trades()

    summary = {
        "date": today,
        "trades_checked": len(open_trades),
        "trades_closed": 0,
        "trades_marked": 0,
        "closures": [],
        "errors": [],
    }

    if not open_trades:
        logger.info("No open shadow trades to check")
        return summary

    logger.info("Checking %d open shadow trades", len(open_trades))

    for trade in open_trades:
        trade_id = trade["id"]
        symbol = trade["symbol"]
        expiry = trade["expiry"]

        try:
            dte = _compute_dte(expiry) if expiry else 999

            # Get current spot
            spot = get_latest_spot(symbol)
            if spot is None:
                logger.warning("No spot price for %s, skipping trade #%d",
                               symbol, trade_id)
                summary["errors"].append(f"#{trade_id} {symbol}: no spot price")
                continue

            # Get current leg prices
            legs = json.loads(trade["legs_json"])

            if dte <= 0:
                # Past expiry — settle at intrinsic value
                leg_prices = _settle_at_expiry(trade, spot)
                price_source = "settlement"
            else:
                # Look up from snapshots
                spread_data = lookup_spread_price(symbol, legs, expiry)
                leg_prices = spread_data["leg_prices"]
                price_source = spread_data["source"]

                if not spread_data["complete"]:
                    logger.warning("Incomplete prices for trade #%d %s, "
                                   "using available data", trade_id, symbol)

                if spread_data["spot"]:
                    spot = spread_data["spot"]

            # Compute current net price
            current_net = 0.0
            for lp in leg_prices:
                mid = lp.get("mid") or 0.0
                if lp["action"] == "sell":
                    current_net += mid
                else:
                    current_net -= mid

            # Check exit rules
            should_close, reason, unrealized_pnl = check_exit_rules(
                trade, current_net, spot, dte
            )

            if should_close and not dry_run:
                close_trade(trade_id, leg_prices, reason, spot)
                summary["trades_closed"] += 1
                summary["closures"].append({
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "strategy": trade["strategy"],
                    "reason": reason,
                    "pnl": round(unrealized_pnl * trade["contracts"], 2),
                    "dte_remaining": dte,
                })
                logger.info("Closed #%d %s/%s: %s, P&L=$%.2f",
                            trade_id, symbol, trade["strategy"],
                            reason, unrealized_pnl * trade["contracts"])
            elif should_close and dry_run:
                summary["closures"].append({
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "strategy": trade["strategy"],
                    "reason": reason,
                    "pnl": round(unrealized_pnl * trade["contracts"], 2),
                    "dte_remaining": dte,
                    "dry_run": True,
                })

            # Record mark-to-market (even for trades we just closed, for history)
            if not dry_run:
                record_mark(
                    trade_id=trade_id,
                    mark_date=today,
                    mark_leg_prices=leg_prices,
                    mark_spot=spot,
                    unrealized_pnl=round(unrealized_pnl, 2),
                    dte_remaining=dte,
                    price_source=price_source,
                )
                summary["trades_marked"] += 1

        except Exception as e:
            logger.error("Error checking trade #%d: %s", trade_id, e)
            summary["errors"].append(f"#{trade_id} {symbol}: {e}")

    logger.info("Daily check complete: %d checked, %d closed, %d marked",
                summary["trades_checked"], summary["trades_closed"],
                summary["trades_marked"])
    return summary
