# Sentiment Analysis Module — Design Document

## Purpose

Standalone, pluggable news-sentiment pipeline for the Index Options Scanner.
Collects financial headlines, scores them with FinBERT, aggregates into
directional signals, persists everything to SQLite for backtesting, and
exposes a clean interface that any consuming system can import.

**This module has zero imports from other `src/` packages.**
It depends only on its own code, standard library, and third-party packages.
Integration with the scanner happens at the *call site*, not inside this module.

---

## Current status (2026-05-26)

### What we have

| Component | Status | Tests |
|---|---|---|
| Data models (Headline, ScoredHeadline, SentimentSnapshot, SentimentSignal) | Done | 11 |
| SQLite store (headlines, scored_headlines, sentiment_snapshots) | Done | 16 |
| CSV provider (Kaggle-format replay for backtesting) | Done | 16 |
| NewsAPI provider (live headlines, free tier) | Done | — |
| FinBERT scorer (batch scoring, lazy model loading) | Done (code) | 11 (mocked) |
| Aggregator (exp-decay rolling windows, velocity, breadth) | Done | 17 |
| Signal generator (40/40/20 weighted composite) | Done | 15 |
| Backtest runner + CLI script | Done (code) | — |
| **Total tests** | **86 passing** | |

All code is written and tested. The pipeline works end-to-end in unit tests
with mocked FinBERT. Two blockers remain before live execution:

### What's blocking

1. **torch + transformers not in Docker** — FinBERT needs PyTorch (~280MB
   CPU-only wheel) and HuggingFace transformers. Without these, the scorer
   can't run live. Tests pass by mocking torch.

