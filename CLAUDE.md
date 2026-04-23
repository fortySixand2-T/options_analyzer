# CLAUDE.md — Index Options Scanner

## What this is

0-14 DTE index options scanner. Five defined-risk strategies. Web UI primary. Docker deployment.

**Read SIGNALS.md first.** It defines every signal, the decision matrix, and conviction scoring.

---

## Five strategies (everything else is removed)

1. **Iron condor** — neutral credit, 7-14 DTE
2. **Short put spread** — bullish credit, 3-10 DTE
3. **Short call spread** — bearish credit, 3-10 DTE
4. **Long call/put spread** — directional debit, 3-14 DTE
5. **Butterfly** — pin play at max pain, 0-7 DTE

No calendar spreads, diagonals, strangles, straddles, or naked options.

---

## Files to DELETE

Remove these files. They're dead code, wrong timeframe, or superseded:

```
src/opportunity_builder.py           # TC-coupled, nobody imports it
src/strategy_selector.py             # Wrong timeframe (7-120 DTE outlooks)
src/formatter.py                     # Only used by old scenario_runner
src/ai_narrative.py                  # Nice-to-have, not core. Re-add later.
src/utils/config.py                  # Old TC config. src/config.py handles everything.
src/utils/data_export.py             # Not used by web UI
src/utils/__init__.py                # Exports from utils/ which is gutted

EXTENSIONS.md                        # TC docs
USECASES.md                          # Old standalone use cases
activate_env.sh                      # Docker replaces this
build.sh                             # start.sh replaces this
frontend/src/assets/hero.png         # Scaffold placeholder
frontend/src/assets/react.svg        # Scaffold placeholder
frontend/src/assets/vite.svg         # Scaffold placeholder
```

Move to `src/strategies/_deferred/` (future swing-trade tab, 14-60 DTE):
```
src/strategies/calendar_spread.py → src/strategies/_deferred/calendar_spread.py
src/strategies/diagonal_spread.py → src/strategies/_deferred/diagonal_spread.py
src/strategies/short_strangle.py  → src/strategies/_deferred/short_strangle.py
src/strategies/long_straddle.py   → src/strategies/_deferred/long_straddle.py
src/strategies/naked_put_1dte.py  → src/strategies/_deferred/naked_put_1dte.py
```
These strategies need different signals (SMA 50/200, IV term structure slope, earnings calendar) and different DTE windows. They return in a future "Swing" tab with its own signal architecture. Do NOT delete them — they are valid strategies for a different timeframe.

Move to `examples/` (useful reference, not part of scanner):
```
src/options_analyzer.py → examples/options_analyzer.py
src/options_test_runner.py → examples/options_test_runner.py
src/mc_runner.py → examples/mc_runner.py
src/scenario_runner.py → examples/scenario_runner.py
src/vol_surface_runner.py → examples/vol_surface_runner.py
src/analytics/simulations.py → examples/simulations.py
src/analytics/visualization.py → examples/visualization.py
```

---

## Files to KEEP frozen (never modify logic)

```
src/models/black_scholes.py
src/monte_carlo/gbm_simulator.py
src/monte_carlo/garch_vol.py
src/monte_carlo/jump_diffusion.py
src/monte_carlo/american_mc.py
src/monte_carlo/mc_greeks.py
src/monte_carlo/risk_metrics.py
src/scanner/edge.py
src/scanner/scorer.py
src/scanner/providers/base.py
src/scanner/providers/cached_provider.py
```

---

## Files to MODIFY

### src/config.py
- Change `OUTLOOKS` to: short (0-5), medium (5-10), long (10-14)
- Change scanner defaults: min_dte=0, max_dte=14
- Add conviction weights from SIGNALS.md (20/20/20/15/10/10/5)
- Remove `PRICING` dict if still present

### src/scanner/iv_rank.py
- Change `_REGIME_THRESHOLDS` to: (50, 'HIGH_IV'), (30, 'MODERATE_IV'), (0, 'LOW_IV')
- Remove ELEVATED and NORMAL — simplify to 3 regimes + SPIKE

