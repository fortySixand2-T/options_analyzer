#!/usr/bin/env python3
"""
signal_ic_sweep — IC-first signal research harness (F-018).

Runs the candidate directional/vol signals (src/backtest/signal_lib.py) through
the information-coefficient gate (src/backtest/signal_eval.py) on cheap, free
underlying data, BEFORE any of them are allowed to touch the scarce option
backtest. This is the desk-quant workaround for our data limits: alpha is
discovered on decades of free underlying OHLCV; only IC-survivors graduate to
the expensive option-execution layer (F-017/F-018).

For each signal it reports, pooled across the requested symbols and per symbol:
  - rank (Spearman) + Pearson IC at horizons 3/5/10 days,
  - sign-stability across symbols and across contiguous time folds,
  - sign-stability across volatility regimes (VIX median split),
  - a strict graduation verdict (significant, |IC|>=0.03, sign-stable).

Underlying + VIX/VIX3M come from yfinance (point-in-time; the signals use only
trailing windows, so there is no lookahead). Usage:

    python3 scripts/signal_ic_sweep.py \
        --symbols SPY,QQQ,AAPL,NFLX --start 2020-01-01 --end 2024-12-31
"""

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.signal_lib import SIGNALS, NEEDS_VIX  # noqa: E402
from backtest.signal_eval import (  # noqa: E402
    ic_table, fold_ic_signs, graduate, _sign,
)

WARMUP_DAYS = 120  # buffer so trailing-window signals are defined from `start`


def _corr(xs, ys):
    """Spearman + Pearson of two aligned 1-D arrays (with p-values)."""
    from scipy.stats import pearsonr, spearmanr
    if len(xs) < 30 or len(set(np.asarray(xs).tolist())) < 3:
        return {"n": int(len(xs)), "note": "insufficient/degenerate"}
    pr, pp = pearsonr(xs, ys)
    sr, sp = spearmanr(xs, ys)
    return {"n": int(len(xs)),
            "pearson": round(float(pr), 4), "pearson_p": round(float(pp), 4),
            "spearman": round(float(sr), 4), "spearman_p": round(float(sp), 4)}


def _fetch(symbol, start, end):
    """Daily OHLCV from yfinance with a warmup buffer before `start`."""
    import yfinance as yf
    df = yf.Ticker(symbol).history(
        start=(start - timedelta(days=WARMUP_DAYS)).isoformat(),
        end=(end + timedelta(days=2)).isoformat(),
        auto_adjust=True,
    )
    if df is None or df.empty:
        return None
    df.index = [d.date() if hasattr(d, "date") else d for d in df.index]
    return df


def _forward_ret(closes, h):
    """h-day forward return per day (NaN in the last h)."""
    c = np.asarray(closes, float)
    fwd = np.full(len(c), np.nan)
    for i in range(len(c) - h):
        if c[i] > 0:
            fwd[i] = c[i + h] / c[i] - 1.0
    return fwd


