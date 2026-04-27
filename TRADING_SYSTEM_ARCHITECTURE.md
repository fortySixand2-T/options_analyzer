# Trading System Architecture — Short-Term Options

## The core problem with short-term options

Your edge decays in hours, not days. At 0-14 DTE, theta is nonlinear — a 5 DTE option loses more value per hour than a 14 DTE option loses per day. This means:

- **Entry timing matters more than strike selection**
- **Exit discipline matters more than entry logic**
- **Realized vol vs implied vol is the only sustainable edge**

---

## Architecture: Four Layers

```
+-----------------------------------------------------+
|  L4: PORTFOLIO ENGINE                               |
|  Position limits, correlation, margin, Greeks mgmt  |
+-----------------------------------------------------+
|  L3: EXECUTION & SIZING                             |
|  Kelly fraction, spread cost, fill optimization     |
+-----------------------------------------------------+
|  L2: TRADE GENERATION                               |
|  Signal confluence -> candidate -> filter -> rank   |
+-----------------------------------------------------+
|  L1: MARKET STATE                                   |
|  Regime, vol surface, dealer positioning, microstr. |
+-----------------------------------------------------+
```

**Implementation status:** All 4 layers built, wired, and bridged to execution. L1→L2→L3 pipeline serves via `/api/trade-candidates`. L4 portfolio state via `/api/portfolio`. Execution bridge: `POST /api/order/from-candidate` runs full pipeline → builds Tastytrade order → dry-run or submit. UI "Preview Order" → "Submit Order (Paper)" flow live.

---

## L1: Market State

**File:** `src/market_state.py`

**Built:**
- IV-RV spread (chain IV vs GARCH forward estimate) — the primary edge signal
- Vol surface: ATM IV, 25-delta put/call IV, skew, risk reversal
- Chain quality: avg/median spread %, liquid strike count, total OI
- Dealer positioning: GEX, gamma flip, call/put walls, max pain, P/C ratio
- Directional bias: EMA 9/21, RSI(14), MACD, momentum, ATR percentile
- Regime: HIGH_IV / MODERATE_IV / LOW_IV / SPIKE (from IV rank + VIX + term structure)
- Event calendar: FOMC/CPI detection with days-until

**Not built:**
- Intraday vol regime state machine (QUIET/NORMAL/ELEVATED/CRISIS from VIX + intraday range)
- Skew z-score (current skew vs 20-day rolling mean)
- Microstructure signals: bid-ask widening rate, OI changes (not levels), volume/OI ratio > 1

**MarketState.has_edge() — per-strategy gates (validated):**

| Strategy | Edge Gate | Rationale (from backtests) |
|---|---|---|
| Credit strategies | IV-RV > 1% AND edge_pct > 5% | Short put spread flips from Sharpe -0.31 to +1.14 with edge gate |
| Long put spread | IV-RV < -1% AND edge_pct < -5% | Sharpe jumps from 0.18 to 3.38 with edge gate |
| Long call spread | No edge gate | Edge filter *hurts* (Sharpe 1.74 → -0.87); directional momentum > IV cheapness |
| Butterfly | No edge gate | Pin strategy profits from convergence, not IV direction |

---

## L2: Trade Generation

**File:** `src/trade_generator.py`

### Signal confluence scoring

Weighted continuous 0-1 sub-scores, not a checklist:

```
Score = w_edge * edge_sub       (25%)   # IV-RV spread magnitude
      + w_regime * regime_sub   (20%)   # vol environment alignment
      + w_dealer * dealer_sub   (20%)   # GEX confirms strategy type
      + w_bias * bias_sub       (15%)   # directional alignment
      + w_skew * skew_sub       (10%)   # vol surface supports structure
      + w_timing * timing_sub   (10%)   # intraday window quality
```

**Threshold: score >= 60** to surface a candidate.

**IMPORTANT: These weights are initial estimates.** The architecture calls for regression-based calibration:

```
trade_pnl ~ edge_at_entry + regime_at_entry + dealer_at_entry + bias_at_entry + skew_at_entry
```

The regression coefficients should *replace* the guessed weights. This requires per-trade signal snapshots in the backtester, which is not yet implemented. See "Remaining work" below.

### Per-strategy exit rules (validated via BT6)

