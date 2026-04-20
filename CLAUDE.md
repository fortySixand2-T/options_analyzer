# CLAUDE.md — Index Options Scanner

## Project overview

**Goal**: Transform `options_analyzer` into a standalone Index Options Scanner for short-term (0–14 DTE) index options day trading. Adds Tastytrade live data, market regime detection, multi-leg strategy scoring with signal checklists, backtesting, and a web UI. Everything runs in Docker.

**Relationship**: Standalone project. NOT part of Trading Copilot. Some modules originally came from TC and have been decoupled; a few `app.services` references remain as dead code to clean up.

**Data stack**: Tastytrade API (live chains + streaming Greeks + backtester, $0) · FlashAlpha (GEX/dealer regime, free tier) · yfinance (VIX/history, free)

---

## Codebase orientation

```
src/
├── models/black_scholes.py          # BS pricer + Greeks (European)
├── monte_carlo/                     # GBM, GARCH(1,1), jump-diffusion, American MC, MC Greeks, VaR
├── analytics/                       # vol_surface (Brent IV solver + 3D plot), scenario, simulations, visualization
├── chain_scanner/                   # MAIN scanner pipeline: providers → IV rank → GARCH → filter → edge → score
│   ├── providers/base.py            # ChainProvider ABC — implement this for new data sources
│   ├── providers/yfinance_provider  # Current default provider
│   ├── scanner.py                   # OptionsScanner orchestrator
│   ├── scorer.py                    # Conviction scoring (edge + IV rank + liquidity + Greeks)
│   ├── strategy_mapper.py           # IV regime → multi-leg strategy recommendation
│   └── strategy_pricer.py           # Resolve legs → concrete strikes → BS price → MC prob-of-profit
├── scanner/                         # OLD duplicate of chain_scanner — DELETE in Phase 0
├── config.py                        # Env-based settings (risk-free rate, MC params, DTE windows)
├── pricer.py                        # Thin wrapper over models/ and monte_carlo/
├── bias_detector.py                 # TA signals → bullish/bearish/neutral classification
├── strategy_selector.py             # (bias, outlook) → strategy + S/R-anchored strikes
├── opportunity_builder.py           # End-to-end: bias → strategy → pricing → formatted opportunity
├── formatter.py                     # Output formatting for scanner results
├── scanner.py                       # TC-coupled scanner (has TC-DECOUPLED markers) — refactor in Phase 0
├── ai_narrative.py                  # LLM narrative generation (has app.config import) — refactor in Phase 0
├── options_analyzer.py              # High-level OptionsAnalyzer class (standalone, works as-is)
├── mc_runner.py                     # CLI MC runner (standalone, works as-is)
├── scenario_runner.py               # CLI scenario runner (standalone, works as-is)
└── vol_surface_runner.py            # CLI vol surface runner (standalone, works as-is)
```

---

## Known issues to fix

1. **`src/scanner/` is a stale duplicate of `src/chain_scanner/`** — delete it entirely, it's a subset
2. **`src/chain_scanner/scanner.py` line 206** imports `from app.database import get_db` inside `_fetch_iv_history()` — make it gracefully skip if unavailable
3. **`src/ai_narrative.py` line 15** imports `from app.config import ...` — decouple to local env vars
4. **`src/scanner.py` lines 16-17** have `# TC-DECOUPLED` markers — the functions below them (`_compute_hist_vol`, `_adapt_signals`, `scan_ticker`) reference `get_or_refresh_data` and `_tc_analyze` which don't exist standalone. This file needs a rewrite to work with `ChainProvider` instead
5. **11 `sys.path.insert` hacks** across the codebase — all because modules use bare imports (`from models.black_scholes import ...`). Fix by making `src/` a proper package or standardizing relative imports
6. **`src/chain_scanner/*.py` still has `pricing/src` path shims** that point to a nested structure that no longer exists — the models are at `src/models/` not `src/pricing/src/models/`
7. **No `__init__.py` exports** in most packages — chain_scanner's `__init__.py` defines `OptionSignal` dataclass and `scan_watchlist` but other packages export nothing

