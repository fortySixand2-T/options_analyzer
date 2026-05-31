#!/usr/bin/env python3
"""
signal_execution_test — the F-019 execution test for the F-018 signal.

The conditioned_reversal signal GRADUATED the IC gate at the SIGNAL layer
(SPY/QQQ, vix_pct gate, IC +0.163 @10d). This script tests whether that edge
survives the EXECUTION layer: it expresses the signal as a 10–14 DTE
long_call_spread on the clean Dolt SPY window and runs the F-017 test —

    does GATING entries on the signal beat the UNCONDITIONAL spread (which F-017
    showed is pure bull-market beta, +$7,445)?

A real edge makes the gated version better on a per-trade / risk-adjusted basis
(return-on-risk, Sortino, win rate), even though it trades far less often. If
gating does NOT help, the signal's IC does not transmit through option
mechanics and we say so plainly.

    python3 scripts/signal_execution_test.py --symbol SPY --start 2020-01-01 --end 2024-12-31
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.models import BacktestRequest  # noqa: E402
from backtest.chain_replay import run_chain_replay  # noqa: E402


def _row(label, stats):
    """One comparison row of the metrics that matter for a directional edge."""
    s = stats
    ror = getattr(s, "return_on_risk", 0.0)
    return (f"  {label:<26} trades={s.total_trades:>4}  pnl=${s.total_pnl:>9,.0f}  "
            f"win={s.win_rate:>5.1f}%  sortino={s.sortino_ratio:>6.2f}  "
            f"ret/risk={ror:>6.3f}  PF={s.profit_factor:>5.2f}")


def main():
    ap = argparse.ArgumentParser(description="F-019 signal execution test")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--strategy", default="long_call_spread")
    ap.add_argument("--gate", default="vix_pct")
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    base = dict(strategy=args.strategy, symbol=args.symbol, start_date=start, end_date=end,
                entry_dte_min=10, entry_dte_max=14, exit_rule="hold", fill_mode="bid_ask")

    print(f"\nF-019 execution test — {args.strategy} {args.symbol} {start}..{end} "
          f"(10-14 DTE, gate={args.gate})\n" + "=" * 88)

    uncond = run_chain_replay(BacktestRequest(**base))
    gated = run_chain_replay(BacktestRequest(**base, signal_filter=True, signal_gate=args.gate))

    print(_row("unconditional (beta)", uncond.stats))
    print(_row(f"signal-gated ({args.gate})", gated.stats))

    u, g = uncond.stats, gated.stats
    print("\n" + "-" * 88)
    print("Does the signal HELP? (per-trade & risk-adjusted, not total $ — the gate trades less)")
    u_ror = getattr(u, "return_on_risk", 0.0)
    g_ror = getattr(g, "return_on_risk", 0.0)
    u_ppt = (u.total_pnl / u.total_trades) if u.total_trades else 0.0
    g_ppt = (g.total_pnl / g.total_trades) if g.total_trades else 0.0
    print(f"  pnl / trade   : unconditional ${u_ppt:,.0f}   gated ${g_ppt:,.0f}")
    print(f"  return-on-risk: unconditional {u_ror:.3f}        gated {g_ror:.3f}")
    print(f"  sortino       : unconditional {u.sortino_ratio:.2f}          gated {g.sortino_ratio:.2f}")
    print(f"  win rate      : unconditional {u.win_rate:.1f}%        gated {g.win_rate:.1f}%")

    helps = (g_ppt > u_ppt) and (g_ror >= u_ror) and g.total_trades >= 10
    print("\n  VERDICT: " + ("✅ signal HELPS — edge transmits through execution"
                             if helps else
                             "❌ signal does NOT improve execution (IC does not transmit / sample too small)"))
    for it in (gated.data_issues or []):
        print(f"    note: {it}")


if __name__ == "__main__":
    main()
