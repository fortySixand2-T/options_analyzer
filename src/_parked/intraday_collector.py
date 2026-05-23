"""
Intraday data collection pipeline for 0 DTE.

Collects:
- 5-min OHLCV bars for SPY, ^SPX, ^VIX (stored in intraday.db)
- Intraday chain snapshots every 30 min for SPY, ^SPX (0-2 DTE only)

Three modes:
- bars:  One-shot fetch of recent 5-min bars (backfill last 5 days)
- chain: One-shot intraday chain snapshot labeled with current time slot
- loop:  Long-lived process collecting chains every 30 min during market hours

Options Analytics Team — 2026-04
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import pytz

from scanner.providers.yfinance_provider import YFinanceProvider
from data.intraday_store import store_bars
from data.chain_store import store_snapshot

logger = logging.getLogger(__name__)

# Tickers for intraday collection
INTRADAY_TICKERS = ["SPY", "^SPX"]
VIX_TICKERS = ["^VIX"]
ALL_BAR_TICKERS = INTRADAY_TICKERS + VIX_TICKERS

# Market hours (Eastern Time)
ET = pytz.timezone("US/Eastern")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN = 0

# Snapshot schedule: every 30 min from 9:30 to 16:00
SNAPSHOT_TIMES = [
    "0930", "1000", "1030", "1100", "1130",
    "1200", "1230", "1300", "1330",
    "1400", "1430", "1500", "1530", "1600",
]


def _current_et() -> datetime:
    """Current time in Eastern."""
    return datetime.now(ET)


def _is_market_hours() -> bool:
    """Check if current ET time is within market hours (weekday 9:30-16:00)."""
    now = _current_et()
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0)
    return market_open <= now <= market_close


def _current_time_label() -> str:
    """Get the current 30-min time slot label (e.g., 'intraday_1030')."""
    now = _current_et()
    # Round down to nearest 30-min slot
    minute = (now.minute // 30) * 30
    return f"intraday_{now.hour:02d}{minute:02d}"


# ── Bar collection ───────────────────────────────────────────────────────────


def collect_intraday_bars(
    tickers: Optional[List[str]] = None,
    interval: str = "5m",
    period: str = "5d",
    delay: float = 2.0,
) -> dict:
    """Fetch and store intraday price bars for tickers.

    One-shot operation — fetches the last `period` of bars and stores them.
    Safe to re-run (upserts).

    Args:
        tickers: Symbols to collect. Defaults to SPY, ^SPX, ^VIX.
        interval: Bar interval ('1m', '5m', '15m').
        period: yfinance period string ('5d', '60d').
        delay: Seconds between API calls.

    Returns:
        Summary dict.
    """
    tickers = tickers or ALL_BAR_TICKERS
    provider = YFinanceProvider(delay=delay)

    results = {
        "tickers_success": 0,
        "tickers_failed": 0,
        "total_bars": 0,
        "interval": interval,
        "period": period,
        "errors": [],
        "details": [],
    }

    start_time = time.time()

    for ticker in tickers:
        logger.info("Fetching %s bars for %s...", interval, ticker)
        try:
            bars_df = provider.get_intraday(ticker, interval=interval, period=period)

            if bars_df.empty:
                msg = f"{ticker}: no bars returned"
                logger.warning(msg)
                results["errors"].append(msg)
                results["tickers_failed"] += 1
                continue

            count = store_bars(ticker, bars_df, interval)
            results["tickers_success"] += 1
            results["total_bars"] += count
            results["details"].append({
                "ticker": ticker,
                "bars": count,
                "date_range": f"{bars_df.index[0]} → {bars_df.index[-1]}",
            })

            logger.info("  %s: %d bars stored", ticker, count)

        except Exception as e:
            msg = f"{ticker}: {e}"
            logger.error("Failed to collect bars for %s: %s", ticker, e)
            results["errors"].append(msg)
            results["tickers_failed"] += 1

    results["duration_sec"] = round(time.time() - start_time, 1)
    return results


# ── Intraday chain snapshot ──────────────────────────────────────────────────


def collect_intraday_chain_snapshot(
    tickers: Optional[List[str]] = None,
    min_dte: int = 0,
    max_dte: int = 2,
    delay: float = 2.0,
    label: Optional[str] = None,
) -> dict:
    """Collect a single chain snapshot labeled with current time slot.

    Only stores 0-2 DTE contracts to keep size manageable for 0 DTE analysis.
    Label defaults to current 30-min slot (e.g., 'intraday_1030').

    Args:
        tickers: Symbols to collect. Defaults to SPY, ^SPX.
        min_dte: Minimum DTE (0 for 0 DTE).
        max_dte: Maximum DTE to include.
        delay: Seconds between API calls.
        label: Override label (default: auto from current time).

    Returns:
        Summary dict.
    """
    tickers = tickers or INTRADAY_TICKERS
    provider = YFinanceProvider(delay=delay)
    label = label or _current_time_label()
    today = datetime.now().strftime("%Y-%m-%d")

    results = {
        "date": today,
        "label": label,
        "tickers_success": 0,
        "tickers_failed": 0,
        "total_contracts": 0,
        "errors": [],
        "details": [],
    }

    start_time = time.time()

    for ticker in tickers:
        logger.info("Collecting intraday chain [%s] for %s...", label, ticker)
        try:
            chain = provider.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

            if not chain.contracts:
                msg = f"{ticker}: no contracts"
                logger.warning(msg)
                results["errors"].append(msg)
                results["tickers_failed"] += 1
                continue

            snapshot_id = store_snapshot(chain, label=label)

            results["tickers_success"] += 1
            results["total_contracts"] += len(chain.contracts)
            results["details"].append({
                "ticker": ticker,
                "contracts": len(chain.contracts),
                "expiries": len(chain.expiries),
                "spot": chain.spot,
                "snapshot_id": snapshot_id,
            })

            logger.info(
                "  %s [%s]: %d contracts, spot=%.2f",
                ticker, label, len(chain.contracts), chain.spot,
            )

        except Exception as e:
            msg = f"{ticker}: {e}"
            logger.error("Failed to collect intraday chain for %s: %s", ticker, e)
            results["errors"].append(msg)
            results["tickers_failed"] += 1

    results["duration_sec"] = round(time.time() - start_time, 1)
    return results


# ── Collection loop ──────────────────────────────────────────────────────────


def run_intraday_collection_loop(
    interval_minutes: int = 30,
    bar_interval: str = "5m",
) -> None:
    """Run continuous intraday collection during market hours.

    Collects chain snapshots every `interval_minutes` for SPY and ^SPX.
    Collects price bars at session end.
    Sleeps outside market hours.

    Intended to run as a long-lived Docker process.
    """
    logger.info(
        "Starting intraday collection loop (chain every %d min, bars=%s)",
        interval_minutes, bar_interval,
    )

    bars_collected_today = False

    while True:
        now = _current_et()

        if not _is_market_hours():
            # After close: collect bars for today if not done yet
            if not bars_collected_today and now.hour >= MARKET_CLOSE_HOUR and now.weekday() < 5:
                logger.info("Market closed — collecting today's bars")
                result = collect_intraday_bars(interval=bar_interval, period="1d")
                logger.info(
                    "Bars collected: %d bars for %d tickers",
                    result["total_bars"], result["tickers_success"],
                )
                bars_collected_today = True

            # Reset flag at midnight
            if now.hour < MARKET_OPEN_HOUR:
                bars_collected_today = False

            # Sleep until next check (5 min outside market hours)
            logger.debug("Outside market hours, sleeping 5 min")
            time.sleep(300)
            continue

        # During market hours: collect chain snapshot
        logger.info("Market hours — collecting intraday chain snapshot")
        result = collect_intraday_chain_snapshot()
        logger.info(
            "Chain snapshot [%s]: %d contracts for %d tickers",
            result["label"], result["total_contracts"], result["tickers_success"],
        )

        # Sleep until next collection window
        sleep_sec = interval_minutes * 60
        logger.info("Sleeping %d seconds until next collection", sleep_sec)
        time.sleep(sleep_sec)
