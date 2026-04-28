#!/usr/bin/env python3
"""
CLI for 0 DTE intraday backtesting.

Usage:
    python scripts/run_intraday_backtest.py --strategy 0dte_iron_condor --symbol SPY
    python scripts/run_intraday_backtest.py --strategy 0dte_iron_condor --symbol SPY --no-day-filter
    python scripts/run_intraday_backtest.py --strategy 0dte_put_spread --symbol SPY --day-type TREND_DAY
    python scripts/run_intraday_backtest.py --strategy 0dte_iron_condor --symbol SPY --entry-times 10:00,11:00,12:00

Options Analytics Team — 2026-04
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="0 DTE intraday backtester",
    )
    parser.add_argument(
        "--strategy", default="0dte_iron_condor",
        help="Strategy: 0dte_iron_condor, 0dte_put_spread, 0dte_call_spread, 0dte_butterfly",
    )
    parser.add_argument(
        "--symbol", default="SPY",
        help="Ticker symbol (default: SPY)",
    )
    parser.add_argument(
        "--start", default=None,
        help="Start date YYYY-MM-DD (default: 30 days ago)",
    )
    parser.add_argument(
        "--end", default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--entry-times", default="10:00,10:30,11:00",
        help="Comma-separated entry times in ET (default: 10:00,10:30,11:00)",
    )
    parser.add_argument(
        "--exit-time", default="15:45",
        help="Force exit time ET (default: 15:45)",
    )
    parser.add_argument(
        "--day-type", default="RANGE_DAY",
        help="Day-type filter: RANGE_DAY, TREND_DAY, UNCERTAIN (default: RANGE_DAY)",
    )
    parser.add_argument(
        "--no-day-filter", action="store_true",
        help="Disable day-type filter (trade all days)",
    )
    parser.add_argument(
        "--dealer-filter", default="LONG_GAMMA",
        help="Dealer regime filter (default: LONG_GAMMA, use 'none' to disable)",
    )
    parser.add_argument(
        "--wing-width", type=float, default=5.0,
        help="Wing width in $ (default: 5.0)",
    )
    parser.add_argument(
        "--profit-target", type=float, default=50.0,
        help="Profit target as %% of max profit (default: 50)",
    )
    parser.add_argument(
        "--stop-loss", type=float, default=200.0,
        help="Stop loss as %% of max profit (default: 200 = 2x)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    from backtest.intraday_backtest import run_intraday_backtest
    from backtest.intraday_models import IntradayBacktestRequest

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = date.fromisoformat(args.start) if args.start else end_date - timedelta(days=30)

    entry_windows = [t.strip() for t in args.entry_times.split(",")]
    day_type_filter = None if args.no_day_filter else args.day_type
    dealer_filter = None if args.dealer_filter.lower() == "none" else args.dealer_filter

    request = IntradayBacktestRequest(
        strategy=args.strategy,
        symbol=args.symbol.upper(),
        start_date=start_date,
        end_date=end_date,
        entry_windows=entry_windows,
        exit_time=args.exit_time,
        day_type_filter=day_type_filter,
        dealer_filter=dealer_filter,
        wing_width=args.wing_width,
        profit_target_pct=args.profit_target,
        stop_loss_pct=args.stop_loss,
    )

    result = run_intraday_backtest(request)

    if args.json:
        print(result.model_dump_json(indent=2))
        return

    # Pretty print
    s = result.stats
    print()
    print("=" * 60)
    print(f"0 DTE Intraday Backtest: {args.strategy}")
    print(f"Symbol: {args.symbol}  |  {start_date} → {end_date}")
    print("=" * 60)
    print()
    print(f"  Days traded:       {s.days_traded}")
    print(f"  Days skipped:      {s.days_skipped}")
    if s.skip_reasons:
        for reason, count in sorted(s.skip_reasons.items()):
            print(f"    {reason}: {count}")
    print()
    print(f"  Total trades:      {s.total_trades}")
    print(f"  Win rate:          {s.win_rate:.1f}%")
    print(f"  Avg win:           ${s.avg_win:.2f}")
    print(f"  Avg loss:          ${s.avg_loss:.2f}")
    print(f"  Avg P&L:           ${s.avg_pnl:.2f}")
    print(f"  Total P&L:         ${s.total_pnl:.2f}")
    print(f"  Profit factor:     {s.profit_factor:.2f}")
    print(f"  Max drawdown:      ${s.max_drawdown:.2f}")
    print(f"  Sharpe ratio:      {s.sharpe_ratio:.2f}")
    print()
    print(f"  Range day WR:      {s.range_day_win_rate:.1f}%")
    print(f"  Trend day WR:      {s.trend_day_win_rate:.1f}%")
    print(f"  Avg entry exhaust: {s.avg_entry_exhaustion:.1f}%")
    print()

    # Day type breakdown
    if result.day_type_breakdown:
        print("  Day Type Breakdown:")
        for dt, info in result.day_type_breakdown.items():
            print(f"    {dt}: {info['trades']} trades, {info['win_rate']:.1f}% WR, ${info['total_pnl']:.2f}")
        print()

    # Entry time breakdown
    if result.entry_time_breakdown:
        print("  Entry Time Breakdown:")
        for et, info in result.entry_time_breakdown.items():
            print(f"    {et}: {info['trades']} trades, {info['win_rate']:.1f}% WR, ${info['total_pnl']:.2f}")
        print()

    # Trade list (last 10)
    if result.trades:
        print("  Recent Trades:")
        print(f"  {'Date':<12} {'Entry':<6} {'Exit':<6} {'P&L':>8} {'Reason':<14} {'DayType':<10}")
        print(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*8} {'-'*14} {'-'*10}")
        for t in result.trades[-10:]:
            print(
                f"  {t.trade_date}  {t.entry_time:<6} {t.exit_time:<6} "
                f"${t.pnl:>7.2f} {t.exit_reason:<14} {t.day_type:<10}"
            )
        print()


if __name__ == "__main__":
    main()
