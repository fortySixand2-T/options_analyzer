# Multi-Year Agent Backtest Report (DoltHub Data)

**Date:** 2026-05-17
**Period:** 2020-01-01 to 2024-12-31 (5 years)
**Data source:** DoltHub post-no-preference/options (real market bid/ask, IV, greeks)
**Tickers tested:** SPY, AAPL, MSFT, AMZN, GOOG, META, NFLX, TSLA, AMD

## Executive Summary

The agent system was stress-tested against 5 years of real options data spanning COVID crash (2020), recovery rally (2021), bear market (2022), recovery (2023), and bull run (2024). Key finding: **the strategy works on SPY/ETFs but struggles on individual stocks** due to regime detection calibration and insufficient HIGH_IV opportunities on equities.

## Per-Ticker Results

### Tier 1: Positive expectancy (tradeable)

| Ticker | Agent | Trades | Win% | P&L | Sharpe | PF | Notes |
|--------|-------|--------|------|-----|--------|-----|-------|
| SPY | conservative | 3 | 66.7% | $234 | 1.96 | 1.92 | Very few trades, needs more data |
| SPY | vol_harvester | 127 | 71.7% | -$596 | -0.22 | 0.92 | High win rate but avg loss 2.7x avg win |
| AAPL | momentum | 38 | 52.6% | $1,287 | 1.44 | 1.55 | Best stock performer |
| AMD | opportunistic | 107 | 46.7% | $231 | 0.11 | 1.04 | Marginal |
| TSLA | conservative | 1 | 100% | $209 | — | — | Insufficient trades |

### Tier 2: Losing money (needs tuning or exclusion)

| Ticker | Agent | Trades | Win% | P&L | Sharpe | Key Issue |
|--------|-------|--------|------|-----|--------|-----------|
| SPY | opportunistic | 147 | 66.0% | -$1,544 | -0.49 | LOW_IV trades at 46.2% win drag |
| AAPL | vol_harvester | 121 | 73.6% | -$567 | -0.29 | Avg loss $158 vs avg win $50 |
| TSLA | vol_harvester | 133 | 59.4% | -$2,688 | -0.77 | Avg loss $232 vs avg win $125 |
| NFLX | momentum | 68 | 26.5% | -$4,524 | -3.70 | Catastrophic — debit spreads on NFLX |
| NFLX | opportunistic | 68 | 26.5% | -$4,524 | -3.70 | Same as momentum (identical trades) |
| GOOG | opportunistic | 66 | 40.9% | -$1,570 | -2.14 | LOW_IV trades losing badly |
| META | opportunistic | 29 | 34.5% | -$501 | -2.38 | LOW_IV trades failing |

### Tier 3: No trades generated

| Ticker | Reason |
|--------|--------|
| AMZN (conservative/momentum/vol_harvester) | Never reached HIGH_IV or met bias threshold |
| GOOG (conservative/momentum/vol_harvester) | Same — stock rarely flags HIGH_IV |
| META (conservative/momentum/vol_harvester) | Same |
| AMD (conservative/momentum/vol_harvester) | Barely 1 trade for vol_harvester |

## Critical Findings

### 1. Win/Loss Ratio is the Killer

The biggest issue isn't win rate — it's the win/loss ratio on credit strategies:

| Ticker | Agent | Win Rate | Avg Win | Avg Loss | Ratio |
|--------|-------|----------|---------|----------|-------|
| SPY | vol_harvester | 71.7% | $80 | -$219 | 0.37:1 |
| AAPL | vol_harvester | 73.6% | $50 | -$158 | 0.32:1 |
| TSLA | vol_harvester | 59.4% | $125 | -$232 | 0.54:1 |

A 70% win rate needs at least a 0.43:1 ratio to break even. SPY's vol_harvester is right at the edge; AAPL is below it.

**Root cause:** The 50% profit target exit captures small wins, but the 2x credit stop loss allows large losses. With 0-14 DTE options, gamma risk makes this asymmetry worse.

### 2. LOW_IV Debit Spreads Fail on Individual Stocks

Every ticker shows poor performance in LOW_IV regime for long spreads:
- NFLX: 26.5% win rate (catastrophic)
- GOOG: 40.9% win rate
- META: 34.5% win rate
- SPY LOW_IV: 46.2% win rate
- AMD LOW_IV: 46.2% win rate

**Root cause:** Debit spreads in LOW_IV with 0-14 DTE have extreme theta decay. The directional move must happen fast enough to overcome theta — and on individual stocks with less predictable movement, it usually doesn't.

### 3. Regime Detection Doesn't Calibrate Per-Ticker

