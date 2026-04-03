"""
CLI entry point for the options chain scanner.

Usage:
    python -m src.scanner.cli --tickers AAPL,MSFT,NVDA --top 10
    python -m src.scanner.cli --tickers AAPL --min_dte 20 --max_dte 60
    python -m src.scanner.cli --watchlist config/watchlist.json --top 20
    python -m src.scanner.cli --tickers AAPL --export scanner_results.csv

Options Analytics Team — 2026-04-02
"""

import argparse
import csv
import json
import logging
import sys
import os

# Ensure src/ is on the path for internal imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scanner import OptionSignal, scan_watchlist
from scanner.providers import create_provider


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='Options Chain Scanner — find high-conviction trade signals',
    )
    p.add_argument('--tickers', type=str, default=None,
                   help='Comma-separated ticker list (e.g. AAPL,MSFT,NVDA)')
    p.add_argument('--watchlist', type=str, default=None,
                   help='Path to JSON watchlist file (list of tickers)')
    p.add_argument('--provider', type=str, default='yfinance',
                   help='Data provider (default: yfinance)')
    p.add_argument('--config', type=str, default=None,
                   help='Path to scanner config JSON')
    p.add_argument('--top', type=int, default=20,
                   help='Show top N signals (default: 20)')
    p.add_argument('--min_dte', type=int, default=None,
                   help='Override minimum DTE filter')
    p.add_argument('--max_dte', type=int, default=None,
                   help='Override maximum DTE filter')
    p.add_argument('--export', type=str, default=None,
                   help='Export results to CSV file')
    return p.parse_args(argv)


def load_tickers(args) -> list:
    """Resolve ticker list from --tickers or --watchlist."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    if args.watchlist:
        with open(args.watchlist) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [t.upper() for t in data]
        if isinstance(data, dict) and 'tickers' in data:
            return [t.upper() for t in data['tickers']]
    return []


def print_signals(signals: list, top: int):
    """Print a formatted table of top signals."""
    if not signals:
        print("\nNo signals found.\n")
        return

    shown = signals[:top]

    # Header
    header = (
        f"{'Ticker':<7} {'Strike':>8} {'Expiry':<12} {'Type':<5} {'DTE':>4} "
        f"{'Mid':>8} {'Edge%':>7} {'Dir':<5} "
        f"{'IVRank':>6} {'Regime':<9} {'Delta':>7} {'Conv':>6}"
    )
    print()
    print("=" * len(header))
    print(f"  Options Scanner — Top {len(shown)} Signals")
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


def export_csv(signals: list, path: str):
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
    print(f"Exported {len(signals)} signals to {path}")


def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    tickers = load_tickers(args)
    if not tickers:
        print("Error: provide --tickers or --watchlist")
        sys.exit(1)

    # Load config
    config = None
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    # Apply CLI overrides
    if config and (args.min_dte is not None or args.max_dte is not None):
        filt = config.setdefault('filter', {})
        if args.min_dte is not None:
            filt['min_dte'] = args.min_dte
        if args.max_dte is not None:
            filt['max_dte'] = args.max_dte

    # Create provider and scan
    provider = create_provider(name=args.provider)
    signals = scan_watchlist(tickers, provider=provider, config=config)

    print_signals(signals, top=args.top)

    if args.export:
        export_csv(signals, args.export)


if __name__ == '__main__':
    main()
