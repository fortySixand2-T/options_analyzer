# Sentiment Backtest Report

**Last updated:** 2026-05-28
**Scorer:** ProsusAI/finbert (transformer model)
**Docker:** Colima 4GB, 4 CPUs, HuggingFace cache mounted

---

## Executive Summary

Sentiment **does not predict next-day direction** (50% hit rate = coin flip) but **does predict next-day realized volatility** (0.17-0.26 correlation, 1.13-1.42x high/low ratio). Validated across 5 market regimes spanning 2008-2024 with N=1,462+ signal days.

**Integration path:** Feed sentiment into vol regime layer, NOT directional bias.

---

## Data Sources

| Dataset | Source | Headlines | Period | Description |
|---------|--------|-----------|--------|-------------|
| `headlines_real.csv` | yfinance + Yahoo RSS | 149 | May 2026 | Live-collected, real-time timestamps |
| `headlines_kaggle.csv` | Kaggle `dyutidasmahaptra/s-and-p-500-with-financial-news-headlines-20082024` | 19,127 | 2008-2024 | S&P 500 headlines with daily close prices |
| `headlines_combined.csv` | Merged from 4 Kaggle datasets | **119,553** | 2008-2024 | SP500 + Reddit/DJIA + CNBC + Reuters + Guardian |

### Combined dataset breakdown

| Source | Headlines | Period | Kaggle ref |
|--------|-----------|--------|------------|
| S&P 500 headlines | 18,152 | 2008-2024 | `dyutidasmahaptra/s-and-p-500-with-financial-news-headlines-20082024` |
| Reddit/DJIA top 25 | 49,695 | 2008-2016 | `aaron7sun/stocknews` |
| Reuters | 32,673 | 2018-2020 | `notlucasp/financial-news-headlines` |
| Guardian Business | 17,759 | 2018-2020 | `notlucasp/financial-news-headlines` |
| CNBC | 1,274 | 2018-2020 | `notlucasp/financial-news-headlines` |
| **Total (deduplicated)** | **119,553** | **2008-2024** | **4,216 unique dates** |

### Kaggle API

- Token: `~/.kaggle/access_token` (bearer format: `KGAT_...`)
- Download: `curl -H "Authorization: Bearer $TOKEN" "https://www.kaggle.com/api/v1/datasets/download/{ref}"`

### Additional datasets available on Kaggle (not yet used)

| Dataset | Size | Description |
|---------|------|-------------|
| `sumeakash/daily-news-for-stock-market-prediction` | 55MB | Large financial news corpus, updated May 2026 |
| `ankurzing/sentiment-analysis-for-financial-news` | 2.7MB | Pre-labeled FinancialPhraseBank (43K downloads) |
| `rdolphin/financial-news-with-ticker-level-sentiment` | 10MB | 5K articles with ticker-level sentiment from LLMs |
| `belbino/financial-news-sentiment-vs-market-2020-present` | 2MB | 2020-present with market data, updated May 2026 |

---

## Round 1: Keyword Scoring (2026-05-27)

**Scorer:** keyword-v1 (dictionary-based fallback, no torch needed)
**Data:** 149 real headlines from yfinance + Yahoo RSS
**Period:** May 5-26, 2026 (14 trading days)

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | MACRO  | SPY   | 24h     | 6h       | 3/14        | 33.3%    | 11.38  | -0.4133     |
| 2      | MACRO  | SPY   | 6h      | 1h       | 3/14        | 33.3%    | 11.38  | -0.9995     |
| 3      | MACRO  | QQQ   | 24h     | 6h       | 3/14        | 33.3%    | 16.16  | -0.7441     |

**Result: INCONCLUSIVE** — N=3 signal days, all signals negative, keyword lexicon has negative bias.

---

## Round 2: FinBERT on Real-Time Headlines (2026-05-28)

**Scorer:** ProsusAI/finbert
**Data:** Same 149 headlines, re-scored with FinBERT
**Period:** May 5-27, 2026 (15 trading days)

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | MACRO  | SPY   | 24h     | 6h       | 5/15        | 60.0%    | 10.52  | 0.3939      |
| 2      | MACRO  | SPY   | 6h      | 1h       | 4/15        | 25.0%    | 15.38  | 0.5556      |
| 3      | MACRO  | QQQ   | 24h     | 6h       | 6/15        | 33.3%    | 19.15  | 0.1968      |

**Result: Config 1 appeared to pass all gates** — but N=5 is far too small. This was a false positive confirmed by Round 3.

---

## Round 3: Kaggle Large Dataset — Direction (2026-05-28)

**Scorer:** ProsusAI/finbert
**Data:** 7,912 headlines from Kaggle S&P 500 dataset
**Period:** 2022-01-03 to 2024-03-08 (547 trading days)

