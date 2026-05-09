"""
Alpaca historical options backfill pipeline.

Fetches daily option bars from Alpaca, enriches with IV and Greeks using
the repo's existing pricing tools, and stores as ChainSnapshots in the
same DB used by the live scanner and backtester.

Pipeline per ticker per date:
    1. Fetch spot price from Alpaca stock bars
    2. Discover candidate OCC symbols (strikes x expiries x call/put)
    3. Fetch daily bars for all candidates (batched at 100)
    4. Enrich each contract: estimate bid/ask, solve IV, compute Greeks
    5. Assemble ChainSnapshot, store via chain_store.store_snapshot()
    6. Compute and store IV summary (ATM IV, skew, term structure)

Options Analytics Team — 2026-05
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from data.alpaca_client import AlpacaOptionsClient
from data.chain_store import store_snapshot, store_iv_snapshot
from scanner.providers.base import ChainSnapshot, OptionContract

logger = logging.getLogger(__name__)

BACKFILL_LABEL = "backfill"
RISK_FREE_RATE = float(os.getenv("OPTIONS_RISK_FREE_RATE", "0.045"))


def _estimate_bid_ask(bar: dict) -> tuple:
    """Estimate bid/ask/mid from OHLC bar data.

    Returns (bid, ask, mid).
    """
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]

    if o > 0 and c > 0:
        bid = min(o, c)
        ask = max(o, c)
        mid = (o + h + l + c) / 4
    elif c > 0:
        bid = c * 0.97
        ask = c * 1.03
        mid = c
    else:
        return 0.0, 0.0, 0.0

    if bid <= 0:
        bid = mid * 0.97
    if ask <= 0:
        ask = mid * 1.03

    return round(bid, 4), round(ask, 4), round(mid, 4)


def _solve_iv(mid: float, spot: float, strike: float, dte: int,
              option_type: str) -> Optional[float]:
    """Solve implied volatility using Brent's method."""
    if mid <= 0 or spot <= 0 or dte <= 0:
        return None

    T = dte / 365.0

    try:
        from analytics.vol_surface import compute_implied_vol
        iv = compute_implied_vol(mid, spot, strike, T, RISK_FREE_RATE, option_type)
        if iv is not None and not math.isnan(iv) and 0.01 < iv < 5.0:
            return round(iv, 6)
    except Exception:
        pass

    return None


def _compute_greeks(spot: float, strike: float, dte: int,
                    iv: float, option_type: str) -> Optional[dict]:
    """Compute Black-Scholes Greeks."""
    if iv is None or dte <= 0:
        return None

    T = dte / 365.0

    try:
        from models.black_scholes import calculate_greeks
        return calculate_greeks(spot, strike, T, RISK_FREE_RATE, iv, option_type)
    except Exception:
        return None


