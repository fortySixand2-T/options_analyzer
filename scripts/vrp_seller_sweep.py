#!/usr/bin/env python3
"""
vrp_seller_sweep — Phase 2(b) / F-024: VRP-conditioned premium selling.

The directional thread is closed (F-023). This tests the OTHER edge family:
harvesting the variance risk premium as a SELLER. Hypothesis — selling
defined-risk premium only when the premium is RICH (VIX well above trailing
realised vol = high-VRP regime) harvests the premium more cleanly than selling
unconditionally.

Crucially this is judged on TAIL metrics, NOT win rate / total P&L — a premium
seller's whole risk is the left tail (the steamroller behind the pennies, F-015).
A real edge means the VRP gate IMPROVES the tail:

    CVaR-95 less negative  AND  Calmar higher  AND  return-on-risk >= unconditional,
    with n >= 30 trades.

Runs short_put_spread / short_call_spread / iron_condor on SPY (clean Dolt
quotes), unconditional vs VRP-gated. VRP regime comes from yfinance (VIX) +
chain replay; gate is point-in-time (vrp_proxy above its trailing-252d median).

    python3 scripts/vrp_seller_sweep.py --symbol SPY
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest  # noqa: E402
from backtest.chain_replay import run_chain_replay  # noqa: E402

# Per-strategy DTE (CLAUDE.md: credit spreads 3-10, iron condor 7-14).
DTE = {"short_put_spread": (3, 10), "short_call_spread": (3, 10), "iron_condor": (7, 14)}


def _tail(stats):
    """The metrics that actually decide a premium-seller's edge."""
    return {
        "n": stats.total_trades,
        "pnl": stats.total_pnl,
        "win": stats.win_rate,
        "cvar95": getattr(stats, "cvar_95", 0.0),
        "maxloss": getattr(stats, "max_single_loss", 0.0),
        "calmar": getattr(stats, "calmar_ratio", 0.0),
        "ror": getattr(stats, "return_on_risk", 0.0),
        "skew": getattr(stats, "pnl_skew", 0.0),
    }


def _fmt(t):
    return (f"n={t['n']:>3}  pnl=${t['pnl']:>8,.0f}  win={t['win']:>5.1f}%  "
            f"CVaR95=${t['cvar95']:>8,.0f}  maxloss=${t['maxloss']:>8,.0f}  "
            f"calmar={t['calmar']:>6.2f}  ror={t['ror']:>6.3f}  skew={t['skew']:>6.2f}")


def main():
    ap = argparse.ArgumentParser(description="Phase 2(b) VRP-seller sweep (F-024)")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--entry-interval", type=int, default=3)
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    print(f"\nF-024 VRP-seller sweep — {args.symbol} {start}..{end}  "
          f"entry_interval={args.entry_interval}  (gate: VRP > trailing-252d median)\n" + "=" * 100)

    helps_any = []
    for strat, (dmin, dmax) in DTE.items():
        base = dict(strategy=strat, symbol=args.symbol, start_date=start, end_date=end,
                    entry_dte_min=dmin, entry_dte_max=dmax, exit_rule="strategy",
                    fill_mode="bid_ask", entry_interval=args.entry_interval)
        u = _tail(run_chain_replay(BacktestRequest(**base)).stats)
        g = _tail(run_chain_replay(BacktestRequest(**base, vrp_filter=True)).stats)

        # Edge = better LEFT TAIL, not more P&L.
        better_tail = (g["cvar95"] > u["cvar95"] and g["calmar"] > u["calmar"]
                       and g["ror"] >= u["ror"] and g["n"] >= 30)
        print(f"\n### {strat}  (DTE {dmin}-{dmax})")
        print(f"  unconditional : {_fmt(u)}")
        print(f"  VRP-gated     : {_fmt(g)}")
        verdict = "✅ tail IMPROVES" if better_tail else (
            "· n<30" if g["n"] < 30 else "✗ no tail improvement")
        print(f"  -> {verdict}  (CVaR {u['cvar95']:,.0f}->{g['cvar95']:,.0f}, "
              f"calmar {u['calmar']:.2f}->{g['calmar']:.2f}, ror {u['ror']:.3f}->{g['ror']:.3f})")
        if better_tail:
            helps_any.append(strat)

    print("\n" + "=" * 100)
    if helps_any:
        print(f"VRP gating IMPROVES the tail for: {helps_any} — candidate seller edge, "
              f"validate with robustness.run_robustness before believing it.")
    else:
        print("VRP gating does NOT improve the tail for any seller strategy (n>=30). "
              "The variance-risk-premium harvest is not rescued by a high-VRP regime gate here.")


if __name__ == "__main__":
    main()
