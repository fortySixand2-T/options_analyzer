# Use Cases — Options Pricing Toolkit

A map of what this repo can do, organized by who is using it and what they're trying to accomplish.

---

## 1. Price a Single Option

The most basic use case — get a fair value and risk profile for one contract.

```bash
# From a static config
python src/options_test_runner.py --json config/option_configs.json

# Against live market data
python src/options_test_runner.py --live --ticker AAPL --days_to_expiry 30
```

```python
from options_analyzer import OptionsAnalyzer

config = {
    'ticker': 'AAPL',
    'current_price': 175.0,
    'strike_price': 180.0,
    'expiration_date': '2026-09-07',
    'option_type': 'call',
    'implied_volatility': 0.25,
    'risk_free_rate': 0.045,
}

analyzer = OptionsAnalyzer(config)
print(f"Price:  ${analyzer.get_current_price():.4f}")
print(f"Greeks: {analyzer.get_greeks()}")
# Delta, Gamma, Theta (per day), Vega (per vol point), Rho
```

**Outputs:** price, Delta, Gamma, Theta, Vega, Rho, intrinsic value.

---

## 2. Understand Time Decay (Theta)

Watch how an option loses value as expiration approaches — useful for deciding when to enter/exit.

```python
time_df = analyzer.analyze_time_decay(time_points=20)
print(time_df[['Days_to_Expiration', 'Option_Price', 'Theta']])
```

**Outputs:** table of price and theta across 20 time points from now to expiry.

---

## 3. Map P&L Across Price Scenarios

Find the break-even, max loss, and profit zones for a position.

```python
price_df = analyzer.analyze_price_scenarios(price_range=(140, 210), num_prices=30)

entry_price = analyzer.get_current_price()
break_even = config['strike_price'] + entry_price
print(f"Break-even: ${break_even:.2f}")
```

**Outputs:** P&L at each underlying price; identifies break-even point.

---

## 4. Stress-Test Volatility Sensitivity

See how much the option price changes if IV spikes or collapses — critical around earnings events.

```python
vol_df = analyzer.analyze_volatility_scenarios(vol_range=(0.10, 0.80), num_vols=15)
```

**Outputs:** option price and Vega across IV levels from 10% to 80%.

---

## 5. Run Monte Carlo Simulation

Price an option via path simulation instead of the closed-form formula — useful when you
want to model non-normal returns or validate the BS price.

```bash
python src/mc_runner.py --json config/mc_config.json --num_paths 50000 --seed 42 --plot
```

```python
results = run_monte_carlo(config, num_paths=50000, seed=42, antithetic=True)

print(f"BS Price:  ${results['bs_price']:.4f}")
print(f"MC Price:  ${results['mc_price']:.4f}  (±{results['std_error']:.4f})")
print(f"VaR(95%):  ${results['var']:.2f}")
print(f"CVaR(95%): ${results['cvar']:.2f}")
```

**Outputs:** MC price vs BS price, standard error, VaR, CVaR, full payoff distribution,
path fan chart, payoff histogram.

---

## 6. Model Volatility Clustering (GARCH)

When the market is in a high-vol regime, constant-vol GBM underestimates tail risk.
GARCH(1,1) calibrates to recent realized vol automatically.

```bash
# Auto-fetches 60 days of returns from yfinance for the ticker
python src/mc_runner.py --json config/mc_config.json --garch --seed 42
```

```python
import yfinance as yf
returns = yf.Ticker('AAPL').history(period='60d')['Close'].pct_change().dropna().values

results = run_monte_carlo(config, use_garch=True, historical_returns=returns, seed=42)
# results['garch_params']: omega, alpha, beta, sigma0, long_run_vol, converged
```

**When to use:** current market vol is significantly above or below long-run average;
you want VaR/CVaR to reflect today's actual vol regime, not a manually chosen number.

---

## 7. Model Crash Risk (Jump-Diffusion)

GBM and GARCH both produce continuous paths. Real markets jump — earnings surprises,
macro shocks, flash crashes. Merton jump-diffusion adds those fat tails.

```bash
python src/mc_runner.py --json config/mc_config.json \
    --jumps --lam 0.1 --mu_J -0.05 --sigma_J 0.15 --seed 42
```

```python
results = run_monte_carlo(
    config,
    use_jumps=True,
    jump_params={'lam': 0.1, 'mu_J': -0.05, 'sigma_J': 0.15},
    seed=42,
)
```

**Parameters:**

| Parameter | Meaning | Typical value |
|-----------|---------|---------------|
| `lam` | Expected jumps per year | 0.1 (one crash per ~10 years) |
| `mu_J` | Average log-jump size | -0.05 (−5% on average) |
| `sigma_J` | Spread of jump sizes | 0.15 |

**Effect:** raises put prices, lowers call prices slightly vs BS. CVaR increases
significantly because tails are heavier.

---

## 8. Price American Options (Early Exercise)

Black-Scholes only prices European options. American puts can be worth more due to
the right to exercise early — especially when deep ITM and interest rates are positive.

```bash
python src/mc_runner.py --json config/mc_config.json --american --seed 42
# Output:
# European MC Price:  $4.23  (std error: ±0.0042)
# American  MC Price: $4.81   (early exercise premium: +$0.58)
```

```python
results = run_monte_carlo(config, option_style='american', num_paths=10000, seed=42)
print(f"Early exercise premium: +${results['early_exercise_premium']:.2f}")
```

**Method:** Longstaff-Schwartz LSMC (backward induction regression). Works on
top of any simulator — GBM, GARCH, or jump-diffusion paths.

---

## 9. Compute Greeks Numerically (MC Greeks)