def _business_days(start: str, end: str) -> List[str]:
    """Generate business days (Mon-Fri) between start and end inclusive."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    days = []
    dt = start_dt
    while dt <= end_dt:
        if dt.weekday() < 5:
            days.append(dt.strftime("%Y-%m-%d"))
        dt += timedelta(days=1)
    return days


def backfill_date(
    client: AlpacaOptionsClient,
    ticker: str,
    date: str,
    max_dte: int = 60,
    strike_range_pct: float = 0.15,
) -> Dict:
    """Backfill one ticker for one date.

    Returns summary dict with counts and stats.
    """
    result = {
        "ticker": ticker, "date": date,
        "spot": None, "contracts_fetched": 0,
        "contracts_priced": 0, "iv_solved": 0,
        "stored": False, "error": None,
    }

    # Step 1: Get spot price
    spot = client.get_spot_price(ticker, date)
    if not spot or spot <= 0:
        result["error"] = "No spot price"
        logger.warning("No spot for %s on %s, skipping", ticker, date)
        return result
    result["spot"] = spot

    # Step 2: Discover candidate contracts
    symbols = client.discover_contracts(
        ticker, date, spot,
        max_dte=max_dte,
        strike_range_pct=strike_range_pct,
    )

    if not symbols:
        result["error"] = "No candidate contracts"
        return result

    # Step 3: Fetch bars in batches
    bars = client.get_daily_bars(symbols, date)
    result["contracts_fetched"] = len(bars)

    if not bars:
        result["error"] = "No bar data returned"
        logger.warning("No bars for %s on %s (%d candidates)", ticker, date, len(symbols))
        return result

    # Step 4: Enrich each contract
    contracts = []
    expiry_set = set()

    for occ_sym, bar in bars.items():
        try:
            parsed = AlpacaOptionsClient.parse_occ_symbol(occ_sym)
        except ValueError:
            continue

        expiry = parsed["expiry"]
        strike = parsed["strike"]
        option_type = parsed["option_type"]

        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        dte = (expiry_dt - date_dt).days

        if dte <= 0:
            continue

        bid, ask, mid = _estimate_bid_ask(bar)
        if mid <= 0:
            continue

        result["contracts_priced"] += 1

        iv = _solve_iv(mid, spot, strike, dte, option_type)
        if iv is not None:
            result["iv_solved"] += 1

        contract = OptionContract(
            ticker=ticker,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            bid=bid,
            ask=ask,
            mid=mid,
            last=bar["close"],
            volume=bar["volume"],
            open_interest=0,
            implied_volatility=iv if iv else float("nan"),
        )
        contracts.append(contract)
        expiry_set.add(expiry)

    if not contracts:
        result["error"] = "No valid contracts after enrichment"
        return result

    # Step 5: Assemble and store ChainSnapshot
    chain = ChainSnapshot(
        ticker=ticker,
        spot=spot,
        fetched_at=datetime.strptime(date, "%Y-%m-%d").replace(hour=16, minute=0),
        contracts=contracts,
        expiries=sorted(expiry_set),
    )

    snapshot_id = store_snapshot(chain, label=BACKFILL_LABEL)
    result["stored"] = True

    # Step 6: Store IV summary
    _store_backfill_iv(ticker, date, chain)

    logger.info(
        "Backfilled %s %s: %d contracts, %d IV solved, spot=%.2f",
        ticker, date, len(contracts), result["iv_solved"], spot,
    )

    return result


def _store_backfill_iv(ticker: str, date: str, chain: ChainSnapshot):
    """Compute and store ATM IV summary from backfilled chain."""
    spot = chain.spot
    if not spot or spot <= 0:
        return

    calls = [c for c in chain.contracts if c.option_type == "call"]
    puts = [c for c in chain.contracts if c.option_type == "put"]

    atm_iv_call = None
    atm_iv_put = None

    if calls:
        atm = min(calls, key=lambda c: abs(c.strike - spot))
        iv = atm.implied_volatility
        if iv and not math.isnan(iv):
            atm_iv_call = iv

    if puts:
        atm = min(puts, key=lambda c: abs(c.strike - spot))
        iv = atm.implied_volatility
        if iv and not math.isnan(iv):
            atm_iv_put = iv

    ivs = [v for v in [atm_iv_call, atm_iv_put] if v is not None]
    atm_iv_avg = sum(ivs) / len(ivs) if ivs else None
    if atm_iv_avg is None:
        return

    skew_25d = None
    if puts and atm_iv_avg:
        put_target = spot * 0.95
        nearest_otm = min(puts, key=lambda c: abs(c.strike - put_target))
        put_iv = nearest_otm.implied_volatility
        if put_iv and not math.isnan(put_iv):
            skew_25d = put_iv - atm_iv_avg

    store_iv_snapshot(
        ticker=ticker,
        snapshot_date=date,
        atm_iv_call=atm_iv_call,
        atm_iv_put=atm_iv_put,
        atm_iv_avg=atm_iv_avg,
        realized_vol_30d=None,
        realized_vol_60d=None,
        spot=spot,
        label=BACKFILL_LABEL,
        skew_25d=skew_25d,
    )


def backfill_range(
    tickers: List[str],
    start: str,
    end: str,
    max_dte: int = 60,
    progress_file: Optional[str] = None,
) -> Dict:
    """Backfill multiple tickers across a date range.

    Args:
        tickers: List of underlying symbols.
        start: Start date "YYYY-MM-DD".
        end: End date "YYYY-MM-DD".
        max_dte: Maximum DTE for contract discovery.
        progress_file: Optional JSON file to track/resume progress.

    Returns:
        Summary dict with total counts.
    """
    client = AlpacaOptionsClient()
    dates = _business_days(start, end)

    completed = set()
    if progress_file and os.path.exists(progress_file):
        try:
            with open(progress_file) as f:
                completed = set(json.load(f).get("completed", []))
            logger.info("Resuming: %d dates already completed", len(completed))
        except (json.JSONDecodeError, IOError):
            pass

    total = {
        "tickers": tickers, "start": start, "end": end,
        "dates_total": len(dates), "dates_processed": 0,
        "dates_skipped": 0, "total_contracts": 0,
        "total_iv_solved": 0, "errors": [],
    }

    for date in dates:
        for ticker in tickers:
            key = f"{ticker}:{date}"
            if key in completed:
                total["dates_skipped"] += 1
                continue

            try:
                result = backfill_date(client, ticker, date, max_dte=max_dte)
                total["dates_processed"] += 1
                total["total_contracts"] += result.get("contracts_priced", 0)
                total["total_iv_solved"] += result.get("iv_solved", 0)

                if result.get("error"):
                    total["errors"].append(f"{ticker} {date}: {result['error']}")
                else:
                    completed.add(key)

            except Exception as e:
                total["errors"].append(f"{ticker} {date}: {e}")
                logger.error("Backfill failed for %s %s: %s", ticker, date, e)

        if progress_file:
            try:
                with open(progress_file, "w") as f:
                    json.dump({"completed": sorted(completed)}, f)
            except IOError:
                pass

    return total
