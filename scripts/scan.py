#!/usr/bin/env python3
"""
Options Chain Scanner CLI — scan index and equity options for trade signals.

Usage:
    python scripts/scan.py SPY --max-dte 14 --top 10
    python scripts/scan.py SPY,QQQ,IWM --strategies --export results.csv
    python scripts/scan.py SPY --provider tastytrade --min-dte 0 --max-dte 7

Environment:
    TT_USERNAME / TT_PASSWORD — Tastytrade credentials (auto-selects TT provider)
    TT_SANDBOX=1              — Use TT sandbox environment

Options Analytics Team — 2026-04
"""

import argparse
import csv
import json
import logging
import os
import sys

# Ensure src/ is on the path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from scanner import OptionSignal, scan_watchlist
from scanner.providers import create_provider
from scanner.scanner import OptionsScanner


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='Options Scanner — find high-conviction trade signals',
    )
    p.add_argument('tickers', type=str, nargs='?', default=None,
                   help='Comma-separated ticker list (e.g. SPY,QQQ,IWM)')
    p.add_argument('--watchlist', type=str, default=None,
                   help='Path to JSON watchlist file')
    p.add_argument('--provider', type=str, default='auto',
                   choices=['auto', 'tastytrade', 'yfinance'],
                   help='Data provider (default: auto)')
    p.add_argument('--config', type=str, default=None,
                   help='Path to scanner config JSON')
    p.add_argument('--top', type=int, default=20,
                   help='Show top N signals (default: 20)')
    p.add_argument('--min-dte', type=int, default=None,
                   help='Minimum days to expiration')
    p.add_argument('--max-dte', type=int, default=None,
                   help='Maximum days to expiration')
    p.add_argument('--strategies', action='store_true',
                   help='Show strategy recommendations for each signal')
    p.add_argument('--export', type=str, default=None,
                   help='Export results to CSV file')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='Enable verbose logging')
    return p.parse_args(argv)


