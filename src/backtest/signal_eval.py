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


# ── Generic IC engine (F-018) ────────────────────────────────────────────────
#
# The functions above evaluate the legacy bias_detector against forward returns.
# The engine below generalises that to ANY point-in-time signal series (see
# signal_lib) and adds the rigour a desk would demand before allocating capital:
# per-horizon rank IC + significance, sign-stability across contiguous time
# folds, and sign-stability across volatility regimes. A signal only
# "graduates" to the (scarce, expensive) option backtest if it clears all three
# — which is the whole point of researching signals on cheap underlying data
# first (F-018). These are pure functions over aligned pandas Series so they are
# unit-testable without any network access.

# Strict graduation thresholds (the "strict & honest" gate, F-018). Equity
# return predictability is weak — a sustained rank IC of 0.03 is already real.
_MIN_ABS_IC = 0.03
_IC_ALPHA = 0.05


def forward_returns(closes, h: int):
    """h-day forward simple return aligned to each day (NaN in the last h)."""
    import numpy as np
    c = np.asarray(closes, dtype=float)
    fwd = np.full(len(c), np.nan)
    for i in range(len(c) - h):
        if c[i] > 0:
            fwd[i] = c[i + h] / c[i] - 1.0
    return fwd


def ic_at_horizon(signal, closes, h: int, min_n: int = 30) -> dict:
    """Spearman (rank) + Pearson IC of `signal` vs the h-day forward return.

    `signal` and `closes` must be aligned, same-length, same-index arrays. Days
    where either the signal or the forward return is NaN are dropped. Returns
    n, both correlations and their p-values; degenerate/under-sampled cases are
    reported honestly rather than guessed.
    """
    import numpy as np
    from scipy.stats import pearsonr, spearmanr

    s = np.asarray(signal, dtype=float)
    fwd = forward_returns(closes, h)
    mask = ~np.isnan(s) & ~np.isnan(fwd)
    xs, ys = s[mask], fwd[mask]
    if len(xs) < min_n or len(set(xs.tolist())) < 3:
        return {"n": int(len(xs)), "note": "insufficient/degenerate"}
    pr, pp = pearsonr(xs, ys)
    sr, sp = spearmanr(xs, ys)
    return {
        "n": int(len(xs)),
        "pearson": round(float(pr), 4), "pearson_p": round(float(pp), 4),
        "spearman": round(float(sr), 4), "spearman_p": round(float(sp), 4),
    }


def ic_table(signal, closes, horizons=(3, 5, 10)) -> dict:
    """IC at each horizon → {h: ic_at_horizon(...)}."""
    return {h: ic_at_horizon(signal, closes, h) for h in horizons}


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def fold_ic_signs(signal, closes, h: int, n_folds: int = 3) -> list:
    """Sign of the Spearman IC within each contiguous time fold.

    A real edge keeps its sign across sub-periods; one that flips is regime-fit.
    Folds with too few usable points contribute a 0 (neither sign).
    """
    import numpy as np
    s = np.asarray(signal, dtype=float)
    n = len(s)
    step = max(n // n_folds, 1)
    signs = []
    for i in range(n_folds):
        lo = i * step
        hi = n if i == n_folds - 1 else (i + 1) * step
        r = ic_at_horizon(s[lo:hi], np.asarray(closes, float)[lo:hi], h, min_n=15)
        signs.append(_sign(r.get("spearman", 0.0)) if "spearman" in r else 0)
    return signs


def regime_ic_signs(signal, closes, regime_series, h: int) -> dict:
    """Spearman IC sign in the low- vs high-`regime_series` halves (median split).

    `regime_series` is typically VIX (or its level): we want to know whether the
    signal works in both calm and stressed markets, because most of these
    signals flip sign across regimes (F-018). Returns the IC of each half.
    """
    import numpy as np
    s = np.asarray(signal, dtype=float)
    c = np.asarray(closes, dtype=float)
    reg = np.asarray(regime_series, dtype=float)
    valid = ~np.isnan(reg)
    if valid.sum() < 40:
        return {"note": "insufficient regime data"}
    med = np.nanmedian(reg[valid])
    out = {}
    for name, mask in (("low", reg <= med), ("high", reg > med)):
        r = ic_at_horizon(s[mask], c[mask], h, min_n=15)
        out[name] = {"spearman": r.get("spearman"), "spearman_p": r.get("spearman_p"),
                     "n": r.get("n"), "sign": _sign(r.get("spearman", 0.0)) if "spearman" in r else 0}
    return out


def graduate(table: dict, fold_signs_by_h: dict, regime_by_h: dict,
             min_abs_ic: float = _MIN_ABS_IC, alpha: float = _IC_ALPHA) -> dict:
    """Strict-and-honest graduation gate (F-018).

    A signal graduates only if, at its best (largest |IC|) horizon, it is:
      (1) significant         — spearman_p < alpha,
      (2) economically real   — |spearman| >= min_abs_ic,
      (3) sign-stable in time — every evaluated time fold shares the IC sign,
      (4) sign-stable across regimes — calm and stressed halves share the sign.
    Anything else is 'no_edge' (with the reason), so we never dignify beta or
    noise as alpha. A consistently NEGATIVE IC still graduates (use −signal) and
    is reported with direction='inverted'.
    """
    # Pick the horizon with the largest |spearman| among scored horizons.
    scored = {h: r for h, r in table.items() if "spearman" in r}
    if not scored:
        return {"graduates": False, "reason": "insufficient_sample"}
    best_h = max(scored, key=lambda h: abs(scored[h]["spearman"]))
    r = scored[best_h]
    sr, sp = r["spearman"], r["spearman_p"]

    reasons = []
    if sp >= alpha:
        reasons.append(f"not significant (p={sp})")
    if abs(sr) < min_abs_ic:
        reasons.append(f"|IC|={abs(sr):.3f} < {min_abs_ic}")

    fsigns = [s for s in fold_signs_by_h.get(best_h, []) if s != 0]
    sign = _sign(sr)
    if fsigns and not all(s == sign for s in fsigns):
        reasons.append(f"time-unstable (fold signs {fold_signs_by_h.get(best_h)})")

    reg = regime_by_h.get(best_h, {})
    reg_signs = [reg[k]["sign"] for k in ("low", "high")
                 if isinstance(reg.get(k), dict) and reg[k].get("sign", 0) != 0]
    if len(reg_signs) == 2 and reg_signs[0] != reg_signs[1]:
        reasons.append("regime-unstable (calm/stress IC signs differ)")

    return {
        "graduates": not reasons,
        "best_horizon": best_h,
        "spearman": sr, "spearman_p": sp,
        "direction": "bullish" if sign > 0 else ("inverted" if sign < 0 else "flat"),
        "reason": "; ".join(reasons) if reasons else "passes all gates",
    }


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