| Config | Ticker | Price | Primary | Velocity | Signal Days | Hit Rate | Sharpe | Correlation |
|--------|--------|-------|---------|----------|-------------|----------|--------|-------------|
| 1      | SPY    | SPY   | 24h     | 6h       | 297/547     | 50.2%    | -0.10  | -0.0041     |
| 2      | SPY    | SPY   | 6h      | 1h       | 0/547       | 0%       | 0.00   | 0.0000      |
| 3      | SPY    | QQQ   | 24h     | 6h       | 297/547     | 49.8%    | -0.09  | -0.0189     |

**Direction gate:** hit_rate > 52%, Sharpe > 0.3, correlation > 0.05

**DEFINITIVE FAIL — all configs fail all gates. 50.2% = coin flip.**

Key findings:
1. The signal is random for direction prediction
2. 89% of signals were LEAN_NEGATIVE — FinBERT has a negative bias on financial headlines
3. Config 2 (6h/1h) produced zero signals — daily timestamps don't fill sub-day windows
4. The Round 2 N=5 pass was sample noise (60% → 50.2% with more data)

---

## Round 3: Kaggle Large Dataset — Volatility (2026-05-28)

**Same data as above, but predicting next-day realized vol (high-low range / close)**

### Single-Period Results (2022-2024)

| Config | Setup | Vol Correlation | Neg→Vol Corr | High/Low Vol Ratio | Gate |
|--------|-------|----------------|-------------|-------------------|------|
| 1      | SPY 24h+6h | **0.2168** | **0.2280** | **1.26x** | **PASS** |
| 2      | SPY 6h+1h  | 0.0000 | 0.0000 | N/A | FAIL (0 signals) |
| 3      | QQQ 24h+6h | **0.1906** | **0.2117** | **1.22x** | **PASS** |

**Volatility gate:** |vol_corr| > 0.10 AND vol_ratio > 1.10x

### Multi-Period Validation (SP500 dataset, all pass)

| Period | Market Regime | Signal Days | Vol Corr | Neg→Vol Corr | Vol Ratio |
|--------|--------------|-------------|----------|-------------|-----------|
| 2008-2012 | GFC + recovery | 192 | 0.167 | 0.142 | 1.13x |
| 2013-2016 | Low-vol bull | 440 | 0.131 | 0.135 | 1.12x |
| 2017-2019 | Late-cycle bull | 300 | 0.211 | 0.225 | 1.23x |
| 2020-2021 | COVID + recovery | 234 | **0.262** | **0.267** | **1.42x** |
| 2022-2024 | Bear + bull | 297 | 0.217 | 0.228 | 1.26x |
| **Full 2008-2024** | **All regimes** | **1,462** | **0.173** | **0.174** | **1.21x** |

**N=1,462 signal days across 16 years. All 5 periods pass both gates.**

Signal strength by regime:
- **Strongest:** COVID 2020-2021 (0.26 corr, 1.42x ratio) — makes sense, extreme sentiment during pandemic
- **Weakest:** Low-vol 2013-2016 (0.13 corr, 1.12x ratio) — less vol to predict in calm markets
- **Consistent:** All periods above gate thresholds

### Per-Label Volatility (Full Dataset, N=1,462)

| Label | Count | Avg Vol | Avg Return |
|-------|-------|---------|------------|
| LEAN_NEGATIVE | 1,318 | 1.25% | +0.012% |
| LEAN_POSITIVE | 77 | 0.92% | +0.019% |
| STRONG_NEGATIVE | 66 | **1.84%** | -0.125% |
| STRONG_POSITIVE | 1 | 0.82% | -0.766% |

Key:
- **STRONG_NEGATIVE → 1.84% avg vol** (47% above LEAN_NEGATIVE baseline)
- **LEAN_POSITIVE → 0.92% avg vol** (26% below baseline)
- Sentiment works as a **vol amplifier detector**, not a directional signal

### Round 4: Combined Dataset — Volatility (2026-05-28)

**Data:** 119,553 headlines from 4 merged Kaggle datasets (SP500 + Reddit/DJIA + CNBC + Reuters + Guardian)
**Period:** 2008-2024 (4,216 unique dates)

| Period | Headlines | Signal Days | Vol Corr | Neg→Vol Corr | Vol Ratio | Gate |
|--------|-----------|-------------|----------|-------------|-----------|------|
| 2008-2012 | 29,384 | 1,109 | 0.009 | 0.009 | 1.04x | **FAIL** |
| 2013-2016 | 25,293 | 927 | 0.088 | 0.077 | 1.03x | **FAIL** |
| 2017-2019 | 40,530 | 497 | 0.150 | 0.135 | 1.25x | **PASS** |
| 2020-2021 | 16,456 | 281 | **0.269** | **0.279** | **1.57x** | **PASS** |
| 2022-2024 | 7,890 | 297 | 0.217 | 0.228 | 1.26x | **PASS** |

