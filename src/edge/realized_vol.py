"""Realized volatility estimators: Yang-Zhang, Parkinson, Garman-Klass.

Range-based estimators are dramatically more efficient than close-to-close:
    - Yang-Zhang: ~8x (accounts for overnight gaps + drift)
    - Garman-Klass: ~7.4x (uses OHLC, best for continuous markets)
    - Parkinson: ~5.2x (high-low only, ignores gaps)

Using the wrong estimator changes computed VRP by 30%+ (FlashAlpha research).
Yang-Zhang is the default for equity options — unbiased, drift-independent,
and handles opening gaps.

References:
    Yang & Zhang (2000), "Drift-Independent Volatility Estimation"
    Garman & Klass (1980), "On the Estimation of Security Price Volatilities"
    Parkinson (1980), "The Extreme Value Method for Estimating the Variance"
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass
class RealizedVolEstimate:
    """Result of a realized vol computation."""
    method: str
    annualized: float
    daily: float
    window: int
    sample_size: int


def yang_zhang(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 30,
) -> Optional[RealizedVolEstimate]:
    """Yang-Zhang realized volatility estimator.

    Combines overnight (close-to-open), Rogers-Satchell (intraday), and
    close-to-close components. Unbiased regardless of drift or opening gaps.
    ~8x more efficient than close-to-close — a 5-day YZ estimate has roughly
    the precision of a 40-day close-to-close estimate.
    """
    if len(closes) < window + 1:
        return None

    o = opens[-(window + 1):]
    h = highs[-(window + 1):]
    l = lows[-(window + 1):]
    c = closes[-(window + 1):]

    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1))

    # Overnight: log(open / prev_close)
    log_oc = np.log(o[1:] / c[:-1])
    overnight_var = np.var(log_oc, ddof=1)

    # Close-to-close: log(close / prev_close)
    log_cc = np.log(c[1:] / c[:-1])
    close_var = np.var(log_cc, ddof=1)

    # Rogers-Satchell intraday component
    log_ho = np.log(h[1:] / o[1:])
    log_hc = np.log(h[1:] / c[1:])
    log_lo = np.log(l[1:] / o[1:])
    log_lc = np.log(l[1:] / c[1:])
    rs_var = np.mean(log_ho * log_hc + log_lo * log_lc)

    # Yang-Zhang combination
    daily_var = overnight_var + k * close_var + (1 - k) * rs_var

    if daily_var < 0:
        daily_var = max(close_var, 1e-10)

    daily_vol = float(np.sqrt(daily_var))
    annualized = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    return RealizedVolEstimate(
        method="yang_zhang",
        annualized=annualized,
        daily=daily_vol,
        window=window,
        sample_size=n,
    )


def parkinson(
    highs: np.ndarray,
    lows: np.ndarray,
    window: int = 30,
) -> Optional[RealizedVolEstimate]:
    """Parkinson high-low range estimator. ~5.2x more efficient than close-to-close.

    Limitation: ignores overnight gaps, assumes zero drift.
    Best for continuous markets (FX, crypto).
    """
    if len(highs) < window:
        return None

    h = highs[-window:]
    l = lows[-window:]

    log_hl = np.log(h / l)
    daily_var = np.mean(log_hl ** 2) / (4 * np.log(2))
    daily_vol = float(np.sqrt(daily_var))
    annualized = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    return RealizedVolEstimate(
        method="parkinson",
        annualized=annualized,
        daily=daily_vol,
        window=window,
        sample_size=window,
    )


def garman_klass(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 30,
) -> Optional[RealizedVolEstimate]:
    """Garman-Klass OHLC estimator. ~7.4x more efficient than close-to-close.

    Best for continuous markets where open ~ prev close.
    """
    if len(closes) < window:
        return None

    o = opens[-window:]
    h = highs[-window:]
    l = lows[-window:]
    c = closes[-window:]

    log_hl = np.log(h / l)
    log_co = np.log(c / o)

    daily_var = np.mean(0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2)

    if daily_var < 0:
        daily_var = np.mean(0.5 * log_hl ** 2)

    daily_vol = float(np.sqrt(daily_var))
    annualized = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    return RealizedVolEstimate(
        method="garman_klass",
        annualized=annualized,
        daily=daily_vol,
        window=window,
        sample_size=window,
    )


def close_to_close(
    closes: np.ndarray,
    window: int = 30,
) -> Optional[RealizedVolEstimate]:
    """Standard close-to-close realized vol. Baseline comparator."""
    if len(closes) < window + 1:
        return None

    tail = closes[-(window + 1):]
    returns = np.diff(np.log(tail))
    daily_vol = float(np.std(returns, ddof=1))
    annualized = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    return RealizedVolEstimate(
        method="close_to_close",
        annualized=annualized,
        daily=daily_vol,
        window=window,
        sample_size=window,
    )


# Window matching: each DTE bucket uses the realized vol window
# that best matches the option's remaining life.
DTE_TO_RV_WINDOW = {
    (0, 7): 5,
    (7, 14): 10,
    (14, 30): 20,
    (30, 60): 30,
    (60, 90): 45,
    (90, 180): 60,
}


def realized_vol_for_dte(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    dte: int,
) -> Optional[RealizedVolEstimate]:
    """Select the appropriate Yang-Zhang window for a given DTE."""
    window = 30
    for (lo, hi), w in DTE_TO_RV_WINDOW.items():
        if lo <= dte < hi:
            window = w
            break
    else:
        if dte >= 180:
            window = 60

    return yang_zhang(opens, highs, lows, closes, window=window)


def compute_all_estimators(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 30,
) -> dict:
    """Compute all four estimators for comparison/diagnostics."""
    results = {}
    for name, fn in [
        ("yang_zhang", lambda: yang_zhang(opens, highs, lows, closes, window)),
        ("parkinson", lambda: parkinson(highs, lows, window)),
        ("garman_klass", lambda: garman_klass(opens, highs, lows, closes, window)),
        ("close_to_close", lambda: close_to_close(closes, window)),
    ]:
        est = fn()
        if est:
            results[name] = {
                "annualized": round(est.annualized, 4),
                "daily": round(est.daily, 6),
            }
    return results
