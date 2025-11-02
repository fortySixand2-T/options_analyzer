#!/usr/bin/env python3
"""
Flexible Options Test Runner
=============================

This script can be run from the command line and will either:
- Load an option configuration from a JSON file (user-specified)
- Fetch real-world market data via yfinance (ticker/live mode)

Usage:  
    python src/options_test_runner.py --json config/my_test_config.json
    python src/options_test_runner.py --live --ticker TSLA --days_to_expiry 30

Required Modules:
    PyYAML, yfinance, numpy, pandas, (all in requirements.txt)
"""

import sys
import argparse
import json
from pathlib import Path
import numpy as np
from datetime import datetime

sys.path.append(str(Path(__file__).parent))  # Allows running from project root or src/

from options_analyzer import OptionsAnalyzer
from utils.config import load_config_from_json

# --- Real world data functions ---
def fetch_live_config(ticker, days_to_expiry):
    import yfinance as yf
    tk = yf.Ticker(ticker)

    stock_price = tk.info.get('currentPrice', None)
    if not stock_price:
        hist = tk.history(period="1d")
        stock_price = hist['Close'].iloc[-1]

    hist = tk.history(period="60d")
    returns = hist['Close'].pct_change().dropna()
    historical_vol = np.std(returns) * np.sqrt(252)
    options = tk.options
    if not options:
        raise ValueError(f"No options for {ticker}")

    # Find expiry near target
    target_expiry = None
    for exp in options:
        days = (datetime.strptime(exp, "%Y-%m-%d") - datetime.now()).days
        if abs(days - days_to_expiry) <= 7:
            target_expiry = exp
            break
    target_expiry = target_expiry or options[0]
    option_chain = tk.option_chain(target_expiry)
    calls = option_chain.calls

    # Pick 4 strikes close to current price
    strikes = sorted(calls['strike'].unique())
    idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - stock_price))
    selected = strikes[max(0, idx-2):idx+2]
    results = []

    for strike in selected:
        config = {
            'ticker': ticker,
            'current_price': stock_price,
            'strike_price': strike,
            'expiration_date': target_expiry,
            'option_type': 'call',
            'implied_volatility': historical_vol,
            'risk_free_rate': 0.045,
            'name': f'{ticker} Call ${strike:.2f}'
        }
        results.append(config)
    return results

# --- Main runner ---
def run_option_test(configs, export_dir=None):
    for config in configs:
        default_name = f"{config['ticker']} {config['option_type'].title()} ${config['strike_price']}"
        test_name = config.get('name', default_name)
        print(f"\n{'='*60}\nTEST: {test_name}")
        analyzer = OptionsAnalyzer(config)
        analyzer.print_summary()
        analyzer.run_full_analysis(export_results=True, export_dir=export_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Options test runner")
    parser.add_argument('--json', type=str, help='JSON config file (single or list of configs)')
    parser.add_argument('--live', action='store_true', help='Use live market data')
    parser.add_argument('--ticker', type=str, help='Ticker for live mode')
    parser.add_argument('--days_to_expiry', type=int, default=30, help='Days to expiry for live mode')
    parser.add_argument('--export_dir', type=str, default='./exports', help='Directory to save results')
    args = parser.parse_args()

    if args.json:
        with open(args.json) as f:
            data = json.load(f)

        if isinstance(data, dict) and 'configurations' in data:
            configs = data['configurations']
        elif isinstance(data, list):
            configs = data
        else:
            configs = [data]
        run_option_test(configs, export_dir=args.export_dir)

    elif args.live:
        if not args.ticker:
            print("You must specify --ticker in live mode.")
            sys.exit(1)
        live_configs = fetch_live_config(args.ticker, args.days_to_expiry)
        run_option_test(live_configs, export_dir=args.export_dir)

    else:
        print("Please specify either --json or --live mode with options.")
        parser.print_help()
