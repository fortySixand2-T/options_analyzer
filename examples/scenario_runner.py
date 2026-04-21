#!/usr/bin/env python3
"""
Scenario Runner — Options P&L Risk Matrix
==========================================

CLI for computing option P&L across (ΔS%, Δvol pp, Δdays) scenario grids.

Modes:
    Greek approx (fast): Taylor expansion using MC greeks by default.
                         Use --bs-greeks to fall back to Black-Scholes greeks.
    Full reprice:        --reprice re-runs run_monte_carlo() for every scenario.

Usage:
    python src/scenario_runner.py --json config/mc_config.json
    python src/scenario_runner.py --json config/mc_config.json \\
        --ds_pct -15,-10,-5,0,5,10,15 --dvol -10,-5,0,5,10 --days 0,5,10,20
    python src/scenario_runner.py --json config/mc_config.json --reprice --seed 42 --plot
    python src/scenario_runner.py --live --ticker AAPL --days_to_expiry 45 --reprice --plot
"""

import sys
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

sys.path.append(str(Path(__file__).parent))

from analytics.scenario import run_scenario_matrix, format_pnl_table, plot_scenario_matrix
from options_test_runner import fetch_live_config
from utils.config import load_config_from_json


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


def _fetch_returns_for_ticker(ticker, period='60d'):
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=period)
    return hist['Close'].pct_change().dropna().values


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _model_label(args) -> str:
    if getattr(args, 'jumps', False):
        return 'Jump-Diffusion'
    if getattr(args, 'garch', False):
        return 'GARCH'
    return 'GBM'


def _greeks_label(use_bs: bool) -> str:
    return 'BS' if use_bs else 'MC'


