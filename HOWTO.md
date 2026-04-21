# How to Run the Index Options Scanner

## Quick start (3 commands)

```bash
git clone https://github.com/fortySixand2-T/options_analyzer.git
cd options_analyzer
./start.sh
```

That's it. Open **http://localhost:8000** in your browser.

First run takes ~2-3 minutes to build Docker images. Subsequent runs start in seconds.

---

## Prerequisites

You need one thing installed: **Docker Desktop**.

- macOS: https://docs.docker.com/desktop/install/mac-install/
- Windows: https://docs.docker.com/desktop/install/windows-install/
- Linux: https://docs.docker.com/desktop/install/linux-install/

Make sure Docker Desktop is running before you start.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/fortySixand2-T/options_analyzer.git
cd options_analyzer
```

### 2. Configure credentials (optional but recommended)

On first run, `./start.sh` auto-creates a `.env` file from `.env.example`. To use live Tastytrade data instead of delayed yfinance data, edit `.env`:

```bash
# Open .env in your editor
nano .env    # or vim, code, etc.
```

Add your Tastytrade credentials:

```env
TT_USERNAME=your_tastytrade_email
TT_PASSWORD=your_tastytrade_password
```

Everything else has sensible defaults. Without TT credentials, the app works fine using yfinance (free, delayed 15 min).

### 3. Launch

```bash
./start.sh
```

You'll see:

```
╔══════════════════════════════════════╗
║   Index Options Scanner              ║
║   Short-term options decision tool   ║
╚══════════════════════════════════════╝

Starting Options Scanner...
  Backend API:  http://localhost:8000
  API docs:     http://localhost:8000/docs
  Web UI:       http://localhost:8000

  Press Ctrl+C to stop
```

---

## What you get

### Web UI (http://localhost:8000)

Five tabs:

**Regime** — Current market regime classification. Shows VIX level, VIX term structure (contango/backwardation), IV rank, upcoming FOMC/CPI dates, and which strategy types are favored right now.

**Scanner** — Scans your watchlist for trade setups. Each result shows a conviction score (0-100) and an expandable signal checklist explaining what's driving the score: IV rank alignment, GARCH edge, liquidity, Greeks quality, regime match. Toggle between single-contract signals and multi-leg strategy recommendations (iron condors, spreads, straddles, etc.).

**Greeks** — Interactive options calculator. Drag sliders for spot price, strike, DTE, and IV to see how price and Greeks respond in real time. Useful for "what if" analysis before entering a trade.

**Backtest** — Historical strategy validation. Pick a strategy (iron condor, credit spread, etc.), a symbol, and a date range. See win rate, profit factor, Sharpe ratio, max drawdown, and an equity curve. Compare strategies side by side. This answers "would this scanner setup have actually made money?"

**Journal** — Trade log. Record entries and exits, track actual P&L vs predicted, and see per-strategy performance over time.

### API docs (http://localhost:8000/docs)

Full interactive Swagger UI. Every endpoint is documented and testable from the browser.

---

## All start.sh commands

| Command | What it does |
|---|---|
| `./start.sh` | Launch the full app on :8000 |
| `./start.sh dev` | Launch with hot-reload (backend only) |
| `./start.sh scan SPY,QQQ --strategies` | One-off CLI scan |
| `./start.sh backtest --strategy iron_condor --symbol SPY` | One-off backtest |
| `./start.sh test` | Run the test suite (10 test files) |
| `./start.sh shell` | Interactive dev shell inside Docker |
| `./start.sh stop` | Stop all running containers |
| `./start.sh logs` | Tail live app logs |
| `./start.sh status` | Show running containers |
| `./start.sh build` | Rebuild Docker images |
| `./start.sh clean` | Stop + remove all containers and images |

---

## CLI usage (without Docker)

If you prefer running directly with Python:

```bash
# Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set PYTHONPATH
export PYTHONPATH=src       # Windows: set PYTHONPATH=src

# Run the scanner
python scripts/scan.py SPY --top 10
python scripts/scan.py SPY,QQQ,IWM --strategies --top 10

