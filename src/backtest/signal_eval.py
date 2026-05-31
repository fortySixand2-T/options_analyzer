"""
Directional-signal evaluation — information coefficient (IC).

Separates ALPHA from BETA for the directional strategies (long call/put
spreads). Their P&L can be positive simply because the market drifted up while
they were long delta (beta); the only real edge is whether the entry **bias
signal predicts the forward move**. IC measures exactly that:

    IC = correlation( bias_score(t) , forward_return(t → t+h) )

Positive, significant IC = the signal has directional predictive power (alpha);
IC ≈ 0 = the strategy's P&L is beta/noise and the "edge" is illusory. This tests
the SIGNAL on the underlying, independent of option mechanics — the spreads are
just a way to express it. (Rank/Spearman IC is the quant standard; Pearson is
reported too.)
"""

import logging
from datetime import date, timedelta
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)

# Bias-score buckets (bias_detector scale: >0 bullish, thresholds ±2/±4).
_BUCKETS = [
    ("strong_bear", lambda s: s <= -4),
    ("lean_bear", lambda s: -4 < s <= -2),
    ("neutral", lambda s: -2 < s < 2),
    ("lean_bull", lambda s: 2 <= s < 4),
    ("strong_bull", lambda s: s >= 4),
]


def compute_directional_ic(symbol: str, start: date, end: date,
                           horizons=(3, 5, 10), bias_lookback: int = 30) -> Dict:
    """Information coefficient of the bias signal vs forward underlying returns.

    For each trading day in [start, end] we compute the entry bias score from the
    trailing `bias_lookback` days (point-in-time, no lookahead) and the realized
    `h`-day forward return, then correlate them. Uses yfinance OHLCV for the
    underlying — the period should match the backtest era (e.g. the Dolt window).

    Returns {horizon: {pearson, pearson_p, spearman, spearman_p, n,
                       bucket_mean_fwd_return}} plus {"error": ...} on failure.
    """
    try:
        import yfinance as yf
        from bias_detector import detect_bias
        from scipy.stats import pearsonr, spearmanr
    except Exception as e:               # pragma: no cover
        return {"error": f"deps unavailable: {e}"}

    hist = yf.Ticker(symbol).history(
        start=(start - timedelta(days=bias_lookback + 40)).isoformat(),
        end=end.isoformat(),
    )
    if hist is None or hist.empty or len(hist) < bias_lookback + max(horizons) + 5:
        return {"error": "insufficient history"}

    closes = hist["Close"].to_numpy()
    dates = [d.date() for d in hist.index]

    # Point-in-time bias score per day (only within [start, end]).
    scores, idxs = [], []
    for i in range(bias_lookback, len(hist)):
        if not (start <= dates[i] <= end):
            continue
        try:
            br = detect_bias(hist.iloc[i - bias_lookback:i + 1])
        except Exception:
            continue
        scores.append(br.score)
        idxs.append(i)

    out: Dict = {"symbol": symbol, "window": f"{start}..{end}", "signal_days": len(scores)}
    for h in horizons:
        xs, ys = [], []
        for s, i in zip(scores, idxs):
            if i + h < len(closes) and closes[i] > 0:
                xs.append(s)
                ys.append(closes[i + h] / closes[i] - 1.0)
        if len(xs) < 30 or len(set(xs)) < 3:
            out[h] = {"n": len(xs), "note": "insufficient/degenerate"}
            continue
        xa, ya = np.array(xs, float), np.array(ys, float)
        pr, pp = pearsonr(xa, ya)
        sr, sp = spearmanr(xa, ya)
        buckets = {}
        for name, pred in _BUCKETS:
            vals = [y for x, y in zip(xs, ys) if pred(x)]
            buckets[name] = {"n": len(vals), "mean_fwd_ret_pct": round(float(np.mean(vals)) * 100, 3)} if vals else {"n": 0}
        out[h] = {
            "n": len(xs),
            "pearson": round(float(pr), 4), "pearson_p": round(float(pp), 4),
            "spearman": round(float(sr), 4), "spearman_p": round(float(sp), 4),
            "bucket_mean_fwd_return": buckets,
        }
    return out


def ic_verdict(ic_for_horizon: dict) -> str:
    """Classify a single-horizon IC result.

    'predictive' needs a positive, statistically-significant rank IC; 'noise'
    means no detectable directional edge (→ the directional strategy's P&L is
    beta, not alpha)."""
    if not ic_for_horizon or "spearman" not in ic_for_horizon:
        return "insufficient_sample"
    sr = ic_for_horizon["spearman"]
    sp = ic_for_horizon.get("spearman_p", 1.0)
    if sp < 0.05 and sr > 0.03:
        return "predictive"
    if sp < 0.05 and sr < -0.03:
        return "inverted"      # signal predicts the WRONG direction
    return "noise"
