# Sentiment Backtest Report

**Date:** 2026-05-27 (updated 2026-05-28 with FinBERT results)
**Data:** 149 real financial headlines from yfinance + Yahoo Finance RSS
**Period:** 2026-05-05 to 2026-05-27 (15 trading days)
**Source file:** data/headlines_real.csv

---

## Round 2: FinBERT Scoring (2026-05-28)

**Scorer:** ProsusAI/finbert (transformer model, ~420MB)
**Docker memory:** 4GB (Colima VM)
**Scoring distribution:** 24.8% positive, 26.2% negative, 49.0% neutral

### Results

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | MACRO  | SPY   | 24h     | 6h       | 5/15        | 60.0%    | 10.52  | 0.3939      |
| 2      | MACRO  | SPY   | 6h      | 1h       | 4/15        | 25.0%    | 15.38  | 0.5556      |
| 3      | MACRO  | QQQ   | 24h     | 6h       | 6/15        | 33.3%    | 19.15  | 0.1968      |

### Decision Gate

| Criterion          | Threshold | Config 1 | Config 2 | Config 3 |
|--------------------|-----------|----------|----------|----------|
| hit_rate > 52%     | 52%       | **PASS** | FAIL     | FAIL     |
| Sharpe > 0.3       | 0.3       | **PASS** | PASS     | PASS     |
| correlation > 0.05 | 0.05      | **PASS** | PASS     | PASS     |

**Config 1 (SPY, 24h+6h): ALL THREE GATES PASS** — proceed to Phase 5 candidate
**Config 2 (SPY, 6h+1h): FAIL** — hit rate too low (25%)
**Config 3 (QQQ, 24h+6h): FAIL** — hit rate too low (33.3%)

### FinBERT vs Keyword Comparison

| Metric         | Keyword (Round 1)    | FinBERT (Round 2)     |
|----------------|----------------------|-----------------------|
| Signal days    | 3/14                 | 5/15 (Config 1)       |
| Hit rate       | 33.3%                | **60.0%** (Config 1)  |
| Correlation    | -0.41 to -1.00       | **+0.19 to +0.56**    |
| Signal variety | All negative         | Mixed (neg + positive)|
| Neutral rate   | ~62%                 | **49.0%**             |

Key improvements with FinBERT:
1. **More signal days** (5 vs 3) — FinBERT produces fewer neutrals
2. **Positive correlation** — FinBERT signals align with next-day returns (keyword showed contrarian/noise)
3. **Mixed signal labels** — FinBERT detected both LEAN_NEGATIVE and STRONG_POSITIVE; keyword was all-negative
4. **Config 1 passes all gates** — first validated configuration

### Per-Label Breakdown (Config 1)

| Label             | Count | Hit Rate | Avg Return | Avg Score |
|-------------------|-------|----------|------------|-----------|
| LEAN_NEGATIVE     | 4     | 50.0%    | +0.2237%   | -0.321    |
| STRONG_POSITIVE   | 1     | 100.0%   | +0.6639%   | +0.521    |

### Caveats

- **N=5 signal days is still small.** Config 1 passing the gate is encouraging but not statistically robust. Need 50+ signal days for confidence.
- **Single market regime** — May 2026 was a bullish period. The signal hasn't been tested in bear or sideways markets.
- **Sharpe ratios are inflated** by small N and consistent market direction.
- **The 24h primary window is best** — shorter windows (6h, 1h) produced fewer actionable signals and worse hit rates.

---

## Round 1: Keyword Scoring (2026-05-27)

**Scorer:** keyword-v1 (lightweight dictionary-based fallback)

### Results

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | MACRO  | SPY   | 24h     | 6h       | 3/14        | 33.3%    | 11.38  | -0.4133     |
| 2      | MACRO  | SPY   | 6h      | 1h       | 3/14        | 33.3%    | 11.38  | -0.9995     |
| 3      | MACRO  | QQQ   | 24h     | 6h       | 3/14        | 33.3%    | 16.16  | -0.7441     |

**Overall: INCONCLUSIVE** — N=3 too few, all signals negative, negative correlation suggests keyword lexicon bias.

---

## Recommendations

- **Config 1 (SPY, 24h+6h) with FinBERT is the candidate for Phase 5 integration**
- Before integrating: source a larger headline dataset (6+ months) and re-validate with 50+ signal days
- The 24h primary window with 6h velocity is the optimal configuration
- Shorter windows (6h primary, 1h velocity) produce too few actionable signals
- Keyword scorer is not reliable for production — FinBERT is required

## Files

- `data/backtest_finbert_spy_24h6h.json` — FinBERT Config 1 (PASSES gate)
- `data/backtest_finbert_spy_6h1h.json` — FinBERT Config 2
- `data/backtest_finbert_qqq_24h6h.json` — FinBERT Config 3
- `data/backtest_macro_spy_24h6h.json` — Keyword Config 1
- `data/backtest_macro_spy_6h1h.json` — Keyword Config 2
- `data/backtest_macro_qqq_24h6h.json` — Keyword Config 3
- `data/headlines_real.csv` — Input headlines (149)
- `scripts/collect_headlines.py` — Headline collection script
- `scripts/run_sentiment_backtest.py` — Backtest CLI runner
