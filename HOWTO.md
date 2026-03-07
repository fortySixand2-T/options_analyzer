# Options Pricing System — How-To Guide

Complete usage reference for the Black-Scholes analyzer and Monte Carlo simulator.

---

## Table of Contents

1. [Setup](#1-setup)
2. [Project Structure](#2-project-structure)
3. [Black-Scholes Analyzer](#3-black-scholes-analyzer)
4. [Monte Carlo Simulator](#4-monte-carlo-simulator)
5. [GARCH Volatility Model](#5-garch-volatility-model)
6. [Jump-Diffusion Model](#6-jump-diffusion-model)
7. [MC Greeks](#7-mc-greeks)
8. [American Options (Longstaff-Schwartz)](#8-american-options-longstaff-schwartz)
9. [Implied Volatility Surface](#9-implied-volatility-surface)
10. [CLI Reference](#10-cli-reference)
11. [Config File Format](#11-config-file-format)
12. [Risk Metrics](#12-risk-metrics)
13. [Running Tests](#13-running-tests)
14. [Examples](#14-examples)

---

## 1. Setup

### Activate the virtual environment

```bash
source activate_env.sh
# or directly:
source /Users/sirius/projects/environments/options_env/bin/activate
```

### Install / update dependencies

```bash
pip install -r requirements.txt
```

### Run the build script (does everything above + runs tests)

```bash
./build.sh
```

---

## 2. Project Structure

```
options/
├── src/
│   ├── models/
│   │   └── black_scholes.py        # BS pricing, Greeks
│   ├── analytics/
│   │   ├── simulations.py          # Price/vol/time sweeps
│   │   └── visualization.py        # matplotlib charts
│   ├── monte_carlo/
│   │   ├── gbm_simulator.py        # GBM paths, run_monte_carlo()
│   │   └── risk_metrics.py         # VaR, CVaR, distribution stats
│   ├── utils/
│   │   ├── config.py               # JSON/YAML loading & validation
│   │   └── data_export.py          # CSV, Excel, JSON export
│   ├── options_analyzer.py         # High-level BS interface
│   ├── options_test_runner.py      # BS CLI runner
│   └── mc_runner.py                # Monte Carlo CLI runner
├── config/
│   ├── option_configs.json         # BS config examples
│   └── mc_config.json              # MC config example
├── examples/
│   ├── basic_usage.py              # BS basics
│   ├── advanced_strategies.py      # Multi-leg strategies
│   └── monte_carlo_demo.py         # MC demo (4 use cases)
├── tests/
│   ├── test_black_scholes.py
│   └── test_monte_carlo.py
├── build.sh                        # Auto build + test script
├── activate_env.sh                 # venv activation
├── requirements.txt
├── README.md
└── HOWTO.md                        # This file
```

---

## 3. Black-Scholes Analyzer

### Programmatic usage

```python
import sys
sys.path.append('src')

from options_analyzer import OptionsAnalyzer

config = {
    'ticker': 'AAPL',
    'current_price': 175.0,
    'strike_price': 180.0,
    'expiration_date': '2026-09-07',
    'option_type': 'call',          # 'call' or 'put'
    'implied_volatility': 0.25,     # 25% annual vol
    'risk_free_rate': 0.045,        # 4.5%
}

analyzer = OptionsAnalyzer(config)

# Current price and Greeks
print(f"Price:  ${analyzer.get_current_price():.4f}")
print(f"Greeks: {analyzer.get_greeks()}")

# Print full summary table
analyzer.print_summary()

# Run full analysis (time decay + price scenarios + vol sweep) and export
analyzer.run_full_analysis(export_results=True, export_dir='./exports')
```

### Low-level functions

```python
from models.black_scholes import black_scholes_price, calculate_greeks

price = black_scholes_price(S=175, K=180, T=0.5, r=0.045, sigma=0.25, option_type='call')
greeks = calculate_greeks(S=175, K=180, T=0.5, r=0.045, sigma=0.25, option_type='call')
# greeks keys: Delta, Gamma, Theta, Vega, Rho
```

### Scenario simulations

```python
from analytics import simulate_price_scenarios, simulate_volatility_scenarios

# P&L across a range of underlying prices
price_df = simulate_price_scenarios(config, price_range=(140, 210), num_prices=30)

# Option price as volatility varies from 10% to 80%
vol_df = simulate_volatility_scenarios(config, vol_range=(0.10, 0.80), num_vols=15)
```

---

## 4. Monte Carlo Simulator

### Core functions

```python
import sys
sys.path.append('src')

from monte_carlo.gbm_simulator import simulate_gbm_paths, price_option_on_paths, run_monte_carlo
from monte_carlo.risk_metrics import compute_var, compute_cvar, compute_distribution_stats
import numpy as np

# 1. Simulate GBM paths
paths = simulate_gbm_paths(
    S0=175.0,       # initial price
    r=0.045,        # risk-free rate
    sigma=0.25,     # annual volatility
    T=0.5,          # years to expiry
    num_paths=10000,
    num_steps=252,  # daily steps
    seed=42,        # for reproducibility
    antithetic=True # variance reduction
)
# paths.shape == (10000, 253)

# 2. Price a European option on terminal prices
payoffs = price_option_on_paths(paths, K=180, r=0.045, T=0.5, option_type='call')
print(f"MC price: ${np.mean(payoffs):.4f}")

# 3. Compute P&L (assuming entry at BS price)
from models.black_scholes import black_scholes_price
bs = black_scholes_price(175, 180, 0.5, 0.045, 0.25, 'call')
pnl = payoffs - bs

# 4. Risk metrics
var  = compute_var(pnl, confidence=0.95)   # max loss at 95% confidence
cvar = compute_cvar(pnl, confidence=0.95)  # expected loss beyond VaR
stats = compute_distribution_stats(pnl)   # mean, std, p5..p95

print(f"VaR(95%): ${var:.2f}  CVaR(95%): ${cvar:.2f}")
```

### One-shot orchestrator

```python
results = run_monte_carlo(
    config,            # standard option config dict
    num_paths=10000,
    num_steps=252,
    seed=42,
    confidence=0.95,
    antithetic=True,
)

# results keys:
# mc_price, bs_price, std_error,
# var, cvar, confidence,
# percentiles (dict: mean/std/min/max/p5/p25/p50/p75/p95),
# payoffs (np.ndarray shape num_paths),
# paths (np.ndarray shape num_paths x num_steps+1),
# num_paths, num_steps, T
```

### Antithetic variates

Setting `antithetic=True` generates `n/2` base random paths and their mirror images (`-Z`), halving the Monte Carlo variance at negligible extra cost. Recommended for all production runs.

---

## 5. GARCH Volatility Model

### What it does and when to use it

The standard GBM simulator uses a constant volatility `sigma` for all paths and time steps.
GARCH(1,1) models *volatility clustering* — after a large market move, the next move is
more likely to be large too. This makes VaR/CVaR respond to the actual current vol regime
rather than a manually-chosen number.

Use GARCH when:
- You have recent historical returns (≥ 30 daily observations)
- You want risk metrics to reflect the current vol environment
- You suspect the implied vol in the config is stale or unreliable

### `fit_garch11()` API

```python
import sys
sys.path.append('src')
import numpy as np
from monte_carlo.garch_vol import fit_garch11

# daily_returns: 1-D array of simple or log returns
params = fit_garch11(daily_returns)
# params keys:
#   omega       : baseline variance term (daily units)
#   alpha       : shock coefficient
#   beta        : persistence coefficient
#   sigma0      : current conditional vol (annualised) — calibrated to last observation
#   long_run_vol: unconditional long-run annualised vol = sqrt(omega / (1 - alpha - beta))
#   converged   : bool — MLE convergence flag
```

### `run_monte_carlo()` with GARCH

```python
import yfinance as yf
returns = yf.Ticker('AAPL').history(period='60d')['Close'].pct_change().dropna().values

results = run_monte_carlo(
    config,
    num_paths=10000,
    num_steps=252,
    seed=42,
    use_garch=True,
    historical_returns=returns,
)

# results['vol_model']   == 'garch'
# results['garch_params'] — dict with omega, alpha, beta, sigma0, long_run_vol, converged
```

When `use_garch=True` but no returns are provided (or fewer than 30 observations),
the simulator warns and falls back to constant-vol GBM automatically.

### CLI `--garch` flag

```bash
# JSON config (ticker present → auto-fetches 60d returns)
python src/mc_runner.py --json config/mc_config.json --garch --seed 42

# Live mode (returns already fetched alongside live price)
python src/mc_runner.py --live --ticker AAPL --days_to_expiry 45 --garch --num_paths 10000
```

GARCH output block printed to console:
```
Vol Model: GARCH(1,1)  omega=0.000003  alpha=0.0921  beta=0.8812
Long-run vol: 22.1%   Current conditional vol: 28.4%
```

### Interpreting `long_run_vol` vs `sigma0`

| Field | Meaning |
|-------|---------|
| `sigma0` | Today's conditional vol — the vol the market is currently experiencing |
| `long_run_vol` | The unconditional average vol the process reverts to |

If `sigma0 > long_run_vol`: the market is currently more volatile than average — VaR/CVaR will be elevated.
If `sigma0 < long_run_vol`: the market is calm — risk metrics will be lower than a naïve constant-vol run.

### No new config keys needed

GARCH is calibrated entirely from live returns at runtime.
No changes to `option_configs.json` or `mc_config.json` are required.

---

## 6. Jump-Diffusion Model

### What it adds

The Merton (1976) jump-diffusion model augments GBM with a compound Poisson
jump process, capturing sudden large moves (crashes or spikes) not modelled by
continuous diffusion:

```
S(t+dt) = S(t) * exp((r - λκ - ½σ²)dt + σ√dt·Z + J_t)
  κ = exp(μ_J + ½σ_J²) - 1          (drift compensator)
  N ~ Poisson(λ·dt)                  (jumps per step)
  J_t = N·μ_J + √N·σ_J·ε            (compound log-jump)
```

### Programmatic usage

```python
from monte_carlo.jump_diffusion import simulate_jump_paths
from monte_carlo.gbm_simulator import run_monte_carlo, price_option_on_paths

# Low-level: simulate jump-diffusion paths directly
paths = simulate_jump_paths(
    S0=100, r=0.05, sigma=0.20,
    lam=0.1,      # 0.1 jumps/year on average
    mu_J=-0.05,   # average log-jump of -5%
    sigma_J=0.15, # log-jump std-dev 15%
    T=1.0, num_paths=10000, num_steps=252, seed=42,
)

# High-level: via run_monte_carlo()
jump_params = {'lam': 0.1, 'mu_J': -0.05, 'sigma_J': 0.15}
results = run_monte_carlo(
    config,
    use_jumps=True,
    jump_params=jump_params,
    num_paths=10000, seed=42,
)
# results['vol_model'] == 'jump'
# results['jump_params'] == {'lam': 0.1, 'mu_J': -0.05, 'sigma_J': 0.15}
```

### CLI `--jumps` flag

```bash
python src/mc_runner.py --json config/mc_config.json \
    --jumps --lam 0.1 --mu_J -0.05 --sigma_J 0.15 --seed 42
```

Console output:
```
Vol Model: Jump-Diffusion   lam=0.10  mu_J=-0.050  sigma_J=0.150
```

Jump diffusion takes **priority** over `--garch` when both are specified.
Falls back to constant-vol GBM if `--jumps` is given without valid parameters.

---

## 7. MC Greeks

### What it does

Estimates Delta, Gamma, Vega, Theta, and Rho by perturbing one input at a
time and repricing the option via MC.  Common Random Numbers (same seed for
all calls) keep noise low.

| Greek | Method | Bump |
|-------|--------|------|
| Delta | Central diff in S | h = S₀ × 1% |
| Gamma | Second central diff in S | same h |
| Vega  | Central diff in σ | Δσ = 0.01 (per 1 vol point) |
| Theta | One-sided: expiry − 1 day | − |
| Rho   | Central diff in r | Δr = 0.001 (per 1% rate change) |

### Programmatic usage

```python
from monte_carlo.mc_greeks import compute_mc_greeks

greeks = compute_mc_greeks(
    config,
    num_paths=3000,   # ~1 s total (7 repricing calls)
    num_steps=252,
    seed=42,
)

# Keys: delta, gamma, vega, theta, rho  (MC estimates)
#       bs_delta, bs_gamma, bs_vega, bs_theta, bs_rho  (BS reference)
print(f"Delta: {greeks['delta']:.4f}  (BS: {greeks['bs_delta']:.4f})")
```

### CLI `--greeks` flag

```bash
python src/mc_runner.py --json config/mc_config.json --seed 42 --greeks
```

Added output block:
```
MC Greeks (vs Black-Scholes):
  Delta:  0.5234  (BS:  0.5310)
  Gamma:  0.0198  (BS:  0.0201)
  Vega:   0.3872  (BS:  0.3912)   (per 1 vol point)
  Theta: -0.0412  (BS: -0.0405)  (per day)
  Rho:    0.4823  (BS:  0.4876)
```

---

## 8. American Options (Longstaff-Schwartz)

### When to use

European Black-Scholes cannot price American options.  American puts often
carry significant early-exercise premium, especially when deep in-the-money.
The Longstaff-Schwartz LSMC method approximates the optimal stopping time
via backward-induction regression on any set of simulated paths.

### Programmatic usage

```python
from monte_carlo.gbm_simulator import simulate_gbm_paths
from monte_carlo.american_mc import price_american_lsmc

paths = simulate_gbm_paths(S0=100, r=0.05, sigma=0.20,
                           T=1.0, num_paths=10000, num_steps=252, seed=42)

# Price an American put
am_price, std_err = price_american_lsmc(paths, K=100, r=0.05, T=1.0, option_type='put')
print(f"American put: ${am_price:.4f}  (±{std_err:.4f})")

# Via run_monte_carlo():
results = run_monte_carlo(config, num_paths=10000, seed=42, option_style='american')
print(f"European MC:  ${results['mc_price']:.2f}")
print(f"American MC:  ${results['american_price']:.2f}  "
      f"(+${results['early_exercise_premium']:.2f} early exercise)")
```

### CLI `--american` flag

```bash
python src/mc_runner.py --json config/mc_config.json --american --seed 42
```

Added output lines:
```
European MC Price:      $4.23  (std error: ±0.0042)
American  MC Price:     $4.81   (early exercise premium: +$0.58)
```

---

## 9. Implied Volatility Surface

### What it does

Fetches a live option chain via yfinance, back-solves implied volatility for
each strike/expiry via Brent's method, and produces a 3-D surface chart and
a per-expiry vol smile chart.

### Programmatic usage

```python
from analytics.vol_surface import compute_implied_vol, fetch_vol_surface, plot_vol_surface

# Single IV calculation (offline, no live data needed)
from models.black_scholes import black_scholes_price
price = black_scholes_price(100, 100, 1.0, 0.05, 0.25, 'call')
iv = compute_implied_vol(price, S=100, K=100, T=1.0, r=0.05, option_type='call')
# iv ≈ 0.25

# Full live surface
df = fetch_vol_surface('AAPL', r=0.045, max_expiries=6)
# df columns: expiry, T, strike, moneyness, iv, option_type

fig = plot_vol_surface(df, ticker='AAPL', save_path='./aapl_surface.png')
```

### Standalone CLI runner

```bash
python src/vol_surface_runner.py --ticker AAPL --max_expiries 6 --export_dir ./vol_surface/
```

Saves `AAPL_vol_surface.csv` and `AAPL_vol_surface.png`.

---

## 10. CLI Reference

### Black-Scholes runner

```bash
# From a JSON config file
python src/options_test_runner.py --json config/option_configs.json

# Live market data (yfinance)
python src/options_test_runner.py --live --ticker TSLA --days_to_expiry 30 --export_dir ./exports
```

### Monte Carlo runner

```bash
# From a JSON config (flags override config file values)
python src/mc_runner.py --json config/mc_config.json --num_paths 10000 --seed 42

# With plots saved
python src/mc_runner.py --json config/option_configs.json --num_paths 50000 --seed 42 --plot

# Live data mode
python src/mc_runner.py --live --ticker AAPL --days_to_expiry 45 --num_paths 10000 --plot
```

#### All MC runner flags

| Flag | Default | Description |
|------|---------|-------------|
| `--json FILE` | — | JSON config file (single config or `configurations` list) |
| `--live` | — | Fetch live data via yfinance |
| `--ticker SYM` | — | Ticker symbol (live mode only) |
| `--days_to_expiry N` | 30 | Target DTE for live mode |
| `--num_paths N` | 10000 | Number of GBM paths |
| `--num_steps N` | 252 | Steps per path (252 = 1 trading year, daily) |
| `--seed N` | None | Random seed for reproducibility |
| `--confidence F` | 0.95 | Confidence level for VaR/CVaR |
| `--antithetic` | False | Enable antithetic variates |
| `--garch` | False | Use GARCH(1,1) time-varying vol (auto-fetches returns for ticker) |
| `--jumps` | False | Use Merton jump-diffusion (takes priority over `--garch`) |
| `--lam F` | 0.1 | Jump intensity λ (jumps per year) |
| `--mu_J F` | -0.05 | Mean log-jump size |
| `--sigma_J F` | 0.15 | Std-dev of log-jump |
| `--greeks` | False | Compute MC Greeks via bump-and-reprice (CRN) |
| `--american` | False | Price as American option via Longstaff-Schwartz |
| `--export_dir DIR` | ./mc_results | Output directory |
| `--plot` | False | Save distribution histogram and path fan chart |

---

## 11. Config File Format

### Standard option config

```json
{
  "ticker": "AAPL",
  "current_price": 175.0,
  "strike_price": 180.0,
  "expiration_date": "2026-09-07",
  "option_type": "call",
  "implied_volatility": 0.25,
  "risk_free_rate": 0.045,
  "name": "AAPL Call $180"
}
```

### With Monte Carlo parameters (nested key)

```json
{
  "ticker": "AAPL",
  "current_price": 175.0,
  "strike_price": 180.0,
  "expiration_date": "2026-09-07",
  "option_type": "call",
  "implied_volatility": 0.25,
  "risk_free_rate": 0.045,
  "monte_carlo": {
    "num_paths": 10000,
    "num_steps": 252,
    "seed": 42,
    "confidence_level": 0.95,
    "antithetic": true
  }
}
```

CLI flags override `monte_carlo` values when both are provided.

### Multi-config file (for batch runs)

```json
{
  "configurations": [
    { "ticker": "AAPL", "current_price": 175.0, "strike_price": 175.0, ... },
    { "ticker": "AAPL", "current_price": 175.0, "strike_price": 185.0, ... }
  ]
}
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `current_price` | float | Current stock price |
| `strike_price` | float | Option strike |
| `expiration_date` | string | `YYYY-MM-DD` — must be in the future |
| `option_type` | string | `"call"` or `"put"` |
| `implied_volatility` | float | Annual vol as decimal (e.g. `0.25` = 25%) |

### Optional fields

| Field | Default | Description |
|-------|---------|-------------|
| `ticker` | `"UNKNOWN"` | Stock symbol |
| `risk_free_rate` | `0.045` | Annual risk-free rate |
| `name` | auto | Display name |

---

## 12. Risk Metrics

### VaR (Value at Risk)

The loss threshold exceeded with probability `(1 - confidence)`.

```
VaR(95%) = $5.00  →  95% of scenarios lose less than $5.00
```

### CVaR (Conditional VaR / Expected Shortfall)

The *expected* loss in the worst `(1 - confidence)` scenarios — always ≥ VaR.

```
CVaR(95%) = $6.50  →  in the worst 5% of scenarios, you lose $6.50 on average
```

### Key relationships

- `CVaR >= VaR` always
- For a long option: `VaR <= premium paid` (you can't lose more than you paid)
- Higher `sigma` → wider P&L distribution → higher CVaR

---

## 13. Running Tests

```bash
# MC tests only
python -m pytest tests/test_monte_carlo.py -v

# Black-Scholes tests only
python -m pytest tests/test_black_scholes.py -v

# All tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src/ --cov-report=term-missing
```

Expected: **50 tests passing** (10 BS + 18 MC + 7 GARCH + 6 Jump + 5 MCGreeks + 4 American + 4 VolSurface).

---

## 14. Examples

```bash
# Full Monte Carlo demo (4 use cases, saves plots to analysis_results/mc_demo/)
python examples/monte_carlo_demo.py

# Basic BS usage
python examples/basic_usage.py

# Advanced multi-leg strategies
python examples/advanced_strategies.py
```

### What `monte_carlo_demo.py` produces

| Plot | Description |
|------|-------------|
| `1_mc_vs_bs.png` | MC price convergence to BS as n increases |
| `2_pnl_distribution.png` | Payoff histogram with VaR/CVaR lines |
| `3_convergence.png` | Mean ± 2σ confidence band vs num_paths |
| `4_call_vs_put.png` | Side-by-side P&L distribution comparison |
