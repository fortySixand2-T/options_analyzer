# Paper Plan — "Signal alpha is not execution alpha"

> Persistent reference for turning the F-001…F-025 findings into a paper. Created 2026-05-31.
> Companion to FINDINGS.md (the results ledger / provenance trail) and ARCHITECTURE_EVOLUTION.md.

## Thesis (one sentence)
A real, IC-validated directional signal can fail entirely when expressed through the wrong option
vehicle. We give an **information-coefficient-first, two-layer framework** that separates *signal
alpha* (does a feature predict the underlying?) from *execution alpha* (can a given vehicle harvest
it net of costs?), and show — with mechanism — that short-dated defined-risk option spreads cannot
monetize a signal that a delta-1 vehicle can.

## Contributions (what a reviewer rewards)
1. **Method** — IC-first, two-layer evaluation: validate signal IC on the *underlying* (cheap, deep
   data) before any option backtest; treat signal and execution as independent gates.
2. **Backtester-integrity protocol** — the F-001–F-013 bug taxonomy → economic-invariant tests that
   catch phantom edges (look-ahead, coupled-entry/exit path-dependence, cache staleness, P&L sign
   errors, mixed-expiry legs, mid-vs-bid/ask fills).
3. **Empirical, with mechanism** — a regime-conditional index mean-reversion signal (rank IC
   0.10–0.16, p<0.001, 7 ETFs) does NOT transmit through 0–14 DTE defined-risk spreads (any
   DTE/ITM/cadence; gating *hurts*), and short-DTE index VRP sits below the transaction-cost floor.
   The capstone (vehicle-B) shows the SAME signal monetizes in a delta-1 / longer-dated vehicle →
   *the vehicle, not the signal, is decisive.*

## Completing experiment — "vehicle B" (DONE, F-026)
Result (script `scripts/vehicle_b_delta1.py`): the capstone is *subtler than a clean win*, and that
is the paper's strongest point. (a) The signal **generalizes out-of-period** — IC +0.165 @10d
(p<0.001) in 2012-2019, pre-discovery, not a 2020-24 artifact. (b) But it ranks **magnitude within
all-positive outcomes** (laggard fwd +0.72% vs extended +0.18%, *both positive*), so there is no
shortable side: the balanced cross-sectional L/S is Sharpe −0.38, i.e. **no market-neutral alpha**.
(c) It monetizes only as a **modest long-only timing tilt** in delta-1 (SPY +0.89% vs +0.53%/trade,
Sharpe 0.96 vs 0.86) — the vehicle the spread couldn't express.

**Revised thesis for the paper:** *a real, generalizing, statistically-significant directional IC
can still be economically a long tilt rather than extractable alpha — and the chosen vehicle decides
whether even that survives (spreads: no; delta-1 long overlay: modestly yes).* This is a stronger,
more honest contribution than "we found alpha": it quantifies the gap between IC significance and
tradeable alpha along TWO axes (sign-vs-magnitude of the predicted outcome; and execution vehicle).
Also document the methodology guardrail this exposed: sign-based L/S on an imbalanced signal silently
becomes a net-directional bet (we caught and discarded that).

## Section outline
1. Intro — the signal-vs-execution conflation; contributions.
2. Related work — TS-momentum/reversal (Moskowitz-Ooi-Pedersen; Jegadeesh; George-Hwang), VRP
   (Bollerslev-Tauchen-Zhou), option-return literature, backtest overfitting (Bailey/López de Prado).
3. Data — Dolt real quotes 2020-24; integrity caveats up front (indicative vs OPRA, NULL greeks,
   sparse OI) as honest scope.
4. Methods — (a) invariant-guarded backtester; (b) IC engine + strict graduation gate (significance,
   |IC|≥0.03, fold + regime sign-stability); (c) execution-test protocol (the "beats unconditional?"
   alpha-vs-beta test).
5. Results — signal layer (graduating mean-reversion); execution layer (no transmission; VRP below
   cost floor); **vehicle-B capstone** (delta-1 monetizes).
6. Mechanism — the four structural reasons spreads fail (cost-floor / path-dominance; +$172 mid →
   −$518 fills centerpiece).
7. Threats to validity — see below.
8. Conclusion — vehicle matters as much as signal; the framework is the takeaway.

## Figures / tables (each maps to a finding)
- T1: signal IC across 7 ETFs × horizons × regimes (F-022).
- F1: IC decay vs horizon; regime-split IC bars.
- T2: execution sweep gated vs unconditional, DTE × ITM (F-023) — "gating hurts".
- F2: cost-floor chart — put-spread P&L mid vs bid/ask (F-024). Most persuasive single figure.
- T3: backtester-pitfall taxonomy with phantom-edge magnitudes (F-002 sign flip; F-004 51%→100% WR;
  F-008 impossible premiums).
- F3 (capstone): vehicle-B equity curve / Sharpe — same signal, delta-1 vs spread (F-026).

## Threats to validity (foreground these)
Indicative (not OPRA) quotes; NULL greeks → IV-approx strike selection; sparse OI → pin strategies
untestable; 2020-24 sample (COVID + 2022 bear); SPY/index-centric (single-name reversal failed);
overlapping-trade autocorrelation; multiple testing in the signal grid (mitigated: 7/7 underlyings
agree at p<0.001).

## Reproducibility
Public harness: `signal_ic_sweep.py`, `conditioned_signal_test.py`, `signal_vehicle_sweep.py`,
`vrp_seller_sweep.py`, `vehicle_b_delta1.py`; deterministic synthetic tests (`tests/test_signal_lib.py`,
`test_vehicle_knobs.py`); append-only FINDINGS ledger as provenance. Freeze a data snapshot + pin
seeds; ship a repro script.

## Venue & honest appraisal
Targets: arXiv q-fin.TR/PM; *Journal of Financial Data Science*; *Journal of Trading*; a workshop.
A solid methods/empirical paper — NOT a top-tier claim of new alpha. Novelty = the framework + the
honest execution-floor analysis, not a new anomaly. Reviewers will push on data quality (OPRA),
generality beyond SPY/2020-24, and whether IC-first is "just" factor practice applied to options
(defense: the explicit signal/execution separation + the cost-floor mechanism).

## Working process
Freeze data snapshot → run vehicle-B → assemble results ledger from FINDINGS → generate figures from
the existing scripts → write methods from the actual code → lead with mechanism, not P&L.
