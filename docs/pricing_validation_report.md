# Real Pricing Validation Report

**Period**: 2026-05-18 to 2026-05-20
**Scope**: Validating backtest accuracy by comparing Black-Scholes theoretical pricing against real bid/ask from Dolt options chain data (SPY/QQQ/IWM, 2024-01-01 to 2026-01-01).

## What we set out to do

The backtest system had two pricing modes:
- **BS mode**: Black-Scholes theoretical prices + 3% slippage estimate
- **Real mode**: Actual bid/ask from historical Dolt chain snapshots (sell at bid, buy at ask)

We wanted to know: **do our strategies actually make money after real bid/ask spreads?**

## Bugs found and fixed (in order)

### Bug 1: Calendar repricing crashes when front month expires
**Commit**: `a0dfb05`

Calendar/diagonal spreads have two expiries. When the front month expired, the repricing code couldn't find the contract in the snapshot and returned `None`, killing the trade. Fix: value expired legs at intrinsic (OTM = 0), find nearest-expiry fallback for live legs.

### Bug 2: Deep ITM contracts matched during fallback repricing
**Commit**: `f943f1e`

When the exact expiry wasn't in a snapshot, the fallback matcher would pick any contract at the same strike — including deep ITM contracts whose value was mostly intrinsic. This inflated repricing values.

**Five constraints added:**
1. 10% moneyness filter (exclude contracts > 10% ITM)
2. Tightened strike tolerance from 2% to 1%
3. Max 14-day expiry drift limit
4. 1.5x cap on sqrt(time) TV scaling ratio
5. 15% of spot value ceiling per leg

**Result**: Swing real P&L went from $4,920 (inflated) to -$143 (realistic).

### Bug 3: P&L sign destroyed by abs()
**Commit**: `ad9e31f`

`current_value = abs(close_val)` destroyed the sign of the closing value. Combined with `dte_exit` unconditionally overriding `profit_target`, every single real trade exited via time (dte_exit) and never via profit target.

**Five fixes:**
1. Store signed `entry_net` on trades (positive = credit, negative = debit)
2. Remove `abs()` on close value
3. Gate `dte_exit` behind profit/stop checks (don't override P&L exits)
4. Minimum entry threshold for real mode (reject near-worthless spreads)
5. Unified P&L formula using signed values

### Bug 4: P&L formula wrong — subtraction instead of addition
**Commit**: `4bc3def`

The corrected formula used `pnl = close_val - entry_net`. For a $12 debit calendar closing at $14:
- **Wrong**: `14 - (-12) = +$26` (subtracting a negative = adding)
- **Right**: `-12 + 14 = +$2` (sum of cash flows)

This double-counted the entry debit on every trade, inflating total P&L by ~$92K.

**Result**: Swing went from $104,403 (inflated) to -$1,309 (real).

### Bug 5: On-the-fly candidate generation broken for swing/MT/LT
**Commit**: in progress (2026-05-20)

The swing/medium/long-term tiers generated candidates by running the **short-term** pipeline (`generate_trades`) and remapping strategies. When the short-term pipeline produced zero candidates (common for HIGH_IV + NEUTRAL bias), the swing/MT/LT tiers got nothing.

**Fix**: Use the proper tier-specific decision matrices (`map_swing_strategy`, `map_medium_term_strategy`, `map_long_term_strategy`) directly instead of routing through the short-term pipeline.

**Side finding**: `SwingRecommendation.suggested_dte` returns a tuple `(30, 45)`, not an int — had to handle both types.

## Validated backtest results

### Swing tier (14-60 DTE): SPY/QQQ/IWM, 2024–2026

| Metric | Black-Scholes | Real Bid/Ask |
|--------|--------------|--------------|
| Trades | 34 | 77 |
| Win Rate | 97.1% | 45.5% |
| Total P&L | $8,467 | **-$1,309** |
| Avg P&L | $249 | -$17 |
| Max Drawdown | $548 | $2,682 |
| Profit Factor | 16.44 | **0.82** |
| Sharpe | +3.43 | **-0.21** |

**Exit reasons (real mode):** 13 profit_target, 7 stop_loss, 57 dte_exit

### Interpretation

- **BS mode is fantasy**: 97% win rate and Sharpe 3.4 vs real 45.5% win rate and negative Sharpe
- **Swing calendars are net losers after bid/ask**: PF 0.82 means you lose $0.18 for every $1 of gross profit
- **Most trades bleed to time exit**: 57 of 77 trades never reach profit target or stop — the calendar spread just decays without the front/back differential widening enough to overcome the bid/ask spread
- **2x more entries in real mode**: Real mode builds spreads from any valid contracts; BS mode's $0.05 price floor filters more aggressively

## P&L progression across iterations

| Run | Change | Real P&L | Win% | Profit Targets |
|-----|--------|----------|------|----------------|
| Before fixes | abs() + dte override | $4,920 | 63.9% | unknown |
| + ITM filter | 5 repricing constraints | -$143 | 54.5% | 0 (all dte_exit) |
| + Sign fix v1 | close - entry (wrong) | $104,403 | 92.2% | 71 |
| + Sign fix v2 | entry + close (correct) | **-$1,309** | **45.5%** | **13** |

## Outstanding work

1. **Run all tiers**: Medium-term (30-90 DTE) and long-term (90-180 DTE) need the same real pricing comparison — currently blocked on the candidate generation fix (Bug 5)
2. **Investigate trade count gap**: Real mode generates 2x the trades of BS mode — may need tighter entry filters
3. **Strategy implications**: If calendars are PF 0.82 after real spreads, the swing tier may need to focus on iron butterflies or straddles instead
4. **Signal persistence**: The Dolt backtest runs on-the-fly (no persisted swing_signals) — persisting signals would make results reproducible and faster

## Key files changed

| File | Commits | What |
|------|---------|------|
| `src/backtest/real_pricer.py` | a0dfb05, f943f1e | Repricing: expired legs, ITM filter, drift limits, value caps |
| `src/backtest/agent_backtest.py` | ad9e31f, 4bc3def, in-progress | P&L formula, exit logic, entry filter, candidate generation |
| `scripts/run_pricing_comparison.py` | 55f3cf1 | Side-by-side BS vs real comparison tool |
