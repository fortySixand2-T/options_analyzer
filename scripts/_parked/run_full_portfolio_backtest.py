#!/usr/bin/env python3
"""Full portfolio backtest across all tickers and all DTE tiers.

Runs every enabled agent on SPY, QQQ, IWM across short-term, medium-term,
and long-term tiers. Produces a unified portfolio view with per-agent,
per-tier, and aggregate statistics.

Usage:
    python scripts/run_full_portfolio_backtest.py
    python scripts/run_full_portfolio_backtest.py --start 2023-01-01 --end 2026-01-01
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agents.agent_config import load_config
from backtest.agent_backtest import run_agent_backtest

SEP = "=" * 80
LINE = "-" * 80


def main():
    parser = argparse.ArgumentParser(description="Full portfolio backtest")
    parser.add_argument("--ticker", nargs="+", default=["SPY", "QQQ", "IWM"])
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument("--slippage", type=float, default=3.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    config = load_config()
    tickers = args.ticker

    results = {}
    for tier in ["short_term", "swing", "medium_term", "long_term"]:
        print(f"Running {tier} backtest...", flush=True)
        results[tier] = run_agent_backtest(
            tickers=tickers,
            start_date=args.start,
            end_date=args.end,
            config=config,
            dte_tier=tier,
            slippage_pct=args.slippage,
        )

    hold_days = {"short_term": 7, "swing": 30, "medium_term": 60, "long_term": 120}

    print(f"\n{SEP}")
    print(f"  FULL PORTFOLIO BACKTEST")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Period:  {args.start} to {args.end}")
    print(f"  Slippage: {args.slippage}%  |  Portfolio: $100,000")
    print(SEP)

    all_trades = []
    agent_rows = []

    for tier, result in results.items():
        tier_label = tier.upper().replace("_", " ")
        print(f"\n{LINE}")
        print(f"  {tier_label} TIER")
        print(LINE)

        for agent_id, ar in result.agent_results.items():
            stats = ar.stats
            trades = ar.trades

            print(f"\n  >> {agent_id} ({ar.config.capital_pct*100:.0f}% capital)")
            print(f"     {ar.config.description}")

            if not trades:
                print(f"     No trades")
                continue

            pnls = np.array([t.pnl for t in trades])
            hd = hold_days[tier]
            sharpe = (
                np.mean(pnls) / np.std(pnls, ddof=1) * np.sqrt(252 / hd)
                if len(pnls) > 1 and np.std(pnls) > 0
                else 0
            )

            print(
                f"     Trades: {len(trades):>4}  |  "
                f"Win: {stats.win_rate:>5.1f}%  |  "
                f"PF: {stats.profit_factor:>5.2f}  |  "
                f"Sharpe: {sharpe:>+6.3f}"
            )
            print(
                f"     P&L: ${stats.total_pnl:>+10.2f}  |  "
                f"Avg: ${stats.avg_pnl:>+8.2f}  |  "
                f"MaxDD: ${stats.max_drawdown:>9.2f}"
            )

            exits = {}
            for t in trades:
                exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
            exit_str = "  ".join(
                f"{r}:{c}" for r, c in sorted(exits.items(), key=lambda x: -x[1])
            )
            print(f"     Exits: {exit_str}")

            reg = {}
            for t in trades:
                r = t.regime or "?"
                if r not in reg:
                    reg[r] = [0, 0, 0.0]
                reg[r][0] += 1
                reg[r][2] += t.pnl
                if t.win:
                    reg[r][1] += 1
            reg_str = "  ".join(
                f"{r}:{d[0]}t/{d[1]/max(d[0],1)*100:.0f}%/${d[2]:+.0f}"
                for r, d in sorted(reg.items())
            )
            print(f"     Regimes: {reg_str}")

            all_trades.extend(trades)
            agent_rows.append(
                {
                    "agent": agent_id,
                    "tier": tier,
                    "capital": ar.config.capital_pct,
                    "trades": len(trades),
                    "win_rate": stats.win_rate,
                    "total_pnl": stats.total_pnl,
                    "max_dd": stats.max_drawdown,
                    "pf": stats.profit_factor,
                    "sharpe": sharpe,
                }
            )

    # Tier summaries
    print(f"\n{SEP}")
    print(f"  TIER SUMMARIES")
    print(SEP)
    print(
        f"  {'Tier':>15} {'Trades':>7} {'Win%':>7} "
        f"{'Total P&L':>12} {'MaxDD':>10} {'Sharpe':>8}"
    )

    for tier in ["short_term", "swing", "medium_term", "long_term"]:
        ta = [a for a in agent_rows if a["tier"] == tier]
        if not ta:
            continue
        t_trades = sum(a["trades"] for a in ta)
        t_pnl = sum(a["total_pnl"] for a in ta)
        t_dd = max(a["max_dd"] for a in ta)
        t_wins = sum(a["trades"] * a["win_rate"] / 100 for a in ta)
        t_wr = t_wins / max(t_trades, 1) * 100

        hd = hold_days[tier]
        tier_pnls = []
        for ar in results[tier].agent_results.values():
            tier_pnls.extend([t.pnl for t in ar.trades])
        tier_pnls = np.array(tier_pnls) if tier_pnls else np.array([0])
        t_sharpe = (
            np.mean(tier_pnls) / np.std(tier_pnls, ddof=1) * np.sqrt(252 / hd)
            if len(tier_pnls) > 1 and np.std(tier_pnls) > 0
            else 0
        )

        label = tier.upper().replace("_", " ")
        print(
            f"  {label:>15} {t_trades:>7} {t_wr:>6.1f}% "
            f"${t_pnl:>+11.2f} ${t_dd:>9.2f} {t_sharpe:>+7.3f}"
        )

    # Full portfolio
    print(f"\n{SEP}")
    print(f"  FULL PORTFOLIO")
    print(SEP)

    total_trades = len(all_trades)
    total_pnl = sum(t.pnl for t in all_trades)
    total_wins = sum(1 for t in all_trades if t.win)
    all_pnls = np.array([t.pnl for t in all_trades]) if all_trades else np.array([0])

    equity = np.cumsum(all_pnls)
    peak = np.maximum.accumulate(equity)
    drawdowns = equity - peak
    max_dd = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0

    port_sharpe = (
        np.mean(all_pnls) / np.std(all_pnls, ddof=1) * np.sqrt(252 / 30)
        if len(all_pnls) > 1 and np.std(all_pnls) > 0
        else 0
    )

    gross_profit = sum(t.pnl for t in all_trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in all_trades if t.pnl < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    roi = total_pnl / 100000 * 100

    print(f"  Total trades:      {total_trades}")
    print(f"  Win rate:          {total_wins/max(total_trades,1)*100:.1f}%")
    print(f"  Total P&L:         ${total_pnl:+,.2f}")
    print(f"  ROI:               {roi:+.1f}%")
    print(f"  Gross profit:      ${gross_profit:+,.2f}")
    print(f"  Gross loss:        ${gross_loss:,.2f}")
    print(f"  Profit factor:     {pf:.2f}")
    print(f"  Max drawdown:      ${max_dd:,.2f}")
    print(f"  Portfolio Sharpe:  {port_sharpe:+.3f}")
    print(f"  Equity high:       ${np.max(equity):+,.2f}")
    print(f"  Equity final:      ${equity[-1]:+,.2f}")

    # Capital allocation
    print(f"\n  Capital allocation (enabled):")
    enabled_cap = sum(a["capital"] for a in agent_rows)
    for a in agent_rows:
        print(
            f"    {a['agent']:>25}: {a['capital']*100:>4.0f}%  "
            f"${a['total_pnl']:>+10.2f}  ({a['trades']} trades, "
            f"Sharpe {a['sharpe']:+.2f})"
        )
    print(
        f"    {'TOTAL':>25}: {enabled_cap*100:>4.0f}%  "
        f"${total_pnl:>+10.2f}  ({total_trades} trades)"
    )
    print(f"    {'CASH BUFFER':>25}: {(1-enabled_cap)*100:>4.0f}%")

    # Exit reasons
    print(f"\n  Exit reasons (all agents):")
    all_exits = {}
    for t in all_trades:
        all_exits[t.exit_reason] = all_exits.get(t.exit_reason, 0) + 1
    for reason, count in sorted(all_exits.items(), key=lambda x: -x[1]):
        pct = count / total_trades * 100
        # Win rate per exit reason
        wins = sum(1 for t in all_trades if t.exit_reason == reason and t.win)
        wr = wins / count * 100
        avg_pnl = sum(t.pnl for t in all_trades if t.exit_reason == reason) / count
        print(
            f"    {reason:>18}: {count:>4} ({pct:>5.1f}%)  "
            f"win {wr:>5.1f}%  avg ${avg_pnl:>+8.2f}"
        )

    # Regime breakdown
    print(f"\n  Regime breakdown (all agents):")
    all_reg = {}
    for t in all_trades:
        r = t.regime or "?"
        if r not in all_reg:
            all_reg[r] = [0, 0, 0.0]
        all_reg[r][0] += 1
        all_reg[r][2] += t.pnl
        if t.win:
            all_reg[r][1] += 1
    print(f"    {'Regime':>15} {'Trades':>7} {'Win%':>7} {'P&L':>12} {'Avg':>10}")
    for r, d in sorted(all_reg.items()):
        wr = d[1] / max(d[0], 1) * 100
        avg = d[2] / max(d[0], 1)
        print(f"    {r:>15} {d[0]:>7} {wr:>6.1f}% ${d[2]:>+11.2f} ${avg:>+9.2f}")


if __name__ == "__main__":
    main()
