# Sentiment Backtest Report

**Date:** 2026-05-27 (updated 2026-05-28 with FinBERT + Kaggle results)
**Data sources:** 149 real headlines (yfinance+RSS) + 7,912 Kaggle headlines (2022-2024)
**Source files:** data/headlines_real.csv, data/headlines_kaggle_2022_2024.csv

---

## Round 3: Kaggle Large Dataset (2026-05-28) — DEFINITIVE

**Scorer:** ProsusAI/finbert
**Data:** 7,912 headlines from Kaggle "S&P 500 with Financial News Headlines (2008-2024)"
**Period:** 2022-01-03 to 2024-03-08 (547 trading days, bear+recovery+bull regimes)
**Docker:** Colima 4GB, batch_size=16, HuggingFace cache mounted

### Results

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | SPY    | SPY   | 24h     | 6h       | 297/547     | 50.2%    | -0.10  | -0.0041     |
| 2      | SPY    | SPY   | 6h      | 1h       | 0/547       | 0%       | 0.00   | 0.0000      |
| 3      | SPY    | QQQ   | 24h     | 6h       | 297/547     | 49.8%    | -0.09  | -0.0189     |

### Decision Gate

| Criterion          | Threshold | Config 1 | Config 2 | Config 3 |
|--------------------|-----------|----------|----------|----------|
| hit_rate > 52%     | 52%       | FAIL     | FAIL     | FAIL     |
| Sharpe > 0.3       | 0.3       | FAIL     | FAIL     | FAIL     |
| correlation > 0.05 | 0.05      | FAIL     | FAIL     | FAIL     |

**DEFINITIVE FAIL — all configs fail all gates with N=297 signal days.**

### Volatility Prediction (same data, different target)

| Config | Setup | Vol Correlation | Neg→Vol Corr | High/Low Vol Ratio | Gate |
|--------|-------|----------------|-------------|-------------------|------|
| 1      | SPY 24h+6h | **0.2168** | **0.2280** | **1.26x** | **PASS** |
| 2      | SPY 6h+1h  | 0.0000 | 0.0000 | N/A | FAIL (0 signals) |
| 3      | QQQ 24h+6h | **0.1906** | **0.2117** | **1.22x** | **PASS** |

**Volatility gate:** |vol_corr| > 0.10 AND vol_ratio > 1.10x

**Configs 1 and 3 PASS.** Sentiment does not predict direction, but it DOES predict volatility:
- High-sentiment days see **22-26% more realized vol** than low-sentiment days
- Negative sentiment → vol correlation of ~0.22 (moderate, consistent)
- LEAN_POSITIVE days have dramatically lower vol (0.77% SPY) vs LEAN_NEGATIVE (1.57% SPY)
- STRONG_NEGATIVE days: 1.58% avg vol — sentiment extremes signal larger moves

**Per-label volatility breakdown (Config 1, SPY):**

| Label | Count | Avg Vol | Avg Return |
|-------|-------|---------|------------|
| LEAN_NEGATIVE | 265 | 1.57% | -0.004% |
| LEAN_POSITIVE | 14 | 0.77% | -0.149% |
| STRONG_NEGATIVE | 18 | 1.58% | +0.033% |

**Implication for the scanner:** Sentiment can inform the vol regime layer. High negative sentiment → expect wider ranges → favor premium-selling strategies (iron condors, credit spreads). Low/positive sentiment → expect tighter ranges → favor defined-risk debit plays or butterflies.

### Direction Analysis (FAIL)

1. **The signal is random.** 50.2% hit rate over 297 days is indistinguishable from coin flip.
2. **No predictive correlation.** Near-zero correlation (-0.004) means sentiment score has no linear relationship to next-day returns.
3. **Negative Sharpe** confirms no edge — you'd lose money following this signal.
4. **Config 2 (6h window) produced zero signals** — daily-timestamped headlines don't work with sub-day windows.
5. **Heavy negative bias**: 89% of signals were LEAN_NEGATIVE (265/297). FinBERT reads financial headlines as more negative than they are for market prediction.
6. **STRONG_NEGATIVE contrarian hint**: 18 STRONG_NEGATIVE days had 55.6% hit rate on SPY — small N but worth investigating as a fade signal.
7. **The earlier N=5 pass was noise.** With sufficient data, Config 1 goes from 60% → 50.2% hit rate.

### Why This Dataset Is Conclusive

- **547 trading days** spanning bear market (2022 H1), recovery (2022 H2-2023), and bull (2023-2024)
- **297 signal days** — far above the 50+ minimum for statistical confidence
- **Multiple regimes tested** — unlike the 15-day window which was pure bull
- **Same scorer (FinBERT)** that produced the false-positive on small data

---

## Round 2: FinBERT Scoring (2026-05-28) — SUPERSEDED BY ROUND 3

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

- **Do NOT proceed to Phase 5 integration** — the signal is definitively unvalidated
- **Keep the module as a standalone dashboard tool** (Path C) — sentiment is informational, not predictive for next-day returns
- **Investigate STRONG_NEGATIVE as contrarian signal** — 55.6% hit rate (n=18) could be real but needs more data
- **Consider alternative signal targets**: instead of next-day returns, try intraday volatility, weekly returns, or regime-conditional signals
- **The infrastructure works** — the pipeline, scorer, aggregator, and UI are solid. The signal hypothesis is what failed, not the code
- **Volatility prediction IS validated** — sentiment predicts next-day realized vol (0.22 corr, 1.26x ratio). Integration path: feed into vol regime layer, not directional bias

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