### src/scanner/contract_filter.py
- Default min_dte → 0, max_dte → 14

### src/scanner/strategy_mapper.py
- Rewrite to use 3-input decision matrix from SIGNALS.md: (regime, bias, dealer_regime) → strategy
- Remove _map_elevated(), _map_normal() — only 3 regimes now
- Add dealer_regime parameter

### src/scanner/strategy_pricer.py
- Use GEX walls (F3/F4) and max pain (F5) for strike placement instead of fixed increments

### src/scanner/providers/flashalpha_client.py
- Return: net_gex, gamma_flip, call_wall, put_wall, max_pain, dealer_regime, put_call_ratio
- These are signals F1-F7 from SIGNALS.md

### src/scanner/providers/yfinance_provider.py
- Default min_dte → 0

### src/scanner/scanner.py
- Inject dealer positioning into scan loop
- Pass dealer_regime to strategy_mapper
- Pass directional bias to strategy_mapper

### src/regime/detector.py
- Incorporate IV rank into regime: HIGH_IV (rank>50), MODERATE_IV (30-50), LOW_IV (<30), SPIKE (VIX>30)
- Currently only uses VIX level + term structure

### src/regime/vix_analysis.py
- Add VIX9D/VIX ratio

### src/strategies/base.py
- Add dealer_regime to evaluate() signature
- Update score formula to SIGNALS.md weights (20/20/20/15/10/10/5)
- Currently 60% checklist + 40% conviction — change to weighted component formula

### src/strategies/iron_condor.py
- dte_range → (7, 14)
- iv_range → (40, 100)
- Add dealer regime check: only LONG_GAMMA
- Add to checklist: "Dealer regime: LONG_GAMMA"

### src/strategies/credit_spread.py
- dte_range → (3, 10)
- iv_range → (30, 100)
- Add directional bias check to checklist

### src/strategies/debit_spread.py
- dte_range → (3, 14)
- iv_range → (0, 40)
- Add directional bias check

### src/strategies/butterfly.py
- dte_range → (0, 7)
- Center at max pain strike instead of ATM

### src/strategy_scanner.py
- Add bias detection call before strategy evaluation
- Add dealer positioning call before strategy evaluation
- Pass bias + dealer data to each strategy.evaluate()

### src/bias_detector.py
- REWRITE completely. Replace SMA 20/50/200, golden cross, stochastic with:
  EMA 9/21, RSI(14), MACD histogram, prior candle, 2-day momentum, ATR percentile
- Input: pandas DataFrame of daily OHLCV (not a pre-computed signal dict)
- Output: BiasResult(label, score, detail)

### src/ui/app.py
- Add dealer data to /api/regime and /api/scan responses
- Add bias data to /api/scan responses

### Frontend components
- RegimeDashboard.jsx: add GEX display, dealer regime badge
- Scanner.jsx: show dealer regime + bias in checklist
- Add ChainViewer component

---

## Implementation order

**Step 1: Clean house**
Delete files listed above. Move runners to examples/. Verify tests still pass.

**Step 2: Fix all DTE parameters**
Update config.py, iv_rank.py, contract_filter.py, all 4 remaining strategy files. Pure number changes, no logic.

**Step 3: Rewrite bias_detector.py**
New input: DataFrame. New signals: EMA 9/21, RSI, MACD histogram, prior candle, 2-day momentum, ATR pctl.
New output: BiasResult with STRONG_BULLISH to STRONG_BEARISH.

**Step 4: Expand dealer positioning**
Expand flashalpha_client.py. Add compute-from-chain fallback for GEX/max pain/P-C ratio.
Add DealerData to scanner pipeline.

**Step 5: Rebuild decision matrix**
Rewrite strategy_mapper.py with 3-input lookup from SIGNALS.md.
Update strategy_scanner.py to pass all three inputs.
Update strategy base.py evaluate() with new conviction weights.

**Step 6: Update UI**
Add dealer + bias data to API responses.
Update React components:

