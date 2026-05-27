# Sentiment Analysis Pipeline — Phased Task File

## Overview

Standalone news-sentiment module at `src/sentiment/`.
Collects financial headlines, scores with FinBERT, aggregates into
directional signals, persists to SQLite, and exposes `get_sentiment(ticker)`
for any consuming system.

**Design doc:** `src/sentiment/DESIGN.md`
**Rules:** `.claude/rules/sentiment.md`

---

## Phase 1: Foundation ✅ COMPLETE

**Goal:** Core data models, config, SQLite store, provider ABC, CSV provider.

**Files created:**
- `src/sentiment/__init__.py` — public API
- `src/sentiment/models.py` — Headline, ScoredHeadline, SentimentSnapshot, SentimentSignal
- `src/sentiment/config.py` — env-var config
- `src/sentiment/store.py` — SQLite with WAL, idempotent schema
- `src/sentiment/providers/base.py` — NewsProvider ABC
- `src/sentiment/providers/__init__.py` — factory
- `src/sentiment/providers/csv_provider.py` — CSV replay for backtesting
- `src/sentiment/providers/newsapi_provider.py` — live headlines

**Acceptance criteria:**
- [x] `SentimentStore` creates tables on first connect
- [x] `SentimentStore.save_headlines()` inserts, deduplicates
- [x] `CSVProvider` loads a Kaggle financial news CSV
- [x] `CSVProvider.fetch_headlines("SPY")` returns filtered, sorted headlines
- [x] `CSVProvider.fetch_window(ticker, start, end)` returns time-bounded results
- [x] Unit tests pass: `pytest tests/test_sentiment_store.py tests/test_csv_provider.py`

**Stop conditions:**
- Do NOT install torch/transformers yet
- Do NOT wire into scanner, bias_detector, or any other module

---

## Phase 2: FinBERT Scoring ✅ COMPLETE

**Goal:** Score headlines with ProsusAI/finbert. Batch processing. Persist scores.

**Files:**
- `src/sentiment/scorer.py` — SentimentScorer class (implemented)

**Acceptance criteria:**
- [x] `pip install transformers torch` (CPU-only) in Docker — torch 2.12+cpu, transformers 5.9
- [x] Add `transformers>=4.30.0` to `requirements.txt` (torch via --extra-index-url in Dockerfile)
- [x] `SentimentScorer.score_batch(headlines)` returns `List[ScoredHeadline]`
- [x] Each ScoredHeadline has positive/negative/neutral that sum to ~1.0
- [x] Confidence = max(pos, neg, neu)
- [x] Lazy model loading (no download until first call)
- [x] Batch size configurable via FINBERT_BATCH_SIZE
- [x] Score 100 headlines in < 30s on CPU — FinBERT loads in Docker (2GB+ memory)
- [x] `SentimentStore.save_scored()` persists to `scored_headlines` table
- [x] Unit test: `pytest tests/test_sentiment_scorer.py` (11 tests, mocked torch)

**Stop conditions:**
- Do NOT aggregate or generate signals yet
- Do NOT modify Dockerfile (torch install goes in requirements.txt)

**Docker note:** torch CPU wheel is ~2GB. Consider `--extra-index-url
https://download.pytorch.org/whl/cpu` for smaller image.

---

## Phase 3: Aggregation & Signal Generation ✅ COMPLETE

**Goal:** Rolling window aggregation, velocity computation, final signal output.

**Files:**
- `src/sentiment/aggregator.py` — SentimentAggregator (implemented)
- `src/sentiment/signal.py` — generate_signal() (implemented)

**Acceptance criteria:**
- [x] `SentimentAggregator.aggregate(ticker)` produces snapshots for 1h, 6h, 24h
- [x] Exponential decay weighting (halflife configurable)
- [x] Velocity = current composite - prior snapshot composite
- [x] Breadth = positive_count / total_count
- [x] `generate_signal()` combines composite (40%) + velocity (40%) + breadth (20%)
- [x] Signal labels: STRONG_POSITIVE / LEAN_POSITIVE / NEUTRAL / LEAN_NEGATIVE / STRONG_NEGATIVE
- [x] Thresholds configurable via env vars
- [x] Snapshots persisted to `sentiment_snapshots` table
- [x] `get_sentiment("SPY")` works end-to-end — FinBERT in Docker, keyword fallback available
- [x] Unit tests: `pytest tests/test_sentiment_aggregator.py tests/test_sentiment_signal.py` (26 tests)

**Stop conditions:**
- Do NOT start backtesting yet
- Do NOT integrate with scanner

---

## Phase 4: Standalone Backtest ⏳ READY TO RUN — needs real headline CSV

