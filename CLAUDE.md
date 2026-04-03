# Options Pricing Toolkit — Claude Context

## Project Overview
Production-ready options analytics library with dual pricing engines (Black-Scholes + Monte Carlo), advanced volatility models (GARCH, jump-diffusion), American option pricing (LSMC), scenario analysis, and volatility surface tools.

## Environment
- **Python**: 3.9.6
- **venv**: `/Users/sirius/projects/environments/options_env`
- **Activate**: `source activate_env.sh` or `source /Users/sirius/projects/environments/options_env/bin/activate`
- **PYTHONPATH**: `src/` (all internal imports are relative to `src/`)
- **Build/test**: `./build.sh` (flags: `--demo`, `--mc`, `--full`)

## Directory Structure
```
options/
├── src/
│   ├── models/
│   │   └── black_scholes.py          # BS pricing, Greeks (Delta/Gamma/Theta/Vega/Rho)
│   ├── monte_carlo/
│   │   ├── gbm_simulator.py          # GBM paths, run_monte_carlo() orchestrator
│   │   ├── garch_vol.py              # fit_garch11(), simulate_garch_vol_paths()
│   │   ├── jump_diffusion.py         # simulate_jump_paths() (Merton)
│   │   ├── american_mc.py            # price_american_lsmc() (Longstaff-Schwartz)
│   │   ├── mc_greeks.py              # compute_mc_greeks() (bump-and-reprice + CRN)
│   │   └── risk_metrics.py           # compute_var, compute_cvar, compute_distribution_stats
│   ├── analytics/
│   │   ├── simulations.py            # Price/vol/time scenario sweeps
│   │   ├── visualization.py          # matplotlib charting
│   │   ├── vol_surface.py            # compute_implied_vol(), fetch_vol_surface(), plot_vol_surface()
│   │   └── scenario.py               # run_scenario_matrix(), format_pnl_table(), plot_scenario_matrix()
│   ├── utils/
│   │   ├── config.py                 # load_config_from_json(), validate_option_config()
│   │   └── data_export.py            # export_to_csv(), export_to_excel()
│   ├── scanner/
│   │   ├── __init__.py               # OptionSignal dataclass, scan_watchlist() public API
│   │   ├── providers/
│   │   │   ├── __init__.py           # create_provider() factory
│   │   │   ├── base.py              # ChainProvider ABC + OptionContract, ChainSnapshot, HistoryData
│   │   │   ├── yfinance_provider.py # YFinanceProvider (spot, chain, history, RFR)
│   │   │   └── cached_provider.py   # CachedProvider TTL decorator
│   │   ├── iv_rank.py               # compute_iv_metrics() — IV rank, percentile, regime
│   │   ├── contract_filter.py       # filter_contracts() — DTE, delta, moneyness, liquidity
│   │   ├── edge.py                  # compute_edge() — GARCH theo vs market mid
│   │   ├── scorer.py                # score_signal(), rank_signals()
│   │   ├── scanner.py               # OptionsScanner orchestrator
│   │   └── cli.py                   # CLI entry point
│   ├── options_analyzer.py           # High-level OptionsAnalyzer class
│   ├── options_test_runner.py        # BS CLI (--json / --live); adds _historical_returns key
│   ├── mc_runner.py                  # MC CLI (--json / --live / --plot / --garch / --jumps / --greeks / --american)
│   ├── scenario_runner.py            # Scenario CLI (--json / --live / --reprice / --plot)
│   └── vol_surface_runner.py         # Volatility surface CLI
├── config/
│   ├── option_configs.json           # BS configs (supports multi-config with "configurations" key)
│   ├── mc_config.json                # MC config with nested "monte_carlo" key
│   └── scanner_config.json           # Scanner filter/scoring/GARCH parameters
├── examples/
│   ├── basic_usage.py
│   ├── advanced_strategies.py
│   ├── monte_carlo_demo.py
│   └── market_validation.py          # Live market validation (new)
├── tests/
│   ├── test_black_scholes.py         # 10 BS tests
│   ├── test_monte_carlo.py           # 40 MC/GARCH/Jump/Greeks/American tests
│   ├── test_scenario.py              # 6 scenario tests
│   ├── test_vol_surface.py           # 4 IV surface tests
│   └── test_scanner.py              # 33 scanner tests (all mocked, no network)
├── Dockerfile                        # Multi-stage: prod + dev targets
├── docker-compose.yml                # Services: test, shell, bs, mc, scenario
├── .dockerignore
├── build.sh                          # Auto setup + test script
├── activate_env.sh
├── requirements.txt
├── requirements-dev.txt
├── HOWTO.md                          # Full usage reference (14 sections)
├── EXTENSIONS.md
└── CHANGELOG.md
```

