# Phase A — Options Chain Scanner

## Goal

Build an options chain scanner that takes a watchlist of tickers, fetches live
chain data through a pluggable provider abstraction, computes IV rank/percentile,
estimates forward vol via GARCH, calculates edge (theo price vs market mid), and
outputs a ranked list of `OptionSignal` objects scored by conviction.

This is the first integration point between the options pricing toolkit and the
Trading Copilot. The scanner must be usable standalone (CLI) and importable as a
library.

---

## Architecture overview

```
Watchlist (List[str])
    │
    ▼
ChainProvider (ABC)          ← pluggable: YFinance or Polygon
    │
    ├─ get_spot(ticker)
    ├─ get_chain(ticker, min_dte, max_dte) → ChainSnapshot
    ├─ get_history(ticker, days) → HistoryData
    └─ get_risk_free_rate() → float
    │
    ▼
CachedProvider (decorator)   ← TTL cache, wraps any provider
    │
    ▼
IV Rank Engine               ← computes rank, percentile, regime
    │
    ├─ GARCH Forward Vol     ← reuses src/monte_carlo/garch_vol.py
    └─ Contract Filter       ← DTE, liquidity, delta, moneyness
    │
    ▼
Edge Calculator              ← BS price @ GARCH vol vs market mid
    │
    ▼
Scorer                       ← weighted conviction score
    │
    ▼
List[OptionSignal]           ← ranked output
```

---

## File structure to create

```
src/scanner/
├── __init__.py               # Public API: scan_watchlist(), OptionSignal
├── providers/
│   ├── __init__.py           # Re-exports ChainProvider, create_provider()
│   ├── base.py               # ABC + dataclasses (OptionContract, ChainSnapshot, HistoryData)
│   ├── yfinance_provider.py  # YFinanceProvider(ChainProvider)
│   └── cached_provider.py    # CachedProvider(ChainProvider) decorator
├── iv_rank.py                # compute_iv_rank(), compute_iv_percentile(), classify_regime()
├── contract_filter.py        # filter_contracts()
├── edge.py                   # compute_edge()
├── scorer.py                 # score_signal(), rank_signals()
├── scanner.py                # OptionsScanner class — orchestrates the pipeline
└── cli.py                    # CLI entry point: python -m src.scanner.cli

tests/
└── test_scanner.py           # Unit tests for all scanner components

config/
└── scanner_config.json       # Default scanner parameters
```

Do NOT create `polygon_provider.py` yet — leave a stub import in
`providers/__init__.py` with a comment. We build yfinance first, add paid
providers later.

---

## Data structures (define in `providers/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import numpy as np
import pandas as pd


@dataclass
class OptionContract:
    """Single option contract from the chain."""
    ticker: str
    strike: float
    expiry: str                    # YYYY-MM-DD
    option_type: str               # 'call' or 'put'
    bid: float
    ask: float
    mid: float                     # (bid + ask) / 2
    last: float
    volume: int
    open_interest: int
    implied_volatility: float      # from chain data (may be NaN)


@dataclass
class ChainSnapshot:
    """Full chain snapshot for one ticker."""
    ticker: str
    spot: float
    fetched_at: datetime
    contracts: List[OptionContract]
    expiries: List[str]            # available expiry dates


@dataclass
class HistoryData:
    """Historical price data for one ticker."""
    ticker: str
    closes: pd.Series              # DatetimeIndex → float
    returns: np.ndarray            # daily simple returns
    realized_vol_30d: float        # annualized 30-day realized vol
    realized_vol_60d: float        # annualized 60-day realized vol


class ChainProvider(ABC):
    """Abstract interface for options data providers."""

    @abstractmethod
    def get_spot(self, ticker: str) -> float:
        """Current spot price."""
        ...

    @abstractmethod
    def get_chain(self, ticker: str,
                  min_dte: int = 7,
                  max_dte: int = 90) -> ChainSnapshot:
        """Full option chain filtered by DTE range."""
        ...

    @abstractmethod
    def get_history(self, ticker: str,
                    days: int = 365) -> HistoryData:
        """Historical daily closes and derived vol metrics."""
        ...

    @abstractmethod
    def get_risk_free_rate(self) -> float:
        """Current risk-free rate (annualized)."""
        ...
