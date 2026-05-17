# Index Options Scanner

0-14 DTE defined-risk options scanner with multi-agent paper trading orchestrator.
Three-layer signal architecture. Docker deployment. FastAPI + React on `localhost:8000`.

## What It Does

Scans SPY, QQQ, IWM (configurable) for short-term options trades using a three-layer signal pipeline, then paper-trades them through independent agent profiles with portfolio-level risk guardrails.

**Signal layers:**
1. **Vol regime** — IV rank, VIX level, term structure → HIGH_IV / MODERATE_IV / LOW_IV / SPIKE
2. **Directional bias** — EMA 9/21, RSI, MACD, momentum → STRONG_BULLISH to STRONG_BEARISH
3. **Dealer positioning** — GEX, max pain, P/C ratio → LONG_GAMMA / SHORT_GAMMA

**Pipeline:** MarketState (L1) → TradeGenerator (L2) → Sizing (L3) → shadow_store

## Strategies (defined-risk only)

| Strategy | Regime | DTE |
|---|---|---|
| Iron condor | HIGH_IV + LONG_GAMMA | 7-14 |
| Short put spread | HIGH_IV + bullish | 3-10 |
| Short call spread | HIGH_IV + bearish | 3-10 |
| Long call/put spread | LOW/MODERATE_IV + directional | 3-14 |
| Butterfly | MODERATE/LOW_IV, pin at max pain | 0-7 |

No naked options, calendars, diagonals, strangles, or straddles.

## Multi-Agent Orchestrator

Four independent agent profiles compete for a shared risk budget. Each agent applies different filters to the same pipeline output. A central orchestrator enforces portfolio-level safety limits.

### Agent Profiles (`config/agents.yaml`)

| Agent | Allocation | Min Score | Strategies | Filter |
|---|---|---|---|---|
| conservative | 35% | 80 | butterfly, short_put_spread | High conviction only |
| momentum | 25% | 70 | long_call/put_spread | Bias strength >= 3 |
| vol_harvester | 25% | 70 | short_put_spread, butterfly | HIGH_IV, IV-RV edge >= 5% |
| opportunistic | 15% | 65 | all 4 | Broadest, smallest allocation |

### Portfolio Guardrails

| Parameter | Value | Purpose |
|---|---|---|
| max_total_positions | 12 | Hard cap across all agents |
| max_positions_per_ticker | 4 | Diversification per underlying |
| daily_drawdown_limit | 3% | Pause all new entries |
| portfolio_kill_switch | 8% | Full stop on cumulative drawdown |
| max_same_direction | 3 | Limits correlated directional bets |

### Agent-Level Safety

- **Daily loss pause**: Agent auto-pauses if daily loss exceeds its `max_daily_loss_pct`
- **Drawdown pause**: Agent auto-pauses at cumulative drawdown threshold
- **Position cap**: Each agent limited to `max_positions` open trades
- **Conflict resolution**: Opposing directions on same ticker → higher confluence score wins

## Quick Start

```bash
# First run — creates .env, builds Docker images
./start.sh

# Run the multi-agent orchestrator (one cycle)
./start.sh orchestrator

# Preview trades without logging
./start.sh orchestrator --dry-run

# Per-agent performance stats
./start.sh orchestrator-stats

# Pause/enable an agent
./start.sh orchestrator --pause momentum
./start.sh orchestrator --enable momentum
```

## All Commands

```bash
./start.sh                    # Launch app (detached, localhost:8000)
./start.sh dev                # Foreground with hot-reload
./start.sh test               # Run test suite
./start.sh scan               # CLI scan: SPY, QQQ, IWM
./start.sh backtest           # Run backtest
./start.sh orchestrator       # Multi-agent paper trading cycle
./start.sh orchestrator-stats # Per-agent performance breakdown
./start.sh shadow             # Shadow trade scan (single-agent legacy)
./start.sh shadow-stats       # Shadow trade statistics
./start.sh shadow-monitor     # Start exit monitor (5-min loop)
./start.sh collect            # Collect daily chain snapshots
./start.sh collect-stats      # Snapshot DB statistics
./start.sh backfill SPY ...   # Alpaca historical options backfill
./start.sh shell              # Interactive dev shell
./start.sh logs               # Tail app logs
./start.sh stop               # Stop everything
./start.sh clean              # Stop + remove containers/images
```

## Project Structure