BS Greeks only apply to the BS model. For GARCH or jump-diffusion paths,
use bump-and-reprice with Common Random Numbers for low-noise estimates.

```bash
python src/mc_runner.py --json config/mc_config.json --greeks --seed 42
# Output:
# MC Greeks (vs Black-Scholes):
#   Delta:  0.5234  (BS:  0.5310)
#   Gamma:  0.0198  (BS:  0.0201)
#   Vega:   0.3872  (BS:  0.3912)
#   Theta: -0.0412  (BS: -0.0405)
#   Rho:    0.4823  (BS:  0.4876)
```

```python
from monte_carlo.mc_greeks import compute_mc_greeks
greeks = compute_mc_greeks(config, num_paths=3000, seed=42)
```

**Use case:** validating BS Greeks under a different vol model; hedging when your
pricing model is not BS.

---

## 10. Build a P&L Scenario Matrix

Stress-test a position across combinations of stock move, vol change, and time decay.
The output is a heatmap grid — the kind traders use to see where they make or lose money.

```bash
# Fast Greek approximation
python src/scenario_runner.py --json config/mc_config.json --plot

# Full MC repricing (slower, more accurate)
python src/scenario_runner.py --json config/mc_config.json --reprice --seed 42 --plot

# Custom grid
python src/scenario_runner.py --json config/mc_config.json \
    --ds_pct -20,-10,-5,0,5,10,20 \
    --dvol  -10,-5,0,5,10 \
    --days   0,5,10,20
```

**Approximation formula:** `ΔP ≈ δ·ΔS + ½γ·ΔS² + ν·Δσ + θ·Δt`

**Outputs:** heatmap PNG, P&L table per (ΔS%, Δvol, Δdays) cell.

---

## 11. Fetch the Implied Volatility Surface

See what the market actually prices in across strikes and expiries — not just a single IV number.
Reveals vol smile, skew, and term structure.

```bash
python src/vol_surface_runner.py --ticker AAPL --max_expiries 6
# Saves: AAPL_vol_surface.csv + AAPL_vol_surface.png
```

```python
from analytics.vol_surface import fetch_vol_surface, plot_vol_surface

df = fetch_vol_surface('AAPL', r=0.045, max_expiries=6)
# df columns: expiry, T, strike, moneyness, iv, option_type

fig = plot_vol_surface(df, ticker='AAPL', save_path='./aapl_surface.png')
```

**Outputs:** 3D surface plot (moneyness × time × IV) + 2D smile chart per expiry.

**Use case:** checking whether the flat `implied_volatility` in your config is a
reasonable approximation, or spotting where the market prices in tail risk.

---

## 12. Analyze Multi-Leg Strategies

Compare spreads, straddles, iron condors, or any combination side-by-side.

```python
# Bull call spread
long_call = {**base_config, 'strike_price': 175, 'option_type': 'call'}
short_call = {**base_config, 'strike_price': 185, 'option_type': 'call'}

for leg in [long_call, short_call]:
    a = OptionsAnalyzer(leg)
    print(f"Strike {leg['strike_price']}: ${a.get_current_price():.2f}  Delta={a.get_greeks()['Delta']:.3f}")

# Net premium and net delta
net_premium = OptionsAnalyzer(long_call).get_current_price() - OptionsAnalyzer(short_call).get_current_price()
```

**Supported strategies (via `config.py`):** single leg, bull/bear spreads, straddles,
strangles, iron condors, custom combinations.

---

## 13. Batch Analysis from Config File

Run one or many configurations in a single command using multi-config JSON.

```json
{
  "configurations": [
    { "ticker": "AAPL", "strike_price": 175, "option_type": "call", ... },
    { "ticker": "AAPL", "strike_price": 185, "option_type": "call", ... },
    { "ticker": "AAPL", "strike_price": 175, "option_type": "put",  ... }
  ]
}
```

```bash
python src/mc_runner.py --json config/option_configs.json --num_paths 10000 --seed 42
```

All configs are priced in sequence; results are exported to `./mc_results/`.

---

## 14. Export Results

Save analysis for reporting or further processing.

```python
# Full analysis with export
analyzer.run_full_analysis(export_results=True, export_dir='./exports')
# Writes: time_decay.csv, price_scenarios.csv, vol_scenarios.csv, summary.xlsx
```

**Formats:** CSV, Excel (`.xlsx`), JSON. CLI runners auto-export to `./mc_results/`
and `./exports/`.

---

## 15. Run in Docker

Reproduce any workflow in an isolated container — no local Python setup needed.

```bash
# Run full test suite
docker compose run test

# Interactive dev shell (results bind-mounted to host)
docker compose run shell

# Run MC simulation
docker compose run mc

# Run scenario matrix
docker compose run scenario

# Custom command
docker compose run mc python src/mc_runner.py \
    --json config/mc_config.json --garch --american --greeks --plot
```

---

## Quick Reference by Goal

| Goal | Command / Method |
|------|-----------------|
| Price + Greeks (fast) | `options_test_runner.py --live` |
| Monte Carlo price | `mc_runner.py --num_paths 50000` |
| Crash risk / fat tails | `mc_runner.py --jumps` |
| Vol clustering | `mc_runner.py --garch` |
| American put premium | `mc_runner.py --american` |
| Model-free Greeks | `mc_runner.py --greeks` |
| Scenario heatmap | `scenario_runner.py --reprice --plot` |
| IV surface | `vol_surface_runner.py --ticker AAPL` |
| Full export | `analyzer.run_full_analysis(export_results=True)` |
| Isolated environment | `docker compose run test` |
