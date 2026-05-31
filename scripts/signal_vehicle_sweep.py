#!/usr/bin/env python3
"""
signal_vehicle_sweep — Phase 2 (F-023): match the validated directional signal
to a more cost-efficient option vehicle.

F-019 showed the medium-horizon mean-reversion signal (IC ~0.10 on the
underlying) does NOT transmit through a NARROW ATM debit spread — a sign-edge is
swallowed by theta/cost and the need for a large move within DTE, and the long
side fired only n=4. Phase 2 tests whether a better VEHICLE rescues it, by
sweeping the three knobs added to the backtester (F-023):

  - DTE          : more time for the reversion to play out (10-14 vs 21-45)
  - ITM depth    : a deeper-ITM long leg has more delta and less theta drag,
                   so a directional view transmits with less cost bleed
  - entry cadence: smaller interval ⇒ more entries ⇒ usable sample (≥30)

For each (DTE, ITM) cell it runs the signal-GATED long_call_spread vs the
UNCONDITIONAL one and asks the F-017 question: does gating on the signal beat
the unconditional (beta) spread on a per-trade, risk-adjusted basis, with a
real sample? A vehicle "works" only if gated > unconditional AND n ≥ 30.

    python3 scripts/signal_vehicle_sweep.py --symbol SPY --gate contango --entry-interval 2
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest  # noqa: E402
from backtest.chain_replay import run_chain_replay  # noqa: E402

# Vehicle grid: (dte_min, dte_max) × ITM depth (fraction of spot).
DTE_GRID = [(10, 14), (21, 35), (30, 45)]
ITM_GRID = [0.0, 0.03, 0.06]      # ATM, 3% ITM, 6% ITM long leg
WIDTH = 0.05                       # fixed 5%-of-spot spread width (room to capture the move)


def _ppt_ror(stats):
    """(pnl-per-trade, return-on-risk, n) from a stats object."""
    n = stats.total_trades
    ppt = (stats.total_pnl / n) if n else 0.0
    return ppt, getattr(stats, "return_on_risk", 0.0), n


def main():
    ap = argparse.ArgumentParser(description="Phase 2 vehicle sweep (F-023)")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--gate", default="contango", choices=["contango", "vix_pct"])
    ap.add_argument("--entry-interval", type=int, default=2)
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    base = dict(strategy="long_call_spread", symbol=args.symbol, start_date=start, end_date=end,
                exit_rule="hold", fill_mode="bid_ask", entry_interval=args.entry_interval,
                debit_width_pct=WIDTH)

    print(f"\nPhase-2 vehicle sweep — {args.symbol} {start}..{end}  gate={args.gate}  "
          f"entry_interval={args.entry_interval}  width={WIDTH:.0%}\n" + "=" * 92)
    print(f"{'DTE':>7} {'ITM':>5} | {'uncond n':>8} {'u $/trade':>10} {'u ror':>7} | "
          f"{'gated n':>7} {'g $/trade':>10} {'g ror':>7} | helps?")
    print("-" * 92)

    winners = []
    for (dmin, dmax) in DTE_GRID:
        for itm in ITM_GRID:
            cfg = dict(base, entry_dte_min=dmin, entry_dte_max=dmax, debit_itm_pct=itm)
            u = run_chain_replay(BacktestRequest(**cfg)).stats
            g = run_chain_replay(BacktestRequest(**cfg, signal_filter=True,
                                                 signal_gate=args.gate)).stats
            u_ppt, u_ror, u_n = _ppt_ror(u)
            g_ppt, g_ror, g_n = _ppt_ror(g)
            helps = (g_ppt > u_ppt) and (g_ror >= u_ror) and g_n >= 30
            flag = "✅" if helps else ("· n<30" if g_n < 30 else "✗")
            if helps:
                winners.append((dmin, dmax, itm, g_ppt, g_ror, g_n))
            print(f"{dmin:>3}-{dmax:<3} {itm:>5.0%} | {u_n:>8} {u_ppt:>10.0f} {u_ror:>7.3f} | "
                  f"{g_n:>7} {g_ppt:>10.0f} {g_ror:>7.3f} | {flag}")

    print("\n" + "=" * 92)
    if winners:
        print("VEHICLES WHERE GATING HELPS (gated > unconditional, n≥30):")
        for d0, d1, itm, ppt, ror, n in sorted(winners, key=lambda w: -w[4]):
            print(f"  DTE {d0}-{d1}, {itm:.0%} ITM: gated ${ppt:.0f}/trade, ror={ror:.3f}, n={n}")
    else:
        print("NO vehicle (in this grid) makes the signal beat the unconditional spread "
              "with n≥30 — the directional IC does not transmit to defined-risk debit spreads.")


if __name__ == "__main__":
    main()
