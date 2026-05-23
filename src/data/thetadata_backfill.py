"""
ThetaData historical options backfill pipeline.

Fetches EOD option chains with greeks from ThetaData's Theta Terminal
and stores them in chain_snapshots.db via chain_store.

Unlike the Alpaca pipeline, ThetaData returns the full chain (all strikes,
all expiries, both calls and puts) in a single request per ticker per date.
No contract discovery, no IV solving, no bid/ask estimation needed.

Supports EOD granularity. Intraday is a future add-on.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from data.thetadata_client import ThetaDataClient
from data.chain_store import store_snapshot_with_greeks, store_iv_snapshot
from scanner.providers.base import ChainSnapshot, OptionContract

logger = logging.getLogger(__name__)

THETADATA_LABEL = "thetadata"


def backfill_date(
    client: ThetaDataClient,
    ticker: str,
    date: str,
    max_dte: int = 14,
    granularity: str = "eod",
) -> Dict:
    """Backfill one ticker for one date from ThetaData.

    Args:
        client: ThetaDataClient instance.
        ticker: Underlying symbol (e.g. "SPY").
        date: Date string "YYYY-MM-DD".
        max_dte: Maximum DTE filter.
        granularity: "eod" (only supported value for now).

    Returns:
        Summary dict: {ticker, date, spot, contracts, greeks_stored, stored, error}
    """
    if granularity != "eod":
        raise NotImplementedError(f"Granularity '{granularity}' not yet supported")

    result = {
        "ticker": ticker,
        "date": date,
        "spot": None,
        "contracts": 0,
        "greeks_stored": 0,
        "stored": False,
        "error": None,
    }

    rows = client.get_options_greeks_eod(ticker, date, max_dte=max_dte)
    if not rows:
        result["error"] = "No option data returned"
        return result

    spot = rows[0].get("underlying_price", 0) if rows else 0
    if spot <= 0:
        spot_from_api = client.get_spot_eod(ticker, date)
        if spot_from_api:
            spot = spot_from_api
        else:
            result["error"] = "No spot price available"
            return result
    result["spot"] = spot

    contracts = []
    greeks_map = {}
    expiries_set = set()

    for row in rows:
        if row["bid"] <= 0 and row["ask"] <= 0 and row["mid"] <= 0:
            continue

        contract = OptionContract(
            ticker=ticker,
            strike=row["strike"],
            expiry=row["expiry"],
            option_type=row["option_type"],
            bid=row["bid"],
            ask=row["ask"],
            mid=row["mid"],
            last=row["last"],
            volume=row["volume"],
            open_interest=row["open_interest"],
            implied_volatility=row["implied_volatility"],
        )
        contracts.append(contract)
        expiries_set.add(row["expiry"])

        key = (round(row["strike"], 2), row["expiry"], row["option_type"])
        greeks = {}
        for g in ("delta", "gamma", "theta", "vega", "rho"):
            if row.get(g) is not None:
                greeks[g] = row[g]
        if greeks:
            greeks_map[key] = greeks

    if not contracts:
        result["error"] = "No valid contracts after filtering"
        return result

    chain = ChainSnapshot(
        ticker=ticker,
        spot=spot,
        fetched_at=datetime.strptime(date, "%Y-%m-%d"),
        contracts=contracts,
        expiries=sorted(expiries_set),
    )

    try:
        store_snapshot_with_greeks(chain, greeks_map, label=THETADATA_LABEL)
        result["stored"] = True
    except Exception as e:
        result["error"] = f"Storage failed: {e}"
        return result

    result["contracts"] = len(contracts)
    result["greeks_stored"] = len(greeks_map)

    _store_iv_summary(ticker, date, contracts, spot)

    return result


def backfill_range(
    tickers: List[str],
    start: str,
    end: str,
    max_dte: int = 14,
    granularity: str = "eod",
    progress_file: Optional[str] = None,
) -> Dict:
    """Backfill multiple tickers across a date range.

    Same interface as backfill_pipeline.backfill_range.
    Progress file uses same JSON format for resume support.
    """
    client = ThetaDataClient()

    if not client.health_check():
        logger.error(
            "Theta Terminal not reachable at %s. "
            "Start it on the host: java -jar ThetaTerminal.jar",
            client.base_url,
        )
        return {"error": "Theta Terminal not reachable", "tickers": tickers}

    dates = _business_days(start, end)

    completed = set()
    if progress_file and os.path.exists(progress_file):
        try:
            with open(progress_file) as f:
                completed = set(json.load(f).get("completed", []))
            logger.info("Resuming: %d ticker-dates already completed", len(completed))
        except (json.JSONDecodeError, IOError):
            pass

    total = {
        "tickers": tickers, "start": start, "end": end,
        "dates_total": len(dates), "dates_processed": 0,
        "dates_skipped": 0, "total_contracts": 0,
        "total_greeks": 0, "errors": [],
    }

    for date in dates:
        for ticker in tickers:
            key = f"{ticker}:{date}"
            if key in completed:
                total["dates_skipped"] += 1
                continue

            try:
                result = backfill_date(
                    client, ticker, date,
                    max_dte=max_dte, granularity=granularity,
                )
                total["dates_processed"] += 1
                total["total_contracts"] += result.get("contracts", 0)
                total["total_greeks"] += result.get("greeks_stored", 0)

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


def _store_iv_summary(ticker: str, date: str, contracts: list, spot: float):
    """Compute and store ATM IV summary from ThetaData contracts."""
    atm_iv_call = None
    atm_iv_put = None
    best_call_dist = float("inf")
    best_put_dist = float("inf")

    for c in contracts:
        dist = abs(c.strike - spot)
        if c.option_type == "call" and dist < best_call_dist and c.implied_volatility > 0:
            best_call_dist = dist
            atm_iv_call = c.implied_volatility
        elif c.option_type == "put" and dist < best_put_dist and c.implied_volatility > 0:
            best_put_dist = dist
            atm_iv_put = c.implied_volatility

    if atm_iv_call or atm_iv_put:
        atm_iv_avg = None
        if atm_iv_call and atm_iv_put:
            atm_iv_avg = (atm_iv_call + atm_iv_put) / 2
        elif atm_iv_call:
            atm_iv_avg = atm_iv_call
        else:
            atm_iv_avg = atm_iv_put

        try:
            store_iv_snapshot(
                ticker=ticker,
                snapshot_date=date,
                atm_iv_call=atm_iv_call,
                atm_iv_put=atm_iv_put,
                atm_iv_avg=atm_iv_avg,
                realized_vol_30d=None,
                realized_vol_60d=None,
                spot=spot,
                label=THETADATA_LABEL,
            )
        except Exception as e:
            logger.warning("Failed to store IV summary for %s %s: %s", ticker, date, e)


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
