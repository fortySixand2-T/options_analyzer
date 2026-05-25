"""Alert evaluation engine — checks trigger conditions and dispatches notifications.

Registered as a scheduled task, runs every 5 minutes during market hours.
"""

import json
import logging
from datetime import datetime, timezone

from src.data.user_db import get_user_db
from src.notifications.dispatcher import send_notification

logger = logging.getLogger(__name__)


async def evaluate_alerts():
    """Check all active alerts against current market data."""
    conn = get_user_db()
    try:
        alerts = conn.execute(
            """SELECT a.*, u.email FROM alerts a
               JOIN users u ON a.user_id = u.id
               WHERE a.is_active = 1""",
        ).fetchall()
    finally:
        conn.close()

    if not alerts:
        return

    triggered = 0
    for alert in alerts:
        try:
            if _should_skip_cooldown(alert):
                continue
            if _evaluate_trigger(alert):
                _fire_alert(alert)
                triggered += 1
        except Exception as e:
            logger.debug("Alert %s evaluation failed: %s", alert["id"], e)

    if triggered:
        logger.info("Evaluated %d alerts, triggered %d", len(alerts), triggered)


def _should_skip_cooldown(alert) -> bool:
    """Check if alert is still in cooldown period."""
    if not alert["last_triggered_at"]:
        return False
    last = datetime.fromisoformat(alert["last_triggered_at"])
    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
    return elapsed < alert["cooldown_minutes"]


def _evaluate_trigger(alert) -> bool:
    """Evaluate a single alert's trigger condition."""
    config = json.loads(alert["trigger_config_json"])
    trigger_type = alert["trigger_type"]
    symbol = config.get("symbol", "SPY")
    threshold = config.get("threshold")

    if trigger_type == "iv_rank_above":
        iv_rank = _get_iv_rank(symbol)
        return iv_rank is not None and threshold is not None and iv_rank > threshold

    elif trigger_type == "iv_rank_below":
        iv_rank = _get_iv_rank(symbol)
        return iv_rank is not None and threshold is not None and iv_rank < threshold

    elif trigger_type == "price_above":
        spot = _get_spot(symbol)
        return spot is not None and threshold is not None and spot > threshold

    elif trigger_type == "price_below":
        spot = _get_spot(symbol)
        return spot is not None and threshold is not None and spot < threshold

    elif trigger_type == "regime_change":
        return False  # TODO: compare against last known regime

    elif trigger_type == "scan_match":
        return False  # TODO: run scanner and check for matches

    return False


def _fire_alert(alert):
    """Dispatch notification and update last_triggered_at."""
    config = json.loads(alert["trigger_config_json"])
    symbol = config.get("symbol", "")
    threshold = config.get("threshold", "")

    send_notification(
        alert["user_id"],
        title=f"Alert: {alert['name']}",
        body=f"{alert['trigger_type'].replace('_', ' ')} triggered for {symbol} (threshold: {threshold})",
        notif_type="alert",
    )

    conn = get_user_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE alerts SET last_triggered_at = ? WHERE id = ?",
            (now, alert["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def _get_iv_rank(symbol: str):
    """Get current IV rank for a symbol (best-effort)."""
    try:
        from scanner.iv_rank import compute_iv_rank_for_symbol
        data = compute_iv_rank_for_symbol(symbol)
        return data.get("iv_rank") if data else None
    except Exception:
        return None


def _get_spot(symbol: str):
    """Get current spot price for a symbol."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None
