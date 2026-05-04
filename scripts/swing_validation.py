#!/usr/bin/env python3
"""
Swing Validation Backtests — Phase 5a.

6 validation tests for swing strategies, mirroring the short-DTE
validation in run_backtest.py --validate.

Usage:
    python scripts/swing_validation.py
    python scripts/swing_validation.py --symbol SPY --start 2022-01-01

Options Analytics Team — 2026-05
"""

import argparse
import logging
import os
import sys
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from backtest.models import BacktestRequest
from backtest.local_backtest import run_local_backtest

logger = logging.getLogger(__name__)


def print_result(result, label=None):
    """Print backtest result summary."""
    req = result.request
    stats = result.stats

    header = label or f"{req.strategy} on {req.symbol}"

    print(f"\n  --- {header} ---")
    print(f"  Trades: {stats.total_trades}  |  "
          f"Win rate: {stats.win_rate:.1f}%  ({stats.wins}W / {stats.losses}L)")
    print(f"  Avg win: ${stats.avg_win:.2f}  |  Avg loss: ${stats.avg_loss:.2f}  |  "
          f"Avg P&L: ${stats.avg_pnl:.2f}")
    print(f"  Total P&L: ${stats.total_pnl:.2f}  |  "
          f"Sharpe: {stats.sharpe_ratio:.2f}  |  PF: {stats.profit_factor:.2f}")
    print(f"  Max DD: ${stats.max_drawdown:.2f}  |  "
          f"Avg hold: {stats.avg_days_in_trade:.0f}d")

    if result.regime_breakdown:
        for regime, data in result.regime_breakdown.items():
            print(f"    {regime}: {data['count']} trades, "
                  f"WR {data['win_rate']:.1f}%, avg ${data['avg_pnl']:.2f}")


def print_comparison(label_a, result_a, label_b, result_b):
    """Print side-by-side comparison of two results."""
    sa, sb = result_a.stats, result_b.stats

    sharpe_diff = sb.sharpe_ratio - sa.sharpe_ratio
    wr_diff = sb.win_rate - sa.win_rate
    pnl_diff = sb.total_pnl - sa.total_pnl

    verdict = "BETTER" if sharpe_diff > 0.1 else ("WORSE" if sharpe_diff < -0.1 else "SIMILAR")

    print(f"\n  >> Comparison: {label_b} vs {label_a}")
    print(f"     Sharpe: {sa.sharpe_ratio:.2f} → {sb.sharpe_ratio:.2f} ({sharpe_diff:+.2f}) [{verdict}]")
    print(f"     WR:     {sa.win_rate:.1f}% → {sb.win_rate:.1f}% ({wr_diff:+.1f}%)")
    print(f"     P&L:    ${sa.total_pnl:.0f} → ${sb.total_pnl:.0f} ({pnl_diff:+.0f})")
    print(f"     Trades: {sa.total_trades} → {sb.total_trades}")


