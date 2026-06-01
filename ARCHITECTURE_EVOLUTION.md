<!--
  ARCHITECTURE_EVOLUTION.md — how the system's design is changing over time.

  Purpose: TRADING_SYSTEM_ARCHITECTURE.md describes the *intended* design;
  this file records how that design is actually *evolving* as findings come in
  — what changed, why, and where it's heading. Append a dated section per
  evolution step; keep older sections intact (they are the design history).
  Cross-reference findings as F-NNN (see FINDINGS.md) and file edits via
  CHANGELOG.md.
-->

# Architecture Evolution

How the original architecture is changing in response to what we learn. Reads
top-down: the original intent first, then each dated evolution step. Pairs with
`FINDINGS.md` (the evidence) and `TRADING_SYSTEM_ARCHITECTURE.md` (the intended
design).

---

## 0. Original architecture (baseline, as of 2026-05)

A 0–14 DTE defined-risk **options scanner + backtester**, three-layer signal
engine, FastAPI + React, Docker, SQLite "data moat".

```
Watchlist → ChainProvider → [Vol Regime → Bias → Dealer] → Decision Matrix
          → Strategy + Conviction Score
                                   │
                                   ▼
                 Backtesters:  local_backtest (Black-Scholes synthetic)
                               chain_replay   (real chain snapshots)
```

Key baseline properties (the starting point for this evolution):
- **Two backtesters.** `local_backtest` synthesizes option prices via Black-Scholes;
  `chain_replay` walks real snapshots from `chain_snapshots.db`.
- **Pricing.** `chain_replay` priced fills at the snapshot **mid**, with `slippage_pct`
  ignored.
- **Execution loop.** Single position at a time; the next entry was scheduled
  relative to the prior trade's **exit** (`exit_idx + 3`).
- **Data moat.** Chain snapshots from three sources (DoltHub 2020-2024 real quotes;
  Alpaca backfill 2025+; yfinance forward collection), plus persisted signals.
- **Validation.** In-sample 6-backtest suite; the live agent / execution stack was
  parked (2026-05-20) to focus on getting the edge right first.

The decision **not** to merge with the sibling repos, and to instead import their
*validation rigor*, is recorded in `../OPTIONS_REPOS_ANALYSIS.md`.

---

## 1. Backtester fidelity hardening (2026-05-30)

Trigger: the synthesis analysis identified "P&L is partly simulated / validation is
in-sample" as the #1 weakness. Fixing chain-replay fidelity became the first concrete
step. A cascade of findings (F-001…F-006) reshaped two subsystems.

### 1a. Pricing model: mid → real bid/ask → close-as-fill + explicit slippage

The pricing path evolved through three understandings:

```
was:   fill = snapshot mid            (optimistic; F-001)
then:  fill = bid/ask (cross spread)  (realistic where quotes are real)
but:   2025+ "bid/ask" was fabricated from OHLC bars  (F-003)
now:   real-quote rows  → cross the real bid/ask spread
       Alpaca-bar rows  → fill at the bar CLOSE; spread modeled by slippage
```

- **Real quotes** (Dolt 2020-2024, yfinance forward): crossed via `_leg_fill_price`
  (buys lift ask, sells hit bid; exits reverse). `fill_mode="mid"` retained for A/B.
- **Alpaca bars** (2025+): there is no real spread to cross — Alpaca gives OHLC bars,
  not quotes. We now use the bar **close** as the single traded price
  (`bid==ask==mid==close`), mirroring options-algo-trader, and model execution cost
  via **net-level slippage** (`_apply_slippage`, F-004). Existing contaminated rows
  were migrated (`scripts/migrate_backfill_fills.py`).
- **P&L convention** unified to `pnl = entry_net - current_value` for credit and
  debit (F-002), and slippage made a provably strict per-trade cost under it.

Architectural consequence: **fill realism is now data-source-aware**. The backtester
must know *what kind* of data a row is (recorded quote vs traded bar) to price it
honestly. Provenance (the `label` column) is now first-class.

### 1b. Execution loop: serialized single-position → decoupled fixed-cadence

The biggest structural change (F-004):