2. **No headline CSV data** — The backtest needs historical financial
   headlines. A Kaggle dataset (e.g. "Daily Financial News for Stock Market
   Prediction") placed at `data/headlines.csv` would unblock Phase 4.

### Where we're going

```
Current state                          Target state
─────────────                          ────────────
[x] Models + store + providers         [ ] torch in Docker image
[x] Scorer (code, mocked tests)   →   [ ] Scorer runs live on real headlines
[x] Aggregator + signal gen            [ ] Phase 4 backtest with real data
[x] Backtest runner (code)             [ ] Decision gate: hit_rate>52%, Sharpe>0.3, corr>0.05
                                       [ ] If gate passes → Phase 5 integration
                                       [ ] bias_detector gets optional sentiment input
                                       [ ] API endpoint + dashboard widget
```

**Decision gate (Phase 4):** The backtest must show that sentiment velocity
predicts next-day directional moves before we wire it into the scanner.
If it doesn't, we park the module and revisit with better data or a
different model. No integration without evidence.

---

## Architecture

```
NewsProvider (ABC)          FinBERT Scorer          Aggregator           Signal
  |-- NewsAPI              headline text -->      per-ticker rolling   SentimentSignal
  |-- CSVProvider          {pos, neg, neu,        windows (1h, 6h,     dataclass with
  '-- (future)              confidence}            24h) + velocity      label + score +
        |                        |                 computation          velocity + detail
        v                        v                      v                    v
   +---------------- SQLite (sentiment.db) --------------------------------+
   |  headlines        scored_headlines       sentiment_snapshots          |
   |  (raw text,       (+ pos/neg/neu/       (ticker, window,            |
   |   timestamp,       confidence,           composite_score,            |
   |   source)          model_version)        velocity, label)            |
   +----------------------------------------------------------------------+
                                                      |
                                              BacktestRunner
                                        (replay signals vs price,
                                         hit rate, Sharpe, etc.)
```

---

## Module layout

```
src/sentiment/
├── __init__.py              # Public API: SentimentSignal, get_sentiment()
├── DESIGN.md                # This file
├── config.py                # Env-var config (API keys, windows, thresholds)
├── models.py                # Dataclasses: Headline, ScoredHeadline, SentimentSnapshot, SentimentSignal
├── providers/
│   ├── __init__.py          # create_news_provider() factory
│   ├── base.py              # NewsProvider ABC
│   ├── newsapi_provider.py  # NewsAPI.org (free tier, 100 req/day)
│   └── csv_provider.py      # Historical CSV replay for backtesting
├── scorer.py                # FinBERT scoring: headline → sentiment vector
├── aggregator.py            # Rolling windows, velocity, composite signal
├── store.py                 # SQLite persistence (idempotent schema, WAL mode)
├── signal.py                # SentimentSignal generation (labels + thresholds)
└── backtest.py              # Standalone backtest runner

scripts/
└── run_sentiment_backtest.py  # CLI: run backtest, print decision gate

tests/
├── test_sentiment_models.py      # 11 tests
├── test_sentiment_store.py       # 16 tests
├── test_csv_provider.py          # 16 tests
├── test_sentiment_scorer.py      # 11 tests (mocked torch)
├── test_sentiment_aggregator.py  # 17 tests
└── test_sentiment_signal.py      # 15 tests
```

---

## Data flow (per tick)

1. **Collect** — `NewsProvider.fetch_headlines(ticker, since)` returns `List[Headline]`
2. **Score** — `SentimentScorer.score_batch(headlines)` returns `List[ScoredHeadline]`
3. **Store** — `SentimentStore.save_scored(scored_headlines)` persists to SQLite
4. **Aggregate** — `SentimentAggregator.aggregate(ticker, windows)` reads from store,
   computes rolling sentiment per window, derives velocity
5. **Signal** — `generate_signal(aggregation)` maps composite score + velocity to a
   `SentimentSignal` with label (STRONG_POSITIVE → STRONG_NEGATIVE)

---

## Key dataclasses (see models.py)

| Class | Purpose | Key fields |
|---|---|---|
| `Headline` | Raw headline from provider | text, ticker, published_at, source |
| `ScoredHeadline` | After FinBERT | + positive, negative, neutral, confidence, label |
| `SentimentSnapshot` | Aggregated window | ticker, window, composite_score, velocity, headline_count, timestamp |
| `SentimentSignal` | Final output | ticker, label, score, velocity, snapshots, detail |

---

## Signal labels

| Score range | Label | Interpretation |
|---|---|---|
| >= +0.4 | STRONG_POSITIVE | Clear bullish sentiment shift |
| +0.15 to +0.4 | LEAN_POSITIVE | Mild bullish tilt |
| -0.15 to +0.15 | NEUTRAL | No directional edge |
| -0.4 to -0.15 | LEAN_NEGATIVE | Mild bearish tilt |
| <= -0.4 | STRONG_NEGATIVE | Clear bearish sentiment shift |

Thresholds are configurable in `config.py`. Velocity (rate of change in
composite score) is tracked separately and is often a stronger signal than
absolute level — per Bollen et al. (2011), sentiment *shift* matters more
than sentiment *level*.

---

## Composite score formula

```
composite = weighted_mean(scored_headlines, decay=exponential, halflife=window)
            x confidence_filter(min_confidence=0.6)

velocity  = composite(window=1h) - composite(window=6h)
breadth   = positive_count / total_count  (fraction of headlines that are positive)
```

The `SentimentSignal.score` combines:
- composite level (40%)
- velocity (40%)
- breadth divergence from 0.5 (20%)

---

## Integration points (Phase 5 — not built yet, contingent on backtest)

The consuming system imports `SentimentSignal` and uses it however it wants:

```python
from sentiment import get_sentiment, SentimentSignal

sig: SentimentSignal = get_sentiment("SPY")
# sig.label -> "LEAN_POSITIVE"
# sig.score -> 0.23
# sig.velocity -> 0.08

# Add to bias score with configurable weight
bias_score += sig.score * SENTIMENT_WEIGHT
```

The module itself never imports from `scanner/`, `regime/`, `bias_detector`,
or any other `src/` package. This is a hard rule.

Integration plan:
- `src/bias_detector.py` — optional `sentiment_signal` parameter, default weight 10%
- `src/config.py` — `SENTIMENT_WEIGHT` env var
- `src/ui/app.py` — `/api/sentiment/{ticker}` endpoint
- `frontend/` — sentiment gauge widget on dashboard
- `src/scanner/scorer.py` is FROZEN — use a wrapper, not direct modification

---

## SQLite schema

Three tables in `data/sentiment.db`:

### headlines
```sql
CREATE TABLE headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    text TEXT NOT NULL,
    published_at TEXT NOT NULL,      -- ISO 8601
    source TEXT NOT NULL,            -- 'newsapi', 'csv'
    url TEXT,
    collected_at TEXT NOT NULL,
    UNIQUE(ticker, text, published_at)
);
```

### scored_headlines
```sql
CREATE TABLE scored_headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    headline_id INTEGER NOT NULL REFERENCES headlines(id),
    positive REAL NOT NULL,
    negative REAL NOT NULL,
    neutral REAL NOT NULL,
    confidence REAL NOT NULL,
    label TEXT NOT NULL,             -- 'positive', 'negative', 'neutral'
    model_version TEXT NOT NULL,     -- 'ProsusAI/finbert'
    scored_at TEXT NOT NULL,
    UNIQUE(headline_id, model_version)
);
```

### sentiment_snapshots
```sql
CREATE TABLE sentiment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    window TEXT NOT NULL,            -- '1h', '6h', '24h'
    composite_score REAL NOT NULL,
    velocity REAL,
    breadth REAL,
    headline_count INTEGER NOT NULL,
    signal_label TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE(ticker, window, computed_at)
);
```

---

## Dependencies (additions to requirements.txt)

```
transformers>=4.30.0      # FinBERT model loading
torch>=2.0.0              # FinBERT inference (CPU only)
newsapi-python>=0.2.7     # NewsAPI.org client (optional, for live headlines)
```

`torch` is heavy. Use `--extra-index-url https://download.pytorch.org/whl/cpu`
for the CPU-only wheel (~280MB vs ~2GB). FinBERT inference is fast on CPU
for headline-length text (< 50ms per headline).

---

## Phasing

| Phase | Deliverable | Status |
|---|---|---|
| 1 — Foundation | models, config, store, provider ABC, CSV provider | DONE |
| 2 — Scoring | FinBERT scorer, batch processing | CODE DONE (torch not in Docker) |
| 3 — Aggregation | Rolling windows, velocity, composite signal, signal labels | DONE |
| 4 — Backtest | Standalone backtest runner with metrics | CODE DONE (needs torch + CSV) |
| 5 — Integration | bias_detector hook, API endpoint, dashboard widget | NOT STARTED |

Phase 4 is the validation gate. If sentiment doesn't predict next-day moves
(hit_rate <= 52% or Sharpe <= 0.3), Phase 5 is deferred indefinitely.
