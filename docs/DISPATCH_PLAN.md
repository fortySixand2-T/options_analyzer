# Dispatch Plan — continue the regime-based edge research

> Hand-off plan for an async/remote Claude Code session ("claude dispatch") to continue
> while the user is away. Written 2026-05-31, after commit `2c71bd9`. Self-contained: read
> this top to bottom before acting. The narrative record is in `FINDINGS.md` (F-001…F-019).

## Where we are (one paragraph)

We separated edge research into two independent layers: a **signal layer** (does a feature
predict the *underlying's* forward return — tested by Information Coefficient on free yfinance
data) and an **execution layer** (does it survive being traded as a defined-risk option spread on
real Dolt quotes). F-018 found the first IC-validated signal — `conditioned_reversal` (buy the
3-month laggard in a calm vol regime): SPY/QQQ, `vix_pct` gate, rank IC **+0.163 @10d, p<0.001**.
F-019 then showed that signal does **NOT** transmit through 10–14 DTE debit spreads (sign-only edge
swallowed by spread cost + magnitude/timing). Lesson now in memory: **IC is necessary but not
sufficient.** The user endorses **regime-specific strategies across more tickers/indices**, as long
as the regime is identifiable live (point-in-time gate).

## Ground rules (do not violate)

- **Docker is the entry point.** The `test`/`dev` image COPIES `src/`, `scripts/`, `tests/` at
  build time. For a quick run, bind-mount instead of rebuilding:
  ```
  docker-compose run --rm --no-deps \
    -v "$PWD/src:/app/src" -v "$PWD/tests:/app/tests" -v "$PWD/scripts:/app/scripts" -v "$PWD/data:/app/data" \
    test python -m pytest tests/<file> -q
  ```
  After source changes are final, `docker-compose build test` to bake them in. (Use `docker compose`
  if `docker-compose` is absent.)
- **Every file created/edited → docstrings + inline comments**, append a dated `CHANGELOG.md` entry,
  and (for investigations) an append-only `FINDINGS.md` entry `F-0NN` (newest at bottom + index row
  at top; never renumber). This is a hard user rule.
- **No deferred tech debt** — fix issues before moving on; don't log follow-ups as debt.
- **Do NOT touch** frozen files (see `CLAUDE.md` "Frozen files"), and never `src/services/options/`
  style off-limits dirs. Don't commit `.hf_cache/`, `test-results/`, `*.zip`, `docs/response.md`.
- **Regime gates must be point-in-time** (no full-sample median/threshold) so live == backtest.
- Commit + push after each phase with a clear message ending in the `Co-Authored-By: Claude Opus 4.8`
  trailer. Branch is `main`, remote `origin`.

## Key files

| Purpose | Path |
|---|---|
| Point-in-time signals | `src/backtest/signal_lib.py` (`SIGNALS` registry, `conditioned_reversal`) |
| IC engine + strict gate | `src/backtest/signal_eval.py` (`ic_at_horizon`, `fold_ic_signs`, `regime_ic_signs`, `graduate`) |
| IC sweep CLI | `scripts/signal_ic_sweep.py` |
| Conditioned-signal validation | `scripts/conditioned_signal_test.py` |
| Execution test (signal→spread) | `scripts/signal_execution_test.py` |
| Backtester + entry gate | `src/backtest/chain_replay.py` (`signal_filter`/`signal_gate`, `_build_conditioned_signal`) |
| Option data | `data/chain_snapshots.db` (Dolt real quotes; SPY best, 2020-2024) |

---

## Phase 1 — Broaden the signal sweep across tickers/indices, per-regime

**Goal:** find which signals graduate on which underlyings in which vol regime. The user wants this
explicitly extended beyond SPY.

1. Run the existing sweep on a wider universe (already supports regime split):
   ```
   python scripts/signal_ic_sweep.py --symbols SPY,QQQ,IWM,DIA,XLK,XLF,XLE --start 2020-01-01 --end 2024-12-31
   python scripts/conditioned_signal_test.py --symbols SPY,QQQ,IWM,DIA --start 2020-01-01 --end 2024-12-31
   ```
   (Check yfinance has each symbol back to 2020; sector ETFs do.)
