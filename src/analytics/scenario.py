#!/usr/bin/env python3
"""
Scenario Analysis Engine — Options P&L Risk Matrix
====================================================

Computes option P&L across a grid of (ΔS%, Δvol pp, Δdays) scenarios using:
  1. Greek approximation (Taylor expansion) — fast, default MC greeks
  2. Full MC reprice (--reprice) — exact P&L, exposes nonlinearity premium

Author: Options Analytics Team
Date: March 2026
"""

import copy
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bump_scenario_config(config: Dict[str, Any], ds_pct: float,
                           dvol_pp: float, ddays: int) -> Dict[str, Any]:
    """Deep-copy config, then apply scenario bumps."""
    c = copy.deepcopy(config)

    # Bump spot price
    c['current_price'] = c['current_price'] * (1.0 + ds_pct / 100.0)

    # Bump implied vol (clamp to 0.001)
    new_vol = c.get('implied_volatility', 0.20) + dvol_pp / 100.0
    c['implied_volatility'] = max(new_vol, 0.001)

    # Subtract days from expiration (clamp to at least 1 day out from today)
    exp_date = datetime.strptime(c['expiration_date'], '%Y-%m-%d')
    new_exp = exp_date - timedelta(days=ddays)
    # Ensure at least 1 calendar day from now
    floor = datetime.now() + timedelta(days=1)
    if new_exp < floor:
        new_exp = floor
    c['expiration_date'] = new_exp.strftime('%Y-%m-%d')

    return c