---

## Phase 0: Refactor (do this first)

**Goal**: Clean codebase, fix all broken imports, remove dead code, make everything importable.

### Tasks

1. **Delete `src/scanner/`** — it's a stale subset of `src/chain_scanner/`

2. **Fix all `sys.path` hacks** — replace with proper imports. Every file that has `sys.path.insert` needs the import paths updated to work from the project root. The pattern `from models.black_scholes import` should become a path that works when running from the repo root (e.g. `from src.models.black_scholes import` or relative imports within packages).
   - Files to fix: `chain_scanner/scanner.py`, `chain_scanner/edge.py`, `chain_scanner/contract_filter.py`, `chain_scanner/strategy_pricer.py`, `pricer.py`, `analytics/vol_surface.py`, `analytics/scenario.py`
   - Remove ALL `sys.path.insert` calls
   - Remove ALL `_SRC = ...` path construction blocks

3. **Fix `src/chain_scanner/scanner.py` `_fetch_iv_history()`** — add `ImportError` to the except clause so it returns `[]` when `app.database` doesn't exist

4. **Decouple `src/ai_narrative.py`** — replace `from app.config import ANTHROPIC_API_KEY, OPENAI_API_KEY, SYNTHESIS_PROVIDER` with:
   ```python
   ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
   OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
   SYNTHESIS_PROVIDER = os.getenv("SYNTHESIS_PROVIDER", "anthropic")
   ```

5. **Rewrite `src/scanner.py`** — delete the TC-coupled `scan_ticker()` that depends on `app.services.market_data` and `app.services.ta_engine`. Replace with a thin wrapper around `chain_scanner.scanner.OptionsScanner` + `opportunity_builder.build_all_opportunities` that uses the `ChainProvider` interface. Keep the same return shape.

6. **Add clean `__init__.py` exports**:
   - `src/models/__init__.py` — export `black_scholes_price`, `calculate_greeks`
   - `src/monte_carlo/__init__.py` — export key simulator and Greeks functions

7. **Remove TC-only config** from `src/config.py` — remove `PRICING` dict (AI token costs)

### Acceptance criteria
- `python -c "from src.chain_scanner.scanner import OptionsScanner"` works with no errors
- `python -c "from src.models.black_scholes import black_scholes_price"` works
- `python -c "from src.pricer import price_bs, price_mc, get_vol_surface"` works
- `grep -rn "sys.path.insert" src/` returns zero results
- `grep -rn "from app\." src/ --include="*.py" | grep -v "^.*:#"` returns zero results
- All existing tests pass

### Stop conditions
- Do NOT modify the mathematical logic in black_scholes.py, monte_carlo/, analytics/ scoring
- Do NOT change the ChainProvider ABC interface or scorer.py scoring logic
- Do NOT add new features — this phase is cleanup only
- Do NOT change any function signatures in the frozen files

---

## Phase 1: Tastytrade provider + CLI

**Goal**: Wire Tastytrade as a `ChainProvider` so the existing scanner works with live data.

### Tasks