# Run a backtest
python scripts/backtest.py --strategy iron_condor --symbol SPY
python scripts/backtest.py --compare --symbols SPY,QQQ --strategies iron_condor,credit_spread

# Start the web app
python -m uvicorn ui.app:app --host 0.0.0.0 --port 8000
# Then open http://localhost:8000
```

---

## Scanner CLI examples

```bash
# Basic scan — top 10 single-contract signals for SPY
./start.sh scan SPY --top 10

# Multi-ticker scan with strategy recommendations
./start.sh scan SPY,QQQ,IWM,NVDA,TSLA --strategies --top 20

# Scan with custom DTE range (0-7 DTE only)
./start.sh scan SPY --min-dte 0 --max-dte 7 --strategies

# Export results to CSV
./start.sh scan SPY,QQQ --strategies --export results.csv
```

### What the scanner output looks like

```
Market Regime: LOW_VOL_RANGING (VIX: 14.2, contango)
Eligible strategies: iron_condor, credit_spread, butterfly, calendar_spread

  #  Strategy         Ticker  Score  Signals   Entry   Max P   Max L   R:R     P(Profit)
  1  Iron Condor      SPY     82     5/6       $1.45   $145    $355    1:2.4   72.3%
     ├─ Regime match           ✓  LOW_VOL matches iron_condor
     ├─ IV rank > 30           ✓  IV rank 47.2
     ├─ DTE in range           ✓  7 DTE (target 3-14)
     ├─ No event in 2d         ✓  Next: CPI in 8 days
     ├─ VIX < 25               ✓  VIX 14.2
     └─ Spread liquidity       ✗  OI 234 (want 500+)

  2  Credit Spread    QQQ     74     4/5       $0.85   $85     $415    1:4.9   68.1%
     ...
```

---

## Backtest CLI examples

```bash
# Backtest iron condors on SPY for the last 3 years
./start.sh backtest --strategy iron_condor --symbol SPY --start 2023-01-01

# Backtest with Tastytrade's backtester (requires TT credentials)
./start.sh backtest --strategy iron_condor --symbol SPY --provider tastytrade

# Compare strategies
./start.sh backtest --compare --symbols SPY,QQQ --strategies iron_condor,credit_spread,debit_spread

# Local backtest (no TT needed, uses yfinance + BS pricer)
./start.sh backtest --local --strategy credit_spread --symbol QQQ --start 2022-01-01
```

### What backtest output looks like

```
Backtest: iron_condor on SPY (2023-01-01 to 2026-04-20)
Source: local (BS pricer + yfinance OHLCV)

  Total trades:     187
  Win rate:         68.4%
  Avg win:          $124.50
  Avg loss:         -$287.30
  Avg P&L:          $38.20
  Total P&L:        $7,143.40
  Profit factor:    1.42
  Sharpe ratio:     1.18
  Max drawdown:     -$1,240.00 (-12.4%)
  Avg DTE at entry: 8.2
  Avg days in trade: 4.1

  Regime breakdown:
    LOW_VOL_RANGING:    72.1% win rate (134 trades)
    HIGH_VOL_TRENDING:  58.3% win rate (48 trades)
    SPIKE_EVENT:        40.0% win rate (5 trades)