**Goal:** Validate the hypothesis — does sentiment predict next-day moves?

**Files:**
- `src/sentiment/backtest.py` — SentimentBacktester (implemented)
- `scripts/run_sentiment_backtest.py` — CLI runner (implemented, with decision gate)

**Data requirements:**
- Historical headline CSV (Kaggle "Daily Financial News" or similar)
  Place at `data/headlines.csv`
- Price data fetched via yfinance at runtime

**Acceptance criteria:**
- [ ] `run_backtest("data/headlines.csv", price_ticker="SPY")` runs end-to-end
- [ ] BacktestResult contains: hit_rate, avg_return, sharpe, max_drawdown, correlation
- [ ] Per-label breakdown (how does STRONG_POSITIVE perform vs LEAN_NEGATIVE, etc.)
- [ ] Daily log with signal_label, signal_score, velocity, next_day_return
- [ ] Backtest uses separate DB (`data/sentiment_backtest.db`) — never production
- [ ] Results printed to console + saved to `data/sentiment_backtest_results.json`
- [ ] Run at least 3 configs:
  1. SPY with 24h composite + 6h velocity
  2. SPY with 6h composite + 1h velocity
  3. QQQ with 24h composite + 6h velocity
- [ ] Document findings in `docs/sentiment_backtest_report.md`

**Decision gate:**
- If hit_rate > 52% AND Sharpe > 0.3 AND correlation > 0.05 → proceed to Phase 5
- If not → document findings, park module, revisit with better data or model

**Note:** torch is installed, FinBERT works in Docker. Keyword fallback scorer also available
via `scorer_factory.py`. Sample CSV has 55 headlines but is synthetic — need a real dataset
(Kaggle "Daily Financial News" or similar) for meaningful backtest.

**Stop conditions:**
- Do NOT integrate with scanner until backtest validates the signal

---

## Phase 4.5: Standalone UI Tab ✅ COMPLETE

**Goal:** Sentiment tab in the dashboard, separate from scanner pipeline.

**Files created/modified:**
- `src/ui/sentiment_router.py` — 4 API endpoints (signal, headlines, snapshots, stats)
- `frontend/src/components/Sentiment.jsx` — dashboard with gauge, windows, headlines
- `src/sentiment/keyword_scorer.py` — lightweight fallback (no torch needed)
- `src/sentiment/scorer_factory.py` — auto-selects FinBERT or keyword scorer

**Acceptance criteria:**
- [x] Sentiment tab in sidebar, signal card, score gauge, window breakdown, headlines table
- [x] Scorer badge shows "FinBERT" or "Keyword" depending on availability
- [x] Keyword fallback works when FinBERT unavailable (25 new tests, 711 total)
- [x] FinBERT loads and scores headlines in Docker (verified with 2GB memory)

---

## Phase 5: Integration (contingent on Phase 4 results)

**Goal:** Wire sentiment into the scanner's directional bias layer.

**Files to modify (outside sentiment/):**
- `src/bias_detector.py` — add optional `sentiment_weight` parameter
- `src/config.py` — add `SENTIMENT_WEIGHT` to scoring_weights
- `src/scanner/scorer.py` — ⚠️ FROZEN — cannot modify. Use wrapper or new scorer
- `SIGNALS.md` — document sentiment as optional Layer 2 input
- `src/ui/app.py` — add `/api/sentiment/{ticker}` endpoint
- `frontend/src/components/` — sentiment widget on dashboard

**Acceptance criteria:**
- [ ] `detect_bias(df, sentiment_signal=sig)` accepts optional SentimentSignal
- [ ] Sentiment weight defaults to 0.10 (10% of directional bias score)
- [ ] Weight is configurable via `SENTIMENT_WEIGHT` env var
- [ ] When no sentiment data available, bias_detector behaves identically to before
- [ ] API endpoint returns current sentiment signal as JSON
- [ ] Dashboard shows sentiment gauge/indicator
- [ ] Conviction score includes sentiment component (new scorer wrapper, not modifying frozen scorer.py)
- [ ] Docker rebuild works with torch dependency

---

## Frozen files — do not modify

```
src/sentiment/providers/base.py    # after Phase 1 is complete
src/sentiment/models.py            # after Phase 1 is complete
```

These define the module's contracts. Changes require updating DESIGN.md first.

---

## Dependencies to add (Phase 2)

```
# requirements.txt additions:
transformers>=4.30.0
torch>=2.0.0              # or use CPU-only: --extra-index-url https://download.pytorch.org/whl/cpu
```

Optional (Phase 5):
```
newsapi-python>=0.2.7     # only if using NewsAPI provider in production
```
