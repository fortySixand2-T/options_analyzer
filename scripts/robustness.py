#!/usr/bin/env python3
"""
Robustness / OOS harness CLI.

Runs a strategy through time folds, an in/out-of-sample split, and a
fill/slippage perturbation grid, then prints skew-aware metrics per slice and
a consolidated verdict. See src/backtest/robustness.py.

Usage:
    python scripts/robustness.py --strategy short_put_spread --symbol SPY \
        --start 2022-01-01 --end 2026-05-21
    python scripts/robustness.py --strategy butterfly --symbol QQQ --json
"""

import argparse
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.WARNING)


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest robustness / OOS harness")
    p.add_argument("--strategy", default="short_put_spread")
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-05-21")
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--oos", type=float, default=0.3, help="OOS tail fraction")
    p.add_argument("--exit-rule", default="strategy")
    p.add_argument("--json", action="store_true", help="emit raw JSON")
    args = p.parse_args()

    from backtest.models import BacktestRequest
    from backtest.robustness import run_robustness

    req = BacktestRequest(
        strategy=args.strategy, symbol=args.symbol,
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        exit_rule=args.exit_rule, fill_mode="bid_ask",
    )
    report = run_robustness(req, n_folds=args.folds, oos_fraction=args.oos)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"\n{report['strategy']} {report['symbol']} {report['window']}")
    print(f"VERDICT: {report['verdict'].upper()}\n")

    def row(label, m):
        return (f"  {label:<22} trades={m['trades']:>4} WR={m['win_rate']:>5.1f} "
                f"P&L={m['pnl']:>8.0f} Sharpe={m['sharpe']:>6.2f} "
                f"Sortino={m['sortino']:>6.2f} PF={m['profit_factor']:>5.2f} "
                f"skew={m['skew']:>5.2f} ret/risk={m['return_on_risk']:>6.3f}")

    print("Time folds:")
    for f in report["time_folds"]["folds"]:
        print(row(f["window"], f))
    agg = report["time_folds"]["aggregate"]
    print(f"  → sign_consistent={agg['sign_consistent']} "
          f"positive_folds={agg['pnl_positive_folds']}/{agg['folds_evaluated']} "
          f"sharpe={agg['sharpe_mean']}±{agg['sharpe_std']} (min {agg['sharpe_min']})\n")

    oos = report["oos_split"]
    print(f"In/Out-of-sample (verdict: {oos['oos_verdict']}):")
    print(row("in-sample", oos["in_sample"]))
    print(row("out-of-sample", oos["out_of_sample"]))

    pert = report["perturbation"]
    print(f"\nPerturbation grid (trade_count_stable={pert['trade_count_stable']}, "
          f"slippage_monotonic={pert['slippage_monotonic']}, "
          f"P&L range [{pert['pnl_min']:.0f}, {pert['pnl_max']:.0f}]):")
    for g in pert["grid"]:
        print(row(f"{g['fill_mode']} slip={g['slippage_pct']}%", g))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
