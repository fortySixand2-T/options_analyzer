# Index Options Scanner

0-14 DTE defined-risk options scanner with three-layer signal architecture.
Docker deployment. FastAPI + React on `localhost:9000`.

## What It Does

Scans SPY, QQQ, IWM (configurable) for short-term options trades using a three-layer signal pipeline, then validates strategies through a historical backtester.

**Signal layers:**
1. **Vol regime** — IV rank, VIX level, term structure → HIGH_IV / MODERATE_IV / LOW_IV / SPIKE
2. **Directional bias** — EMA 9/21, RSI, MACD, momentum → STRONG_BULLISH to STRONG_BEARISH
3. **Dealer positioning** — GEX, max pain, P/C ratio → LONG_GAMMA / SHORT_GAMMA

**Pipeline:** Watchlist → ChainProvider → [Vol Regime → Bias → Dealer] → Decision Matrix → Strategy + Conviction Score

## Strategies (defined-risk only)

| Strategy | Regime | DTE |
|---|---|---|
| Iron condor | HIGH_IV + LONG_GAMMA | 7-14 |
| Short put spread | HIGH_IV + bullish | 3-10 |
| Short call spread | HIGH_IV + bearish | 3-10 |
| Long call/put spread | LOW/MODERATE_IV + directional | 3-14 |
| Butterfly | MODERATE/LOW_IV, pin at max pain | 0-7 |

No naked options, calendars, diagonals, strangles, or straddles.
Deferred strategies for a future swing module live in `src/strategies/_deferred/`.

## Quick Start

```bash
git clone https://github.com/fortySixand2-T/options_analyzer.git
cd options_analyzer
./start.sh
```

Open **http://localhost:9000** in your browser. First run takes ~2-3 minutes to build Docker images.

## Web UI

Five tabs:

- **Regime** — VIX level, term structure, IV rank, dealer positioning badge
- **Scanner** — Conviction-scored trade setups with signal checklists
- **Greeks** — Interactive options calculator (spot, strike, DTE, IV sliders)
- **Backtest** — Historical strategy validation with compare mode, signal filters, equity curves, P&L distribution, regime/DTE breakdowns, and trade log. Supports BS Model (fast, synthetic) and Real Data (chain_replay) sources
- **Journal** — Trade log with entry/exit tracking

## All Commands

```bash
./start.sh                    # Launch app (detached, localhost:9000)
./start.sh dev                # Foreground with hot-reload
./start.sh test               # Run test suite (364 tests)
./start.sh scan               # CLI scan: SPY, QQQ, IWM
./start.sh backtest           # Run backtest
./start.sh collect            # Collect daily chain snapshots
./start.sh collect-stats      # Snapshot DB statistics
./start.sh backfill SPY ...   # Alpaca historical options backfill
./start.sh backfill-status    # Show backfill progress
./start.sh backfill-theta     # ThetaData backfill (needs Theta Terminal)
./start.sh shell              # Interactive dev shell
./start.sh logs               # Tail app logs
./start.sh stop               # Stop everything
./start.sh build              # Rebuild Docker images
./start.sh restart            # Stop + rebuild + start
./start.sh clean              # Stop + remove containers/images
```

## Architecture

```
Watchlist → ChainProvider → [Vol Regime → Bias → Dealer] → Decision Matrix → Strategy + Score
```

The scanner evaluates all three signal layers independently, maps the combination to an appropriate strategy via the decision matrix, then scores the opportunity using weighted conviction scoring.

## Project Structure