```

---

## Scanner output (define in `scanner/__init__.py` or a `models.py`)

```python
@dataclass
class OptionSignal:
    """Single scored options trade signal."""
    # Contract identity
    ticker: str
    strike: float
    expiry: str
    option_type: str               # 'call' / 'put'
    dte: int

    # Market data
    spot: float
    bid: float
    ask: float
    mid: float
    open_interest: int
    bid_ask_spread_pct: float      # (ask - bid) / mid * 100

    # IV context
    chain_iv: float                # IV from the chain
    iv_rank: float                 # 0–100
    iv_percentile: float           # 0–100
    iv_regime: str                 # LOW / NORMAL / ELEVATED / HIGH

    # Edge
    garch_vol: float               # GARCH-calibrated forward vol
    theo_price: float              # BS price using garch_vol
    edge_pct: float                # (theo - mid) / mid * 100
    direction: str                 # BUY (positive edge) / SELL (negative edge)

    # Greeks (BS, computed at chain IV)
    delta: float
    gamma: float
    theta: float
    vega: float

    # Conviction
    conviction: float              # 0–100, weighted composite
```

---

## Implementation details by file

### `providers/yfinance_provider.py`

- `get_spot()`: use `yf.Ticker(ticker).fast_info['lastPrice']`.
  Fallback: `yf.Ticker(ticker).history(period='1d')['Close'].iloc[-1]`.
- `get_chain()`: iterate `yf.Ticker(ticker).options`, filter expiries by
  min_dte/max_dte, call `yf.Ticker(ticker).option_chain(expiry)` for each.
  Build `OptionContract` from each row. Compute `mid = (bid + ask) / 2`.
  Skip rows where `bid <= 0` or `ask <= 0`.
- `get_history()`: `yf.Ticker(ticker).history(period=f'{days}d')`.
  Compute `returns = closes.pct_change().dropna().values`.
  Compute `realized_vol_Nd = np.std(returns[-N:]) * np.sqrt(252)`.
- `get_risk_free_rate()`: `yf.Ticker('^IRX').fast_info['lastPrice'] / 100`.
  This is the 13-week T-bill yield. Fallback: return 0.045.
- Wrap all yfinance calls in try/except. On failure, log warning and
  return empty/default results — don't crash the whole scan.

### `providers/cached_provider.py`

- Wraps any `ChainProvider`.
- Constructor: `CachedProvider(provider, chain_ttl=900, history_ttl=3600)`.
- Cache is a dict: `{(method_name, ticker): (result, timestamp)}`.
- On cache hit within TTL: return cached result.
- On miss or stale: call underlying provider, store result, return it.
- `get_risk_free_rate()` cache key is just `('rfr',)`, TTL = 3600.
- Thread-safe: use `threading.Lock` around cache reads/writes.

### `iv_rank.py`

Functions:

```python
def compute_iv_metrics(current_iv: float,
                       history: HistoryData) -> dict:
    """
    Compute IV rank and percentile using realized vol as proxy.

    Since yfinance doesn't provide historical IV, we compute 30-day
    rolling realized vol over the past year and compare the chain's
    current ATM IV against that distribution.

    Returns dict with keys: iv_rank, iv_percentile, iv_regime,
    rv_high, rv_low, rv_mean.
    """
```

- Rolling 30-day realized vol: slide a 30-day window across the 1yr returns,
  compute `std * sqrt(252)` for each window. This gives ~230 data points.
- `iv_rank = (current_iv - min(rolling_rv)) / (max(rolling_rv) - min(rolling_rv)) * 100`
- `iv_percentile = (count where rolling_rv < current_iv) / len(rolling_rv) * 100`
- Regime thresholds:
  - `iv_rank < 25` → `LOW`
  - `25 <= iv_rank < 60` → `NORMAL`
  - `60 <= iv_rank < 80` → `ELEVATED`
  - `iv_rank >= 80` → `HIGH`

### `contract_filter.py`

```python
def filter_contracts(snapshot: ChainSnapshot,
                     min_dte: int = 20,
                     max_dte: int = 60,
                     min_delta: float = 0.15,
                     max_delta: float = 0.50,
                     min_oi: int = 100,
                     max_spread_pct: float = 15.0,
                     moneyness_range: tuple = (0.85, 1.15)) -> List[OptionContract]:
```

- Compute DTE from `contract.expiry` vs today.
- Compute moneyness = `strike / spot`.
- Compute spread_pct = `(ask - bid) / mid * 100`.
- Delta filter: compute BS delta using chain IV (or skip if IV is NaN).
  Use `calculate_greeks()` from `src/models/black_scholes.py`.
- Return contracts passing all filters.

### `edge.py`

```python
def compute_edge(contract: OptionContract,
                 spot: float,
                 garch_vol: float,
                 risk_free_rate: float,
                 dte: int) -> dict:
