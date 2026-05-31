#!/usr/bin/env python3
"""
conditioned_signal_test — validate the F-018 conditioned signal (iteration 2).

The F-018 sweep found no UNCONDITIONAL edge but a strong CONDITIONAL one:
medium-horizon reversal that works in calm vol regimes (ts_momentum low-VIX 10d
IC = −0.107, p<0.001). This script makes that lead a single, tradeable,
point-in-time signal (signal_lib.conditioned_reversal) and re-runs it through
the SAME strict graduation gate (signal_eval.graduate) — significant, |IC|≥0.03,
sign-stable across time folds and symbols. The regime split is skipped because
the signal is single-regime by construction.

It first prints VIX/VIX3M reliability diagnostics (the gate's data dependency),
then evaluates two point-in-time calm gates so we learn which reproduces the
edge rather than assuming: 'contango' (VIX<VIX3M) and 'vix_pct' (VIX below its
trailing median). Underlying + VIX from yfinance.

    python3 scripts/conditioned_signal_test.py \
        --symbols SPY,QQQ,AAPL,NFLX --start 2020-01-01 --end 2024-12-31
"""

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.signal_lib import conditioned_reversal  # noqa: E402
from backtest.signal_eval import (  # noqa: E402
    ic_at_horizon, fold_ic_signs, graduate, _sign,
)

WARMUP_DAYS = 200  # 63d momentum + 252d trailing median gate need a long buffer


def _fetch(symbol, start, end):
    """Daily OHLCV from yfinance with a warmup buffer before `start`."""
    import yfinance as yf
    df = yf.Ticker(symbol).history(
        start=(start - timedelta(days=WARMUP_DAYS + 200)).isoformat(),
        end=(end + timedelta(days=2)).isoformat(),
        auto_adjust=True,
    )
    if df is None or df.empty:
        return None
    df.index = [d.date() if hasattr(d, "date") else d for d in df.index]
    return df


def _corr(xs, ys):
    from scipy.stats import pearsonr, spearmanr
    if len(xs) < 30 or len(set(np.asarray(xs).tolist())) < 3:
        return {"n": int(len(xs)), "note": "insufficient/degenerate"}
    pr, pp = pearsonr(xs, ys)
    sr, sp = spearmanr(xs, ys)
    return {"n": int(len(xs)),
            "pearson": round(float(pr), 4), "pearson_p": round(float(pp), 4),
            "spearman": round(float(sr), 4), "spearman_p": round(float(sp), 4)}


def _forward_ret(closes, h):
    c = np.asarray(closes, float)
    fwd = np.full(len(c), np.nan)
    for i in range(len(c) - h):
        if c[i] > 0:
            fwd[i] = c[i + h] / c[i] - 1.0
    return fwd


def _vix_diagnostics(vix_df, vix3m_df, start, end):
    """Honest data-quality report for the VIX series the gate depends on."""
    print("VIX data reliability (yfinance):")
    for name, df in (("^VIX", vix_df), ("^VIX3M", vix3m_df)):
        if df is None or df.empty:
            print(f"  {name}: MISSING")
            continue
        in_win = [d for d in df.index if start <= d <= end]
        closes = df.loc[[d for d in df.index if start <= d <= end], "Close"]
        nans = int(closes.isna().sum()) if hasattr(closes, "isna") else 0
        # Largest calendar gap between consecutive trading days in-window.
        gaps = [(in_win[i] - in_win[i - 1]).days for i in range(1, len(in_win))]
        print(f"  {name}: {len(in_win)} trading days {in_win[0]}..{in_win[-1]}, "
              f"NaN={nans}, max gap={max(gaps) if gaps else 0}d, "
              f"range=[{closes.min():.1f}, {closes.max():.1f}]")
    # How often is the market calm under each gate (sanity on gate balance)?
    if vix_df is not None and vix3m_df is not None:
        import pandas as pd
        v = pd.Series(list(vix_df["Close"]), index=list(vix_df.index))
        v3 = pd.Series(list(vix3m_df["Close"]), index=list(vix3m_df.index))
        wd = [d for d in v.index if start <= d <= end]
        contango = (v.reindex(wd) < v3.reindex(wd)).mean()
        print(f"  contango fraction (calm days, 2020-2024): {contango:.0%}")
    print()