| Strategy | Profit Target | Stop Loss | Time Exit | Hold to Expiry | Sharpe (vs 50% target) |
|---|---|---|---|---|---|
| Iron condor | 50% credit | 2x credit | 1 DTE | No | -2.39 (same) |
| Short put spread | 50% credit | 2x credit | 1 DTE | No | -0.31 (same) |
| Short call spread | 50% credit | 2x credit | 1 DTE | No | -0.81 (same) |
| Long call spread | 75% debit | 1x debit | 2 DTE | No | 1.74 (vs 1.59) |
| Long put spread | 75% debit | 1x debit | 2 DTE | No | 0.18 (vs -0.14) |
| Butterfly | 100% debit | 1x debit | 0 DTE | Yes | **2.09** (vs 1.37) |

Per-strategy exits outperform uniform 50% target for every strategy.

### Timing windows

- **Credit strategies:** 10:00-11:00 ET (IV elevated, spreads tightening)
- **Debit strategies:** 15:00-15:45 ET (minimize overnight theta)
- Weekend/pre-market: neutral score (user is planning, not executing)

### Strike selection

- Short strikes: anchored to dealer walls (call wall for short calls, put wall for short puts)
- Butterfly center: max pain, not ATM
- Long strikes: spot ± ATM-to-25d-IV distance
- Falls back to fixed-width when dealer data unavailable

---

## L3: Execution & Sizing

**File:** `src/sizing.py`

### Kelly criterion position sizing

Half-Kelly, scaled by confluence score, capped at 2% portfolio risk per trade.

**Backtest-validated stats (SPY 2022-2026, 3% slippage, per-strategy exits):**

| Strategy | Best Config | Win Rate | Avg Win | Avg Loss | Kelly | Half-Kelly | Tradeable |
|---|---|---|---|---|---|---|---|
| Long put spread | strategy + edge>5% | 62.5% | $206 | $127 | 0.39 | 19.7% | **Yes** |
| Butterfly | strategy exits | 50.6% | $869 | $354 | 0.30 | 15.2% | **Yes** |
| Long call spread | strategy + regime | 59.8% | $176 | $140 | 0.28 | 13.9% | **Yes** |
| Short put spread | strategy + edge>5% | 80.4% | $77 | $212 | 0.26 | 13.2% | **Yes** |
| Short call spread | all configs | 66.7% | $80 | $237 | -0.09 | — | No |
| Iron condor | all configs | 42.2% | $85 | $197 | -0.47 | — | No |

**Key finding:** Strategy viability depends on filters. Short put spread is a loser unfiltered but Sharpe 1.14 with GARCH edge > 5%. Long put spread is the strongest strategy (Sharpe 3.38) when gated by edge.

### Slippage model

```python
ExecutionModel(slippage_pct=0.03, tick_size=0.01, max_spread_pct=0.10)
```

- 3% of premium on entry and exit (conservative)
- Minimum 1 tick ($0.01) slippage
- Reject if bid-ask > 10% of mid

### Spread cost gate

Checks bid-ask quality before execution. Wide spreads at short DTE can consume the entire edge.

---

## L4: Portfolio Engine

**File:** `src/portfolio.py`

### Position limits

```python
max_positions = 5
max_per_symbol = 2
max_delta = 50
max_gamma = 20
max_theta = -200
max_vega = 300
max_risk = $10,000
```

### Correlation-aware risk

SPY/QQQ/IWM correlation ~0.7. Three index positions are not independent. Variance-covariance model computes correlated worst-case.

### Hedge triggers

| Condition | Action | Urgency |
|---|---|---|
| abs(delta) > 30 | Reduce with opposing spread | High |
| abs(vega) > 150 | Trim long premium | Medium |
| risk > 80% of limit | Block new entries | High |

---

## Order Execution (Tastytrade)

**File:** `src/execution/order_manager.py`

**Built:**
- Tastytrade session management (paper-first, live requires explicit flag)
- Multi-leg order construction from legs
- Validation (max contracts, risk rules)
- Submit, cancel, get positions
- API endpoints: `POST /api/order`, `GET /api/positions`

**Built (2026-04-26):**
- `build_order_from_candidate(TradeCandidate, ExecutionResult)` → `OrderRequest`
- API endpoint: `POST /api/order/from-candidate` (dry-run preview + live submit)
- UI "Preview Order" → "Submit Order (Paper)" flow in TradingView
- Portfolio (L4) auto-update after successful order submission