1. **Create `src/chain_scanner/providers/tastytrade_provider.py`** implementing `ChainProvider`:
   - `get_spot()` — dxfeed Quote stream via tastytrade SDK
   - `get_chain()` — `tastytrade.instruments.get_option_chain()` → map to `OptionContract` dataclass
   - `get_history()` — delegate to yfinance (TT doesn't serve multi-year OHLCV)
   - `get_risk_free_rate()` — yfinance `^TNX`
   - Graceful fallback to `YFinanceProvider` if TT auth fails
   - Set `OptionContract.implied_volatility` from TT's per-expiry IV data

2. **Update `src/chain_scanner/providers/__init__.py`** — add `create_provider()` factory:
   ```python
   def create_provider(name="auto") -> ChainProvider:
       if name == "tastytrade" or (name == "auto" and os.getenv("TT_USERNAME")):
           return TastytradeProvider()
       return YFinanceProvider()
   ```

3. **Create `scripts/scan.py`** — CLI:
   ```
   python scripts/scan.py SPY --max-dte 14 --top 10
   python scripts/scan.py SPY,QQQ,IWM --strategies --export results.csv
   ```

4. **Add to `requirements.txt`**: `tastytrade>=8.0`

### Acceptance criteria
- `python scripts/scan.py SPY` prints ranked signals from live TT data (or yfinance fallback)
- Same OptionSignal output shape as existing scanner
- TT auth failure → graceful fallback, no crash

---

## Phase 2: Regime detection + strategy layer

**Goal**: Add market regime awareness. Scanner surfaces regime-appropriate multi-leg strategies with signal checklists.

### Tasks

1. **Create `src/regime/`**:
   - `detector.py` — classify: LOW_VOL_RANGING (VIX<18, contango) · HIGH_VOL_TRENDING (VIX 18-30) · SPIKE_EVENT (VIX>30 or pre-FOMC/CPI)
   - `vix_analysis.py` — VIX, VIX9D, VIX3M, VIX6M term structure via yfinance
   - `calendar.py` — FOMC/CPI/opex dates for 2026

2. **Create `src/strategies/`**:
   - `base.py` — `StrategyDefinition` ABC: ideal regime, DTE range, IV range, signal checklist, `evaluate()` → `StrategyResult`
   - `registry.py` — strategy catalog, `for_regime()` filter
   - One file per strategy (9 total): iron_condor, credit_spread, debit_spread, long_straddle, butterfly, calendar_spread, diagonal_spread, short_strangle, naked_put_1dte

3. **Create `src/strategy_scanner.py`** — wraps existing scanner + regime + strategies:
   - Detect regime → filter strategies → score per ticker × strategy → rank results

### Acceptance criteria
- `python scripts/scan.py SPY --strategies` prints regime + ranked multi-leg setups with checklists
- Each result: strategy name, score 0-100, checklist (X/Y signals), suggested strikes, risk/reward, P(profit)

---

## Phase 3: Backtesting engine

**Goal**: Validate strategies against historical data before trading live. The backtester answers "would this scanner setup have been profitable over the last N years?"

### Why backtesting matters
The scanner produces scored setups, but conviction scores alone don't prove edge. Before risking real capital, every strategy needs historical validation:
- Does this iron condor setup with score>70 actually produce positive EV over 500+ occurrences?
- Does regime filtering improve win rate vs unfiltered?
- What is the actual drawdown profile of each strategy?
- Do the MC probability estimates (P(profit)) match realized outcomes?

Without backtesting, the scanner is just an opinion generator. With backtesting, it's an empirically validated decision tool.

### Tasks

1. **Create `src/backtest/`**:
   - `__init__.py`
   - `tt_backtest.py` — Tastytrade Backtester API wrapper:
     - Uses TT's `/backtests` REST API (13 years of data, 137+ symbols)
     - Submit backtest: strategy type, entry conditions (delta, DTE, qty), exit conditions (profit %, loss %, DTE exit)
     - Poll for results, parse response
     - Returns per-trade P&L, aggregate stats, transaction logs
   - `local_backtest.py` — offline backtester using historical chain data:
     - For when TT API is unavailable or for custom strategy logic TT can't express
     - Uses yfinance/Polygon historical OHLCV + our BS pricer to simulate entries/exits
     - Applies the same scanner filters + scoring logic historically
     - Reuses existing `monte_carlo/` engine for path simulation
   - `analyzer.py` — backtest results analysis:
     - Win rate, avg win/loss, profit factor, max drawdown, Sharpe ratio
     - EV per setup: group by (strategy, regime, score_bucket) → realized P&L
     - Compare predicted P(profit) from MC vs actual realized win rate
     - Regime-conditional performance: does the regime filter add alpha?
     - Generate summary report as dict/DataFrame for UI consumption
   - `models.py` — Pydantic models:
     - `BacktestRequest`: strategy, symbol, date range, entry/exit rules
     - `BacktestTrade`: entry date/price, exit date/price, P&L, DTE at entry, regime at entry
     - `BacktestResult`: list of trades + aggregate stats + equity curve data

2. **Create `scripts/backtest.py`** — CLI entry point:
   ```
   # Run TT backtester for a specific strategy
   python scripts/backtest.py --strategy iron_condor --symbol SPY --start 2020-01-01 --end 2025-12-31

   # Run local backtest with scanner scoring
   python scripts/backtest.py --local --strategy credit_spread --symbol QQQ --min-score 60

   # Compare strategy performance across regimes
   python scripts/backtest.py --compare --symbols SPY,QQQ,IWM --strategies iron_condor,credit_spread,debit_spread
   ```

3. **Integrate with scanner output** — each `ScanResult` or `StrategyResult` should include a `backtest_summary` field (optional) showing historical performance for that exact setup when available. The UI can display this as "historically this setup has X% win rate over Y occurrences."

4. **Add backtest results caching** — store results in SQLite so repeated queries don't re-hit the TT API (5 calls/day is limited). Cache key: `(strategy, symbol, date_range, entry_params)`.

### Acceptance criteria
- `python scripts/backtest.py --strategy iron_condor --symbol SPY` returns aggregate stats
- TT backtester works when credentials available, local backtester works without
- Results include: win rate, avg P&L, max drawdown, profit factor, Sharpe, equity curve
- Backtest results cached in SQLite, re-query returns from cache

---

## Phase 4: FlashAlpha + risk management

1. `src/chain_scanner/providers/flashalpha_client.py` — GEX walls, gamma flip, dealer regime (5 calls/day free)
2. `src/risk/sizer.py` — Kelly / fixed-fractional position sizing from fund size + max risk %
3. `src/risk/rules.py` — event blackout, max positions, correlation check, stop/target
4. MC-based expected value for multi-leg positions (reuse existing `monte_carlo/`)

---

## Phase 5: Web UI (FastAPI + React)

### Backend
- `src/ui/app.py` — FastAPI entry point
- Routes:
  - `GET /api/regime` — current regime classification + VIX data
  - `GET /api/scan?symbols=SPY,QQQ&max_dte=14` — scanner results with checklists
  - `GET /api/chain/{symbol}?max_dte=14` — options chain with Greeks
  - `POST /api/greeks` — compute Greeks for arbitrary inputs (powers the interactive explorer)
  - `GET /api/backtest/{strategy}?symbol=SPY&start=2020-01-01` — backtest results
  - `GET /api/journal` — trade journal entries
  - `POST /api/journal` — log a trade
  - `WS /ws/greeks` — WebSocket streaming Greeks (Phase 6)

### Frontend (React)
- **Regime dashboard** — VIX gauge, term structure chart, IV rank heatmap, macro calendar, GEX levels
- **Scanner results** — table rows with expandable signal checklist dropdowns, conviction score badge per row
- **Chain viewer** — full options chain with Greeks columns, click-to-select legs
- **Trade builder** — interactive Greeks explorer (sliders: spot/vol/DTE/strike → live price + Greeks chart), P&L curve, MC scenario distribution cones, position sizing calculator
- **Backtest tab** — strategy performance charts (equity curve, drawdown, win rate by regime), compare strategies side-by-side, historical P&L distribution histogram
- **Journal** — trade log, actual P&L vs predicted EV, per-strategy performance stats

### Design direction
- Dark trading terminal aesthetic, data-dense but scannable
- Color coding: green/red for bullish/bearish signals, amber for neutral, blue for informational
- Signal checklist as accordion per scan result row
- Metric cards for regime stats (VIX, IV rank, term structure, days to event)
- Backtest charts: equity curve with drawdown overlay, regime-colored background bands

---

## Phase 6: Streaming + execution

1. WebSocket live Greeks streaming via dxfeed
2. Real-time score recalculation on price changes
3. Tastytrade order placement (paper first, then live)

---

## Docker setup

Everything runs in Docker for one-command launch. Update the existing `Dockerfile` and `docker-compose.yml`.

### Dockerfile updates
- Base image: `python:3.11-slim` (upgrade from 3.9)
- Set `PYTHONPATH=/app` so all imports work as `from src.xxx import`
- Add `node` for React frontend build (multi-stage: python base → node build → final)
- Install all requirements including `tastytrade`, `fastapi`, `uvicorn`, `rich`

### docker-compose.yml services

```yaml
services:
  # Full app: FastAPI backend + React frontend
  app:
    build:
      context: .
      target: prod
    ports:
      - "8000:8000"     # FastAPI
      - "3000:3000"     # React dev server (dev only)
    env_file: .env
    volumes:
      - ./data:/app/data          # SQLite backtest cache, trade journal
    command: uvicorn src.ui.app:app --host 0.0.0.0 --port 8000

  # CLI scanner (one-off runs)
  scan:
    build:
      context: .
      target: prod
    env_file: .env
    command: python scripts/scan.py SPY,QQQ,IWM --strategies --top 10

  # Backtester (one-off runs)
  backtest:
    build:
      context: .
      target: prod
    env_file: .env
    volumes:
      - ./data:/app/data
    command: python scripts/backtest.py --strategy iron_condor --symbol SPY

  # Tests
  test:
    build:
      context: .
      target: dev
    command: python -m pytest tests/ -v

  # Dev shell
  shell:
    build:
      context: .
      target: dev
    stdin_open: true
    tty: true
    env_file: .env
    volumes:
      - .:/app
      - ./data:/app/data
    command: bash
```

### .env file (create from .env.example)

```env
# Tastytrade (required for live data, free with funded account)
TT_USERNAME=
TT_PASSWORD=

# FlashAlpha (optional, free tier: 5 calls/day)
FLASHALPHA_API_KEY=

# AI narrative (optional)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
SYNTHESIS_PROVIDER=anthropic

# Fund parameters
OPTIONS_FUND_SIZE=10000
OPTIONS_MAX_RISK_PCT=0.02
OPTIONS_MAX_POSITIONS=5

# Scanner defaults
OPTIONS_RISK_FREE_RATE=0.045
OPTIONS_MC_PATHS=5000
OPTIONS_MC_STEPS=252
OPTIONS_MC_SEED=42
SCANNER_MIN_DTE=0
SCANNER_MAX_DTE=14
SCANNER_SCORE_THRESHOLD=60

# Underlyings watchlist
SCANNER_WATCHLIST=SPX,SPY,QQQ,IWM,NVDA,TSLA
```

### Launch commands
```bash
# First time setup
cp .env.example .env
# Edit .env with your credentials

# Launch the full app (backend + frontend)
docker compose up app

# Run a one-off scan
docker compose run --rm scan

# Run a backtest
docker compose run --rm backtest --strategy iron_condor --symbol SPY

# Run tests
docker compose run --rm test

# Dev shell
docker compose run --rm shell
```

---

## Frozen files (modify imports/paths only, never the math)

- `src/models/black_scholes.py`
- `src/monte_carlo/gbm_simulator.py`
- `src/monte_carlo/garch_vol.py`
- `src/monte_carlo/jump_diffusion.py`
- `src/monte_carlo/american_mc.py`
- `src/monte_carlo/mc_greeks.py`
- `src/monte_carlo/risk_metrics.py`
- `src/chain_scanner/scorer.py`
- `src/chain_scanner/edge.py`

---

## Dev conventions

- Python 3.11+, `ruff` for linting
- Pydantic v2 for new data models
- Async where tastytrade SDK requires it
- `rich` for CLI output
- Env vars: `TT_USERNAME`, `TT_PASSWORD`, `FLASHALPHA_API_KEY`, `OPTIONS_*` prefix
- Tests mirror `src/` structure in `tests/`
- Commits: `phase N: description`
- Run phase 0 first. Do not skip to later phases.
- All new services must work in Docker. Test with `docker compose run --rm test` before committing.