def run_swing_validation(symbol: str, start_date: date, end_date: date):
    """Run the 6 swing validation backtests."""

    print("\n" + "=" * 70)
    print("  Swing Strategy Validation Backtests")
    print(f"  Symbol: {symbol}  |  Period: {start_date} to {end_date}")
    print("=" * 70)

    # Common swing DTE range
    swing_dte_min = 14
    swing_dte_max = 45
    slippage = 3.0

    # ── Test 1: Calendar spreads — VRP filter ON vs OFF ──────────────────

    print("\n" + "-" * 70)
    print("  TEST 1: Calendar Spreads — VRP filter ON vs OFF")
    print("-" * 70)

    cal_base = BacktestRequest(
        strategy="calendar_spread", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
    )
    r1_base = run_local_backtest(cal_base)
    print_result(r1_base, "Calendar — No filters (baseline)")

    cal_vrp = BacktestRequest(
        strategy="calendar_spread", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
        vrp_filter=True, vrp_threshold=3.0,
    )
    r1_vrp = run_local_backtest(cal_vrp)
    print_result(r1_vrp, "Calendar — VRP > 3% filter ON")
    print_comparison("baseline", r1_base, "VRP filter", r1_vrp)

    # ── Test 2: Calendar spreads — regime filter ON vs OFF ───────────────

    print("\n" + "-" * 70)
    print("  TEST 2: Calendar Spreads — Regime filter ON vs OFF")
    print("-" * 70)

    cal_regime = BacktestRequest(
        strategy="calendar_spread", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
        regime_filter=True,
    )
    r2_regime = run_local_backtest(cal_regime)
    print_result(r2_regime, "Calendar — Regime filter ON (HIGH_IV/MODERATE_IV)")
    print_comparison("baseline", r1_base, "regime filter", r2_regime)

    # ── Test 3: Iron butterflies — VRP > 3% vs all ──────────────────────

    print("\n" + "-" * 70)
    print("  TEST 3: Iron Butterflies — VRP > 3% vs all")
    print("-" * 70)

    ib_base = BacktestRequest(
        strategy="iron_butterfly", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
    )
    r3_base = run_local_backtest(ib_base)
    print_result(r3_base, "Iron Butterfly — No filters (baseline)")

    ib_vrp = BacktestRequest(
        strategy="iron_butterfly", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
        vrp_filter=True, vrp_threshold=3.0,
    )
    r3_vrp = run_local_backtest(ib_vrp)
    print_result(r3_vrp, "Iron Butterfly — VRP > 3% filter ON")
    print_comparison("baseline", r3_base, "VRP filter", r3_vrp)

    # ── Test 4: Long straddles — regime filter (LOW_IV) vs all ───────────

    print("\n" + "-" * 70)
    print("  TEST 4: Long Straddles — LOW_IV regime filter vs all")
    print("-" * 70)

    ls_base = BacktestRequest(
        strategy="long_straddle", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
    )
    r4_base = run_local_backtest(ls_base)
    print_result(r4_base, "Long Straddle — No filters (baseline)")

    ls_regime = BacktestRequest(
        strategy="long_straddle", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
        exit_rule="strategy", slippage_pct=slippage,
        regime_filter=True,
    )
    r4_regime = run_local_backtest(ls_regime)
    print_result(r4_regime, "Long Straddle — LOW_IV regime filter ON")
    print_comparison("baseline", r4_base, "regime filter", r4_regime)

    # ── Test 5: All swing strategies — DTE bucket comparison ─────────────

    print("\n" + "-" * 70)
    print("  TEST 5: All Swing Strategies — DTE bucket comparison")
    print("-" * 70)

    dte_buckets = [(14, 21), (21, 30), (30, 45), (45, 60)]
    for strategy in ["calendar_spread", "iron_butterfly", "long_straddle"]:
        print(f"\n  {strategy}:")
        for min_dte, max_dte in dte_buckets:
            req = BacktestRequest(
                strategy=strategy, symbol=symbol,
                start_date=start_date, end_date=end_date,
                entry_dte_min=min_dte, entry_dte_max=max_dte,
                exit_rule="strategy", slippage_pct=slippage,
            )
            result = run_local_backtest(req)
            s = result.stats
            print(f"    DTE {min_dte}-{max_dte}: {s.total_trades} trades, "
                  f"WR {s.win_rate:.1f}%, Sharpe {s.sharpe_ratio:.2f}, "
                  f"P&L ${s.total_pnl:.0f}")

    # ── Test 6: All swing strategies — with vs without swing bias filter ──

    print("\n" + "-" * 70)
    print("  TEST 6: All Swing Strategies — Swing bias filter ON vs OFF")
    print("-" * 70)

    for strategy in ["calendar_spread", "diagonal_spread", "iron_butterfly", "long_straddle"]:
        base_req = BacktestRequest(
            strategy=strategy, symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
            exit_rule="strategy", slippage_pct=slippage,
        )
        r_base = run_local_backtest(base_req)

        bias_req = BacktestRequest(
            strategy=strategy, symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=swing_dte_min, entry_dte_max=swing_dte_max,
            exit_rule="strategy", slippage_pct=slippage,
            swing_bias_filter=True,
        )
        r_bias = run_local_backtest(bias_req)

        print_result(r_base, f"{strategy} — No filters")
        print_result(r_bias, f"{strategy} — Swing bias filter ON")
        print_comparison("baseline", r_base, "swing bias", r_bias)

    print("\n" + "=" * 70)
    print("  Swing validation complete.")
    print("=" * 70)


def main():
    p = argparse.ArgumentParser(description='Swing Strategy Validation')
    p.add_argument('--symbol', default='SPY')
    p.add_argument('--start', default='2022-01-01')
    p.add_argument('--end', default=None)
    p.add_argument('-v', '--verbose', action='store_true')
    args = p.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s %(name)s %(levelname)s %(message)s')

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = date.fromisoformat(args.start)

    run_swing_validation(args.symbol, start_date, end_date)


if __name__ == '__main__':
    main()
