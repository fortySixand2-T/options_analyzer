#!/usr/bin/env python3
"""
Implied Volatility Surface Runner
===================================

Standalone CLI for fetching live option chains, computing per-strike/expiry
implied volatilities, and saving the vol surface and smile charts.

Usage:
    python src/vol_surface_runner.py --ticker AAPL
    python src/vol_surface_runner.py --ticker SPY --max_expiries 8 --r 0.05 --export_dir ./vol_surface/
"""

import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

import matplotlib
matplotlib.use('Agg')

from analytics.vol_surface import fetch_vol_surface, plot_vol_surface


def main():
    parser = argparse.ArgumentParser(description='Implied Volatility Surface')
    parser.add_argument('--ticker', required=True, type=str,
                        help='Underlying symbol (e.g. AAPL)')
    parser.add_argument('--max_expiries', type=int, default=6,
                        help='Maximum number of expiry dates to fetch (default 6)')
    parser.add_argument('--r', type=float, default=0.045,
                        help='Risk-free rate (default 0.045 = 4.5%%)')
    parser.add_argument('--export_dir', type=str, default='./vol_surface',
                        help='Output directory for charts and CSV (default ./vol_surface)')
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    ticker = args.ticker.upper()

    print(f"\nFetching option chain for {ticker} (max {args.max_expiries} expiries, r={args.r:.3f})...")
    df = fetch_vol_surface(ticker, r=args.r, max_expiries=args.max_expiries)

    if df.empty:
        print("No valid IV data returned.  Check that yfinance can reach the market and the ticker is valid.")
        sys.exit(1)

    # --- Print IV table ---
    print(f"\n{'='*70}")
    print(f"  {ticker} Implied Volatility Table ({len(df)} options)")
    print(f"{'='*70}")
    summary = (
        df.groupby(['expiry', 'option_type'])
        .agg(n=('iv', 'count'), iv_min=('iv', 'min'), iv_mean=('iv', 'mean'), iv_max=('iv', 'max'))
        .round(4)
    )
    print(summary.to_string())
    print(f"{'='*70}\n")

    # --- Save CSV ---
    csv_path = export_dir / f"{ticker}_vol_surface.csv"
    df.to_csv(csv_path, index=False)
    print(f"  CSV saved: {csv_path}")

    # --- Plot vol surface ---
    surface_path = export_dir / f"{ticker}_vol_surface.png"
    fig = plot_vol_surface(df, ticker, save_path=str(surface_path))
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"  Surface chart saved: {surface_path}")

    print(f"\nDone.  Output in {export_dir}/\n")


if __name__ == '__main__':
    main()