```

---

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `TT_USERNAME` | (empty) | Tastytrade email/username |
| `TT_PASSWORD` | (empty) | Tastytrade password |
| `FLASHALPHA_API_KEY` | (empty) | FlashAlpha API key for GEX data |
| `ANTHROPIC_API_KEY` | (empty) | For AI narrative generation |
| `OPTIONS_FUND_SIZE` | 10000 | Your fund size in dollars |
| `OPTIONS_MAX_RISK_PCT` | 0.02 | Max risk per trade (2%) |
| `OPTIONS_MAX_POSITIONS` | 5 | Max concurrent positions |
| `OPTIONS_RISK_FREE_RATE` | 0.045 | Annual risk-free rate |
| `OPTIONS_MC_PATHS` | 5000 | Monte Carlo simulation paths |
| `OPTIONS_MC_STEPS` | 252 | MC time steps (trading days/year) |
| `OPTIONS_MC_SEED` | 42 | MC random seed (reproducibility) |
| `SCANNER_MIN_DTE` | 0 | Default min DTE filter |
| `SCANNER_MAX_DTE` | 14 | Default max DTE filter |
| `SCANNER_SCORE_THRESHOLD` | 60 | Min score to show a result |
| `SCANNER_WATCHLIST` | SPX,SPY,QQQ,IWM,NVDA,TSLA | Default scan symbols |

---

## Data sources

| Source | What it provides | Cost | Credential needed |
|---|---|---|---|
| Tastytrade API | Live options chains, streaming Greeks, backtester (13yr history) | $0 (funded account) | `TT_USERNAME` + `TT_PASSWORD` |
| yfinance | Historical prices, VIX term structure, options chains (delayed) | $0 | None |
| FlashAlpha | GEX walls, gamma flip, dealer regime classification | $0 (5 calls/day) | `FLASHALPHA_API_KEY` |

Without any credentials, the app runs on yfinance alone. Each data source you add improves the scanner's accuracy.

---

## Project structure (for developers)

```
options_analyzer/
├── start.sh                 # One-command launcher
├── .env.example             # Environment template
├── Dockerfile               # Multi-stage build (Python 3.11 + Node 20)
├── docker-compose.yml       # Service definitions
├── requirements.txt         # Python dependencies
│
├── src/                     # All Python source code
│   ├── models/              # Black-Scholes pricer + Greeks
│   ├── monte_carlo/         # GBM, GARCH, jump-diffusion, American MC
│   ├── analytics/           # Vol surface, scenario analysis, visualization
│   ├── scanner/             # Chain scanner pipeline (providers → filter → score)
│   │   └── providers/       # Data provider implementations (Tastytrade, yfinance)
│   ├── regime/              # Market regime detection (VIX, term structure, calendar)
│   ├── strategies/          # 9 multi-leg strategy definitions + registry
│   ├── backtest/            # Backtesting engine (Tastytrade API + local)
│   ├── risk/                # Position sizing, pre-trade risk rules
│   ├── streaming/           # Live Greeks streaming via dxfeed WebSocket
│   ├── execution/           # Tastytrade order placement
│   └── ui/                  # FastAPI backend
│
├── frontend/                # React frontend (Vite)
│   └── src/components/      # RegimeDashboard, Scanner, GreeksExplorer, Backtest, Journal
│
├── scripts/                 # CLI entry points
│   ├── scan.py              # Scanner CLI
│   └── backtest.py          # Backtest CLI
│
├── tests/                   # 10 test files, ~150 tests
├── config/                  # JSON config files
└── data/                    # SQLite databases (backtest cache, trade journal)
```

---

## Troubleshooting

**Docker build fails on first run**

Make sure Docker Desktop is running and has at least 4GB memory allocated. The numpy/scipy build needs it.

**"Cannot connect to Tastytrade"**

Check your `TT_USERNAME` and `TT_PASSWORD` in `.env`. The app works fine without them using yfinance as a fallback.

**Port 8000 already in use**

```bash
# Find what's using port 8000
lsof -i :8000
# Or change the port in docker-compose.yml: ports: - "9000:8000"
```

**Frontend not loading / blank page**

The frontend is built during `docker build`. If you see a blank page, try:

```bash
./start.sh clean
./start.sh
```

**Scanner returns no results**

Markets may be closed. The scanner needs live or recent data. Try expanding the DTE range:

```bash
./start.sh scan SPY --max-dte 30 --top 10
```

**Backtest is slow**

Local backtests fetch historical data from yfinance on first run. Subsequent runs use the SQLite cache and are instant. Tastytrade backtests (with TT credentials) are faster since they use pre-computed data.

---

## Getting a Tastytrade account (free)

1. Go to https://tastytrade.com
2. Click "Open Account" — no minimum deposit required
3. Complete the application (takes ~5 minutes)
4. Fund with any amount (even $100 works — you need a funded account for free API data)
5. Add your credentials to `.env`

The Tastytrade API gives you real-time options chains with Greeks, 13 years of backtesting data, and eventually order execution — all for $0/month.