def _compute_greek_pnl(greeks: Dict[str, float], S0: float,
                        ds_pct: float, dvol_pp: float,
                        ddays: int, dr_pp: float = 0.0) -> float:
    """
    Second-order Taylor expansion P&L estimate.

    Greek units (matching BS/MC convention):
        delta  : per $1 change in S
        gamma  : per $1 change in S (second derivative)
        vega   : per 1 pp (percentage-point) change in vol
        theta  : per calendar day (negative for long options)
        rho    : per 1 pp change in r
    """
    # Normalise keys to lowercase (handles BS Capital keys)
    g = {k.lower(): v for k, v in greeks.items()}

    dS = S0 * ds_pct / 100.0
    pnl = (
        g.get('delta', 0.0) * dS
        + 0.5 * g.get('gamma', 0.0) * dS ** 2
        + g.get('vega', 0.0) * dvol_pp
        + g.get('theta', 0.0) * ddays
        + g.get('rho', 0.0) * dr_pp
    )
    return pnl


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def run_scenario_matrix(
    config: Dict[str, Any],
    s_shocks: tuple = (-10, -5, 0, 5, 10),
    vol_shocks: tuple = (-5, 0, 5, 10),
    day_shocks: tuple = (0, 5),
    reprice: bool = False,
    use_bs_greeks: bool = False,
    use_garch: bool = False,
    historical_returns=None,
    use_jumps: bool = False,
    jump_params: Optional[Dict[str, float]] = None,
    num_paths: int = 3000,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Compute P&L scenario matrix for an option.

    Parameters
    ----------
    config : dict
        Standard option config dict.
    s_shocks : tuple
        Stock price shocks in percent (e.g. -10 means S drops 10%).
    vol_shocks : tuple
        Implied-vol shocks in percentage points (e.g. 5 means +5pp).
    day_shocks : tuple
        Time passage in calendar days (e.g. 5 means 5 days have passed).
    reprice : bool
        If True, re-run Monte Carlo for each non-zero scenario point.
    use_bs_greeks : bool
        If True, use Black-Scholes greeks for the Taylor approximation.
        Default: MC greeks (consistent with simulator).
    use_garch : bool
        Pass-through to run_monte_carlo / compute_mc_greeks.
    historical_returns : array-like, optional
        Historical returns for GARCH calibration.
    use_jumps : bool
        Pass-through for jump-diffusion.
    jump_params : dict, optional
        Jump parameters {lam, mu_J, sigma_J}.
    num_paths : int
        Paths for base pricing and reprice calls.
    seed : int
        Random seed.

    Returns
    -------
    dict with keys:
        base_price, greeks, s_shocks, vol_shocks, day_shocks,
        greek_pnl, mc_pnl, ticker, option_type, K, S0
    """
    from monte_carlo.gbm_simulator import run_monte_carlo, _time_to_expiry
    from monte_carlo.mc_greeks import compute_mc_greeks
    from models.black_scholes import calculate_greeks

    S0 = config['current_price']
    K = config['strike_price']
    sigma = config.get('implied_volatility', 0.20)
    r = config.get('risk_free_rate', 0.045)
    option_type = config.get('option_type', 'call').lower()
    T = _time_to_expiry(config)

    # Strip monte_carlo key so num_paths arg is respected in all reprice calls
    config_stripped = {k: v for k, v in config.items() if k != 'monte_carlo'}

    # --- Base price via MC ---
    mc_kw = dict(
        num_paths=num_paths,
        seed=seed,
        use_garch=use_garch,
        historical_returns=historical_returns,
        use_jumps=use_jumps,
        jump_params=jump_params,
    )
    base_result = run_monte_carlo(config_stripped, **mc_kw)
    base_price = base_result['mc_price']

    # --- Greeks ---
    if use_bs_greeks:
        bs_g = calculate_greeks(S0, K, T, r, sigma, option_type)
        greeks = {k.lower(): v for k, v in bs_g.items()}
    else:
        mc_g = compute_mc_greeks(
            config_stripped,
            num_paths=num_paths,
            seed=seed,
            use_garch=use_garch,
            historical_returns=historical_returns,
            use_jumps=use_jumps,
            jump_params=jump_params,
        )
        greeks = {k: mc_g[k] for k in ('delta', 'gamma', 'vega', 'theta', 'rho')}

    # --- Build scenario grids ---
    s_shocks = list(s_shocks)
    vol_shocks = list(vol_shocks)
    day_shocks = list(day_shocks)

    greek_pnl: Dict[Tuple, float] = {}
    mc_pnl: Dict[Tuple, Optional[float]] = {}

    for dd in day_shocks:
        for ds in s_shocks:
            for dv in vol_shocks:
                key = (ds, dv, dd)

                # Greek approximation
                greek_pnl[key] = _compute_greek_pnl(greeks, S0, ds, dv, dd)

                # MC reprice
                if not reprice:
                    mc_pnl[key] = None
                elif ds == 0 and dv == 0 and dd == 0:
                    # Exact zero — skip reprice to avoid noise on baseline
                    mc_pnl[key] = 0.0
                else:
                    bumped = _bump_scenario_config(config_stripped, ds, dv, dd)
                    v_scenario = run_monte_carlo(bumped, **mc_kw)['mc_price']
                    mc_pnl[key] = v_scenario - base_price

    return {
        'base_price':  base_price,
        'greeks':      greeks,
        's_shocks':    s_shocks,
        'vol_shocks':  vol_shocks,
        'day_shocks':  day_shocks,
        'greek_pnl':   greek_pnl,
        'mc_pnl':      mc_pnl,
        'ticker':      config.get('ticker', 'OPTION'),
        'option_type': option_type,
        'K':           K,
        'S0':          S0,
    }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_pnl_table(results: Dict[str, Any], ddays: int,
                     source: str = 'greek') -> str:
    """
    Format a 2D P&L table (ΔS rows × Δvol cols) for a given day shock.

    Parameters
    ----------
    results : dict
        Output of run_scenario_matrix().
    ddays : int
        Which day shock to display.
    source : str
        'greek', 'mc', or 'gap'.
    """
    s_shocks = results['s_shocks']
    vol_shocks = results['vol_shocks']

    if source == 'greek':
        data = results['greek_pnl']
    elif source == 'mc':
        data = results['mc_pnl']
    else:  # gap
        data = {
            k: (results['mc_pnl'][k] - results['greek_pnl'][k])
            if results['mc_pnl'].get(k) is not None else None
            for k in results['greek_pnl']
        }

    # Header row
    col_w = 8
    header_parts = [f"{'':>12}"]
    for dv in vol_shocks:
        sign = '+' if dv > 0 else ''
        header_parts.append(f"{sign}{dv:>3}pp".rjust(col_w))
    lines = ['  Δvol: ' + ''.join(header_parts[1:])]

    # Data rows
    for ds in s_shocks:
        sign = '+' if ds > 0 else ''
        row_label = f" ΔS {sign}{ds}%:".ljust(12)
        row_parts = [row_label]
        for dv in vol_shocks:
            key = (ds, dv, ddays)
            val = data.get(key)
            if val is None:
                cell = 'N/A'.rjust(col_w)
            else:
                sign_v = '+' if val >= 0 else ''
                cell = f"{sign_v}{val:.2f}".rjust(col_w)
            row_parts.append(cell)
        lines.append(''.join(row_parts))

    return '\n'.join(lines)


def plot_scenario_matrix(results: Dict[str, Any], ticker: str,
                         save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot a grid of heatmaps for the scenario matrix.

    Rows = day_shocks; Cols = 1 (greek only) or 3 (greek|mc|gap if reprice).
    """
    s_shocks = results['s_shocks']
    vol_shocks = results['vol_shocks']
    day_shocks = results['day_shocks']
    has_reprice = any(v is not None for v in results['mc_pnl'].values()
                      if v != 0.0 or True)
    # Determine if we actually have reprice data beyond (0,0,0)
    mc_vals = [v for k, v in results['mc_pnl'].items()
               if v is not None and not (k[0] == 0 and k[1] == 0 and k[2] == 0)]
    has_reprice = len(mc_vals) > 0

    n_rows = len(day_shocks)
    n_cols = 3 if has_reprice else 1
    col_titles = (['Greek Approx P&L', 'Full MC Reprice P&L', 'Gap (MC − Approx)']
                  if has_reprice else ['Greek Approx P&L'])

    # Compute global colour scale
    all_vals = [v for v in results['greek_pnl'].values()]
    if has_reprice:
        for v in results['mc_pnl'].values():
            if v is not None:
                all_vals.append(v)
    max_abs = max(abs(v) for v in all_vals) if all_vals else 1.0
    vmin, vmax = -max_abs, max_abs

    fig, axes = plt.subplots(n_rows, n_cols,
                             figsize=(5 * n_cols + 1, 4 * n_rows + 1),
                             squeeze=False)

    for row_i, dd in enumerate(day_shocks):
        for col_i in range(n_cols):
            ax = axes[row_i][col_i]
            source = ['greek', 'mc', 'gap'][col_i] if has_reprice else 'greek'

            if source == 'greek':
                grid_data = np.array([
                    [results['greek_pnl'][(ds, dv, dd)] for dv in vol_shocks]
                    for ds in s_shocks
                ])
            elif source == 'mc':
                grid_data = np.array([
                    [results['mc_pnl'].get((ds, dv, dd), 0.0) or 0.0
                     for dv in vol_shocks]
                    for ds in s_shocks
                ])
            else:  # gap
                grid_data = np.array([
                    [(results['mc_pnl'].get((ds, dv, dd)) or 0.0)
                     - results['greek_pnl'][(ds, dv, dd)]
                     for dv in vol_shocks]
                    for ds in s_shocks
                ])

            im = ax.pcolormesh(grid_data, cmap='RdYlGn',
                               vmin=vmin, vmax=vmax)

            # Overlay P&L text
            for r_i, ds in enumerate(s_shocks):
                for c_i, dv in enumerate(vol_shocks):
                    val = grid_data[r_i, c_i]
                    sign = '+' if val >= 0 else ''
                    ax.text(c_i + 0.5, r_i + 0.5, f'{sign}{val:.2f}',
                            ha='center', va='center', fontsize=7,
                            color='black')

            # Axis labels
            ax.set_xticks(np.arange(len(vol_shocks)) + 0.5)
            ax.set_xticklabels([f'{dv:+}pp' for dv in vol_shocks], fontsize=8)
            ax.set_yticks(np.arange(len(s_shocks)) + 0.5)
            ax.set_yticklabels([f'{ds:+}%' for ds in s_shocks], fontsize=8)
            ax.set_xlabel('Δ implied vol', fontsize=9)
            ax.set_ylabel('ΔS', fontsize=9)

            title = col_titles[col_i]
            ax.set_title(f'{title}  (Δdays={dd})', fontsize=10)

            plt.colorbar(im, ax=ax, shrink=0.8)

    option_type = results['option_type'].title()
    K = results['K']
    fig.suptitle(
        f'{ticker} {option_type} ${K}  —  Scenario P&L Matrix',
        fontsize=13, fontweight='bold', y=1.01
    )
    plt.tight_layout()

    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  Scenario heatmap saved: {save_path}")

    return fig
