# Sentiment Backtest Report

**Date:** 2026-05-27
**Scorer:** keyword-v1 (lightweight dictionary-based)
**Data:** 149 real financial headlines from yfinance + Yahoo Finance RSS
**Period:** 2026-05-05 to 2026-05-26 (14 trading days)
**Source file:** data/headlines_real.csv

## Configurations Run

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | MACRO  | SPY   | 24h     | 6h       | 3/14        | 33.3%    | 11.38  | -0.4133     |
| 2      | MACRO  | SPY   | 6h      | 1h       | 3/14        | 33.3%    | 11.38  | -0.9995     |
| 3      | MACRO  | QQQ   | 24h     | 6h       | 3/14        | 33.3%    | 16.16  | -0.7441     |

## Decision Gate

| Criterion          | Threshold | Config 1 | Config 2 | Config 3 |
|--------------------|-----------|----------|----------|----------|
| hit_rate > 52%     | 52%       | FAIL     | FAIL     | FAIL     |
| Sharpe > 0.3       | 0.3       | PASS     | PASS     | PASS     |
| correlation > 0.05 | 0.05      | FAIL     | FAIL     | FAIL     |

**Overall: INCONCLUSIVE** (not FAIL — insufficient data)

## Analysis

### Why results are inconclusive, not definitive

- **N=3 signal days** is far too few for statistical significance. Any conclusion from 3 data points is noise.
- **149 headlines over 14 trading days**, with 98 (66%) concentrated on a single day (May 26). Most days had 0-3 headlines.
- **Keyword scorer** is a rough proxy — it lacks FinBERT's contextual understanding and produces ~62% neutral classifications, reducing the number of actionable signal days.
- The Sharpe ratios appear high but are artifacts of N=3 with consistent positive returns (the market happened to rally on signal days).

### Observations

1. **All signals were negative** (LEAN_NEGATIVE or STRONG_NEGATIVE). The keyword lexicon may have a negative bias from terms like "risk," "tariff," and "fear" appearing in neutral financial reporting.
2. **Negative correlation** (-0.41 to -0.99) suggests a contrarian pattern: negative sentiment preceded positive returns. This is consistent with buy-the-dip / mean-reversion behavior in the May 2026 market.
3. **The 6h window produced more uniform signals** (all LEAN_NEGATIVE) while 24h produced a mix of LEAN and STRONG negative, suggesting the longer window captures more edge cases.

## What's Needed for a Definitive Test

1. **More data** — minimum 100+ signal days (roughly 6 months of daily headlines, or 3-4 months with multiple headlines per day)
2. **Real headline CSV** — a dataset like Kaggle "Daily Financial News for 6000+ Stocks" with years of history
3. **FinBERT scoring** — requires Docker Desktop memory ≥ 4GB (currently 2GB causes OOM on batch scoring)
4. **Multiple market regimes** — the 22-day window was a single bullish regime; need bear, sideways, and volatile periods

## Recommendations

- **Do NOT proceed to Phase 5 integration** — the signal is unvalidated
- **Do NOT park the module** — the infrastructure works, the data is the bottleneck
- **Source a historical headline dataset** (Kaggle, Quandl, or GDELT) and re-run with FinBERT
- **Increase Docker Desktop memory to 4GB+** for FinBERT batch scoring
- The contrarian pattern is worth investigating with more data — if consistent, the signal should be used as a fade indicator rather than a confirmation indicator

## Files

- `data/backtest_macro_spy_24h6h.json` — Config 1 full results
- `data/backtest_macro_spy_6h1h.json` — Config 2 full results
- `data/backtest_macro_qqq_24h6h.json` — Config 3 full results
- `data/headlines_real.csv` — Input headlines
- `scripts/collect_headlines.py` — Headline collection script
- `scripts/run_sentiment_backtest.py` — Backtest CLI runner
