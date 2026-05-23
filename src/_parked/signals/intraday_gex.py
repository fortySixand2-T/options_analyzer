"""
Intraday GEX recomputation for 0 DTE.

Recomputes dealer positioning (F1-F7) from intraday chain snapshots
stored with "intraday_HHMM" labels. Tracks how the gamma flip level
and dealer regime change throughout the trading day.

Uses the existing compute_dealer_data_from_chain() from flashalpha_client.py
— the GEX math is the same whether the chain is from EOD or intraday.

Options Analytics Team — 2026-04
"""

import logging
from typing import List, Optional, Tuple

from scanner.providers.flashalpha_client import DealerData, compute_dealer_data_from_chain

logger = logging.getLogger(__name__)


def compute_intraday_gex(chain_snapshot) -> Optional[DealerData]:
    """Compute dealer positioning from an intraday chain snapshot.

    Parameters
    ----------
    chain_snapshot : ChainSnapshot
        An intraday chain snapshot (typically labeled "intraday_HHMM").

    Returns
    -------
    DealerData or None if computation fails.
    """
    if chain_snapshot is None or not chain_snapshot.contracts:
        logger.warning("No contracts in chain snapshot for GEX computation")
        return None

    try:
        dealer = compute_dealer_data_from_chain(chain_snapshot)
        logger.info(
            "Intraday GEX for %s: net_gex=%.4f, regime=%s, gamma_flip=%.2f",
            chain_snapshot.ticker, dealer.net_gex, dealer.dealer_regime, dealer.gamma_flip,
        )
        return dealer
    except Exception as e:
        logger.error("Intraday GEX computation failed for %s: %s", chain_snapshot.ticker, e)
        return None


def track_gamma_flip_movement(
    snapshots: List[Tuple[str, "ChainSnapshot"]],
) -> List[dict]:
    """Track how the gamma flip level moves throughout the day.

    Parameters
    ----------
    snapshots : list of (label, ChainSnapshot) tuples
        Ordered by time (from get_intraday_snapshots).

    Returns
    -------
    List of dicts with keys: label, time, gamma_flip, net_gex, dealer_regime, spot
    """
    results = []
    for label, chain in snapshots:
        dealer = compute_intraday_gex(chain)
        if dealer is None:
            continue

        # Extract time from label (e.g., "intraday_1030" → "10:30")
        time_str = label.replace("intraday_", "")
        if len(time_str) == 4:
            time_str = f"{time_str[:2]}:{time_str[2:]}"

        results.append({
            "label": label,
            "time": time_str,
            "gamma_flip": dealer.gamma_flip,
            "net_gex": dealer.net_gex,
            "dealer_regime": dealer.dealer_regime,
            "spot": dealer.spot,
            "call_wall": dealer.call_wall,
            "put_wall": dealer.put_wall,
            "max_pain": dealer.max_pain,
            "gamma_flip_distance_pct": round(
                (dealer.spot - dealer.gamma_flip) / dealer.spot * 100, 2
            ) if dealer.spot > 0 else 0.0,
        })

    if results:
        first = results[0]
        last = results[-1]
        flip_move = last["gamma_flip"] - first["gamma_flip"]
        logger.info(
            "Gamma flip movement: %.2f → %.2f ($%.2f) across %d snapshots",
            first["gamma_flip"], last["gamma_flip"], flip_move, len(results),
        )

    return results


def get_latest_intraday_dealer(
    ticker: str,
    date: str,
) -> Optional[DealerData]:
    """Load the most recent intraday chain snapshot and compute GEX.

    Parameters
    ----------
    ticker : str
        Symbol (e.g., "SPY", "^SPX").
    date : str
        Date string (YYYY-MM-DD).

    Returns
    -------
    DealerData or None if no intraday snapshots exist.
    """
    from data.chain_store import get_intraday_snapshots

    snapshots = get_intraday_snapshots(ticker, date)
    if not snapshots:
        logger.info("No intraday snapshots for %s on %s, trying EOD", ticker, date)
        # Fall back to EOD snapshot
        from data.chain_store import get_snapshot
        eod_chain = get_snapshot(ticker, date, label="eod")
        if eod_chain:
            return compute_intraday_gex(eod_chain)
        return None

    # Use the latest snapshot (last in the sorted list)
    latest_label, latest_chain = snapshots[-1]
    logger.info("Using intraday snapshot %s for %s GEX", latest_label, ticker)
    return compute_intraday_gex(latest_chain)