```

- Compute `T = dte / 365`.
- `theo_price = black_scholes_price(spot, contract.strike, T, risk_free_rate, garch_vol, contract.option_type)`.
- `edge_pct = (theo_price - contract.mid) / contract.mid * 100`.
- `direction = 'BUY' if edge_pct > 0 else 'SELL'`.
- Also compute full Greeks at both chain IV and GARCH vol for comparison.
- Return dict with `theo_price`, `edge_pct`, `direction`, and Greeks.

### `scorer.py`

```python
def score_signal(edge_pct: float,
                 iv_rank: float,
                 spread_pct: float,
                 open_interest: int,
                 theta: float,
                 vega: float,
                 direction: str) -> float:
```

Weighted scoring (0–100):

| Component       | Weight | Logic                                                    |
|-----------------|--------|----------------------------------------------------------|
| Edge magnitude  | 0.40   | `min(abs(edge_pct) / 20 * 100, 100)` — 20%+ edge = max  |
| IV rank signal  | 0.25   | HIGH rank + SELL = high score; LOW rank + BUY = high     |
| Liquidity       | 0.20   | Combine spread tightness and OI into 0–100               |
| Greeks quality  | 0.15   | For SELL: favor high |theta|/vega. For BUY: favor low cost |

```python
def rank_signals(signals: List[OptionSignal]) -> List[OptionSignal]:
    """Sort signals by conviction descending."""
```

### `scanner.py` — orchestrator

```python
class OptionsScanner:
    def __init__(self, provider: ChainProvider, config: dict = None):
        self.provider = provider
        self.config = config or DEFAULT_SCANNER_CONFIG

    def scan_ticker(self, ticker: str) -> List[OptionSignal]:
        """Full pipeline for one ticker."""
        # 1. Fetch chain + history
        # 2. Compute IV rank/percentile
        # 3. Fit GARCH to recent returns
        # 4. Filter contracts
        # 5. Compute edge for each surviving contract
        # 6. Score and return signals

    def scan_watchlist(self, tickers: List[str]) -> List[OptionSignal]:
        """Scan all tickers, merge and rank signals globally."""
        all_signals = []
        for ticker in tickers:
            try:
                signals = self.scan_ticker(ticker)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning(f"Failed to scan {ticker}: {e}")
                continue
        return rank_signals(all_signals)
