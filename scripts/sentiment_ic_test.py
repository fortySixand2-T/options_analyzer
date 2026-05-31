#!/usr/bin/env python3
"""
sentiment_ic_test — Phase 4 IC test for the FinBERT sentiment archive (F-020).

Tests whether the composite sentiment score computed from scored headlines in
`data/sentiment_backtest.db` predicts SPY forward returns at 3/5/10 day
horizons, using the same `signal_eval` IC engine as the Phase-1 signal sweep.

Design rules (per Dispatch_Plan.md Phase 4 + .claude/rules/sentiment.md):
  - ZERO imports from src/sentiment/**. Reads raw scores directly from the
    SQLite DB to stay fully decoupled from the sentiment package.
  - Point-in-time: for each snapshot date t, only headlines with
    published_at <= t (within a rolling lookback window) are used.
  - Price data comes from data/chain_snapshots.db (local, no network) so
    this script runs fully offline.

Usage:
    python3 scripts/sentiment_ic_test.py
    python3 scripts/sentiment_ic_test.py --lookback-days 7 --min-confidence 0.6

Outputs the same graduation table format as signal_ic_sweep.py.
"""

import argparse
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.signal_eval import ic_table, fold_ic_signs, graduate, _sign  # noqa: E402

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_SENTIMENT_DB = os.path.join(
    os.path.dirname(__file__), "..", "data", "sentiment_backtest.db"
)
DEFAULT_PRICE_DB = os.path.join(
    os.path.dirname(__file__), "..", "data", "chain_snapshots.db"
)
WARMUP_DAYS = 7        # days of sentiment history before first signal value
HALFLIFE_HOURS = 96.0  # exponential decay half-life (4 days) — tunable


def _exp_weight(age_hours: float, halflife: float) -> float:
    """Exponential decay weight. age_hours=0 → weight=1; age_hours=halflife → 0.5."""
    if halflife <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_hours / halflife)


def _load_prices(price_db: str, ticker: str = "SPY") -> Dict[date, float]:
    """Load date → spot-price mapping from chain_snapshots.db."""
    conn = sqlite3.connect(price_db)
    rows = conn.execute(
        "SELECT snapshot_date, spot FROM chain_snapshots WHERE ticker = ? ORDER BY snapshot_date",
        (ticker,),
    ).fetchall()
    conn.close()
    prices = {}
    for date_str, spot in rows:
        try:
            prices[date.fromisoformat(date_str)] = float(spot)
        except (ValueError, TypeError):
            pass
    return prices