def print_scenario_results(results, args):
    ticker = results['ticker']
    option_type = results['option_type'].title()
    K = results['K']
    base_price = results['base_price']
    greeks = results['greeks']
    day_shocks = results['day_shocks']
    has_reprice = any(
        v is not None
        for k, v in results['mc_pnl'].items()
        if not (k[0] == 0 and k[1] == 0 and k[2] == 0)
    )

    print(f"\nSCENARIO ANALYSIS: {ticker} {option_type} ${K}  "
          f"(entry: ${base_price:.2f}, MC)")

    g = greeks
    print(
        f"Model: {_model_label(args)}  |  "
        f"Greeks: {_greeks_label(getattr(args, 'bs_greeks', False))} "
        f"(Δ={g.get('delta', 0):.3f}  "
        f"Γ={g.get('gamma', 0):.4f}  "
        f"V={g.get('vega', 0):.3f}  "
        f"Θ={g.get('theta', 0):.4f}/day)"
    )
    print('═' * 62)

    for dd in day_shocks:
        print(f"\nGREEK APPROX P&L  (Δdays={dd})")
        print(format_pnl_table(results, dd, source='greek'))

    if has_reprice:
        num_paths = getattr(args, 'num_paths', 3000)
        for dd in day_shocks:
            print(f"\nFULL MC REPRICE P&L  (Δdays={dd})  [{num_paths:,} paths]")
            print(format_pnl_table(results, dd, source='mc'))
        for dd in day_shocks:
            print(f"\nGAP (MC − approx)  (Δdays={dd})  — nonlinearity penalty")
            print(format_pnl_table(results, dd, source='gap'))


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(results, export_dir, label):
    import pandas as pd
    rows = []
    for (ds, dv, dd), gpnl in results['greek_pnl'].items():
        mpnl = results['mc_pnl'].get((ds, dv, dd))
        gap = (mpnl - gpnl) if mpnl is not None else None
        rows.append({
            'ds_pct':    ds,
            'dvol_pp':   dv,
            'ddays':     dd,
            'greek_pnl': round(gpnl, 6),
            'mc_pnl':    round(mpnl, 6) if mpnl is not None else None,
            'gap':       round(gap, 6) if gap is not None else None,
        })
    df = pd.DataFrame(rows).sort_values(['ddays', 'ds_pct', 'dvol_pp'])
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = export_dir / f"{label}_scenario_{ts}.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Results exported: {csv_path}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_scenario_on_configs(configs, args):
    export_dir = Path(getattr(args, 'export_dir', './scenarios'))
    export_dir.mkdir(parents=True, exist_ok=True)

    s_shocks = tuple(float(x) for x in args.ds_pct.split(','))
    vol_shocks = tuple(float(x) for x in args.dvol.split(','))
    day_shocks = tuple(int(x) for x in args.days.split(','))
    use_bs_greeks = getattr(args, 'bs_greeks', False)

    for config in configs:
        ticker = config.get('ticker', 'OPTION')
        option_type = config.get('option_type', 'call')
        K = config.get('strike_price', 0)
        label = f"{ticker}_{option_type}_{K:.0f}"

        # GARCH: fetch returns if needed
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

        # Jump params
        use_jumps = getattr(args, 'jumps', False)
        jump_params = None
        if use_jumps:
            jump_params = {
                'lam':     getattr(args, 'lam', 0.1),
                'mu_J':    getattr(args, 'mu_J', -0.05),
                'sigma_J': getattr(args, 'sigma_J', 0.15),
            }

        results = run_scenario_matrix(
            config,
            s_shocks=s_shocks,
            vol_shocks=vol_shocks,
            day_shocks=day_shocks,
            reprice=args.reprice,
            use_bs_greeks=use_bs_greeks,
            use_garch=use_garch,
            historical_returns=historical_returns,
            use_jumps=use_jumps,
            jump_params=jump_params,
            num_paths=args.num_paths,
            seed=args.seed,
        )

        print_scenario_results(results, args)

        # Export CSV
        export_csv(results, export_dir, label)

        # Plot
        if args.plot:
            plot_path = export_dir / f"{label}_scenario.png"
            plot_scenario_matrix(results, ticker, save_path=str(plot_path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Options Scenario P&L Risk Matrix',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Config source
    src = parser.add_mutually_exclusive_group()
    src.add_argument('--json', type=str, metavar='FILE',
                     help='JSON config file (single config or list)')
    src.add_argument('--live', action='store_true',
                     help='Fetch live market data via yfinance')

    parser.add_argument('--ticker', type=str, help='Ticker symbol (live mode)')
    parser.add_argument('--days_to_expiry', type=int, default=30,
                        help='Target DTE for live mode (default: 30)')

    # Scenario grid
    parser.add_argument('--ds_pct', type=str, default='-10,-5,0,5,10',
                        help='ΔS%% values comma-separated (default: -10,-5,0,5,10)')
    parser.add_argument('--dvol', type=str, default='-5,0,5,10',
                        help='Δvol pp comma-separated (default: -5,0,5,10)')
    parser.add_argument('--days', type=str, default='0,5',
                        help='Δdays comma-separated (default: 0,5)')

    # Pricing / model flags
    parser.add_argument('--reprice', action='store_true',
                        help='Full MC reprice each scenario point')
    parser.add_argument('--num_paths', type=int, default=3000,
                        help='Paths per reprice call (default: 3000)')
    parser.add_argument('--bs-greeks', dest='bs_greeks', action='store_true',
                        help='Use BS greeks for approximation (default: MC greeks)')
    parser.add_argument('--model', type=str, default='gbm',
                        choices=['gbm', 'garch', 'jump'],
                        help='Simulator model (default: gbm)')
    parser.add_argument('--garch', action='store_true',
                        help='Use GARCH(1,1) vol model')
    parser.add_argument('--jumps', action='store_true',
                        help='Use Merton jump-diffusion')
    parser.add_argument('--lam', type=float, default=0.1,
                        help='Jump intensity λ (default: 0.1)')
    parser.add_argument('--mu_J', type=float, default=-0.05,
                        help='Mean log-jump (default: -0.05)')
    parser.add_argument('--sigma_J', type=float, default=0.15,
                        help='Log-jump std-dev (default: 0.15)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed (default: 42)')

    # Output
    parser.add_argument('--plot', action='store_true',
                        help='Save scenario heatmap PNG')
    parser.add_argument('--export_dir', type=str, default='./scenarios',
                        help='Output directory (default: ./scenarios)')

    args = parser.parse_args()

    # Propagate --model flag to --garch / --jumps convenience
    if args.model == 'garch':
        args.garch = True
    elif args.model == 'jump':
        args.jumps = True

    if args.json:
        configs = load_configs_from_file(args.json)
        run_scenario_on_configs(configs, args)
    elif args.live:
        if not args.ticker:
            print("Error: --ticker is required in live mode.")
            sys.exit(1)
        configs = fetch_live_config(args.ticker, args.days_to_expiry)
        run_scenario_on_configs(configs, args)
    else:
        print("Please specify --json or --live.")
        parser.print_help()