```
├── config/
│   └── agents.yaml              # Agent profiles + guardrails (future use)
├── scripts/
│   ├── scan.py                  # Scanner CLI entry point
│   ├── run_backtest.py          # Backtest CLI entry point
│   ├── collect_chains.py        # Daily chain snapshot collector
│   ├── backfill_chains.py       # Alpaca historical backfill
│   ├── backfill_thetadata.py    # ThetaData historical backfill
│   └── daily_collect.sh         # Cron: daily chain snapshots
├── src/
│   ├── backtest/                # Backtesting engine
│   │   ├── local_backtest.py    # BS-model backtest runner
│   │   ├── chain_replay.py      # Real-data chain replay backtester
│   │   ├── analyzer.py          # Results analysis + breakdowns
│   │   └── models.py            # BacktestTrade, BacktestResult models
│   ├── data/                    # Data layer
│   │   ├── chain_store.py       # Chain snapshot SQLite storage
│   │   ├── alpaca_client.py     # Alpaca REST client
│   │   ├── thetadata_client.py  # ThetaData REST client
│   │   ├── thetadata_backfill.py# ThetaData backfill pipeline
│   │   └── backfill_pipeline.py # Alpaca backfill orchestrator
│   ├── regime/                  # Vol regime detection
│   │   └── detector.py          # IV rank, VIX, term structure
│   ├── scanner/                 # Chain scanning + scoring
│   │   ├── scanner.py           # Scan orchestration
│   │   ├── scorer.py            # Conviction scoring (frozen)
│   │   ├── strategy_mapper.py   # Decision matrix
│   │   ├── strategy_pricer.py   # Strike placement
│   │   └── providers/           # Data providers (TT, yfinance)
│   ├── strategies/              # Strategy implementations
│   │   ├── iron_condor.py
│   │   ├── credit_spread.py
│   │   ├── debit_spread.py
│   │   ├── butterfly.py
│   │   └── _deferred/           # Future swing strategies (14-60 DTE)
│   ├── models/                  # Black-Scholes pricer + Greeks (frozen)
│   ├── monte_carlo/             # GBM, GARCH, jump-diffusion (frozen)
│   ├── ui/
│   │   └── app.py               # FastAPI backend
│   ├── bias_detector.py         # Directional bias signals
│   └── config.py                # Conviction weights + config
├── frontend/src/
│   ├── App.jsx                  # React app with tab navigation
│   └── components/
│       ├── RegimeDashboard.jsx  # Vol regime visualization
│       ├── Scanner.jsx          # Options scanner view
│       ├── GreeksExplorer.jsx   # Interactive Greeks calculator
│       ├── Backtest.jsx         # Backtest config + orchestration
│       ├── BacktestParts.jsx    # Results views, charts, trade table
│       └── Journal.jsx          # Trade journal
├── data/                        # SQLite databases (Docker volume)
├── docker-compose.yml
├── Dockerfile
├── start.sh                     # Single entry point for everything
└── SIGNALS.md                   # Signal definitions (read first)
```

## Security

- Containers run as non-root user
- API key authentication on mutating endpoints (`API_SECRET_KEY` in .env)
- Input validation bounds on query parameters
- Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- Path traversal protection
- Error response sanitization

## Stack

- Python 3.11+, FastAPI, Pydantic v2
- React + Vite frontend
- Docker Compose (two images: `options_analyzer:prod` and `:dev`)
- SQLite for all persistence
- yfinance for chain data (free, delayed)
- Tastytrade API for live data (optional, free with funded account)
- Alpaca for historical backfill (optional)
- ThetaData for EOD greeks backfill (optional, $40/mo)
- ruff for linting, pytest for tests

## Environment Variables

Copy `.env.example` to `.env` and configure:

```
API_SECRET_KEY=      # API authentication key (protects mutating endpoints)
TT_USERNAME=         # Tastytrade (optional, for live data)
TT_PASSWORD=
APCA_API_KEY_ID=     # Alpaca (optional, for historical backfill)
APCA_API_SECRET_KEY=
THETADATA_URL=       # ThetaData Terminal URL (optional)
FLASHALPHA_API_KEY=  # FlashAlpha dealer data (optional, chain fallback works)
```

Without any credentials, the app runs on yfinance alone.

## Key Documentation

| File | Contents |
|---|---|
| `SIGNALS.md` | Signal definitions, decision matrix, conviction weights |
| `CLAUDE.md` | Development rules and frozen files |
| `HOWTO.md` | User guide |
| `VALIDATION_RESULTS.md` | Backtest results from 6 validation runs |
