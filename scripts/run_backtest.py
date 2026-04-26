#!/usr/bin/env python3
"""
Backtest CLI — validate options strategies against historical data.

Usage:
    python scripts/run_backtest.py --strategy iron_condor --symbol SPY
    python scripts/run_backtest.py --strategy iron_condor --symbol SPY --start 2020-01-01 --end 2025-12-31
    python scripts/run_backtest.py --compare --symbols SPY,QQQ --strategies iron_condor,short_put_spread
    python scripts/run_backtest.py --validate   # Run all 6 SIGNALS.md backtests

Options Analytics Team — 2026-04
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


def parse_args(argv=None):
    p = argparse.ArgumentParser(description='Options Strategy Backtester')
    p.add_argument('--strategy', type=str, default='iron_condor',
                   help='Strategy name (default: iron_condor)')
    p.add_argument('--symbol', type=str, default='SPY',
                   help='Symbol to backtest (default: SPY)')
    p.add_argument('--symbols', type=str, default=None,
                   help='Comma-separated symbols for --compare mode')
    p.add_argument('--strategies', type=str, default=None,
                   help='Comma-separated strategies for --compare mode')
    p.add_argument('--start', type=str, default='2022-01-01',
                   help='Start date (default: 2022-01-01)')
    p.add_argument('--end', type=str, default=None,
                   help='End date (default: today)')
    p.add_argument('--compare', action='store_true',
                   help='Compare multiple strategies/symbols')
    p.add_argument('--validate', action='store_true',
                   help='Run all 6 SIGNALS.md validation backtests')
    p.add_argument('--delta', type=float, default=0.20,
                   help='Target entry delta (default: 0.20)')
    p.add_argument('--min-dte', type=int, default=3,
                   help='Min DTE for entry (default: 3)')
    p.add_argument('--max-dte', type=int, default=14,
                   help='Max DTE for entry (default: 14)')
    p.add_argument('--min-score', type=float, default=0.0,
                   help='Min strategy score to enter (default: 0)')
    p.add_argument('--regime-filter', action='store_true',
                   help='Only enter when regime matches strategy')
    p.add_argument('--bias-filter', action='store_true',
                   help='Only enter when directional bias aligns')
    p.add_argument('--dealer-filter', action='store_true',
                   help='Only enter when dealer regime matches')
    p.add_argument('--edge-threshold', type=float, default=0.0,
                   help='Min GARCH edge %% to enter (default: 0)')
    p.add_argument('--exit-rule', type=str, default='50pct',
                   choices=['50pct', 'hold', 'strategy'],
                   help='Exit rule: 50pct target, hold to expiry, or per-strategy rules')
    p.add_argument('--slippage', type=float, default=0.0,
                   help='Slippage as %% of premium (e.g., 3.0 = 3%%). Default: 0')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='Verbose output')
    return p.parse_args(argv)


def print_result(result, label=None):
    """Print backtest result summary."""
    req = result.request
    stats = result.stats

    source_tag = f"[{result.source}]"
    cached_tag = " [cached]" if result.cached else ""
    header = label or f"{req.strategy} on {req.symbol}"

    print()
    print(f"  === {header} {source_tag}{cached_tag} ===")
    print(f"  Period: {req.start_date} to {req.end_date}")
    print(f"  Entry: delta={req.entry_delta}, DTE {req.entry_dte_min}-{req.entry_dte_max}")
    print(f"  Exit: profit {req.exit_profit_pct}% / loss {req.exit_loss_pct}% / DTE {req.exit_dte}")

    filters = []
    if req.regime_filter:
        filters.append("regime")
    if req.bias_filter:
        filters.append("bias")
    if req.dealer_filter:
        filters.append("dealer")
    if req.edge_threshold > 0:
        filters.append(f"edge>{req.edge_threshold}%")
    if filters:
        print(f"  Filters: {', '.join(filters)}")
    print(f"  Exit rule: {req.exit_rule}")
    if req.slippage_pct > 0:
        print(f"  Slippage: {req.slippage_pct:.1f}% of premium")

    print()
    print(f"  Trades:         {stats.total_trades}")
    print(f"  Win rate:       {stats.win_rate:.1f}%  ({stats.wins}W / {stats.losses}L)")
    print(f"  Avg win:        ${stats.avg_win:.2f}")
    print(f"  Avg loss:       ${stats.avg_loss:.2f}")
    print(f"  Avg P&L:        ${stats.avg_pnl:.2f}")
    print(f"  Total P&L:      ${stats.total_pnl:.2f}")
    print(f"  Profit factor:  {stats.profit_factor:.2f}")
    print(f"  Max drawdown:   ${stats.max_drawdown:.2f} ({stats.max_drawdown_pct:.1f}%)")
    print(f"  Sharpe ratio:   {stats.sharpe_ratio:.2f}")
    print(f"  Avg DTE entry:  {stats.avg_dte_at_entry:.0f}d")
    print(f"  Avg hold time:  {stats.avg_days_in_trade:.0f}d")

    if result.regime_breakdown:
        print()
        print(f"  --- Regime Breakdown ---")
        for regime, data in result.regime_breakdown.items():
            print(f"    {regime}: {data['count']} trades, "
                  f"win rate {data['win_rate']:.1f}%, "
                  f"avg P&L ${data['avg_pnl']:.2f}")

    if result.dte_breakdown:
        print()
        print(f"  --- DTE Breakdown ---")
        for dte_bucket, data in result.dte_breakdown.items():
            print(f"    {dte_bucket} DTE: {data['count']} trades, "
                  f"win rate {data['win_rate']:.1f}%, "
                  f"avg P&L ${data['avg_pnl']:.2f}")

    print()


def run_validation(start_date, end_date):
    """Run the 6 SIGNALS.md validation backtests.

    1. Iron condors: dealer filter (LONG_GAMMA) vs all conditions
    2. Iron condors: regime filter (HIGH_IV) vs all conditions
    3. Credit spreads: with vs without directional bias filter
    4. Credit spreads: GARCH edge > 5% vs all
    5. Iron condors: DTE window comparison (3-5, 5-7, 7-10, 10-14)
    6. All strategies: 50% profit target vs hold to expiry
    """
    symbol = "SPY"

    print("\n" + "=" * 70)
    print("  SIGNALS.md Validation Backtests")
    print(f"  Symbol: {symbol}  |  Period: {start_date} to {end_date}")
    print("=" * 70)

    # --- Test 1: Iron condors — dealer filter vs no filter ---
    print("\n" + "-" * 70)
    print("  TEST 1: Iron Condors — LONG_GAMMA dealer filter vs all conditions")
    print("-" * 70)

    base_ic = BacktestRequest(
        strategy="iron_condor", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=7, entry_dte_max=14,
    )
    result_no_filter = run_local_backtest(base_ic)
    print_result(result_no_filter, "IC — No filters (baseline)")

    ic_dealer = BacktestRequest(
        strategy="iron_condor", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=7, entry_dte_max=14,
        dealer_filter=True,
    )
    result_dealer = run_local_backtest(ic_dealer)
    print_result(result_dealer, "IC — Dealer filter ON (LONG_GAMMA only)")

    # --- Test 2: Iron condors — regime filter vs no filter ---
    print("-" * 70)
    print("  TEST 2: Iron Condors — HIGH_IV regime filter vs all conditions")
    print("-" * 70)

    ic_regime = BacktestRequest(
        strategy="iron_condor", symbol=symbol,
        start_date=start_date, end_date=end_date,
        entry_dte_min=7, entry_dte_max=14,
        regime_filter=True,
    )
    result_regime = run_local_backtest(ic_regime)
    print_result(result_regime, "IC — Regime filter ON (HIGH_IV only)")

    # --- Test 3: Credit spreads — bias filter vs no filter ---
    print("-" * 70)
    print("  TEST 3: Credit Spreads — Directional bias filter vs all conditions")
    print("-" * 70)

    for strat in ["short_put_spread", "short_call_spread"]:
        base_cs = BacktestRequest(
            strategy=strat, symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=3, entry_dte_max=10,
        )
        result_cs_base = run_local_backtest(base_cs)
        print_result(result_cs_base, f"{strat} — No filters (baseline)")

        cs_bias = BacktestRequest(
            strategy=strat, symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=3, entry_dte_max=10,
            bias_filter=True,
        )
        result_cs_bias = run_local_backtest(cs_bias)
        print_result(result_cs_bias, f"{strat} — Bias filter ON")

    # --- Test 4: Credit spreads — GARCH edge > 5% vs all ---
    print("-" * 70)
    print("  TEST 4: Credit Spreads — GARCH edge > 5% vs all")
    print("-" * 70)

    for strat in ["short_put_spread", "short_call_spread"]:
        cs_edge = BacktestRequest(
            strategy=strat, symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=3, entry_dte_max=10,
            edge_threshold=5.0,
        )
        result_cs_edge = run_local_backtest(cs_edge)
        print_result(result_cs_edge, f"{strat} — GARCH edge > 5%")

    # --- Test 5: Iron condors — DTE window comparison ---
    print("-" * 70)
    print("  TEST 5: Iron Condors — DTE window comparison")
    print("-" * 70)

    dte_windows = [(3, 5), (5, 7), (7, 10), (10, 14)]
    for min_dte, max_dte in dte_windows:
        ic_dte = BacktestRequest(
            strategy="iron_condor", symbol=symbol,
            start_date=start_date, end_date=end_date,
            entry_dte_min=min_dte, entry_dte_max=max_dte,
        )
        result_dte = run_local_backtest(ic_dte)
        print_result(result_dte, f"IC — {min_dte}-{max_dte} DTE window")

    # --- Test 6: All strategies — 50% target vs hold to expiry ---
    print("-" * 70)
    print("  TEST 6: All Strategies — 50% profit target vs hold to expiry")
    print("-" * 70)

    all_strategies = [
        ("iron_condor", 7, 14),
        ("short_put_spread", 3, 10),
        ("short_call_spread", 3, 10),
        ("long_call_spread", 3, 14),
        ("long_put_spread", 3, 14),
        ("butterfly", 3, 7),
    ]

    for strat, min_dte, max_dte in all_strategies:
        for exit_rule in ["50pct", "hold"]:
            req = BacktestRequest(
                strategy=strat, symbol=symbol,
                start_date=start_date, end_date=end_date,
                entry_dte_min=min_dte, entry_dte_max=max_dte,
                exit_rule=exit_rule,
            )
            result = run_local_backtest(req)
            rule_label = "50% target" if exit_rule == "50pct" else "Hold to expiry"
            print_result(result, f"{strat} — {rule_label}")

    print("=" * 70)
    print("  Validation complete.")
    print("=" * 70)


def main(argv=None):
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = date.fromisoformat(args.start)

    if args.validate:
        run_validation(start_date, end_date)
        return

    if args.compare:
        symbols = [s.strip() for s in (args.symbols or args.symbol).split(',')]
        strategies = [s.strip() for s in (args.strategies or args.strategy).split(',')]

        print(f"\n  === Comparing {len(strategies)} strategies x {len(symbols)} symbols ===\n")

        for strategy in strategies:
            for symbol in symbols:
                req = BacktestRequest(
                    strategy=strategy, symbol=symbol,
                    start_date=start_date, end_date=end_date,
                    entry_delta=args.delta,
                    entry_dte_min=args.min_dte, entry_dte_max=args.max_dte,
                    min_score=args.min_score,
                    regime_filter=args.regime_filter,
                    bias_filter=args.bias_filter,
                    dealer_filter=args.dealer_filter,
                    edge_threshold=args.edge_threshold,
                    exit_rule=args.exit_rule,
                    slippage_pct=args.slippage,
                )
                result = run_local_backtest(req)
                print_result(result)
        return

    # Single backtest
    req = BacktestRequest(
        strategy=args.strategy, symbol=args.symbol,
        start_date=start_date, end_date=end_date,
        entry_delta=args.delta,
        entry_dte_min=args.min_dte, entry_dte_max=args.max_dte,
        min_score=args.min_score,
        regime_filter=args.regime_filter,
        bias_filter=args.bias_filter,
        dealer_filter=args.dealer_filter,
        edge_threshold=args.edge_threshold,
        exit_rule=args.exit_rule,
        slippage_pct=args.slippage,
    )

    result = run_local_backtest(req)
    print_result(result)


if __name__ == '__main__':
    main()
