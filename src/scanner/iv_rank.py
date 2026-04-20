"""
IV rank and percentile engine.

Computes IV rank, IV percentile, and vol regime classification by comparing
the current ATM implied volatility against a rolling window of historical
realized volatility.

Options Analytics Team — 2026-04-02
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from .providers.base import HistoryData

logger = logging.getLogger(__name__)

# Regime thresholds (applied to iv_rank)
_REGIME_THRESHOLDS = [
    (80, 'HIGH'),
    (60, 'ELEVATED'),
    (25, 'NORMAL'),
    (0,  'LOW'),
]


def compute_iv_metrics(
    current_iv: float,
    history: HistoryData,
    iv_history_rows: Optional[List[Dict]] = None,
) -> dict:
    """Compute IV rank, percentile, and regime.

    When *iv_history_rows* contains ≥30 days of actual ATM IV snapshots the
    rank/percentile are computed from real implied-vol history.  Otherwise
    falls back to the realized-vol proxy (original behaviour).

    Parameters
    ----------
    current_iv : float
        Current ATM implied volatility (annualized decimal, e.g. 0.30).
    history : HistoryData
        Historical price data with daily returns (used for RV fallback).
    iv_history_rows : list[dict] | None
        Rows from the ``iv_history`` table, each containing at least
        ``atm_iv_avg``.  When provided and length ≥ 30 the real-IV path
        is used.

    Returns
    -------
    dict
        Keys: iv_rank, iv_percentile, iv_regime, rv_high, rv_low, rv_mean,
        iv_source ('real' | 'proxy').
    """

    # ── Real IV history path ────────────────────────────────────────
    if iv_history_rows and len(iv_history_rows) >= 30:
        historical_ivs = [r["atm_iv_avg"] for r in iv_history_rows if r.get("atm_iv_avg") is not None]
        if len(historical_ivs) >= 30:
            iv_min = min(historical_ivs)
            iv_max = max(historical_ivs)
            denom = iv_max - iv_min
            if denom < 1e-10:
                iv_rank = 50.0
            else:
                iv_rank = max(0.0, min(100.0, (current_iv - iv_min) / denom * 100))
            iv_percentile = sum(1 for iv in historical_ivs if iv < current_iv) / len(historical_ivs) * 100

            iv_regime = 'LOW'
            for threshold, label in _REGIME_THRESHOLDS:
                if iv_rank >= threshold:
                    iv_regime = label
                    break

            return {
                'iv_rank': round(iv_rank, 2),
                'iv_percentile': round(iv_percentile, 2),
                'iv_regime': iv_regime,
                'rv_high': round(iv_max, 6),
                'rv_low': round(iv_min, 6),
                'rv_mean': round(float(np.mean(historical_ivs)), 6),
                'iv_source': 'real',
            }

    # ── Realized-vol proxy (fallback) ──────────────────────────────
    returns = history.returns

    if len(returns) < 30:
        logger.warning(
            "Only %d daily returns for %s (need >=30). "
            "Returning default IV metrics.",
            len(returns), history.ticker,
        )
        return {
            'iv_rank': 50.0,
            'iv_percentile': 50.0,
            'iv_regime': 'NORMAL',
            'rv_high': float('nan'),
            'rv_low': float('nan'),
            'rv_mean': float('nan'),
            'iv_source': 'proxy',
        }

    window = 30
    rolling_rv = np.array([
        np.std(returns[i:i + window]) * np.sqrt(252)
        for i in range(len(returns) - window + 1)
    ])

    rv_min = float(np.min(rolling_rv))
    rv_max = float(np.max(rolling_rv))
    rv_mean = float(np.mean(rolling_rv))

    denom = rv_max - rv_min
    if denom < 1e-10:
        iv_rank = 50.0
    else:
        iv_rank = float(np.clip((current_iv - rv_min) / denom * 100, 0, 100))

    iv_percentile = float(np.mean(rolling_rv < current_iv) * 100)

    iv_regime = 'LOW'
    for threshold, label in _REGIME_THRESHOLDS:
        if iv_rank >= threshold:
            iv_regime = label
            break

    return {
        'iv_rank': round(iv_rank, 2),
        'iv_percentile': round(iv_percentile, 2),
        'iv_regime': iv_regime,
        'rv_high': round(rv_max, 6),
        'rv_low': round(rv_min, 6),
        'rv_mean': round(rv_mean, 6),
        'iv_source': 'proxy',
    }
