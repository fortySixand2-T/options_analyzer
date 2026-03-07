#!/usr/bin/env python3
"""
Implied Volatility Surface
==========================

Tools for computing, fetching, and visualising the implied-volatility
surface from live option chains.

Public API
----------
    compute_implied_vol(market_price, S, K, T, r, option_type) -> float | nan
    fetch_vol_surface(ticker, r, max_expiries) -> pd.DataFrame
    plot_vol_surface(df, ticker, save_path) -> plt.Figure

Author: Options Analytics Team
Date: March 2026
"""

import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# Core: back-solve implied vol from a single market price
# ---------------------------------------------------------------------------

def compute_implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
) -> float:
    """
    Back-solve implied volatility from a market option price using Brent's method.

    The IV is defined as the sigma that makes BS(sigma) == market_price.

    Parameters
    ----------
    market_price : float
        Observed mid-price of the option.
    S : float
        Current underlying price.
    K : float
        Strike price.
    T : float
        Time to expiration (years).
    r : float
        Risk-free rate (annual).
    option_type : str
        'call' or 'put'.

    Returns
    -------
    float
        Implied volatility, or np.nan if the price is outside the
        arbitrage-free range or root-finding fails.
    """
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from models.black_scholes import black_scholes_price

    if T <= 0 or market_price <= 0:
        return np.nan

    # Arbitrage lower bound for the option price
    discount = np.exp(-r * T)
    if option_type.lower() == 'call':
        lower_bound = max(S - K * discount, 0.0)
    else:
        lower_bound = max(K * discount - S, 0.0)

    if market_price <= lower_bound:
        return np.nan

    def objective(sigma: float) -> float:
        return black_scholes_price(S, K, T, r, sigma, option_type) - market_price

    try:
        iv = brentq(objective, 1e-4, 10.0, xtol=1e-6, rtol=1e-6)
        return float(iv)
    except (ValueError, RuntimeError):
        return np.nan


# ---------------------------------------------------------------------------
# Live data: fetch option chain and build vol surface dataframe
# ---------------------------------------------------------------------------

def fetch_vol_surface(
    ticker: str,
    r: float = 0.045,
    max_expiries: int = 6,
) -> pd.DataFrame:
    """
    Fetch a live option chain and compute implied volatilities.

    Requires yfinance.  Filters:
      - bid > 0, ask > 0
      - open_interest > 0
      - moneyness (K/S) in [0.70, 1.40]

    Parameters
    ----------
    ticker : str
        Underlying symbol (e.g. 'AAPL').
    r : float
        Risk-free rate used for IV calculation.
    max_expiries : int
        Maximum number of expiry dates to include.

    Returns
    -------
    pd.DataFrame
        Columns: expiry, T, strike, moneyness, iv, option_type
    """
    import yfinance as yf

    t = yf.Ticker(ticker)
    info = t.fast_info
    S = float(info['last_price'])

    today = datetime.today()
    expiry_strs = list(t.options)[:max_expiries]

    rows = []
    for exp_str in expiry_strs:
        try:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d')
        except ValueError:
            continue

        T = (exp_date - today).days / 365.0
        if T <= 0:
            continue

        try:
            chain = t.option_chain(exp_str)
        except Exception:
            continue

        for opt_type, opts in [('call', chain.calls), ('put', chain.puts)]:
            for _, row in opts.iterrows():
                try:
                    K_val = float(row['strike'])
                    bid = float(row['bid'])
                    ask = float(row['ask'])
                    oi = float(row.get('openInterest', 0) or 0)
                except (ValueError, TypeError, KeyError):
                    continue

                if bid <= 0 or ask <= 0 or oi <= 0:
                    continue

                moneyness = K_val / S
                if moneyness < 0.70 or moneyness > 1.40:
                    continue

                mid = (bid + ask) / 2.0
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    iv = compute_implied_vol(mid, S, K_val, T, r, opt_type)

                if np.isnan(iv):
                    continue

                rows.append({
                    'expiry':      exp_str,
                    'T':           T,
                    'strike':      K_val,
                    'moneyness':   moneyness,
                    'iv':          iv,
                    'option_type': opt_type,
                })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def plot_vol_surface(
    df: pd.DataFrame,
    ticker: str,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Plot implied volatility surface and per-expiry vol smiles.

    Creates a figure with two subplots:
      1. 3-D scatter (moneyness × T × IV) coloured by IV
      2. 2-D vol smile per expiry (moneyness × IV, one line per expiry)

    Parameters
    ----------
    df : pd.DataFrame
        Output of fetch_vol_surface().
    ticker : str
        Ticker symbol used for plot titles.
    save_path : str, optional
        If given, saves the figure to this path.

    Returns
    -------
    plt.Figure
    """
    if df.empty:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes, ha='center')
        return fig

    fig = plt.figure(figsize=(16, 7))

    # ---- Panel 1: 3-D scatter ----
    ax3d = fig.add_subplot(1, 2, 1, projection='3d')
    sc = ax3d.scatter(
        df['moneyness'], df['T'], df['iv'] * 100,
        c=df['iv'] * 100,
        cmap='RdYlGn_r',
        s=18, alpha=0.8,
    )
    fig.colorbar(sc, ax=ax3d, shrink=0.5, label='IV (%)')
    ax3d.set_xlabel('Moneyness (K/S)', labelpad=6)
    ax3d.set_ylabel('Time to Expiry (yr)', labelpad=6)
    ax3d.set_zlabel('IV (%)', labelpad=6)
    ax3d.set_title(f'{ticker} — IV Surface')

    # ---- Panel 2: 2-D smile per expiry ----
    ax2d = fig.add_subplot(1, 2, 2)
    expiries = sorted(df['expiry'].unique())
    cmap = plt.get_cmap('tab10')
    for i, exp in enumerate(expiries):
        subset = df[df['expiry'] == exp].sort_values('moneyness')
        label = f"{exp} (T={subset['T'].iloc[0]:.2f}y)"
        ax2d.plot(subset['moneyness'], subset['iv'] * 100,
                  marker='o', markersize=3, linewidth=1.5,
                  color=cmap(i % 10), label=label)

    ax2d.axvline(1.0, color='black', linewidth=0.8, linestyle='--', alpha=0.6)
    ax2d.set_xlabel('Moneyness (K/S)')
    ax2d.set_ylabel('Implied Volatility (%)')
    ax2d.set_title(f'{ticker} — Vol Smile by Expiry')
    ax2d.legend(fontsize=7, loc='upper right')
    ax2d.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')

    return fig
