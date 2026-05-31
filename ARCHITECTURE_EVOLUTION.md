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

### 1c. Emerging principle — perturbation stability as a design constraint

A backtester intended for robustness testing must satisfy: *small, economically-
meaningless input perturbations must not change which trades exist, only their
outcomes.* This is now an explicit design constraint, and it retroactively justifies
1b. It also exposed an infra gap: the result cache keys on request params but not on
backtester logic version (F-005), so it can serve stale results across code changes.

---

## 2. Where this is heading (direction, not yet built)

1. **Perturbation / robustness harness.** Run one strategy across a grid of
   perturbations (fill mode, slippage, entry/exit timing jitter, strike tolerance,
   data provenance, time window) and report the *distribution* of (Sharpe, PF, P&L).
   Robust = tight, positive; fragile/overfit = wide, sign-flipping. This generalizes
   the planned **OOS / walk-forward gate** (Step 2 of the synthesis plan) into one
   axis of a broader sensitivity framework.

2. **Concurrency / return-series model (F-006).** Decide how overlapping positions
   aggregate: mark-to-market portfolio equity curve, concurrency cap, or
   calendar-resampled returns — so Sharpe/PF stop treating correlated trades as
   independent.

3. **True bid/ask for 2025+ (backlog #2).** Wire Alpaca's options **quotes** endpoint
   so the recent era has real NBBO spreads, giving the provenance perturbation axis a
   true-spread leg instead of close±slippage.

4. **Cache invalidation (F-005).** Add a logic-version/source-hash component to the
   backtest cache key.

5. **Longer arc — two engines, not a merge.** Per `../OPTIONS_REPOS_ANALYSIS.md`, the
   intended end state keeps options_analyzer as the **edge engine** (regime · dealer ·
   IV-RV · sentiment · defined-risk candidate generation) and, only once the edge
   clears an OOS gate, hands validated candidates to a separate **execution engine**
   (the parked agent / a sibling repo). The work above is what makes "the edge clears
   an OOS gate" a statement we can actually trust.