## Import Pattern
- All packages under `src/` use **relative imports** (`.module`)
- Tests set `sys.path.append('src')` and import as `from monte_carlo.gbm_simulator import ...`
- `src/__init__.py` exposes top-level API

## Key Function Signatures

### Black-Scholes
```python
black_scholes_price(S, K, T, r, sigma, option_type='call') -> float
calculate_greeks(S, K, T, r, sigma, option_type='call') -> Dict[str, float]
    # Keys: Delta, Gamma, Theta, Vega, Rho
intrinsic_value(S, K, option_type) -> float
```

### Monte Carlo
```python
simulate_gbm_paths(S0, r, sigma, T, num_paths, num_steps, seed=None, antithetic=False) -> np.ndarray
    # Returns shape (num_paths, num_steps+1)

run_monte_carlo(config, num_paths=10000, num_steps=252, seed=None,
                confidence=0.95, antithetic=False, use_garch=False,
                use_jumps=False, jump_params=None, option_style='european',
                historical_returns=None) -> Dict
    # Returns: mc_price, bs_price, std_error, var, cvar, confidence, percentiles,
    #          payoffs, paths, num_paths, num_steps, T, vol_model, garch_params,
    #          jump_params, american_price, early_exercise_premium
    # vol_model: 'constant' | 'garch' | 'jump' (jumps take priority over garch)
```

### Risk Metrics
```python
compute_var(pnl: np.ndarray, confidence: float = 0.95) -> float
compute_cvar(pnl: np.ndarray, confidence: float = 0.95) -> float
compute_distribution_stats(values: np.ndarray) -> Dict[str, float]
```

### Advanced Models
```python
fit_garch11(daily_returns: np.ndarray) -> Dict          # omega, alpha, beta, sigma0, long_run_vol, converged
simulate_jump_paths(S0, r, sigma, lam, mu_J, sigma_J, T, num_paths, num_steps, seed) -> np.ndarray
price_american_lsmc(paths, K, r, T, option_type='put', degree=3) -> Tuple[float, float]
compute_mc_greeks(config, num_paths=3000, num_steps=252, seed=42) -> Dict
```

### Analytics
```python
run_scenario_matrix(config, ds_pct, dvol, days, use_mc_greeks=True,
                    reprice=False, **mc_kwargs) -> Dict
# PnL approx: ΔP ≈ Delta·ΔS + 0.5·Gamma·ΔS² + Vega·Δσ + Theta·Δt
```

### Scanner
```python
# Public API
scan_watchlist(tickers: List[str], provider=None, config=None) -> List[OptionSignal]

# Provider factory
create_provider(name='yfinance', cache=True, chain_ttl=900, history_ttl=3600) -> ChainProvider

# Components
compute_iv_metrics(current_iv: float, history: HistoryData) -> dict
    # Keys: iv_rank, iv_percentile, iv_regime, rv_high, rv_low, rv_mean
filter_contracts(contracts, spot, risk_free_rate, min_dte=20, max_dte=60,
                 min_delta=0.15, max_delta=0.50, min_oi=100,
                 max_spread_pct=15.0, moneyness_range=(0.85, 1.15)) -> List[OptionContract]
compute_edge(contract, spot, garch_vol, risk_free_rate, dte) -> dict
    # Keys: theo_price, edge_pct, direction, delta, gamma, theta, vega, rho
score_signal(edge_pct, iv_rank, spread_pct, open_interest, theta, vega, direction) -> float
    # Returns conviction 0–100

# Orchestrator
OptionsScanner(provider, config=None)
    .scan_ticker(ticker) -> List[OptionSignal]
    .scan_watchlist(tickers) -> List[OptionSignal]  # ranked by conviction
```

