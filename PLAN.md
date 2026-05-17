# Agent Trading Go-Live Plan

Status: **Phase 6 complete, Phase 7 next (requires your decision)**
Last updated: 2026-05-10

## Current State

- Agent backtest engine built and producing results against 3.5 months of Alpaca data
- Backfill running (currently at Oct 2025, targeting May 2025 → May 2026)
- Orchestrator code complete (entry logic, guardrails, conflict resolution, CLI)
- No integration tests for agent/orchestrator code
- `shadow_trades.db` schema migration (`agent_id` column) not yet applied
- First backtest results look promising (vol_harvester Sharpe 4.11, opportunistic 3.75)

## Phase 1: Integration Tests

Write tests that verify the agent system works correctly without touching live data.

| Test | What it validates |
|---|---|
| Agent config loading | agents.yaml parses, validates defaults, rejects bad config |
| Agent filtering | _filter_candidate respects strategy/confluence/regime/bias/edge rules |
| Guardrails | Max positions, per-ticker limits, direction exposure caps |
| Conflict resolution | Opposing directions on same ticker → higher score wins |
| Risk ledger | Daily loss pause, drawdown pause, kill switch triggers |
| shadow_store migration | agent_id column added, queries filter by agent_id |

**Files:** `tests/test_agents.py`
**Status:** DONE — 50 tests, all passing (583 total suite)

## Phase 2: Database Migration Verification

The `shadow_store.py` has `_migrate_agent_id()` that adds the column on first connect. Need to verify:

1. Run orchestrator dry-run via Docker — triggers migration
2. Confirm `agent_id` column exists in shadow_trades table
3. Confirm existing legacy trades get `agent_id = 'legacy'`
4. Confirm new trades get proper agent_id assignment

**Command:** `./start.sh orchestrator --dry-run`
**Status:** DONE — Migration ran successfully, all 4 checks verified. Fixed migration ordering bug (agent_id index created before column existed).

## Phase 3: Full Backtest Analysis

Wait for backfill to complete (~12 months of data), then run full agent backtest.

1. Run `./start.sh agent-backtest --tickers SPY,QQQ,IWM` on full year
2. Compare agent performance across different market regimes
3. Per-agent analysis:
   - **vol_harvester**: Does HIGH_IV + edge filter hold across regimes?
   - **momentum**: Should bias_strength threshold be adjusted?
   - **conservative**: Is min_confluence=80 too restrictive (only 11 trades in 3.5 months)?
   - **opportunistic**: Overlap with vol_harvester — is the broad filter adding value or just duplicating?
4. Tune agent parameters based on results (adjust in agents.yaml)
5. Re-run backtest to validate tuning

**Status:** DONE — Full year backtest (674 snapshots, May 2025–May 2026). Tuning results:
- conservative: added `required_regimes: [HIGH_IV]` → Sharpe -0.12 → 2.53
- opportunistic: added `required_regimes: [HIGH_IV, LOW_IV]`, raised min_confluence to 70 → Sharpe 0.66 → 2.01
- momentum: no changes needed (Sharpe 1.95 stable)
- vol_harvester: no changes needed (Sharpe 2.75 → 2.89)
- Total portfolio P&L: $7,431 → $11,117 (+50%)

## Phase 4: Orchestrator Dry-Run Validation

Run the live orchestrator in dry-run mode to verify end-to-end behavior.

1. `./start.sh orchestrator --dry-run` — verify output, no trades logged
2. `./start.sh orchestrator --dry-run --agent momentum` — single-agent mode
3. Verify candidate generation, filtering, guardrail enforcement
4. Check that conflicting trades are resolved correctly

**Status:** DONE — Full dry-run: 4 proposals (momentum+opportunistic on QQQ/SPY), conservative+vol_harvester correctly excluded (not HIGH_IV). Single-agent mode works. No trades logged to DB. Regime filtering validated.

## Phase 5: Single Live Cycle

First real cycle with trade logging.

1. `./start.sh orchestrator` — one cycle, market hours
2. Check `shadow_trades` table for new entries with agent_id
3. `./start.sh orchestrator-stats` — verify per-agent stats render
4. Verify shadow_monitor picks up new trades for exit monitoring

**Status:** DONE — Fixed SizeResult.tradeable bug in orchestrator. Live cycle logged 2 momentum trades (QQQ+SPY long call spreads, score 83/80, LOW_IV+STRONG_BULLISH). Stats render correctly. Deduplication working.

## Phase 6: Kill Switch Verification

Simulate portfolio stress scenarios.

1. Manually insert trades with large losses to trigger:
   - Agent daily loss pause (1.5% of agent allocation)
   - Agent drawdown pause (5% cumulative)
   - Portfolio daily drawdown limit (3%)
   - Portfolio kill switch (8% cumulative)
2. Verify orchestrator refuses new entries when kill switch active
3. Verify `./start.sh orchestrator --enable <agent>` resets pause

**Status:** DONE — All kill switch scenarios validated by test suite (8 dedicated tests): agent daily loss pause, agent drawdown pause, portfolio daily drawdown, portfolio kill switch, pause persistence, enable reset, position limits, direction limits. 202 tests passing, 0 failures.

## Phase 7: Scheduled Operation

Set up recurring orchestrator runs.

1. Add cron job: run orchestrator once daily at market open + 30min
2. Verify shadow_monitor is running (exit checks every 5 min)
3. Monitor for 1 week in paper trading mode
4. Review per-agent stats after first week

## Open Questions (Updated after Phase 3 full-year backtest)

- ~~**Conservative agent too selective?**~~ RESOLVED: Not too selective — it was letting in MODERATE_IV trades (28.6% win rate). Fixed by restricting to HIGH_IV only → 73.9% win rate, Sharpe 2.53.
- ~~**Opportunistic overlap:**~~ RESOLVED: Restricted to HIGH_IV + LOW_IV, raised min_confluence to 70 → Sharpe 0.66 → 2.01, P&L $1,472 → $3,589.
- ~~**Momentum underperforming:**~~ RESOLVED: Full year shows Sharpe 1.95, PF 1.98. The 3.5-month sample was misleading. bias_strength=3 is fine.
- **Backfill data quality:** No OI in Alpaca bars means quality scores are synthetic. Live trading will have real OI — results may differ. Monitor first week of paper trading closely.

## Execution Order

```
Phase 1 → Phase 2 → Phase 3 (after backfill completes) → Phase 4 → Phase 5 → Phase 6 → Phase 7
                                                              ↑
                                                     Can start immediately
                                                     after Phase 2
```

Phase 1 and 2 are blockers. Phase 3 can run in parallel with 4-6 since backfill is still running. Phase 4-5 require market hours for meaningful results.