2. Add 1–2 new candidate signals to `signal_lib.SIGNALS` from the F-018 literature shortlist that we
   have not yet tested — prioritize ones that are FREE/CHEAP and orthogonal: e.g. a **VRP proxy**
   (`^VIX` − trailing realized vol) and **52-week-high proximity**. Keep them point-in-time. Add unit
   tests in `tests/test_signal_lib.py` (orientation + no-lookahead, mirror the existing ones).
3. Run everything through `graduate()` (strict gate) and the per-regime split. Produce a table:
   **signal × underlying × regime → graduates? (IC, p, n)**.
4. **Acceptance / log:** write `FINDINGS.md` F-020 with the table and which (signal, underlying,
   regime) combinations graduate. Update `CHANGELOG.md`. If a new signal graduates on a new
   underlying, note it as a golden-param candidate.

**Decision point (leave for the user if unclear):** which graduated (signal, underlying, regime)
combos are worth carrying to Phase 2. Default: carry every combo with IC ≥ 0.05, p < 0.01,
sign-stable.

## Phase 2 — Match each validated signal to the RIGHT vehicle (execution layer)

F-019 proved a directional signal can be real yet fail as a debit spread. For each Phase-1 survivor,
test the vehicle that fits its edge type:

- **Directional signals** (like `conditioned_reversal`): the debit spread failed on cost/magnitude.
  Re-run `scripts/signal_execution_test.py` but vary the structure toward MORE delta / LESS cost
  drag — higher `entry_delta` (e.g. 0.35–0.50, deeper ITM long leg) and/or longer DTE. The script
  already takes `--strategy` and `--gate`; extend it to accept `--entry-delta` and `--dte-min/max`
  and sweep them. A real edge should show improving per-trade return-on-risk as cost drag falls, on
  a sample of **≥ 30 trades** (n=4 is noise — this killed the first F-019 read).
- **Volatility-regime signals** (e.g. VRP/term-structure): route to **premium sellers**
  (`short_put_spread`, `iron_condor`) and test whether the regime gate improves the seller's TAIL
  metrics (CVaR/Calmar/max-loss — see `analyzer.py` and `robustness.primary_metrics`), not win rate.
  Compare gated vs unconditional with `run_chain_replay`.

**Acceptance / log:** F-021 — for each signal, a clear "helps / doesn't help, with sample size and
the metric that matters for its family." Honest negatives are valuable; do not curve-fit to make
something pass.

## Phase 3 — Pay down the debt this work exposed

1. **Cache key completeness** (`src/backtest/cache.py` `_cache_key`): it currently omits
   `vrp_filter` and `swing_bias_filter` (harmless today because unused, but a latent F-005-class
   bug). Add every result-affecting `BacktestRequest` field to the key, and add a test that fails if
   a new such field is missing (e.g. iterate the model's fields against a known allow-list). Log in
   CHANGELOG (no new finding needed unless it changes a result).
2. **Index data thinness:** Dolt QQQ has 0 trades at 10–14 DTE (too sparse). Document in
   `DATA_ISSUES.md` and restrict execution tests to SPY on current data, OR note that broader index
   execution testing needs more option data (external acquisition decision — surface to user, don't
   spend).

## Phase 4 — (Stretch) the unused sentiment archive

`data/sentiment_backtest.db` holds ~119k FinBERT-scored headlines (2008–2026, 12 tickers) — a 4th,
genuinely orthogonal signal source. Build a `sentiment_score(t) → forward-return` IC test reusing
the `signal_eval` engine (point-in-time: only headlines dated ≤ t). If it graduates the strict gate,
carry to Phase 2 vehicle-matching. Respect the sentiment module's "zero imports from other src/"
rule (`.claude/rules/sentiment.md`) — read scores from the DB, don't import the package internals.

---

## After each phase
Run the relevant tests in Docker (bind-mount), `docker-compose build test`, append CHANGELOG +
FINDINGS, update persistent memory if a durable fact emerged (golden params, a new lesson), then
`git commit` + `git push origin main`. If a genuine external blocker or a real fork appears (e.g.
"is this combo worth pursuing?"), state it plainly and stop rather than guessing.
