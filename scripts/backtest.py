#!/usr/bin/env python3
"""
Backtest CLI — validate options strategies against historical data.

Usage:
    python scripts/backtest.py --strategy iron_condor --symbol SPY
    python scripts/backtest.py --strategy iron_condor --symbol SPY --start 2020-01-01 --end 2025-12-31
    python scripts/backtest.py --local --strategy credit_spread --symbol QQQ
    python scripts/backtest.py --compare --symbols SPY,QQQ --strategies iron_condor,short_put_spread

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
from backtest.tt_backtest import run_tt_backtest
from backtest.analyzer import compute_regime_breakdown


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
    p.add_argument('--local', action='store_true',
                   help='Force local backtester (skip TT API)')
    p.add_argument('--compare', action='store_true',
                   help='Compare multiple strategies/symbols')
    p.add_argument('--delta', type=float, default=0.20,
                   help='Target entry delta (default: 0.20)')
    p.add_argument('--min-dte', type=int, default=21,
                   help='Min DTE for entry (default: 21)')
    p.add_argument('--max-dte', type=int, default=45,
                   help='Max DTE for entry (default: 45)')
    p.add_argument('--min-score', type=float, default=0.0,
                   help='Min strategy score to enter (default: 0)')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='Verbose output')
    return p.parse_args(argv)


def print_result(result):
    """Print backtest result summary."""
    req = result.request
    stats = result.stats

    source_tag = f"[{result.source}]"
    cached_tag = " [cached]" if result.cached else ""

    print()
    print(f"  === Backtest: {req.strategy} on {req.symbol} {source_tag}{cached_tag} ===")
    print(f"  Period: {req.start_date} to {req.end_date}")
    print(f"  Entry: delta={req.entry_delta}, DTE {req.entry_dte_min}-{req.entry_dte_max}")
    print(f"  Exit: profit {req.exit_profit_pct}% / loss {req.exit_loss_pct}% / DTE {req.exit_dte}")
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

    print()


def main(argv=None):
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = date.fromisoformat(args.start)

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
    )

    # Try TT first, fall back to local
    result = None
    if not args.local:
        result = run_tt_backtest(req)

    if result is None:
        result = run_local_backtest(req)

    print_result(result)


if __name__ == '__main__':
    main()
