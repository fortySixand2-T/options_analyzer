"""
IV rank and percentile engine.

Computes IV rank, IV percentile, and vol regime classification by comparing
the current ATM implied volatility against a rolling window of historical
realized volatility.

Supports per-ticker-class thresholds so individual stocks can reach HIGH_IV
even when their absolute IV rank is lower than SPY/ETF thresholds.

Options Analytics Team — 2026-04-02
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from .providers.base import HistoryData

logger = logging.getLogger(__name__)

# Per-ticker-class regime thresholds (iv_rank cutoffs)
TICKER_CLASSES = {
    "broad_etf": ["SPY", "DIA", "XSP"],
    "tech_etf": ["QQQ", "XLK"],
    "small_cap_etf": ["IWM"],
    "sector_etf": ["XLF", "XLE", "GLD", "TLT"],
    "mega_cap": ["AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "BRK.B", "UNH", "JNJ", "V"],
    "high_vol": ["TSLA", "NFLX", "AMD", "NVDA", "COIN", "MARA", "RIOT", "GME", "AMC"],
}

_CLASS_THRESHOLDS = {
    "broad_etf":     [(50, "HIGH_IV"), (30, "MODERATE_IV"), (0, "LOW_IV")],
    "tech_etf":      [(60, "HIGH_IV"), (38, "MODERATE_IV"), (0, "LOW_IV")],
    "small_cap_etf": [(55, "HIGH_IV"), (33, "MODERATE_IV"), (0, "LOW_IV")],
    "sector_etf":    [(50, "HIGH_IV"), (30, "MODERATE_IV"), (0, "LOW_IV")],
    "mega_cap":      [(40, "HIGH_IV"), (25, "MODERATE_IV"), (0, "LOW_IV")],
    "high_vol":      [(35, "HIGH_IV"), (20, "MODERATE_IV"), (0, "LOW_IV")],
    "default":       [(50, "HIGH_IV"), (30, "MODERATE_IV"), (0, "LOW_IV")],
}

# Legacy alias for existing code
_REGIME_THRESHOLDS = _CLASS_THRESHOLDS["default"]


def get_ticker_class(ticker: str) -> str:
    ticker = ticker.upper()
    for cls, tickers in TICKER_CLASSES.items():
        if ticker in tickers:
            return cls
    return "default"


def get_regime_thresholds(ticker: str) -> List[tuple]:
    return _CLASS_THRESHOLDS[get_ticker_class(ticker)]


def compute_iv_metrics(
    current_iv: float,
    history: HistoryData,
    iv_history_rows: Optional[List[Dict]] = None,
    ticker: Optional[str] = None,
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
    _ticker = ticker or getattr(history, 'ticker', None) or ''
    thresholds = get_regime_thresholds(_ticker)

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
            for threshold, label in thresholds:
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
            'iv_regime': 'MODERATE_IV',
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
    for threshold, label in thresholds:
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


def compute_historical_iv_rank(
    ticker: str,
    current_date: str,
    current_atm_iv: float,
    label: str = "dolt",
    lookback_days: int = 252,
) -> dict:
    """Compute IV rank from stored chain ATM IVs (self-referencing).

    Instead of relying on yfinance realized vol, this looks up the ticker's
    own historical ATM IV from chain_snapshots.db and ranks the current IV
    against that distribution. This is essential for backtesting individual
    stocks where yfinance data may be unavailable or from the wrong time period.
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "chain_snapshots.db"
    if not db_path.exists():
        return None

    thresholds = get_regime_thresholds(ticker)

    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT cs.snapshot_date, AVG(cc.implied_volatility) as atm_iv
            FROM chain_snapshots cs
            JOIN chain_contracts cc ON cc.snapshot_id = cs.id
            WHERE cs.ticker = ? AND cs.label = ?
              AND cs.snapshot_date < ?
              AND cc.option_type = 'call'
              AND cc.implied_volatility > 0.01
              AND cc.implied_volatility < 3.0
              AND ABS(cc.strike - cs.spot) / cs.spot < 0.03
            GROUP BY cs.snapshot_date
            ORDER BY cs.snapshot_date DESC
            LIMIT ?
        """, (ticker, label, current_date, lookback_days)).fetchall()
        conn.close()

        if len(rows) < 20:
            return None

        historical_ivs = [r["atm_iv"] for r in rows if r["atm_iv"] is not None]
        if len(historical_ivs) < 20:
            return None

        iv_min = min(historical_ivs)
        iv_max = max(historical_ivs)
        denom = iv_max - iv_min

        if denom < 1e-10:
            iv_rank = 50.0
        else:
            iv_rank = max(0.0, min(100.0, (current_atm_iv - iv_min) / denom * 100))

        iv_percentile = sum(1 for iv in historical_ivs if iv < current_atm_iv) / len(historical_ivs) * 100

        iv_regime = "LOW_IV"
        for threshold, regime_label in thresholds:
            if iv_rank >= threshold:
                iv_regime = regime_label
                break

        return {
            "iv_rank": round(iv_rank, 2),
            "iv_percentile": round(iv_percentile, 2),
            "iv_regime": iv_regime,
            "iv_source": "historical_chain",
            "lookback_count": len(historical_ivs),
        }
    except Exception as e:
        logger.warning("Historical IV rank failed for %s: %s", ticker, e)
        return None
