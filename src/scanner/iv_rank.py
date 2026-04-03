"""
IV rank and percentile engine.

Computes IV rank, IV percentile, and vol regime classification by comparing
the current ATM implied volatility against a rolling window of historical
realized volatility.

Options Analytics Team — 2026-04-02
"""

import logging

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


def compute_iv_metrics(current_iv: float, history: HistoryData) -> dict:
    """Compute IV rank, percentile, and regime using realized vol as proxy.

    Since yfinance does not provide historical IV, we compute 30-day rolling
    realized vol over the past year and compare the chain's current ATM IV
    against that distribution.

    Parameters
    ----------
    current_iv : float
        Current ATM implied volatility (annualized decimal, e.g. 0.30).
    history : HistoryData
        Historical price data with daily returns.

    Returns
    -------
    dict
        Keys: iv_rank, iv_percentile, iv_regime, rv_high, rv_low, rv_mean.
    """
    returns = history.returns

    # Edge case: not enough data for a 30-day rolling window
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
        }

    # 30-day rolling realized vol (annualized)
    window = 30
    rolling_rv = np.array([
        np.std(returns[i:i + window]) * np.sqrt(252)
        for i in range(len(returns) - window + 1)
    ])

    rv_min = float(np.min(rolling_rv))
    rv_max = float(np.max(rolling_rv))
    rv_mean = float(np.mean(rolling_rv))

    # IV rank: where does current_iv sit in [rv_min, rv_max]?
    denom = rv_max - rv_min
    if denom < 1e-10:
        iv_rank = 50.0
    else:
        iv_rank = float(np.clip((current_iv - rv_min) / denom * 100, 0, 100))

    # IV percentile: fraction of rolling windows with rv < current_iv
    iv_percentile = float(np.mean(rolling_rv < current_iv) * 100)

    # Regime classification
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
    }
