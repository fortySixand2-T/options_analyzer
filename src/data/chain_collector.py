"""
Daily chain snapshot collector.

Fetches current option chains via YFinanceProvider and stores them in SQLite.
Designed to run once per trading day (after market close) to build up a
historical dataset of real bid/ask/IV/OI data for backtester validation.

Inspired by Trading-copilot's nightly_chain_scan + iv_history pattern,
adapted for our existing provider architecture.

Usage:
    from data.chain_collector import collect_daily_snapshots
    result = collect_daily_snapshots(["SPY", "QQQ", "IWM"])

Options Analytics Team — 2026-04
"""

import logging
import math
import time
from datetime import datetime
from typing import List, Optional

from scanner.providers.base import ChainSnapshot
from scanner.providers.yfinance_provider import YFinanceProvider
from data.chain_store import store_snapshot, store_iv_snapshot

logger = logging.getLogger(__name__)

# Default tickers to collect
DEFAULT_TICKERS = ["SPY", "QQQ", "^SPX", "^NDX", "IWM", "META", "AAPL", "AMZN", "NFLX", "GOOG"]

# Wider DTE range for collection — we store everything, filter at query time
COLLECT_MIN_DTE = 0
COLLECT_MAX_DTE = 60


def collect_daily_snapshots(
    tickers: Optional[List[str]] = None,
    min_dte: int = COLLECT_MIN_DTE,
    max_dte: int = COLLECT_MAX_DTE,
    delay: float = 2.0,
    label: str = "eod",
) -> dict:
    """Collect and store chain snapshots for all tickers.

    Args:
        tickers: Symbols to collect. Defaults to full watchlist.
        min_dte: Minimum DTE to include.
        max_dte: Maximum DTE to include (wider than scanner default).
        delay: Seconds between yfinance calls (rate limiting).
        label: Snapshot label — "eod" for full daily, "shortdte" for focused 1-7 DTE.

    Returns:
        Summary dict with counts and any errors.
    """
    tickers = tickers or DEFAULT_TICKERS
    provider = YFinanceProvider(delay=delay)
    today = datetime.now().strftime("%Y-%m-%d")

    results = {
        "date": today,
        "label": label,
        "tickers_requested": len(tickers),
        "tickers_success": 0,
        "tickers_failed": 0,
        "total_contracts": 0,
        "errors": [],
        "details": [],
    }

    start_time = time.time()

    for ticker in tickers:
        logger.info("Collecting chain snapshot for %s...", ticker)

        try:
            # Fetch the full chain via our existing provider
            chain = provider.get_chain(ticker, min_dte=min_dte, max_dte=max_dte)

            if not chain.contracts:
                msg = f"{ticker}: no contracts returned"
                logger.warning(msg)
                results["errors"].append(msg)
                results["tickers_failed"] += 1
                continue

            # Store chain snapshot
            snapshot_id = store_snapshot(chain, label=label)

            # Extract and store IV summary (like Trading-copilot's _store_iv_snapshots)
            _store_iv_from_chain(ticker, today, chain, provider, label=label)

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
                "  %s: %d contracts across %d expiries, spot=%.2f",
                ticker, len(chain.contracts), len(chain.expiries), chain.spot,
            )

        except Exception as e:
            msg = f"{ticker}: {e}"
            logger.error("Failed to collect %s: %s", ticker, e)
            results["errors"].append(msg)
            results["tickers_failed"] += 1

    results["duration_sec"] = round(time.time() - start_time, 1)
    logger.info(
        "Collection complete: %d/%d tickers, %d contracts in %.1fs",
        results["tickers_success"],
        results["tickers_requested"],
        results["total_contracts"],
        results["duration_sec"],
    )

    return results


def _store_iv_from_chain(
    ticker: str,
    snapshot_date: str,
    chain: ChainSnapshot,
    provider: YFinanceProvider,
    label: str = "eod",
):
    """Extract ATM IV from chain and store daily IV summary.

    Mirrors Trading-copilot's _store_iv_snapshots pattern:
    find the ATM call and put, extract their IV, compute average.
    """
    spot = chain.spot
    if not spot or math.isnan(spot) or spot <= 0:
        return

    calls = [c for c in chain.contracts if c.option_type == "call"]
    puts = [c for c in chain.contracts if c.option_type == "put"]

    atm_iv_call = None
    atm_iv_put = None

    # Find nearest-to-ATM contract for each type
    if calls:
        atm_call = min(calls, key=lambda c: abs(c.strike - spot))
        iv = atm_call.implied_volatility
        if iv and not math.isnan(iv):
            atm_iv_call = iv

    if puts:
        atm_put = min(puts, key=lambda c: abs(c.strike - spot))
        iv = atm_put.implied_volatility
        if iv and not math.isnan(iv):
            atm_iv_put = iv

    # Average
    ivs = [v for v in [atm_iv_call, atm_iv_put] if v is not None]
    atm_iv_avg = sum(ivs) / len(ivs) if ivs else None

    if atm_iv_avg is None:
        return

    # Get realized vol from history
    rv_30d = None
    rv_60d = None
    try:
        history = provider.get_history(ticker, days=120)
        rv_30d = history.realized_vol_30d
        rv_60d = history.realized_vol_60d
        if rv_30d and math.isnan(rv_30d):
            rv_30d = None
        if rv_60d and math.isnan(rv_60d):
            rv_60d = None
    except Exception:
        pass

    store_iv_snapshot(
        ticker=ticker,
        snapshot_date=snapshot_date,
        atm_iv_call=atm_iv_call,
        atm_iv_put=atm_iv_put,
        atm_iv_avg=atm_iv_avg,
        realized_vol_30d=rv_30d,
        realized_vol_60d=rv_60d,
        spot=spot,
        label=label,
    )
    logger.info(
        "  %s IV: call=%.3f put=%.3f avg=%.3f rv30=%.3f spot=%.2f",
        ticker,
        atm_iv_call or 0,
        atm_iv_put or 0,
        atm_iv_avg or 0,
        rv_30d or 0,
        spot,
    )