- RegimeDashboard.jsx: add GEX display, dealer regime badge
- Scanner.jsx: show dealer regime + bias in checklist
- Add ChainViewer component
- **Backtest.jsx — update heavily:**
  1. Fix strategy dropdown — only show 4 active strategies: iron_condor, credit_spread, debit_spread, butterfly (remove the 5 deferred ones still in the list)
  2. Add a **compare mode** — side-by-side backtests of 2-3 strategies on the same symbol/date range with combined equity curve (different colored lines) and stat comparison table. This is how Trading Copilot's hypothesis testing works: define experiment → run → see results.
  3. Add **filter toggles** for each signal layer so the user can test "does this filter improve results":
     - Regime filter ON/OFF (only take trades when regime matches)
     - Bias filter ON/OFF (only take trades when directional bias aligns)
     - Dealer regime filter ON/OFF (only take trades when GEX regime matches)
     - GARCH edge filter ON/OFF (only take trades when edge > threshold)
     These toggles are the core backtesting feature — they answer "does each signal layer add value?"
  4. Add **DTE bucket breakdown** table: group results by 0-3, 3-5, 5-7, 7-10, 10-14 DTE to find optimal entry window
  5. Add **P&L distribution histogram** — show the distribution of trade outcomes, not just the equity curve. Helps visualize fat tails and skew.
  6. Add **exit rule comparison** — toggle between 50% profit target vs hold-to-expiry to see which exit produces better Sharpe
  7. Add **trade table** — expandable list of individual backtest trades showing: date, entry/exit price, P&L, DTE, regime at entry, bias at entry, dealer regime. Sortable by any column.

- **Backend (`src/ui/app.py`) changes for backtest:**
  1. `GET /api/backtest/{strategy}` — add query params: `regime_filter`, `bias_filter`, `dealer_filter`, `edge_threshold`, `exit_rule` (50pct|hold)
  2. `GET /api/backtest/compare` — accepts `strategies` param (comma-separated), returns results for all, same date range
  3. Response should include: `stats`, `equity_curve`, `regime_breakdown`, `dte_breakdown`, `pnl_distribution` (histogram buckets), `trades` (list of individual trades)

**Step 7: Run backtests to validate**
Run the 6 backtests from SIGNALS.md using the UI:
1. Iron condors: toggle regime filter ON vs OFF — does HIGH_IV filter improve win rate?
2. Iron condors: toggle dealer filter ON vs OFF — does LONG_GAMMA filter improve win rate?
3. Credit spreads: toggle bias filter ON vs OFF — does directional bias improve results?
4. Credit spreads: toggle GARCH edge filter ON vs OFF — does edge > 5% improve results?
5. Iron condors: compare DTE buckets in the breakdown table
6. All strategies: compare 50% profit target vs hold-to-expiry exit rules

Use results to calibrate conviction score weights. If a filter doesn't improve results, reduce its weight. If it significantly improves results, increase it.

---

## Dev conventions

- Python 3.11+
- `ruff` for linting
- Pydantic v2 for new models
- `rich` for CLI output
- Docker via `./start.sh`
- Read SIGNALS.md before implementing any signal logic
- One step at a time. Test before moving on.
- Do not modify frozen files.

---

## Future: Swing trade tab (do NOT build yet)

After the 0-14 DTE system is backtested and calibrated, add a second tab:

| Tab | DTE | Strategies | Signals |
|---|---|---|---|
| Day trade (current) | 0-14 | IC, credit spread, debit spread, butterfly | EMA 9/21, RSI, MACD hist, GEX, dealer regime |
| Swing (future) | 14-60 | Calendar, diagonal, strangle, straddle | SMA 20/50/200, IV term structure slope, earnings calendar, sector rotation |

The deferred strategies in `src/strategies/_deferred/` are the starting point. They need their own bias detector (the old SMA-based `bias_detector.py` signals are actually correct for swing), their own regime thresholds, and their own conviction weights. This is a separate signal architecture, not a parameter tweak on the current one.

Build the day-trade system first. Prove it works with backtesting. Then add scope.
