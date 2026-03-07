#!/usr/bin/env python3
"""
Monte Carlo Options Demo
========================

Four progressive demonstrations:
  1. Basic MC vs BS comparison
  2. P&L distribution with VaR/CVaR overlay
  3. Convergence analysis (MC price vs num_paths)
  4. Call vs Put comparison

All plots saved to ./analysis_results/mc_demo/

Run from project root:
    python examples/monte_carlo_demo.py
"""

import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Allow running from project root or examples/
sys.path.append(str(Path(__file__).parent.parent / 'src'))

from monte_carlo.gbm_simulator import simulate_gbm_paths, price_option_on_paths, run_monte_carlo
from monte_carlo.risk_metrics import compute_var, compute_cvar, compute_distribution_stats
from models.black_scholes import black_scholes_price

OUTPUT_DIR = Path('./analysis_results/mc_demo')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Common parameters
S0, K, r, sigma, T = 175.0, 180.0, 0.045, 0.25, 0.5   # 6-month ATM call
BASE_CONFIG = {
    'ticker': 'DEMO',
    'current_price': S0,
    'strike_price': K,
    'expiration_date': '2026-09-07',
    'option_type': 'call',
    'implied_volatility': sigma,
    'risk_free_rate': r,
}

print("=" * 60)
print("Monte Carlo Options Demo")
print("=" * 60)


# ---------------------------------------------------------------------------
# 1. Basic MC vs BS comparison
# ---------------------------------------------------------------------------
print("\n[1] Basic MC vs BS comparison")

bs = black_scholes_price(S0, K, T, r, sigma, 'call')
path_counts = [500, 1000, 5000, 10000, 50000]
mc_prices = []

for n in path_counts:
    paths = simulate_gbm_paths(S0, r, sigma, T, n, 252, seed=42)
    payoffs = price_option_on_paths(paths, K, r, T, 'call')
    mc_prices.append(float(np.mean(payoffs)))
    print(f"  n={n:>6,}: MC=${mc_prices[-1]:.4f}  (BS=${bs:.4f}, diff=${abs(mc_prices[-1]-bs):.4f})")

fig, ax = plt.subplots(figsize=(9, 5))
ax.semilogx(path_counts, mc_prices, 'o-', label='MC Price', color='steelblue')
ax.axhline(bs, color='red', linestyle='--', label=f'BS Price ${bs:.4f}')
ax.set_xlabel('Number of Paths')
ax.set_ylabel('Option Price ($)')
ax.set_title('MC vs Black-Scholes Convergence')
ax.legend()
plt.tight_layout()
fig.savefig(OUTPUT_DIR / '1_mc_vs_bs.png', dpi=150)
plt.close(fig)
print(f"  Saved: {OUTPUT_DIR / '1_mc_vs_bs.png'}")


# ---------------------------------------------------------------------------
# 2. P&L distribution with VaR/CVaR
# ---------------------------------------------------------------------------
print("\n[2] P&L distribution with VaR/CVaR")

results = run_monte_carlo(BASE_CONFIG, num_paths=20000, num_steps=252, seed=42)
pnl = results['payoffs'] - results['bs_price']
var = results['var']
cvar = results['cvar']

print(f"  MC price: ${results['mc_price']:.4f} | BS: ${results['bs_price']:.4f}")
print(f"  VaR(95%): ${var:.4f}  CVaR(95%): ${cvar:.4f}")

fig, ax = plt.subplots(figsize=(10, 6))
ax.hist(pnl, bins=120, color='steelblue', alpha=0.7, edgecolor='none', density=True)
ax.axvline(-var, color='orange', linewidth=2, label=f'VaR 95%: -${var:.2f}')
ax.axvline(-cvar, color='red', linewidth=2, linestyle='--', label=f'CVaR 95%: -${cvar:.2f}')
ax.axvline(0, color='black', linewidth=1, linestyle=':')
ax.set_title('P&L Distribution — DEMO Call $180 (20,000 paths)')
ax.set_xlabel('P&L ($)')
ax.set_ylabel('Density')
ax.legend()
plt.tight_layout()
fig.savefig(OUTPUT_DIR / '2_pnl_distribution.png', dpi=150)
plt.close(fig)
print(f"  Saved: {OUTPUT_DIR / '2_pnl_distribution.png'}")


# ---------------------------------------------------------------------------
# 3. Convergence analysis
# ---------------------------------------------------------------------------
print("\n[3] Convergence analysis")

n_values = np.logspace(2, 5, 20).astype(int)
means, stds = [], []

for n in n_values:
    paths = simulate_gbm_paths(S0, r, sigma, T, int(n), 252, seed=99)
    payoffs = price_option_on_paths(paths, K, r, T, 'call')
    means.append(float(np.mean(payoffs)))
    stds.append(float(np.std(payoffs) / np.sqrt(n)))

means = np.array(means)
stds = np.array(stds)

fig, ax = plt.subplots(figsize=(10, 6))
ax.semilogx(n_values, means, '-', color='steelblue', label='MC Mean Price')
ax.fill_between(n_values, means - 2*stds, means + 2*stds, alpha=0.25, color='steelblue', label='±2 Std Error')
ax.axhline(bs, color='red', linestyle='--', linewidth=1.5, label=f'BS Price ${bs:.4f}')
ax.set_xlabel('Number of Paths')
ax.set_ylabel('Option Price ($)')
ax.set_title('MC Price Convergence vs Number of Paths')
ax.legend()
plt.tight_layout()
fig.savefig(OUTPUT_DIR / '3_convergence.png', dpi=150)
plt.close(fig)
print(f"  Saved: {OUTPUT_DIR / '3_convergence.png'}")


# ---------------------------------------------------------------------------
# 4. Call vs Put comparison
# ---------------------------------------------------------------------------
print("\n[4] Call vs Put comparison")

configs = [BASE_CONFIG.copy(), BASE_CONFIG.copy()]
configs[0]['option_type'] = 'call'
configs[1]['option_type'] = 'put'
configs[1]['name'] = 'DEMO Put'

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

for ax, cfg in zip(axes, configs):
    res = run_monte_carlo(cfg, num_paths=20000, num_steps=252, seed=42)
    pnl = res['payoffs'] - res['bs_price']
    otype = cfg['option_type'].title()
    print(f"  {otype}: MC=${res['mc_price']:.4f} | BS=${res['bs_price']:.4f} | "
          f"VaR=${res['var']:.4f} | CVaR=${res['cvar']:.4f}")

    ax.hist(pnl, bins=100, alpha=0.7, edgecolor='none',
            color='steelblue' if otype == 'Call' else 'darkorange')
    ax.axvline(-res['var'], color='red', linewidth=1.5, linestyle='--',
               label=f"VaR: ${res['var']:.2f}")
    ax.set_title(f'P&L — {otype} ${K}')
    ax.set_xlabel('P&L ($)')
    ax.set_ylabel('Count')
    ax.legend()

plt.suptitle('Call vs Put P&L Comparison (20,000 paths)', y=1.01)
plt.tight_layout()
fig.savefig(OUTPUT_DIR / '4_call_vs_put.png', dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"  Saved: {OUTPUT_DIR / '4_call_vs_put.png'}")


print(f"\nAll demo plots saved to: {OUTPUT_DIR}")
print("=" * 60)