def evaluate(symbols, start, end, gate, aux, frames, horizons=(3, 5, 10)):
    """Pool the conditioned signal across symbols and run the strict gate."""
    pooled = {h: {"sig": [], "fwd": []} for h in horizons}
    fold_signs = {h: [] for h in horizons}
    per_symbol = {}

    for sym, df in frames.items():
        sig = conditioned_reversal(df, aux, gate=gate).reindex(df.index)
        in_win = [start <= d <= end for d in df.index]
        sig_a = np.array([v for v, k in zip(sig.to_numpy(), in_win) if k], float)
        close_a = np.array([v for v, k in zip(df["Close"].to_numpy(), in_win) if k], float)
        per_symbol[sym] = {h: ic_at_horizon(sig_a, close_a, h) for h in horizons}
        for h in horizons:
            fwd = _forward_ret(close_a, h)
            mask = ~np.isnan(sig_a) & ~np.isnan(fwd)
            pooled[h]["sig"].extend(sig_a[mask].tolist())
            pooled[h]["fwd"].extend(fwd[mask].tolist())
            fold_signs[h].extend([s for s in fold_ic_signs(sig_a, close_a, h, 3) if s != 0])

    table = {h: _corr(np.array(pooled[h]["sig"], float), np.array(pooled[h]["fwd"], float))
             for h in horizons}
    verdict = graduate(table, fold_signs, {})        # regime split N/A (single-regime)
    bh = verdict.get("best_horizon")
    sym_signs = [_sign(per_symbol[s][bh]["spearman"]) for s in per_symbol
                 if "spearman" in per_symbol[s].get(bh, {})] if bh else []
    verdict["symbol_signs"] = sym_signs
    verdict["symbol_sign_agree"] = bool(sym_signs) and len(set(sym_signs)) == 1
    return table, per_symbol, verdict


def main():
    ap = argparse.ArgumentParser(description="F-018 conditioned-signal validation")
    ap.add_argument("--symbols", default="SPY,QQQ,AAPL,NFLX")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    print(f"\nConditioned-signal test — symbols={symbols}  window={start}..{end}\n" + "=" * 72)
    vix_df, vix3m_df = _fetch("^VIX", start, end), _fetch("^VIX3M", start, end)
    _vix_diagnostics(vix_df, vix3m_df, start, end)
    if vix_df is None or vix3m_df is None:
        print("ABORT: VIX data unavailable — gate cannot be built.")
        return

    import pandas as pd
    aux = {"vix": pd.Series(list(vix_df["Close"]), index=list(vix_df.index)),
           "vix3m": pd.Series(list(vix3m_df["Close"]), index=list(vix3m_df.index))}
    frames = {s: _fetch(s, start, end) for s in symbols}
    frames = {s: d for s, d in frames.items() if d is not None}

    for gate in ("contango", "vix_pct"):
        table, _, v = evaluate(symbols, start, end, gate, aux, frames)
        print(f"### gate='{gate}'   conditioned_reversal (positive = predictive)")
        for h, d in table.items():
            line = (f"IC={d['spearman']:+.3f} p={d['spearman_p']:.3f} n={d['n']}"
                    if "spearman" in d else f"n={d.get('n', 0)} (insuff.)")
            print(f"    {h:>2}d : {line}")
        flag = "✅ GRADUATES" if v.get("graduates") else "❌ no edge"
        print(f"  verdict: {flag}  [best={v.get('best_horizon')}d IC={v.get('spearman')} "
              f"dir={v.get('direction')}]")
        print(f"           symbol signs={v.get('symbol_signs')} agree={v.get('symbol_sign_agree')}")
        print(f"           reason: {v.get('reason')}\n")


if __name__ == "__main__":
    main()