def run_sweep(symbols, start, end, horizons=(3, 5, 10)):
    """Evaluate every signal across `symbols`; return a per-signal report."""
    # Exogenous VIX term-structure series (shared across symbols).
    vix = _fetch("^VIX", start, end)
    vix3m = _fetch("^VIX3M", start, end)
    aux = None
    if vix is not None and vix3m is not None:
        import pandas as pd
        aux = {"vix": pd.Series([c for c in vix["Close"]], index=list(vix.index)),
               "vix3m": pd.Series([c for c in vix3m["Close"]], index=list(vix3m.index))}

    # Per-symbol price frames, trimmed to [start, end] for evaluation.
    frames = {}
    for sym in symbols:
        df = _fetch(sym, start, end)
        if df is not None:
            frames[sym] = df

    report = {}
    for name, fn in SIGNALS.items():
        if name in NEEDS_VIX and aux is None:
            report[name] = {"error": "VIX/VIX3M unavailable"}
            continue

        per_symbol = {}
        # Pooled (signal, fwd) pairs per horizon + pooled vix level for regimes.
        pooled = {h: {"sig": [], "fwd": [], "vix": []} for h in horizons}
        fold_signs = {h: [] for h in horizons}

        for sym, df in frames.items():
            sig = fn(df, aux)
            sig = sig.reindex(df.index)
            # Restrict to the evaluation window [start, end].
            in_win = [start <= d <= end for d in df.index]
            sig_a = np.array([v for v, k in zip(sig.to_numpy(), in_win) if k], float)
            close_a = np.array([v for v, k in zip(df["Close"].to_numpy(), in_win) if k], float)
            dates_w = [d for d, k in zip(df.index, in_win) if k]
            per_symbol[sym] = ic_table(sig_a, close_a, horizons)

            # VIX level aligned to this symbol's in-window dates (for regimes).
            if aux is not None:
                vlvl = aux["vix"].reindex(dates_w).ffill().to_numpy()
            else:
                vlvl = np.full(len(sig_a), np.nan)

            for h in horizons:
                fwd = _forward_ret(close_a, h)
                mask = ~np.isnan(sig_a) & ~np.isnan(fwd)
                pooled[h]["sig"].extend(sig_a[mask].tolist())
                pooled[h]["fwd"].extend(fwd[mask].tolist())
                pooled[h]["vix"].extend(vlvl[mask].tolist())
                fs = fold_ic_signs(sig_a, close_a, h, n_folds=3)
                fold_signs[h].extend([s for s in fs if s != 0])

        # Pooled IC per horizon + pooled regime split.
        pooled_table, regime_by_h = {}, {}
        for h in horizons:
            xs = np.array(pooled[h]["sig"], float)
            ys = np.array(pooled[h]["fwd"], float)
            pooled_table[h] = _corr(xs, ys)
            v = np.array(pooled[h]["vix"], float)
            if np.isfinite(v).sum() >= 40:
                med = np.nanmedian(v[np.isfinite(v)])
                reg = {}
                for nm, m in (("low", v <= med), ("high", v > med)):
                    rc = _corr(xs[m], ys[m])
                    reg[nm] = {"spearman": rc.get("spearman"), "spearman_p": rc.get("spearman_p"),
                               "n": rc.get("n"),
                               "sign": _sign(rc.get("spearman", 0.0)) if "spearman" in rc else 0}
                regime_by_h[h] = reg

        verdict = graduate(pooled_table, fold_signs, regime_by_h)
        # Conditional edge: a (horizon, regime) cell that is itself significant
        # and economically real — a signal that only works in one vol regime.
        cond = []
        for h, reg in regime_by_h.items():
            for nm in ("low", "high"):
                cell = reg.get(nm, {})
                sp, p = cell.get("spearman"), cell.get("spearman_p")
                if sp is not None and p is not None and abs(sp) >= 0.03 and p < 0.05:
                    cond.append({"horizon": h, "regime": nm, "spearman": sp,
                                 "spearman_p": p, "n": cell.get("n")})
        verdict["conditional_edges"] = sorted(cond, key=lambda c: -abs(c["spearman"]))
        # Cross-symbol sign agreement at the graduating horizon.
        bh = verdict.get("best_horizon")
        sym_signs = [_sign(per_symbol[s][bh]["spearman"])
                     for s in per_symbol if "spearman" in per_symbol[s].get(bh, {})] if bh else []
        verdict["symbol_signs"] = sym_signs
        verdict["symbol_sign_agree"] = bool(sym_signs) and len(set(sym_signs)) == 1

        report[name] = {"pooled": pooled_table, "per_symbol": per_symbol,
                        "regimes": regime_by_h, "verdict": verdict}
    return report


def _fmt_ic(d):
    if "spearman" not in d:
        return f"n={d.get('n', 0)} (insuff.)"
    return f"IC={d['spearman']:+.3f} p={d['spearman_p']:.3f} n={d['n']}"


def main():
    ap = argparse.ArgumentParser(description="IC-first signal research sweep (F-018)")
    ap.add_argument("--symbols", default="SPY,QQQ,AAPL,NFLX")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"\nIC sweep — symbols={symbols}  window={start}..{end}\n" + "=" * 72)
    report = run_sweep(symbols, start, end)

    for name, res in report.items():
        print(f"\n### {name}")
        if "error" in res:
            print(f"  ERROR: {res['error']}")
            continue
        print("  pooled IC:")
        for h, d in res["pooled"].items():
            print(f"    {h:>2}d : {_fmt_ic(d)}")
        if res["regimes"]:
            print("  regime split (best-horizon vicinity):")
            for h, reg in res["regimes"].items():
                lo, hi = reg.get("low", {}), reg.get("high", {})
                print(f"    {h:>2}d : low-VIX IC={lo.get('spearman')}  "
                      f"high-VIX IC={hi.get('spearman')}")
        v = res["verdict"]
        flag = "✅ GRADUATES" if v.get("graduates") else "❌ no edge"
        print(f"  verdict: {flag}  [best={v.get('best_horizon')}d "
              f"IC={v.get('spearman')} dir={v.get('direction')}]")
        print(f"           symbol signs={v.get('symbol_signs')} "
              f"agree={v.get('symbol_sign_agree')}")
        print(f"           reason: {v.get('reason')}")
        for c in v.get("conditional_edges", []):
            print(f"           ↳ CONDITIONAL: {c['regime']}-VIX @ {c['horizon']}d  "
                  f"IC={c['spearman']:+.3f} p={c['spearman_p']:.3f} n={c['n']}")

    grads = [n for n, r in report.items()
             if "verdict" in r and r["verdict"].get("graduates")]
    print("\n" + "=" * 72)
    print(f"GRADUATED signals (→ option backtest): {grads or 'NONE'}")


if __name__ == "__main__":
    main()
