#!/usr/bin/env python3
"""
Monte Carlo Options Runner
==========================

CLI for running Monte Carlo GBM simulations on European options.
Supports JSON config files, live market data via yfinance, and
optional distribution plots.

Usage:
    python src/mc_runner.py --json config/option_configs.json --num_paths 10000 --seed 42
    python src/mc_runner.py --json config/option_configs.json --num_paths 50000 --seed 42 --plot
    python src/mc_runner.py --live --ticker AAPL --days_to_expiry 45 --num_paths 10000 --export_dir ./results
"""

import sys
import argparse
import json
import os
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.append(str(Path(__file__).parent))

from monte_carlo.gbm_simulator import run_monte_carlo
from options_test_runner import fetch_live_config
from utils.config import load_config_from_json
from utils.data_export import create_export_directory


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def plot_distribution(payoffs, pnl, results, config, export_dir, label):
    """Save a payoff distribution histogram with VaR/CVaR lines."""
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.hist(pnl, bins=100, color='steelblue', alpha=0.7, edgecolor='none', density=True)

    var = results['var']
    cvar = results['cvar']
    ax.axvline(-var, color='orange', linewidth=2, label=f'VaR ({results["confidence"]*100:.0f}%): ${var:.2f}')
    ax.axvline(-cvar, color='red', linewidth=2, linestyle='--', label=f'CVaR: ${cvar:.2f}')
    ax.axvline(0, color='black', linewidth=1, linestyle=':')

    ticker = config.get('ticker', 'Option')
    option_type = config.get('option_type', 'call').title()
    K = config.get('strike_price', 0)
    ax.set_title(f'{ticker} {option_type} ${K} — P&L Distribution ({results["num_paths"]:,} paths)')
    ax.set_xlabel('P&L ($)')
    ax.set_ylabel('Density')
    ax.legend()
    plt.tight_layout()

    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    fname = export_dir / f"{label}_distribution.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Plot saved: {fname}")


def plot_paths(paths, config, export_dir, label, num_paths_shown=100):
    """Save a fan chart of a subset of GBM paths."""
    fig, ax = plt.subplots(figsize=(10, 6))
    subset = paths[:num_paths_shown]
    T = paths.shape[1] - 1
    t = np.linspace(0, T / 252, T + 1)

    for path in subset:
        ax.plot(t, path, alpha=0.15, linewidth=0.5, color='steelblue')

    ax.plot(t, np.median(paths, axis=0), color='navy', linewidth=2, label='Median path')
    ax.axhline(config.get('strike_price', 0), color='red', linestyle='--', linewidth=1.5, label='Strike')

    ticker = config.get('ticker', 'Option')
    ax.set_title(f'{ticker} — GBM Path Fan ({num_paths_shown} of {paths.shape[0]:,} paths)')
    ax.set_xlabel('Time (years)')
    ax.set_ylabel('Stock Price ($)')
    ax.legend()
    plt.tight_layout()

    export_dir = Path(export_dir)
    fname = export_dir / f"{label}_paths.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Plot saved: {fname}")


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_results(config, results, num_paths, seed):
    ticker = config.get('ticker', 'Option')
    option_type = config.get('option_type', 'call').title()
    K = config.get('strike_price', 0)
    seed_str = str(seed) if seed is not None else 'random'
    confidence = results['confidence']
    pct = results['percentiles']

    print(f"\n{'='*60}")
    print(f"MC SIMULATION: {ticker} {option_type} ${K} | {num_paths:,} paths | seed={seed_str}")
    print(f"{'-'*60}")

    vol_model = results.get('vol_model', 'constant')
    garch_params = results.get('garch_params')
    jump_params = results.get('jump_params')

    if vol_model == 'jump' and jump_params:
        p = jump_params
        print(f"Vol Model: Jump-Diffusion   "
              f"lam={p['lam']:.2f}  mu_J={p['mu_J']:.3f}  sigma_J={p['sigma_J']:.3f}")
        print(f"{'-'*60}")
    elif vol_model == 'garch' and garch_params:
        p = garch_params
        print(f"Vol Model: GARCH(1,1)  "
              f"omega={p['omega']:.6f}  alpha={p['alpha']:.4f}  beta={p['beta']:.4f}")
        print(f"Long-run vol: {p['long_run_vol']*100:.1f}%   "
              f"Current conditional vol: {p['sigma0']*100:.1f}%")
        print(f"{'-'*60}")
    else:
        print(f"Vol Model: Constant (sigma={config.get('implied_volatility', 0)*100:.1f}%)")
        print(f"{'-'*60}")

    print(f"Black-Scholes Price:    ${results['bs_price']:.2f}")

    # European price line
    american_price = results.get('american_price')
    if american_price is not None:
        print(f"European MC Price:      ${results['mc_price']:.2f}  (std error: ±{results['std_error']:.4f})")
        premium = results.get('early_exercise_premium', 0.0)
        print(f"American  MC Price:     ${american_price:.2f}   "
              f"(early exercise premium: +${premium:.2f})")
    else:
        print(f"MC Mean Price:          ${results['mc_price']:.2f}  (std error: ±{results['std_error']:.4f})")

    print(f"{'-'*60}")
    print(f"P&L Distribution (entry at BS price):")
    print(f"  5th pct:  ${pct['p5']:>8.2f}    25th pct: ${pct['p25']:>8.2f}")
    print(f"  Median:   ${pct['p50']:>8.2f}    75th pct: ${pct['p75']:>8.2f}")
    print(f"  95th pct: ${pct['p95']:>8.2f}")
    print(f"{'-'*60}")
    print(f"Risk Metrics ({confidence*100:.0f}% confidence):")
    print(f"  VaR:   ${results['var']:.2f}   (max loss at {confidence*100:.0f}% confidence)")
    print(f"  CVaR:  ${results['cvar']:.2f}   (expected loss beyond VaR)")
    print(f"{'='*60}")


