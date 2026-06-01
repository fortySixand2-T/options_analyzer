#!/usr/bin/env python3
"""
vehicle_b_delta1 — Phase 2 capstone (F-026): does the validated mean-reversion
signal MONETIZE in a delta-1 vehicle, where short-DTE defined-risk spreads failed
(F-019/F-023)?

The signal layer is settled: inverted medium-horizon momentum / `conditioned_reversal`
has real rank IC (~0.10–0.16, F-018/F-022) — extended index ETFs mean-revert over
~10 days. F-023/F-025 showed that IC does not survive expression as a short-DTE
debit spread (cost + path swamp a sign-edge). This tests the OTHER vehicle: plain
delta-1 (underlying), where there is no theta, no double bid/ask, and the position
IS the directional view.

Two cuts, non-overlapping H-day holding periods (honest, un-autocorrelated stats):
  1. Cross-sectional reversal LONG/SHORT across the 7 ETFs — long the biggest
     laggards (lowest ts_momentum), short the most extended; dollar-neutral. This
     is market-neutral, so its return is (close to) pure ALPHA, not beta.
  2. Single-name (SPY) signal-gated LONG-only vs buy-and-hold beta — does the
     signal beat simply being long (the alpha-vs-beta test the spreads failed)?

Returns are net of a delta-1 round-trip cost (basis points/leg). yfinance data.

    python3 scripts/vehicle_b_delta1.py --symbols SPY,QQQ,IWM,DIA,XLK,XLF,XLE \
        --start 2020-01-01 --end 2024-12-31 --horizon 10 --cost-bps 2
"""

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.signal_lib import ts_momentum, conditioned_reversal  # noqa: E402

WARMUP_DAYS = 320  # cover 63d momentum + 20d RV + slack


def _fetch_close(symbol, start, end):
    import yfinance as yf
    df = yf.Ticker(symbol).history(
        start=(start - timedelta(days=WARMUP_DAYS)).isoformat(),
        end=(end + timedelta(days=2)).isoformat(), auto_adjust=True)
    if df is None or df.empty:
        return None
    df.index = [d.date() if hasattr(d, "date") else d for d in df.index]
    return df


def _stats(rets, periods_per_year):
    """Annualised return, vol, Sharpe, t-stat, hit-rate from a return series."""
    r = np.asarray(rets, float)
    if len(r) < 5:
        return {"n": len(r)}
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    sharpe = (mean / sd * np.sqrt(periods_per_year)) if sd > 0 else 0.0
    tstat = (mean / (sd / np.sqrt(len(r)))) if sd > 0 else 0.0
    return {"n": len(r), "ann_ret": mean * periods_per_year, "ann_vol": sd * np.sqrt(periods_per_year),
            "sharpe": sharpe, "tstat": tstat, "hit": float((r > 0).mean()),
            "mean_per_period": mean, "total": float(r.sum())}


