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

## Architecture

```
NewsProvider (ABC)          FinBERT Scorer          Aggregator           Signal
  ├─ NewsAPI               headline text ──►      per-ticker rolling   SentimentSignal
  ├─ Benzinga              {pos, neg, neu,        windows (1h, 6h,     dataclass with
  ├─ CSVProvider            confidence}            24h) + velocity      label + score +
  └─ (future)                                      computation          velocity + detail
        │                        │                      │                    │
        ▼                        ▼                      ▼                    ▼
   ┌──────────────── SQLite (sentiment.db) ─────────────────────────────────────┐
   │  headlines        scored_headlines       sentiment_snapshots               │
   │  (raw text,       (+ pos/neg/neu/       (ticker, window,                  │
   │   timestamp,       confidence,           composite_score,                  │
   │   source)          model_version)        velocity, label)                  │
   └────────────────────────────────────────────────────────────────────────────┘
                                                      │
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
│   ├── benzinga_provider.py # Benzinga (paid, richer data)
│   └── csv_provider.py      # Historical CSV replay for backtesting
├── scorer.py                # FinBERT scoring: headline → sentiment vector
├── aggregator.py            # Rolling windows, velocity, composite signal
├── store.py                 # SQLite persistence (idempotent schema, WAL mode)
├── signal.py                # SentimentSignal generation (labels + thresholds)
└── backtest.py              # Standalone backtest runner
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
            × confidence_filter(min_confidence=0.6)

velocity  = composite(window=1h) - composite(window=6h)
breadth   = positive_count / total_count  (fraction of headlines that are positive)
```

The `SentimentSignal.score` combines:
- composite level (40%)
- velocity (40%)
- breadth divergence from 0.5 (20%)

---

## Integration points (Phase 5 — not built in this module)

The consuming system imports `SentimentSignal` and uses it however it wants:

```python
# Example: wire into bias_detector as an optional input
from sentiment import get_sentiment, SentimentSignal

sig: SentimentSignal = get_sentiment("SPY")
# sig.label → "LEAN_POSITIVE"
# sig.score → 0.23
# sig.velocity → 0.08

# Add to bias score with configurable weight
bias_score += sig.score * SENTIMENT_WEIGHT
```

The module itself never imports from `scanner/`, `regime/`, `bias_detector`,
or any other `src/` package. This is a hard rule.

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
    source TEXT NOT NULL,            -- 'newsapi', 'benzinga', 'csv'
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

## Backtest design

The standalone backtest answers: **does sentiment velocity predict
next-session directional moves?**

Input:
- Historical headlines (CSV or from SQLite)
- Price data (yfinance, same as the scanner uses)

Process:
1. For each trading day, score all prior-session headlines
2. Compute composite score + velocity
3. Generate signal label
4. Record next-day return (open-to-close or close-to-close)

Output:
- Hit rate per signal label
- Average return per signal label
- Sharpe ratio of signal-following strategy
- Correlation of sentiment velocity with next-day returns
- Drawdown analysis
- Comparison: sentiment-only vs random

---

## Dependencies (additions to requirements.txt)

```
transformers>=4.30.0      # FinBERT model loading
torch>=2.0.0              # FinBERT inference (CPU only)
newsapi-python>=0.2.7     # NewsAPI.org client (optional)
```

`torch` is heavy (~2GB). For Docker, use `torch-cpu` or `--extra-index-url`
for the CPU-only wheel. FinBERT inference is fast on CPU for headline-length
text (< 50ms per headline).

---

## Phasing

| Phase | Deliverable | Test |
|---|---|---|
| 1 — Foundation | models, config, store, provider ABC, CSV provider | Unit tests for store CRUD, CSV loading |
| 2 — Scoring | FinBERT scorer, batch processing | Score a batch of 100 headlines, verify output shape |
| 3 — Aggregation | Rolling windows, velocity, composite signal, signal labels | Aggregate scored headlines, verify velocity math |
| 4 — Backtest | Standalone backtest runner with metrics | Run on 6mo of Kaggle headlines, produce report |
| 5 — Integration | Hooks into bias_detector + scorer (optional weight), API endpoint, dashboard widget | End-to-end: collect → score → signal → display |

Each phase is independently testable. Phase 4 (backtest) is the validation
gate — if sentiment doesn't show signal, Phase 5 integration is deferred.