def load_tickers(args) -> list:
    """Resolve ticker list from positional arg or --watchlist."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    if args.watchlist:
        with open(args.watchlist) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [t.upper() for t in data]
        if isinstance(data, dict) and 'tickers' in data:
            return [t.upper() for t in data['tickers']]
    # Default watchlist from env
    env_watchlist = os.getenv('SCANNER_WATCHLIST', '')
    if env_watchlist:
        return [t.strip().upper() for t in env_watchlist.split(',') if t.strip()]
    return []


def print_signals(signals, top, provider_name):
    """Print a formatted table of top signals."""
    if not signals:
        print("\nNo signals found.\n")
        return

    shown = signals[:top]

    header = (
        f"{'Ticker':<7} {'Strike':>8} {'Expiry':<12} {'Type':<5} {'DTE':>4} "
        f"{'Mid':>8} {'Edge%':>7} {'Dir':<5} "
        f"{'IVRank':>6} {'Regime':<9} {'Delta':>7} {'Conv':>6}"
    )
    print()
    print("=" * len(header))
    print(f"  Options Scanner — Top {len(shown)} Signals  [provider: {provider_name}]")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for s in shown:
        print(
            f"{s.ticker:<7} {s.strike:>8.1f} {s.expiry:<12} {s.option_type:<5} {s.dte:>4} "
            f"${s.mid:>7.2f} {s.edge_pct:>+6.1f}% {s.direction:<5} "
            f"{s.iv_rank:>5.0f}% {s.iv_regime:<9} {s.delta:>+6.3f} {s.conviction:>5.1f}"
        )

    print("-" * len(header))
    print(f"  {len(signals)} total signals, showing top {len(shown)}")
    print()


def print_strategies(signals, top):
    """Print strategy recommendations for top signals."""
    try:
        from scanner.strategy_mapper import map_signal
        from scanner.strategy_pricer import price_recommendation
    except ImportError:
        print("  Strategy modules not available.\n")
        return

    shown = signals[:top]
    mapped = 0

    for s in shown:
        rec = map_signal(s)
        if rec is None:
            continue

        mapped += 1
        print(f"  {s.ticker} {s.strike:.0f} {s.option_type} {s.expiry} "
              f"(conv={s.conviction:.0f})")
        print(f"    Strategy: {rec.strategy_label}")
        print(f"    Rationale: {rec.rationale}")
        print(f"    Legs: {len(rec.legs)} | Risk: {rec.risk_profile} | "
              f"Edge: {rec.edge_source}")

        priced = price_recommendation(s, rec)
        if priced:
            print(f"    Entry: ${priced['entry']:.2f} | "
                  f"Exit: ${priced['exit_target']:.2f} ({priced['exit_pct']:.0f}%) | "
                  f"Stop: ${priced['option_stop']:.2f}")
            if priced.get('max_profit') and priced.get('max_loss'):
                print(f"    Max profit: ${priced['max_profit']:.2f} | "
                      f"Max loss: ${priced['max_loss']:.2f} | "
                      f"R:R {priced['risk_reward']}")
            print(f"    P(profit): {priced['prob_profit']:.1f}%")
        print()

    if mapped == 0:
        print("  No strategy recommendations for current signals.\n")


def print_regime_strategies(tickers, provider, config, top):
    """Run strategy scanner with regime detection and print results."""
    from strategy_scanner import scan_strategies

    result = scan_strategies(
        tickers=tickers,
        provider=provider,
        scanner_config=config,
        top=top,
    )

    regime = result["regime"]
    strategies = result["strategies"]

    print(f"  === Market Regime ===")
    print(f"  {regime.regime.value}")
    print(f"  {regime.rationale}")
    print(f"  VIX: {regime.vix.vix:.1f}")
    if regime.vix.vix3m:
        print(f"  VIX3M: {regime.vix.vix3m:.1f} (slope: {regime.vix.term_structure_slope:+.1f}%)")
    if regime.event_type:
        print(f"  Event: {regime.event_type} in {regime.event_days}d")
    print()

    if not strategies:
        print("  No strategy setups met minimum score threshold.\n")
        return

    print(f"  === Strategy Setups ({len(strategies)}) ===\n")
    for r in strategies:
        check_str = f"{r.checks_passed}/{r.checks_total}"
        print(f"  {r.ticker} — {r.strategy_label}  [score: {r.score:.0f}]  [{check_str} checks]")

        # Checklist
        for c in r.checklist:
            mark = "X" if c.passed else " "
            val = f" ({c.value})" if c.value else ""
            print(f"    [{mark}] {c.name}{val}")

        # Legs
        if r.legs:
            legs_str = ", ".join(
                f"{l['action']} {l['option_type']} ${l['strike']:.0f}"
                for l in r.legs
            )
            print(f"    Legs: {legs_str}")

        print(f"    {r.rationale}")
        print()


def export_csv(signals, path):
    """Export signals to CSV."""
    if not signals:
        return
    fields = [
        'ticker', 'strike', 'expiry', 'option_type', 'dte',
        'spot', 'bid', 'ask', 'mid', 'open_interest', 'bid_ask_spread_pct',
        'chain_iv', 'iv_rank', 'iv_percentile', 'iv_regime',
        'garch_vol', 'theo_price', 'edge_pct', 'direction',
        'delta', 'gamma', 'theta', 'vega', 'conviction',
    ]
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for s in signals:
            writer.writerow({k: getattr(s, k) for k in fields})
    print(f"  Exported {len(signals)} signals to {path}")


def main(argv=None):
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    tickers = load_tickers(args)
    if not tickers:
        print("Error: provide tickers as first argument, --watchlist, or set SCANNER_WATCHLIST env var")
        print("  Example: python scripts/scan.py SPY,QQQ,IWM")
        sys.exit(1)

    # Load config
    config = None
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    # Apply CLI overrides
    if args.min_dte is not None or args.max_dte is not None:
        if config is None:
            config = {}
        filt = config.setdefault('filter', {})
        if args.min_dte is not None:
            filt['min_dte'] = args.min_dte
        if args.max_dte is not None:
            filt['max_dte'] = args.max_dte

    # Create provider and scan
    provider = create_provider(name=args.provider)
    provider_name = type(provider).__name__
    # Unwrap CachedProvider to get actual provider name
    if hasattr(provider, '_inner'):
        provider_name = type(provider._inner).__name__

    signals = scan_watchlist(tickers, provider=provider, config=config)

    print_signals(signals, top=args.top, provider_name=provider_name)

    if args.strategies:
        print_regime_strategies(tickers, provider, config, args.top)

    if args.export:
        export_csv(signals, args.export)


if __name__ == '__main__':
    main()
