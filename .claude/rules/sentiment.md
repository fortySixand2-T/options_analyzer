# Sentiment Module Rules

Applies when working in `src/sentiment/**`.

## Hard rules

1. **Zero imports from other src/ packages.** The sentiment module is standalone.
   It depends only on its own code, stdlib, and third-party packages
   (transformers, torch, requests, yfinance, numpy, pandas).
2. **Follow existing patterns.** Use dataclasses (not Pydantic) for models.
   Use env vars in config.py. Use SQLite with WAL mode and idempotent schema.
   Use ABCs for provider interfaces.
3. **Persist everything.** Every headline, score, and snapshot goes to SQLite.
   The backtester replays from the DB — never from live computation.
4. **FinBERT is lazy-loaded.** The model downloads ~420MB on first use.
   Never import torch/transformers at module level.
5. **SentimentSignal is the only output.** External systems import
   `SentimentSignal` and `get_sentiment()`. Nothing else crosses the boundary.

## Architecture reference

```
NewsProvider → SentimentScorer → SentimentAggregator → generate_signal → SentimentSignal
                                       ↕
                                  SentimentStore (SQLite)
```

See `src/sentiment/DESIGN.md` for full architecture.

## Files

| Purpose | File |
|---|---|
| Public API | `__init__.py` |
| Design doc | `DESIGN.md` |
| Config | `config.py` |
| Data models | `models.py` |
| Provider ABC | `providers/base.py` |
| CSV replay | `providers/csv_provider.py` |
| NewsAPI live | `providers/newsapi_provider.py` |
| FinBERT scorer | `scorer.py` |
| Rolling aggregation | `aggregator.py` |
| Signal generation | `signal.py` |
| SQLite persistence | `store.py` |
| Backtest runner | `backtest.py` |
