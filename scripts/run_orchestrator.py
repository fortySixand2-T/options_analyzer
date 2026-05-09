#!/usr/bin/env python3
"""
Multi-agent paper trading orchestrator CLI.

Usage:
    python scripts/run_orchestrator.py                    # Run one cycle
    python scripts/run_orchestrator.py --dry-run          # Preview without logging
    python scripts/run_orchestrator.py --agent momentum   # Run only one agent
    python scripts/run_orchestrator.py --stats            # Per-agent performance
    python scripts/run_orchestrator.py --stats --agent momentum  # Single agent detail
    python scripts/run_orchestrator.py --pause vol_harvester     # Pause an agent
    python scripts/run_orchestrator.py --enable vol_harvester    # Re-enable an agent

Options Analytics Team — 2026-05
"""

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def show_stats(config, agent_filter=None):
    """Display per-agent performance statistics."""
    from data.shadow_store import get_agent_stats, get_stats

    agents = config.agents
    if agent_filter:
        if agent_filter not in agents:
            print(f"Unknown agent: {agent_filter}", file=sys.stderr)
            sys.exit(1)
        agents = {agent_filter: agents[agent_filter]}

    print(f"\n{'='*60}")
    print(f"Multi-Agent Paper Trading Stats")
    print(f"{'='*60}")
    print(f"  Portfolio value:  ${config.portfolio_value:,.0f}")
    print(f"  Tickers:          {', '.join(config.tickers)}")
    print()

    for name, cfg in agents.items():
        stats = get_agent_stats(name)
        capital = config.portfolio_value * cfg.capital_pct
        status = "ENABLED" if cfg.enabled else "DISABLED"

        print(f"  Agent: {name} [{status}]")
        print(f"    Description:    {cfg.description}")
        print(f"    Capital:        ${capital:,.0f} ({cfg.capital_pct:.0%})")
        print(f"    Strategies:     {', '.join(cfg.allowed_strategies)}")
        print(f"    Min confluence: {cfg.min_confluence}")
        if cfg.required_regimes:
            print(f"    Regimes:        {', '.join(cfg.required_regimes)}")
        if cfg.min_iv_rv_edge_pct > 0:
            print(f"    Min IV-RV edge: {cfg.min_iv_rv_edge_pct}%")
        print(f"    Open trades:    {stats['open_trades']}")
        print(f"    Closed trades:  {stats['closed_trades']}")
        if stats['closed_trades'] > 0:
            print(f"    Win rate:       {stats['win_rate']}%")
            print(f"    Total P&L:      ${stats['total_pnl']:,.2f}")
            print(f"    Avg P&L:        ${stats['avg_pnl']:,.2f}")
            print(f"    Max drawdown:   ${stats['max_drawdown']:,.2f}")
            if stats['by_strategy']:
                print(f"    By strategy:")
                for s, sd in stats['by_strategy'].items():
                    wr = round(sd['wins'] / sd['trades'] * 100, 1) if sd['trades'] else 0
                    print(f"      {s}: {sd['trades']} trades, {wr}% win, ${sd['pnl']:,.2f}")
        print()

    # Aggregate
    all_stats = get_stats()
    print(f"  Portfolio Aggregate:")
    print(f"    Total open:     {all_stats['open_trades']}")
    print(f"    Total closed:   {all_stats['closed_trades']}")
    if all_stats['closed_trades'] > 0:
        print(f"    Win rate:       {all_stats['win_rate']}%")
        print(f"    Total P&L:      ${all_stats['total_pnl']:,.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent paper trading orchestrator",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to agents.yaml (default: config/agents.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview trades without logging to DB",
    )
    parser.add_argument(
        "--agent", default=None,
        help="Run only this specific agent",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show per-agent performance statistics",
    )
    parser.add_argument(
        "--pause", metavar="AGENT_ID",
        help="Pause an agent (prevents new entries)",
    )
    parser.add_argument(
        "--enable", metavar="AGENT_ID",
        help="Re-enable a paused agent",
    )
    parser.add_argument(
        "--tickers", default=None,
        help="Override tickers (comma-separated)",
    )

    args = parser.parse_args()

    from agents.agent_config import load_config
    config = load_config(args.config)

    # Pause/enable commands
    if args.pause:
        from agents.risk_ledger import RiskLedger
        ledger = RiskLedger(config.guardrails, config.portfolio_value)
        ledger.pause_agent(args.pause, "Manual pause via CLI")
        print(f"Agent '{args.pause}' paused.")
        return

    if args.enable:
        from agents.risk_ledger import RiskLedger
        ledger = RiskLedger(config.guardrails, config.portfolio_value)
        ledger.enable_agent(args.enable)
        print(f"Agent '{args.enable}' enabled.")
        return

    # Stats
    if args.stats:
        show_stats(config, args.agent)
        return

    # Run cycle
    from agents.orchestrator import Orchestrator

    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    orchestrator = Orchestrator(config)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    agent_label = f" (agent: {args.agent})" if args.agent else ""
    print(f"\n{'='*60}")
    print(f"Multi-Agent Orchestrator — {mode}{agent_label}")
    print(f"{'='*60}")
    print(f"  Portfolio:  ${config.portfolio_value:,.0f}")
    print(f"  Tickers:    {', '.join(tickers or config.tickers)}")
    print(f"  Agents:     {', '.join(n for n, a in config.agents.items() if a.enabled)}")
    print()

    result = orchestrator.run_cycle(
        tickers=tickers,
        dry_run=args.dry_run,
        agent_filter=args.agent,
    )

    print(f"\n{'='*60}")
    print(f"Cycle Summary")
    print(f"{'='*60}")
    print(f"  Tickers scanned:     {result.tickers_scanned}")
    print(f"  Candidates generated:{result.candidates_generated}")
    print(f"  Proposals created:   {result.proposals_created}")
    print(f"  Proposals approved:  {result.proposals_approved}")
    print(f"  Trades logged:       {result.trades_logged}")

    if result.agents_paused:
        print(f"  Agents paused:       {', '.join(result.agents_paused)}")
    if result.portfolio_killed:
        print(f"  KILL SWITCH:         {result.kill_reason}")

    if result.details:
        print(f"\n  Trades:")
        for d in result.details:
            prefix = "  [DRY]" if d["dry_run"] else "  "
            print(f"  {prefix} {d['agent']:>15} | {d['ticker']:>5} | "
                  f"{d['strategy']:<20} | score={d['score']:.1f} | {d['direction']}")

    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for e in result.errors[:10]:
            print(f"    - {e}")

    print()


if __name__ == "__main__":
    main()