```
was:   for snapshot:
           if a position is open: maybe exit it; else maybe enter
           next entry scheduled at  exit_idx + 3      ← entries depend on exits

now:   for entry_idx in fixed cadence (every N snapshots):
           build entry (filters → strikes → price)
           forward-scan independently for THIS position's exit
       positions may overlap (concurrency allowed)    ← entries independent of exits
```

Why: the old loop coupled the entry calendar to prior exit timing, making the trade
*set* a chaotic function of P&L. A <1% perturbation reshuffled the whole sequence
(F-004). Decoupling makes the **trade set a deterministic function of (cadence,
filters, data)** — independent of fills/slippage/exit thresholds. This is the
prerequisite for perturbation-based robustness analysis.

New trade-off introduced: concurrent overlapping positions are **correlated** in
trending periods, inflating Sharpe/PF (F-006). Resolving the portfolio/return-series
model is the next architectural decision.

### 1d. Performance measurement: per-trade series → time-indexed mark-to-market

Allowing concurrent positions (1b) broke the per-trade Sharpe: overlapping trades are
correlated, so counting them as independent samples (annualized √52/trades) inflated
Sharpe to ~18 on trending windows (F-006).

```
was:   Sharpe/drawdown from the per-trade P&L series, annualized by trade count
now:   Sharpe/drawdown from a TIME-INDEXED mark-to-market portfolio curve,
       annualized by actual snapshots-per-year
```

`chain_replay` now builds a portfolio curve over snapshots (each position adds its mark
while open, its realized P&L thereafter); `analyzer.analyze_results` takes that curve and
computes risk metrics from its periodic returns (per-trade *descriptive* stats — win
rate, PF — are unchanged). SPY `long_put_spread` Sharpe fell 18 → 1.76 with a meaningful
drawdown. Caveat (F-007): with sparse snapshots the curve currently approximates a
*time-indexed realized* curve (intra-hold marks often unavailable), so it captures
exit-clustering correlation but not intra-hold unrealized vol. Architectural consequence:
**performance is measured on a portfolio timeline, not a trade ledger** — the natural
basis for the concurrency/return model and for the perturbation harness.

### 1e. Strike selection must be single-expiry (F-008) — and a defined-risk invariant gate

Tracing a "too good" result (QQQ `long_put_spread` 100% WR) exposed a **strike-selection
bug**: `_select_strikes` chose legs from the *entire* entry DTE window, which spans multiple
expiries, so a "vertical" took its two legs from **different expiries** — a calendar/diagonal
whose value far exceeds the strike span. This produced impossible premiums
(`|entry_net| > strike_span` in 40–96% of entries) that "decayed to zero" into phantom
profit, silently inflating spread results (SPY `long_put` +$5,164→−$650; butterfly −$57k→−$5.1k).

> Correction trail: this was first mis-attributed to "every-other-day cadence" (data is
> already daily) and then to "non-synchronous marks → need OPRA quotes" (the per-expiry chain
> is actually clean and monotonic). It was a **free code bug**, caught by inspecting the
> selected legs' expiries. Lesson: inspect the objects before escalating to a paid feed.

Architectural consequences:
- **Spread construction is now single-expiry by contract.** `_select_strikes` filters to the
  nearest expiry before picking strikes, so all legs (and entry/exit) share one expiration.
- **A defined-risk invariant is enforced at entry** as a cheap backstop: reject
  `|entry_net| > strike_span` (catches the rare residual from wide/odd quotes).
- After the fix, chain-replay spread results are realistic (credit spreads 80–85% WR,
  modest PF; debit/fly mostly mediocre) — trustworthy enough for the OOS/perturbation gate,
  with **no data subscription required**. (Real NBBO quotes remain a *nice-to-have* for true
  bid/ask realism and F-007 intra-hold resolution, not a correctness blocker.)

### 1c. Emerging principle — perturbation stability as a design constraint

A backtester intended for robustness testing must satisfy: *small, economically-
meaningless input perturbations must not change which trades exist, only their
outcomes.* This is now an explicit design constraint, and it retroactively justifies
1b. It also exposed an infra gap: the result cache keys on request params but not on
backtester logic version (F-005), so it can serve stale results across code changes.

---

## 2. Where this is heading (direction, not yet built)