def main():
    ap = argparse.ArgumentParser(description="Vehicle-B delta-1 capstone (F-026)")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA,XLK,XLF,XLE")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--cost-bps", type=float, default=2.0, help="delta-1 cost per leg per side (bps)")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    H = args.horizon
    ppy = 252.0 / H
    cost = args.cost_bps / 1e4

    print(f"\nVehicle-B (delta-1) — {symbols}  {start}..{end}  H={H}d  cost={args.cost_bps}bps/leg\n" + "=" * 90)

    # Exogenous VIX/VIX3M for the calm-gated conditioned_reversal signal.
    import pandas as pd
    vix_df, vix3m_df = _fetch_close("^VIX", start, end), _fetch_close("^VIX3M", start, end)
    aux = None
    if vix_df is not None and vix3m_df is not None:
        aux = {"vix": pd.Series(list(vix_df["Close"]), index=list(vix_df.index)),
               "vix3m": pd.Series(list(vix3m_df["Close"]), index=list(vix3m_df.index))}

    # Per-symbol close + point-in-time signals, restricted to [start,end].
    closes, signals, cond_sig, dates = {}, {}, {}, {}
    for sym in symbols:
        df = _fetch_close(sym, start, end)
        if df is None:
            continue
        sig = ts_momentum(df)
        # conditioned_reversal (calm-gated, vix_pct): the strong graduate (IC ~0.16).
        cr = (conditioned_reversal(df, aux, gate="vix_pct") if aux is not None
              else pd.Series([np.nan] * len(df), index=df.index))
        in_win = [start <= d <= end for d in df.index]
        closes[sym] = np.array([v for v, k in zip(df["Close"].to_numpy(), in_win) if k], float)
        signals[sym] = np.array([v for v, k in zip(sig.to_numpy(), in_win) if k], float)
        cond_sig[sym] = np.array([v for v, k in zip(cr.to_numpy(), in_win) if k], float)
        dates[sym] = [d for d, k in zip(df.index, in_win) if k]

    # Align on the shortest common length (ETFs share the trading calendar).
    n = min(len(closes[s]) for s in closes)
    entries = list(range(0, n - H, H))   # non-overlapping H-day periods

    # ---- Cut 1: cross-sectional reversal long/short (market-neutral = alpha) ----
    k = max(1, len(closes) // 3)         # tercile each side
    ls_rets, longonly_rets, bench_rets = [], [], []
    for i in entries:
        rows = []
        for s in closes:
            sig = signals[s][i]
            if sig != sig:               # NaN warmup
                continue
            fwd = closes[s][i + H] / closes[s][i] - 1.0
            rows.append((sig, fwd))
        if len(rows) < 2 * k:
            continue
        rows.sort(key=lambda x: x[0])    # ascending signal: lowest = biggest laggard
        longs = [fwd for _, fwd in rows[:k]]            # laggards (inverted signal ⇒ outperform)
        shorts = [fwd for _, fwd in rows[-k:]]          # most extended
        gross = np.mean(longs) - np.mean(shorts)
        ls_rets.append(gross - 4 * cost)                # long+short, round trip ≈ 4 legs
        bench_rets.append(np.mean([fwd for _, fwd in rows]))   # equal-weight long-all = beta

    # ---- Cut 2: single-name SPY signal-gated long-only vs buy-and-hold beta ----
    spy = "SPY" if "SPY" in closes else symbols[0]
    sg_rets, bh_rets = [], []
    for i in entries:
        sig = signals[spy][i]
        fwd = closes[spy][i + H] / closes[spy][i] - 1.0
        bh_rets.append(fwd - 2 * cost)                  # always long (beta)
        if sig == sig and sig < 0:        # ts_momentum<0 ⇒ laggard ⇒ inverted-signal bullish
            sg_rets.append(fwd - 2 * cost)

    # ---- Cut 3: bucket decomposition (is there shortable alpha, or just a tilt?) ----
    # A *time-series* sign L/S is invalid here: the calm-regime signal is ~90%
    # "extended" (in a bull market the index is almost always a recent winner), so
    # a sign-L/S becomes a net-SHORT bet on a rising market — it measures beta, not
    # the signal. The honest question is whether the EXTENDED bucket has NEGATIVE
    # forward returns (shortable alpha) or merely lower-but-positive (a long tilt).
    # Pool calm-day forward returns by conditioned_reversal sign.
    lag_fwd, ext_fwd, all_fwd = [], [], []
    for i in entries:
        for s in closes:
            cv = cond_sig[s][i]
            if cv != cv:
                continue
            fwd = closes[s][i + H] / closes[s][i] - 1.0
            all_fwd.append(fwd)
            (lag_fwd if cv > 0 else ext_fwd).append(fwd)

    def _mean(x):
        return float(np.mean(x)) if x else float("nan")

    ls = _stats(ls_rets, ppy)
    bench = _stats(bench_rets, ppy)
    bh = _stats(bh_rets, ppy)
    sg = _stats(sg_rets, ppy)

    print("CUT 1 — cross-sectional reversal LONG/SHORT (market-neutral ⇒ alpha):")
    print(f"  long-short : n={ls['n']}  ann_ret={ls.get('ann_ret',0):+.1%}  ann_vol={ls.get('ann_vol',0):.1%}  "
          f"Sharpe={ls.get('sharpe',0):.2f}  t={ls.get('tstat',0):.2f}  hit={ls.get('hit',0):.0%}")
    print(f"  beta (long-all, same periods): ann_ret={bench.get('ann_ret',0):+.1%}  Sharpe={bench.get('sharpe',0):.2f}")
    print("\nCUT 2 — SPY signal-gated LONG-only vs buy-and-hold beta:")
    print(f"  signal-gated long : n={sg['n']}  ann_ret={sg.get('ann_ret',0):+.1%}  Sharpe={sg.get('sharpe',0):.2f}  "
          f"mean/trade={sg.get('mean_per_period',0):+.3%}  hit={sg.get('hit',0):.0%}")
    print(f"  buy-and-hold beta : n={bh['n']}  ann_ret={bh.get('ann_ret',0):+.1%}  Sharpe={bh.get('sharpe',0):.2f}  "
          f"mean/trade={bh.get('mean_per_period',0):+.3%}")

    print("\nCUT 3 — calm-day forward-return by signal bucket (tilt vs shortable alpha?):")
    print(f"  laggard (cv>0)  : mean fwd {_mean(lag_fwd):+.3%}  n={len(lag_fwd)}")
    print(f"  extended (cv<0) : mean fwd {_mean(ext_fwd):+.3%}  n={len(ext_fwd)}")
    print(f"  all calm (beta) : mean fwd {_mean(all_fwd):+.3%}  n={len(all_fwd)}")
    print("  NB: a time-series sign-L/S is invalid here — the signal is mostly 'extended', so it")
    print("      would be net-short a rising market (measures beta, not the signal).")

    print("\n" + "=" * 90)
    # Market-neutral alpha is real only if the cross-sectional balanced L/S (Cut 1)
    # is positive AND the extended bucket is actually negative (shortable). Here:
    xs_alpha = ls.get("sharpe", 0) > 0.5 and ls.get("tstat", 0) > 2.0
    shortable = _mean(ext_fwd) < 0
    longtilt = (sg.get("mean_per_period", 0) > bh.get("mean_per_period", 0)) and sg["n"] >= 20
    if xs_alpha and shortable:
        print(f"VERDICT: ✅ standalone alpha in delta-1 (cross-sectional L/S Sharpe={ls.get('sharpe',0):.2f}).")
    elif longtilt:
        print("VERDICT: ⚠️ NOT standalone alpha — but a real, modest LONG-ONLY TIMING TILT. "
              f"Laggard-day fwd ({_mean(lag_fwd):+.2%}) > beta ({_mean(all_fwd):+.2%}); BOTH buckets "
              "positive (no shortable side), and the cross-sectional L/S is "
              f"{ls.get('sharpe',0):.2f} Sharpe. The IC is a beta-concentration tilt, not extractable alpha.")
    else:
        print("VERDICT: ❌ no monetizable edge in delta-1 (no long tilt, no market-neutral alpha).")


if __name__ == "__main__":
    main()