```
├── config/
│   └── agents.yaml              # Agent profiles + guardrails (user-editable)
├── scripts/
│   ├── run_orchestrator.py      # Orchestrator CLI entry point
│   ├── shadow_check.py          # Shadow trade scanner
│   ├── backfill_chains.py       # Alpaca historical backfill CLI
│   ├── daily_collect.sh         # Cron: daily chain snapshots
│   └── daily_collect_midday.sh  # Cron: midday chain snapshots
├── src/
│   ├── agents/                  # Multi-agent orchestrator
│   │   ├── agent_config.py      # Pydantic v2 config models
│   │   ├── orchestrator.py      # Core loop: build → filter → guardrails → log
│   │   └── risk_ledger.py       # Per-agent + portfolio risk tracking
│   ├── backtest/                # Backtesting engine
│   │   ├── local_backtest.py    # Backtest runner with signal replay
│   │   ├── analyzer.py          # Results analysis
│   │   └── models.py            # Backtest data models
│   ├── data/                    # Data layer
│   │   ├── shadow_store.py      # SQLite shadow trade persistence
│   │   ├── shadow_monitor.py    # Exit monitor (5-min loop)
│   │   ├── chain_store.py       # Chain snapshot storage
│   │   ├── alpaca_client.py     # Alpaca REST client for historical data
│   │   └── backfill_pipeline.py # Historical backfill orchestrator
│   ├── execution/               # Order management (Alpaca paper)
│   │   └── order_manager.py     # Order bridge: candidate → order
│   ├── regime/                  # Vol regime detection
│   │   └── detector.py          # IV rank, VIX, term structure
│   ├── scanner/                 # Chain scanning + scoring
│   │   ├── scanner.py           # Scan orchestration
│   │   ├── scorer.py            # Conviction scoring
│   │   ├── strategy_mapper.py   # Decision matrix
│   │   └── strategy_pricer.py   # Strike placement
│   ├── strategies/              # Strategy implementations
│   │   ├── butterfly.py
│   │   ├── credit_spread.py
│   │   ├── debit_spread.py
│   │   ├── iron_condor.py
│   │   └── _deferred/          # Future swing strategies (14-60 DTE)
│   ├── swing/                   # Swing trading module
│   ├── ui/
│   │   └── app.py               # FastAPI backend (40+ endpoints)
│   ├── market_state.py          # L1: signal aggregation
│   ├── trade_generator.py       # L2: candidate generation + scoring
│   ├── sizing.py                # L3: Kelly criterion sizing
│   ├── bias_detector.py         # Directional bias signals
│   ├── portfolio.py             # Portfolio engine
│   └── config.py                # Conviction weights + config
├── frontend/src/
│   ├── App.jsx                  # React app with tab navigation
│   └── components/
│       ├── Scanner.jsx          # Options scanner view
│       ├── Backtest.jsx         # Backtesting UI with compare mode
│       ├── TradingView.jsx      # L1→L2→L3 pipeline + order placement
│       ├── RegimeDashboard.jsx  # Vol regime visualization
│       ├── ShadowTrades.jsx     # Paper trade tracker
│       ├── Portfolio.jsx        # Portfolio + charts (Recharts)
│       ├── Journal.jsx          # Trade journal
│       ├── SwingScanner.jsx     # Swing trade scanner
│       └── GreeksExplorer.jsx   # Interactive Greeks calculator
├── data/                        # SQLite databases (Docker volume)
├── docker-compose.yml
├── Dockerfile
├── start.sh                     # Single entry point for everything
└── SIGNALS.md                   # Signal definitions (read first)
```

## Architecture

```
Watchlist → ChainProvider → [Vol Regime → Bias → Dealer] → Decision Matrix → Strategy + Score
                                                                                    │
                                                        ┌───────────────────────────┘
                                                        ▼
                                                  agents.yaml
                                                        │
                                                  Orchestrator
                                                        │
                            ┌──────────┬────────────────┼────────────────┐
                            ▼          ▼                ▼                ▼
                       conservative  momentum      vol_harvester   opportunistic
                            │          │                │                │
                            └──────────┴────────────────┴────────────────┘
                                                        │
                                              Portfolio Guardrails
                                                        │
                                              shadow_store (SQLite)
                                                        │
                                              shadow_monitor (exits)
```

## Security

- Containers run as non-root user
- API key authentication on all endpoints
- Input validation bounds on query parameters
- Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- Path traversal protection
- Error response sanitization

## Stack

- Python 3.11+, FastAPI, Pydantic v2
- React + Vite frontend
- Docker Compose
- SQLite for all persistence
- yfinance for chain data
- Alpaca for paper trading + historical backfill
- ruff for linting, pytest for tests (570+ tests)

## Environment Variables

Copy `.env.example` to `.env` and configure:

```
TT_USERNAME=         # Tastytrade (optional)
TT_PASSWORD=
FLASHALPHA_API_KEY=  # FlashAlpha dealer data (optional, chain fallback works)
APCA_API_KEY_ID=     # Alpaca paper trading
APCA_API_SECRET_KEY=
API_KEY=             # API authentication key
```

## Key Documentation

| File | Contents |
|---|---|
| `SIGNALS.md` | Signal definitions, decision matrix, conviction weights |
| `CLAUDE.md` | Development rules and frozen files |
| `VALIDATION_RESULTS.md` | Backtest results from 6 validation runs |
| `HOWTO.md` | User guide |
| `config/agents.yaml` | Agent profiles and guardrails |