def _load_scored_headlines(sentiment_db: str, ticker: str = "SPY",
                           min_confidence: float = 0.5,
                           model_version: str = "ProsusAI/finbert") -> List[dict]:
    """Load all FinBERT-scored headlines for `ticker` from sentiment_backtest.db.

    Returns list of dicts with keys: published_at (datetime), positive, negative,
    neutral, confidence. Does NOT import from src/sentiment — reads raw SQL only.
    """
    conn = sqlite3.connect(sentiment_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT h.published_at, s.positive, s.negative, s.neutral, s.confidence
           FROM headlines h
           JOIN scored_headlines s ON s.headline_id = h.id
           WHERE h.ticker = ?
             AND s.model_version = ?
             AND s.confidence >= ?
           ORDER BY h.published_at""",
        (ticker, model_version, min_confidence),
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        try:
            pub_str = row["published_at"]
            # Parse ISO string — may or may not have timezone suffix.
            pub_dt = datetime.fromisoformat(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            result.append({
                "published_at": pub_dt,
                "positive": float(row["positive"]),
                "negative": float(row["negative"]),
                "neutral": float(row["neutral"]),
                "confidence": float(row["confidence"]),
            })
        except (ValueError, TypeError):
            pass
    return result


def _compute_daily_signal(
    snapshot_dates: List[date],
    scored_headlines: List[dict],
    lookback_days: int = 7,
    halflife_hours: float = HALFLIFE_HOURS,
    min_headlines: int = 3,
) -> np.ndarray:
    """For each snapshot date t, compute a weighted sentiment score from all
    scored headlines in the window (t - lookback_days, t].

    Point-in-time: only headlines with published_at.date() <= t are used.
    Returns a float array aligned to snapshot_dates; NaN where insufficient data.
    """
    signals = np.full(len(snapshot_dates), np.nan)

    for i, snap_date in enumerate(snapshot_dates):
        window_start = datetime(snap_date.year, snap_date.month, snap_date.day,
                                tzinfo=timezone.utc) - timedelta(days=lookback_days)
        # End-of-day on snap_date: midnight UTC of the next day.
        window_end = datetime(snap_date.year, snap_date.month, snap_date.day,
                              23, 59, 59, tzinfo=timezone.utc)

        # Filter headlines strictly in the window (point-in-time).
        in_window = [
            h for h in scored_headlines
            if window_start <= h["published_at"] <= window_end
        ]

        if len(in_window) < min_headlines:
            continue  # leave as NaN

        # Compute exponentially-decayed weighted mean of (positive - negative).
        ref_time = window_end
        total_weight = 0.0
        weighted_sum = 0.0

        for h in in_window:
            age_hours = (ref_time - h["published_at"]).total_seconds() / 3600.0
            w = _exp_weight(age_hours, halflife_hours)
            signed = h["positive"] - h["negative"]   # in [-1, +1]; positive = bullish
            weighted_sum += signed * w
            total_weight += w

        if total_weight > 0:
            signals[i] = weighted_sum / total_weight

    return signals


def run_sentiment_ic_test(
    sentiment_db: str = DEFAULT_SENTIMENT_DB,
    price_db: str = DEFAULT_PRICE_DB,
    ticker: str = "SPY",
    lookback_days: int = 7,
    min_confidence: float = 0.5,
    horizons: tuple = (3, 5, 10),
) -> dict:
    """Run the full IC test for the sentiment signal on `ticker`.

    Returns a report dict in the same shape as run_sweep() in signal_ic_sweep.py
    so the graduation logic is identical.
    """
    # 1. Load prices (our forward-return base).
    prices_map = _load_prices(price_db, ticker)
    if not prices_map:
        return {"error": f"No price data for {ticker} in {price_db}"}

    # 2. Load scored headlines.
    headlines = _load_scored_headlines(sentiment_db, ticker, min_confidence)
    if not headlines:
        return {"error": f"No scored headlines for {ticker} in {sentiment_db}"}

    # 3. Restrict to dates where both prices AND headlines exist.
    min_headline_date = min(h["published_at"].date() for h in headlines)
    max_headline_date = max(h["published_at"].date() for h in headlines)
    snapshot_dates = sorted(
        d for d in prices_map
        if min_headline_date + timedelta(days=WARMUP_DAYS) <= d <= max_headline_date
    )
    if len(snapshot_dates) < 30:
        return {"error": f"Insufficient overlapping date range (n={len(snapshot_dates)})"}

    closes = np.array([prices_map[d] for d in snapshot_dates], dtype=float)

    # 4. Compute daily sentiment signal (point-in-time).
    sig = _compute_daily_signal(snapshot_dates, headlines, lookback_days)

    # 5. Run IC engine (identical to signal_ic_sweep logic).
    per_horizon = ic_table(sig, closes, horizons)

    fold_signs = {h: fold_ic_signs(sig, closes, h, n_folds=5) for h in horizons}

    # Regime split: use VIX-level proxy (sig volatility as regime stand-in).
    # Because this test is offline-only we don't have live VIX; instead we use
    # the trailing 63-day rolling std of closes as a vol-regime proxy.
    close_vol = np.full(len(closes), np.nan)
    for i in range(64, len(closes)):
        daily_returns = closes[i - 63:i] / closes[i - 64:i - 1] - 1
        close_vol[i] = float(np.std(daily_returns))

    regime_by_h: dict = {}
    for h in horizons:
        fwd = np.full(len(closes), np.nan)
        for j in range(len(closes) - h):
            if closes[j] > 0:
                fwd[j] = closes[j + h] / closes[j] - 1.0
        mask = ~np.isnan(sig) & ~np.isnan(fwd) & ~np.isnan(close_vol)
        if mask.sum() >= 40:
            med_vol = float(np.nanmedian(close_vol[mask]))
            reg = {}
            for nm, m in (("low_vol", close_vol <= med_vol), ("high_vol", close_vol > med_vol)):
                combined = mask & m
                xs, ys = sig[combined], fwd[combined]
                if len(xs) >= 15:
                    from scipy.stats import spearmanr
                    sr, sp = spearmanr(xs, ys)
                    reg[nm] = {"spearman": round(float(sr), 4), "spearman_p": round(float(sp), 4),
                               "n": int(len(xs)), "sign": _sign(float(sr))}
            if reg:
                regime_by_h[h] = reg

    verdict = graduate(per_horizon, fold_signs, regime_by_h)

    return {
        "ticker": ticker,
        "n_headlines": len(headlines),
        "n_dates": len(snapshot_dates),
        "date_range": f"{snapshot_dates[0]} → {snapshot_dates[-1]}",
        "lookback_days": lookback_days,
        "min_confidence": min_confidence,
        "pooled": per_horizon,
        "regimes": regime_by_h,
        "verdict": verdict,
    }


def main():
    ap = argparse.ArgumentParser(description="Phase 4 sentiment IC test")
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--lookback-days", type=int, default=7,
                    help="Headline lookback window in days (default 7)")
    ap.add_argument("--min-confidence", type=float, default=0.5,
                    help="Minimum FinBERT confidence to include (default 0.5)")
    ap.add_argument("--sentiment-db", default=DEFAULT_SENTIMENT_DB)
    ap.add_argument("--price-db", default=DEFAULT_PRICE_DB)
    args = ap.parse_args()

    print(f"\nSentiment IC test — {args.ticker}  lookback={args.lookback_days}d  "
          f"min_conf={args.min_confidence}\n" + "=" * 72)

    res = run_sentiment_ic_test(
        sentiment_db=args.sentiment_db,
        price_db=args.price_db,
        ticker=args.ticker,
        lookback_days=args.lookback_days,
        min_confidence=args.min_confidence,
    )

    if "error" in res:
        print(f"ERROR: {res['error']}")
        return

    print(f"Headlines: {res['n_headlines']:,}  |  "
          f"Dates: {res['n_dates']}  |  Range: {res['date_range']}")
    print("\nIC by horizon:")
    for h, d in res["pooled"].items():
        if "spearman" in d:
            print(f"  {h:>2}d : IC={d['spearman']:+.4f}  p={d['spearman_p']:.4f}  n={d['n']}")
        else:
            print(f"  {h:>2}d : {d.get('note', 'n/a')}  n={d.get('n', 0)}")

    if res["regimes"]:
        print("\nRegime split (low vs high trailing vol):")
        for h, reg in res["regimes"].items():
            lo = reg.get("low_vol", {})
            hi = reg.get("high_vol", {})
            print(f"  {h:>2}d : low-vol IC={lo.get('spearman')} (n={lo.get('n')})  "
                  f"high-vol IC={hi.get('spearman')} (n={hi.get('n')})")

    v = res["verdict"]
    flag = "✅ GRADUATES" if v.get("graduates") else "❌ no edge"
    print(f"\nVerdict: {flag}")
    print(f"  best horizon : {v.get('best_horizon')}d")
    print(f"  IC           : {v.get('spearman')}")
    print(f"  direction    : {v.get('direction')}")
    print(f"  reason       : {v.get('reason')}")


if __name__ == "__main__":
    main()