def print_greeks(greeks):
    """Print MC Greeks alongside Black-Scholes reference values."""
    print(f"\n{'MC Greeks (vs Black-Scholes)':}")
    print(f"  Delta:  {greeks['delta']:>7.4f}  (BS: {greeks['bs_delta']:>7.4f})")
    print(f"  Gamma:  {greeks['gamma']:>7.4f}  (BS: {greeks['bs_gamma']:>7.4f})")
    print(f"  Vega:   {greeks['vega']:>7.4f}  (BS: {greeks['bs_vega']:>7.4f})   (per 1 vol point)")
    print(f"  Theta:  {greeks['theta']:>7.4f}  (BS: {greeks['bs_theta']:>7.4f})  (per day)")
    print(f"  Rho:    {greeks['rho']:>7.4f}  (BS: {greeks['bs_rho']:>7.4f})")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_configs_from_file(json_path):
    data = load_config_from_json(json_path)
    if isinstance(data, dict) and 'configurations' in data:
        return data['configurations']
    elif isinstance(data, list):
        return data
    else:
        return [data]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _fetch_returns_for_ticker(ticker, period='60d'):
    """Fetch daily simple returns for a ticker via yfinance."""
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=period)
    return hist['Close'].pct_change().dropna().values


def run_mc_on_configs(configs, args):
    export_base = Path(args.export_dir)
    export_base.mkdir(parents=True, exist_ok=True)

    for config in configs:
        ticker = config.get('ticker', 'OPTION')
        option_type = config.get('option_type', 'call')
        K = config.get('strike_price', 0)
        label = f"{ticker}_{option_type}_{K:.0f}"

        # GARCH: fetch returns if needed and not already in config
        use_garch = getattr(args, 'garch', False)
        historical_returns = None
        if use_garch:
            if '_historical_returns' in config:
                historical_returns = config['_historical_returns']
            elif ticker and ticker != 'OPTION':
                print(f"  Fetching 60d returns for {ticker} (GARCH calibration)...")
                try:
                    historical_returns = _fetch_returns_for_ticker(ticker)
                except Exception as e:
                    print(f"  Warning: could not fetch returns for {ticker}: {e}")

        # Jump diffusion params
        use_jumps = getattr(args, 'jumps', False)
        jump_params = None
        if use_jumps:
            jump_params = {
                'lam':     getattr(args, 'lam', 0.1),
                'mu_J':    getattr(args, 'mu_J', -0.05),
                'sigma_J': getattr(args, 'sigma_J', 0.15),
            }

        # American vs European
        option_style = 'american' if getattr(args, 'american', False) else 'european'

        results = run_monte_carlo(
            config,
            num_paths=args.num_paths,
            num_steps=args.num_steps,
            seed=args.seed,
            confidence=args.confidence,
            antithetic=args.antithetic,
            use_garch=use_garch,
            historical_returns=historical_returns,
            use_jumps=use_jumps,
            jump_params=jump_params,
            option_style=option_style,
        )

        print_results(config, results, results['num_paths'], args.seed)

        # MC Greeks
        if getattr(args, 'greeks', False):
            from monte_carlo.mc_greeks import compute_mc_greeks
            greeks = compute_mc_greeks(
                config,
                num_paths=min(3000, results['num_paths']),
                num_steps=results['num_steps'],
                seed=args.seed if args.seed is not None else 42,
                use_garch=use_garch,
                historical_returns=historical_returns,
                use_jumps=use_jumps,
                jump_params=jump_params,
            )
            print_greeks(greeks)

        if args.plot:
            pnl = results['payoffs'] - results['bs_price']
            plot_distribution(results['payoffs'], pnl, results, config, export_base, label)
            plot_paths(results['paths'], config, export_base, label)

        # Export payoffs as CSV
        import pandas as pd
        pnl = results['payoffs'] - results['bs_price']
        df = pd.DataFrame({'payoff': results['payoffs'], 'pnl': pnl})
        ts = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = export_base / f"{label}_mc_{ts}.csv"
        df.to_csv(csv_path, index=False)
        print(f"  Results exported: {csv_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monte Carlo Options Simulator')
    parser.add_argument('--json', type=str, help='JSON config file (single config or list)')
    parser.add_argument('--live', action='store_true', help='Fetch live market data via yfinance')
    parser.add_argument('--ticker', type=str, help='Ticker symbol (live mode)')
    parser.add_argument('--days_to_expiry', type=int, default=30, help='Target DTE for live mode')
    parser.add_argument('--num_paths', type=int, default=10000, help='Number of GBM paths')
    parser.add_argument('--num_steps', type=int, default=252, help='Steps per path (252 = 1yr daily)')
    parser.add_argument('--seed', type=int, default=None, help='Random seed for reproducibility')
    parser.add_argument('--confidence', type=float, default=0.95, help='VaR/CVaR confidence level')
    parser.add_argument('--antithetic', action='store_true', help='Enable antithetic variates')
    parser.add_argument('--garch', action='store_true', help='Use GARCH(1,1) time-varying vol (auto-fetches returns)')
    parser.add_argument('--jumps', action='store_true', help='Use Merton jump-diffusion (takes priority over --garch)')
    parser.add_argument('--lam', type=float, default=0.1, help='Jump intensity λ (jumps/year, default 0.1)')
    parser.add_argument('--mu_J', type=float, default=-0.05, help='Mean log-jump size (default -0.05)')
    parser.add_argument('--sigma_J', type=float, default=0.15, help='Std-dev of log-jump (default 0.15)')
    parser.add_argument('--greeks', action='store_true', help='Compute MC Greeks via bump-and-reprice')
    parser.add_argument('--american', action='store_true', help='Price as American option via Longstaff-Schwartz')
    parser.add_argument('--export_dir', type=str, default='./mc_results', help='Output directory')
    parser.add_argument('--plot', action='store_true', help='Save distribution and path plots')
    args = parser.parse_args()

    if args.json:
        configs = load_configs_from_file(args.json)
        run_mc_on_configs(configs, args)
    elif args.live:
        if not args.ticker:
            print("Error: --ticker is required in live mode.")
            sys.exit(1)
        configs = fetch_live_config(args.ticker, args.days_to_expiry)
        run_mc_on_configs(configs, args)
    else:
        print("Please specify --json or --live.")
        parser.print_help()