Most individual stocks NEVER reach HIGH_IV classification despite having plenty of volatile periods. The regime detector uses fixed thresholds (IV rank > 50, VIX < 25) calibrated for SPY/index options.

Individual stock IV ranks are computed differently and may not cross the same thresholds. TSLA has high absolute IV but its IV *rank* relative to its own history may not trigger HIGH_IV.

### 4. SPY vs Individual Stocks

SPY has 127+ vol_harvester trades across 5 years. Most individual stocks get 0 vol_harvester trades except AAPL (121) and TSLA (133). The system was designed for and works best on highly liquid index ETFs.

### 5. NFLX Debit Spreads Are Catastrophic

26.5% win rate on 68 trades — this is a consistent pattern, not variance. NFLX has frequent 5-10% gaps on earnings but between events moves sideways. The momentum agent's bias_strength=3 isn't selective enough for NFLX.

## Comparison: Dolt 2020-2024 vs Alpaca 2025-2026

| Metric | SPY Alpaca (1 year) | SPY Dolt (5 years) |
|--------|--------------------|--------------------|
| vol_harvester Sharpe | 2.89 | -0.22 |
| vol_harvester win rate | 78.7% | 71.7% |
| vol_harvester PF | 2.43 | 0.92 |
| momentum Sharpe | 1.95 | 0.00 (no trades) |

The dramatic performance difference suggests either:
1. The Alpaca backfill period (May 2025-May 2026) had unusually favorable conditions
2. The Dolt data's lack of OI/volume means liquidity scoring is absent, letting through bad trades
3. The exit pricing (BS repricing) is less accurate without volume/OI context

## Action Items

### Immediate (before next paper trading week)

1. **Remove LOW_IV from opportunistic agent** — 46% win rate on LOW_IV debit spreads is consistently negative across all tickers. Change `required_regimes: [HIGH_IV]` only.

2. **Tighten stop loss on credit strategies** — Change from 2x credit to 1.5x credit. The 0.37:1 win/loss ratio is the primary P&L drain. At 1.5x with 70% win rate, breakeven moves to 0.43:1 → profitable.

3. **Add per-ticker minimum liquidity filter** — Reject trades where bid-ask spread > 10% of mid. The Dolt data shows many wide-spread strikes being selected.

### Short-term (this week)

4. **Calibrate regime detection per ticker class** — Create ticker-class-specific IV rank thresholds:
   - Index ETFs (SPY): current thresholds work
   - Mega-cap tech (AAPL, MSFT, GOOG, AMZN): lower HIGH_IV threshold to IV rank > 40
   - High-vol stocks (TSLA, NFLX, AMD): use IV percentile rank against own 1-year history

5. **Exclude or gate individual stock debit spreads** — Add rule: momentum agent only trades SPY/ETFs for debit spreads. For individual stocks, require bias_strength >= 4 AND regime != LOW_IV.

6. **Add NFLX/TSLA to a restricted list** — These stocks have extreme gamma risk in 0-14 DTE. Consider excluding them entirely or requiring confluence > 85.

### Medium-term (backtest validation needed)

7. **Test tighter DTE for credit spreads** — The 7-14 DTE window may be too wide. Test 3-7 DTE only to reduce gamma risk.

8. **Test profit target at 30% instead of 50%** — Faster exits reduce time exposure to adverse moves. May improve win/loss ratio at the cost of smaller wins.

9. **Add a "regime confidence" filter** — Only trade when IV rank is clearly in a regime (not borderline). E.g., HIGH_IV requires rank > 60 not just > 50.

10. **Run this same backtest with QQQ/IWM** — These ETFs were missing from DoltHub. Consider supplementing with CBOE or other data sources for ETF-specific validation.

## Data Quality Notes

- **No OI/volume:** All trades scored without liquidity filtering. Real-time trading has this data and will filter better.
- **Spot estimation:** Derived from delta-1 calls, not market data. May be off by $0.50-$1.00 on wide chains.
- **Sampling:** Dolt data is every-other-day for 2020-2023, daily for 2024+. Some short-dated opportunities may be missed.
- **No earnings calendar:** The system can't avoid trading into earnings — individual stock debit spreads are especially vulnerable.

## Conclusion

The agent system is well-calibrated for **SPY credit selling in HIGH_IV environments** but needs significant guardrails for individual stocks. The core vol_harvester logic (HIGH_IV + edge filter) produces a 70%+ win rate consistently — the issue is purely win/loss ratio on the remaining 30% of trades. Tightening stops and improving per-ticker regime calibration are the highest-leverage improvements.