1. **Perturbation / robustness harness — BUILT (2026-05-30).** `src/backtest/robustness.py`
   + `scripts/robustness.py`: runs a strategy across time folds, an in/out-of-sample split,
   and a fill×slippage perturbation grid, reporting skew-aware metrics per slice and a
   conservative verdict (robust / fragile_or_no_edge / insufficient_sample). It runs on the
   now-trustworthy backtester and self-checks the F-004/F-006 guarantees (trade-count stable,
   slippage monotonic). First survey: surveyed strategies flag **fragile_or_no_edge** — e.g.
   short_put_spread SPY is negative over the full window with skew ≈ −3 (high win rate masking
   a fat left tail), and its "edge" lives in a single time fold. See FINDINGS.md F-014.

2. **Concurrency / return-series model (F-006 — DONE; F-007 follow-up).** Risk metrics
   now use a time-indexed mark-to-market portfolio curve. Remaining: make the curve a
   *continuous* MTM (intra-hold marks are sparse, F-007) via denser data / the quotes
   endpoint, so drawdown reflects interim risk, not just exit-to-exit.

3. **Finer risk visibility (F-007) — reframed after measurement.** Update (c) corrected the
   earlier "daily bar re-backfill" plan: the 2025+ data is **already daily** (re-backfill is
   a no-op), and the ~1-mark-per-trade curve granularity is **exit-logic-bound** — trades
   exit at the first snapshot that triggers a rule (QQQ `long_put` median hold 1 day; SPY 12
   days), so each contributes ≈ one mark regardless of data density. SPY's longer holds
   already give a real curve ($6,337 drawdown, Sharpe 1.76); QQQ's flat-up curve is the F-008
   fast-flip regime artifact. The genuine residual is **intraday / between-snapshot** dips,
   which need **minute bars** (entitled on Alpaca — the next thing to measure) or continuous
   **quotes** (gated, OPRA). The `get_option_quotes()` client is ready for the latter; true
   bid/ask realism still wants it. Net: not a free daily-cadence task as previously claimed —
   it's an intraday-data question. See FINDINGS.md F-007 (c) / F-008.

4. **Cache invalidation (F-005).** Add a logic-version/source-hash component to the
   backtest cache key.

5. **Longer arc — two engines, not a merge.** Per `../OPTIONS_REPOS_ANALYSIS.md`, the
   intended end state keeps options_analyzer as the **edge engine** (regime · dealer ·
   IV-RV · sentiment · defined-risk candidate generation) and, only once the edge
   clears an OOS gate, hands validated candidates to a separate **execution engine**
   (the parked agent / a sibling repo). The work above is what makes "the edge clears
   an OOS gate" a statement we can actually trust.

---

## Architecture verdict — short-DTE defined-risk is a vehicle/edge mismatch (2026-05-31, FINDINGS F-025)

The integrity work (F-001–F-013) was meant to make "does the edge clear an OOS gate?" a trustworthy
statement. It now is — and the answer for the **0–14 DTE defined-risk spread architecture is NO**, on
the clean data, for every edge family tested (directional F-019/F-023, sentiment F-021, vol-premium
F-024, bias F-017, butterfly F-013).

This is **structural, not a bug**: short-DTE multi-leg defined-risk spreads (a) pay the bid/ask twice
on proportionally wide legs, (b) cap the edge (buy the wing) while keeping the tail, (c) are governed
by path/gamma/theta so a sign-only IC can't pay, and (d) collect premium below the transaction-cost
floor. The signal-research layer found a real phenomenon (index mean-reversion, IC ~0.16); the
execution layer cannot monetize it here.

**Course change.** The "two engines, not a merge" plan above still holds, but the EDGE-ENGINE's
output should no longer assume the short-DTE defined-risk vehicle. Two avenues, in priority order:
1. **Change the vehicle (recommended):** express the validated index mean-reversion signal in a
   **delta-1 / underlying or longer-dated higher-delta** structure where cost/path don't swamp the
   edge. Open experiment: re-express `conditioned_reversal` and test that the IC monetizes.
2. **Buy execution:** OPRA-tight quotes + OI/greeks could tip the marginal put-side VRP positive — a
   spend decision with modest upside.

The reusable assets that survive the verdict: the trustworthy backtester + invariant tests, the
IC-first two-layer research method (signal IC on cheap data → execution test on scarce data), and the
tail-aware evaluation (CVaR/Calmar/skew, robustness/perturbation harness).