## Configuration Format

### Standard Option Config (JSON)
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

### Multi-Config
```json
{ "configurations": [ {...}, {...} ] }
```

### MC Config (nested key)
```json
{ "monte_carlo": { "num_paths": 10000, "num_steps": 252, "seed": 42, "confidence_level": 0.95, "antithetic": false } }
```

## CLI Reference

### Black-Scholes
```bash
python src/options_test_runner.py --json config/option_configs.json
python src/options_test_runner.py --live --ticker AAPL --days_to_expiry 30 [--export_dir ./exports]
```

### Monte Carlo
```bash
python src/mc_runner.py --json config/mc_config.json [--num_paths N] [--seed N] [--plot]
python src/mc_runner.py --json config/mc_config.json --garch --seed 42
python src/mc_runner.py --json config/mc_config.json --jumps --lam 0.1 --mu_J -0.05 --sigma_J 0.15
python src/mc_runner.py --json config/mc_config.json --american --greeks --seed 42
python src/mc_runner.py --live --ticker AAPL --days_to_expiry 45 --num_paths 10000 --plot
```

### Scenario
```bash
python src/scenario_runner.py --json config/mc_config.json [--reprice] [--plot]
python src/scenario_runner.py --json config/mc_config.json \
    --ds_pct -15,-10,-5,0,5,10,15 --dvol -10,-5,0,5,10 --days 0,5,10,20
python src/scenario_runner.py --live --ticker AAPL --days_to_expiry 45 --reprice --plot
```

### Volatility Surface
```bash
python src/vol_surface_runner.py --ticker AAPL --max_expiries 6 --export_dir ./vol_surface/
```

### Scanner
```bash
python -m src.scanner.cli --tickers AAPL,MSFT,NVDA --top 10
python -m src.scanner.cli --tickers AAPL --min_dte 20 --max_dte 60
python -m src.scanner.cli --watchlist config/watchlist.json --top 20
python -m src.scanner.cli --tickers AAPL --config config/scanner_config.json --export results.csv
```

## Docker
```bash
docker compose run test                      # Run full test suite
docker compose run shell                     # Interactive dev shell
docker compose run mc                        # MC simulation (10k paths, plots)
docker compose run bs                        # BS analysis from config
docker compose run scenario                  # Scenario matrix

docker build --target prod -t options-pricing .   # Production image only
docker build --target dev  -t options-pricing-dev . # Dev image with test tools
```

## Tests
- **93 total** (10 BS + 25 MC/GARCH + 6 Jump + 5 MCGreeks + 4 American + 4 VolSurface + 6 Scenario + 33 Scanner)
- **Run**: `python -m pytest tests/ -v`
- All 93 passing

## Output Directories (auto-created by CLI runners)
- `./mc_results/` — MC CSV exports + plots
- `./exports/` — BS CSV/Excel exports
- `./analysis_results/mc_demo/` — Demo plots
- `./vol_surface/` — Vol surface CSV + PNG

## Phase A: Options Chain Scanner — COMPLETE

**Task file:** `.claude/phase-a-scanner.md`

Scanner module (`src/scanner/`) scans watchlists for high-conviction trade signals.
Pipeline: fetch chain → IV rank → GARCH forward vol → filter → edge calc → score → rank.

**Status:** Complete. 12 files created, 33 tests passing. No new dependencies added.

## Changelog Rule
Every time a file is created, edited, or deleted, append an entry to `CHANGELOG.md`:
```
- [YYYY-MM-DD] <action>: <filename> — <brief description>
```