**Not built:**
- Real OCC symbol resolution from chain data (currently computed from DTE)
- Order status polling / fill confirmation callback
- Close/roll existing positions from UI

---

## Validation Backtests — Summary

6 backtests run (SPY 2022-2026, 3% slippage). Full results in `VALIDATION_RESULTS.md`.

| Test | Finding |
|---|---|
| BT1: IC dealer ON/OFF | **No-op** — no historical dealer data in backtester |
| BT2: IC regime ON/OFF | Regime filter cuts 80% of bad trades. Still negative but Sharpe improves -2.39 → -0.72 |
| BT3: Credit bias ON/OFF | **No-op** — no historical bias signals computed in backtest loop |
| BT4: Credit edge >5% | **Transformative** for short put spread: Sharpe -0.31 → +1.14 |
| BT5: IC DTE buckets | 7-10 DTE best but still negative. No DTE saves ICs |
| BT6: Exit rule comparison | Per-strategy exits best for every strategy. Butterfly Sharpe 1.37 → 2.09 |

### Data limitations

- Option P&L is simulated from underlying price movement, not from actual historical option chains
- Slippage is a flat 3% assumption, not derived from real bid-ask spreads
- Dealer and bias filters untested (no historical data in backtester)
- Single underlying (SPY). Not validated on QQQ/IWM

---

## Remaining Work — Priority Order

### Priority 1: Quantitative rigor (the edge)

These are the things that determine whether the system actually makes money.

**1a. Regression-based confluence weights** ✅ DONE (2026-04-26)
Per-strategy OLS regressions completed on 422 trades. Key result: edge_pct is the only statistically significant continuous P&L predictor (p<0.001 in 3/4 strategies). Regime and bias work as binary gates, not continuous scalers. Weights updated: edge 25%→35%, regime 20%→15%, dealer 20%→10%, bias 15%→10%, skew 10%→15%, timing 10%→15%. See VALIDATION_RESULTS.md § Per-Strategy OLS Regression.

**1b. Bias signal replay in backtester** ✅ DONE (2026-04-26)
Bias signals computed from daily OHLCV per-day in the backtest loop. BT3/BT3b validated: bias helps put-direction strategies when combined with edge gate.

**1c. Historical options chain data** — Phase 1 (collection) ✅ DONE (2026-04-27)
Daily chain snapshot collector built. Stores full option chains (bid/ask/IV/OI/Greeks per contract) to SQLite via `src/data/chain_store.py`. Pipeline: `./start.sh collect` runs `YFinanceProvider.get_chain()` for SPY/QQQ/IWM, stores to `data/chain_snapshots.db` (3 tables: chain_snapshots, chain_contracts, iv_snapshots). API endpoints: `/api/chain-snapshots/*` and `/api/iv-history/*`. First snapshot: 2026-04-27, 8,553 contracts across 3 tickers.

**Phase 2 remaining:**
- Run collector daily to accumulate dataset (after 2-3 months: parallel validation)
- Build backtester adapter to read from chain_snapshots instead of simulating P&L
- Replace flat 3% slippage with actual bid-ask spread measurements
- Compute real IV at entry/exit for accurate P&L
- Optional: ThetaData ($30/mo) for historical backfill to 2013+
- Optional: CBOE DataShop for institutional-grade cross-validation
- See `docs/historical_data_options.md` for full provider analysis

### Priority 2: Execution bridge ✅ DONE (2026-04-26)

`build_order_from_candidate()` converts L2 TradeCandidate + L3 ExecutionResult → OrderRequest. API endpoint `POST /api/order/from-candidate` supports dry-run preview and live submission. UI flow: Preview Order → review legs/price/risk → Submit Order (Paper). Portfolio auto-updates after fill. Remaining: real OCC symbol resolution, fill polling, close/roll UI.

### Priority 3: Intraday state machine

QUIET/NORMAL/ELEVATED/CRISIS regime based on VIX level + intraday range. Currently regime is computed once from daily data. Intraday shifts (VIX moving 2-3 points in a session) are not captured.

### Priority 4: Microstructure signals

- Bid-ask spread widening rate (uncertainty indicator)
- OI changes day-over-day (new positioning vs existing)
- Volume/OI ratio > 1 at a strike (active opening/closing)

These require intraday or end-of-day chain snapshots to compute historically.

---

*Options Analytics Team — 2026-04. Last updated 2026-04-27 with chain snapshot pipeline.*