**3 of 5 periods pass. The 2 failures are the Reddit-heavy periods (2008-2016).**

#### Why the discrepancy vs Round 3?

Round 3 used only SP500 financial headlines (curated, wire-service quality). Round 4 added 50K Reddit headlines (2008-2016) from `aaron7sun/stocknews` — these are general world news (wars, politics, Olympics), not financial headlines. FinBERT, trained on financial text, produces noise on non-financial content.

**Evidence:** In 2008-2012, 1,109 of 1,261 days had signals (88%) — almost every day was "actionable" because Reddit fills every day with 25 headlines. But the signal is meaningless noise (0.009 correlation). In 2022-2024 with only SP500 headlines, 297 of 547 days had signals (54%) — more selective, more meaningful.

#### Conclusion

- **Financial-quality headlines (Reuters, CNBC, SP500 dataset): signal works (0.15-0.27 corr)**
- **Reddit/general news: signal washes out (0.01-0.09 corr)**
- **Headline source quality matters more than headline volume**
- For production: use financial news sources only (NewsAPI with financial filters, yfinance, Reuters RSS)

---

## Methodology

### Signal Pipeline

```
Headlines (CSV) → FinBERT scorer → SentimentStore (SQLite) → Aggregator (exp decay) → generate_signal()
```

- **Aggregation:** Exponential decay weighting, halflife=4h, windows: 1h/6h/24h
- **Signal composition:** 40% composite + 40% velocity + 20% breadth
- **Labels:** STRONG_POSITIVE / LEAN_POSITIVE / NEUTRAL / LEAN_NEGATIVE / STRONG_NEGATIVE
- **Actionable:** headline_count >= 3 AND label != NEUTRAL

### Volatility Metrics

- **Vol correlation:** Pearson corr of abs(sentiment_score) vs next-day realized vol
- **Neg vol correlation:** Pearson corr of abs(negative sentiment scores) vs realized vol
- **Realized vol:** (next-day High - Low) / today's Close
- **Vol predictive ratio:** avg vol on high-sentiment days / avg vol on low-sentiment days (split at median abs score)
- **Vol gate:** |vol_corr| > 0.10 AND vol_ratio > 1.10x

### Direction Metrics

- **Hit rate:** Fraction of days where sentiment direction matches next-day return direction
- **Sharpe:** Annualized (mean / std * sqrt(252)) of returns on signal days
- **Direction gate:** hit_rate > 52% AND Sharpe > 0.3 AND correlation > 0.05

---

## Recommendations

1. **Direction prediction: DEAD.** Do not revisit unless fundamentally different model/data.
2. **Volatility prediction: VALIDATED** on financial-quality headlines (0.15-0.27 corr, 1.25-1.57x ratio across 2017-2024).
3. **Headline source quality > quantity.** Reddit/general news destroys the signal. Use financial sources only.
4. **Integration target:** High negative sentiment → bias regime toward HIGH_IV → favor premium-selling. Low/positive → bias toward LOW_IV → favor debit plays.
5. **Keep Sentiment UI tab** as informational dashboard showing vol expectation, not direction.
6. **Accumulate real-time data** with proper timestamps from financial sources (NewsAPI with business filter, yfinance, Reuters/CNBC RSS).
7. **X/Twitter not worth it** — $100+/month for read API. StockTwits (free, finance-focused) is better for trading sentiment.
8. **Best config:** SPY, 24h primary window, 6h velocity window, FinBERT scorer.

---

## Files

### Data files (in `data/`, gitignored)
- `headlines_real.csv` — 149 live headlines (May 2026)
- `headlines_kaggle.csv` — 19,127 SP500 headlines (2008-2024)
- `headlines_combined.csv` — 119,553 merged headlines (2008-2024)
- `headlines_kaggle_*.csv` — Period-specific splits
- `headlines_combined_*.csv` — Period-specific splits for combined dataset
- `backtest_*.json` — Full results for each backtest run

### Scripts
- `scripts/collect_headlines.py` — Live headline collector (yfinance + RSS)
- `scripts/run_sentiment_backtest.py` — Backtest CLI (`--target direction|volatility`, `--scorer finbert|keyword`)

### Module
- `src/sentiment/backtest.py` — Backtester with direction + volatility targets
- `src/sentiment/scorer.py` — FinBERT scorer
- `src/sentiment/scorer_factory.py` — Auto-selects FinBERT or keyword
- `src/sentiment/keyword_scorer.py` — Lightweight fallback (no torch)

### Infrastructure
- Colima VM: 4GB memory, 4 CPUs (`colima start --memory 4 --cpu 4`)
- HuggingFace cache: `.hf_cache:/home/appuser/.cache/huggingface` (mount in docker-compose)
- Kaggle API: `~/.kaggle/access_token` (bearer token)