```

### `cli.py`

```bash
# Usage:
python -m src.scanner.cli --tickers AAPL,MSFT,NVDA --top 10
python -m src.scanner.cli --tickers AAPL --provider yfinance --min_dte 20 --max_dte 60
python -m src.scanner.cli --watchlist config/watchlist.json --top 20
```

- Parse args, create provider via `create_provider()`, instantiate
  `OptionsScanner`, call `scan_watchlist()`, print results as a formatted table.
- Columns: Ticker, Strike, Expiry, Type, DTE, Mid, Edge%, IV Rank, Regime,
  Delta, Conviction.
- Optional `--export` flag to dump results to CSV.

---

## Config (`config/scanner_config.json`)

```json
{
  "chain_provider": "yfinance",
  "cache_ttl_chain": 900,
  "cache_ttl_history": 3600,
  "filter": {
    "min_dte": 20,
    "max_dte": 60,
    "min_delta": 0.15,
    "max_delta": 0.50,
    "min_open_interest": 100,
    "max_spread_pct": 15.0,
    "moneyness_range": [0.85, 1.15]
  },
  "garch": {
    "history_days": 120,
    "min_returns": 30
  },
  "scoring_weights": {
    "edge": 0.40,
    "iv_rank": 0.25,
    "liquidity": 0.20,
    "greeks": 0.15
  }
}
```

---

## What to reuse from existing codebase

| Existing module                          | What to import                         | Used in              |
|------------------------------------------|----------------------------------------|----------------------|
| `src/models/black_scholes.py`            | `black_scholes_price`, `calculate_greeks` | edge.py, contract_filter.py |
| `src/monte_carlo/garch_vol.py`           | `fit_garch11`                          | scanner.py           |
| `src/analytics/vol_surface.py`           | `compute_implied_vol`                  | iv_rank.py (optional)|

Import pattern: `sys.path.insert(0, src/)` then `from models.black_scholes import ...`
— same pattern as existing tests and CLI runners.

---

## Task sequence

### Task 1: Data layer (`providers/`)

Create `base.py` with all dataclasses and the ABC. Then implement
`YFinanceProvider` and `CachedProvider`. Write `providers/__init__.py` with
`create_provider()` factory.

**Acceptance criteria:**
- `YFinanceProvider().get_chain('AAPL')` returns a `ChainSnapshot` with >0 contracts
- `YFinanceProvider().get_history('AAPL', 365)` returns `HistoryData` with ~250 daily returns
- `YFinanceProvider().get_risk_free_rate()` returns a float between 0.0 and 0.15
- `CachedProvider` returns cached results on second call within TTL
- All methods handle yfinance failures gracefully (no uncaught exceptions)

**Stop condition:** If yfinance API has changed and `option_chain()` no longer
works, stop and document the failure. Do not guess at a workaround.

### Task 2: IV rank engine (`iv_rank.py`)

Implement `compute_iv_metrics()`. Requires `HistoryData` and a current IV float.

**Acceptance criteria:**
- iv_rank is 0–100
- iv_percentile is 0–100
- iv_regime is one of LOW/NORMAL/ELEVATED/HIGH
- When current_iv == min(rolling_rv), iv_rank == 0
- When current_iv == max(rolling_rv), iv_rank == 100
- Edge case: if history has <30 days of data, return defaults (rank=50, percentile=50, regime=NORMAL) and log a warning

### Task 3: Contract filter (`contract_filter.py`)

Implement `filter_contracts()`.

**Acceptance criteria:**
- Filters by DTE, moneyness, liquidity (OI + spread), and delta
- Delta computation uses `calculate_greeks()` from BS module
- Contracts with NaN IV are excluded
- Returns empty list (not error) when no contracts pass

### Task 4: Edge calculator (`edge.py`)

Implement `compute_edge()`.

**Acceptance criteria:**
- `theo_price` uses GARCH vol, not chain IV
- `edge_pct` is signed: positive = underpriced, negative = overpriced
- Greeks are computed at chain IV (market perspective)
- Returns complete dict even when edge is near zero

### Task 5: Scorer (`scorer.py`)

Implement `score_signal()` and `rank_signals()`.

**Acceptance criteria:**
- Conviction is 0–100
- Higher |edge| → higher conviction
- IV rank alignment matters: HIGH rank + SELL direction scores higher than HIGH rank + BUY
- Tighter spreads and higher OI → higher liquidity score
- `rank_signals()` returns list sorted by conviction descending

### Task 6: Orchestrator + CLI (`scanner.py`, `cli.py`)

Wire everything together. `scan_ticker()` runs the full pipeline.
`scan_watchlist()` iterates tickers and merges results.

**Acceptance criteria:**
- `scan_watchlist(['AAPL'])` returns a non-empty `List[OptionSignal]`
- Signals are sorted by conviction
- Failed tickers are skipped with a warning, not a crash
- CLI prints a clean table and optionally exports CSV
- `--tickers AAPL,MSFT` works

### Task 7: Tests (`tests/test_scanner.py`)

Write unit tests for each component. Mock yfinance where needed to avoid
network dependency in CI.

**Test plan:**
- `TestProviderBase`: dataclass construction, ABC enforcement
- `TestYFinanceProvider`: mock `yf.Ticker`, verify ChainSnapshot shape
- `TestCachedProvider`: verify cache hit/miss behavior, TTL expiry
- `TestIVRank`: known inputs → expected rank/percentile/regime
- `TestContractFilter`: verify each filter criterion independently
- `TestEdge`: known BS price → expected edge_pct and direction
- `TestScorer`: verify weight application, ranking order
- `TestScanner`: mock provider, verify end-to-end pipeline output

**Acceptance criteria:**
- All tests pass with `python -m pytest tests/test_scanner.py -v`
- No network calls in tests (all yfinance mocked)
- At least 20 test cases

---

## Conventions

- Follow existing code style: PEP 8, type hints on all public functions,
  numpy-style docstrings.
- Imports: `sys.path.insert(0, ...)` then bare module imports, matching
  existing pattern in `mc_runner.py`, `scenario_runner.py`, etc.
- No new dependencies. yfinance, numpy, pandas, scipy are already in
  `requirements.txt`. The scanner uses only these.
- All new files get a module docstring with description, author line
  ("Options Analytics Team"), and date.
- Update `CHANGELOG.md` after each task.
- Update `CLAUDE.md` after all tasks are complete — add the scanner section
  to the directory structure, CLI reference, and key function signatures.

---

## What NOT to build in Phase A

- No Polygon/Tradier/paid provider implementation (just leave the
  abstraction ready for it)
- No async/concurrent scanning (sequential is fine for now)
- No web UI or API endpoint
- No strategy template mapping (that's Phase B)
- No integration with Trading Copilot repo (that's Phase C)
- No options trade tracking (that's Phase D)

---

## Pre-flight check

Before starting Task 1, verify:
1. `python -m pytest tests/ -v` passes all 60 existing tests
2. `from models.black_scholes import black_scholes_price` works from `src/`
3. `from monte_carlo.garch_vol import fit_garch11` works from `src/`
4. `import yfinance as yf; print(yf.Ticker('AAPL').fast_info['lastPrice'])` returns a price

If any of these fail, fix them first before proceeding.
