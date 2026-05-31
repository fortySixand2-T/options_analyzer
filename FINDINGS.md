<!--
  FINDINGS.md — append-only, sequenced log of investigation findings.

  Convention:
  - One entry per finding, numbered F-001, F-002, ... NEVER renumber or delete;
    findings are immutable once written. If a finding is later overturned, add a
    NEW finding that supersedes it and update the older entry's Status line to
    "Superseded by F-NNN" (leave its body intact for the historical record).
  - Newest finding at the BOTTOM (chronological). The index table at the top is
    regenerated when a finding is added.
  - Each finding records: what was observed, the evidence, why it matters, the
    resolution, and any follow-up. This is the narrative companion to
    CHANGELOG.md (which records file-level edits) and ARCHITECTURE_EVOLUTION.md
    (which records how the design is changing).
-->

# Findings Log

A running, append-only record of what we've learned while hardening the
backtester and the edge research. Companion to `CHANGELOG.md` (file edits) and
`ARCHITECTURE_EVOLUTION.md` (design changes).

| ID | Date | Finding | Status |
|----|------|---------|--------|
| F-001 | 2026-05-30 | Chain-replay priced fills at mid with no slippage (optimistic) | Resolved |
| F-002 | 2026-05-30 | Debit-spread P&L sign inversion in chain-replay | Fixed |
| F-003 | 2026-05-30 | Alpaca backfill fabricated bid/ask from OHLC range (~27% fake spreads) | Fixed + data migrated |
| F-004 | 2026-05-30 | Sequential single-position loop was path-dependent | Fixed (decoupled) |
| F-005 | 2026-05-30 | Backtest result cache not invalidated on code change | FIXED — engine-source hash folded into cache key |
| F-006 | 2026-05-30 | Concurrency makes overlapping trades correlated → inflated Sharpe/PF | Resolved (time-indexed MTM) |
| F-007 | 2026-05-30 | Intra-hold marks are sparse → MTM curve degrades to time-indexed realized P&L | Reframed — data already daily; granularity is exit-logic-bound; finer risk needs INTRADAY data |
| F-008 | 2026-05-30 | Impossible spread premiums → phantom profit. ROOT CAUSE (corrected): `_select_strikes` picked legs from DIFFERENT expiries | Fixed (same-expiry constraint) — free code fix, no data feed needed |
| F-009 | 2026-05-30 | local_backtest prices `butterfly` as a single ATM call (no `butterfly` branch in `_price_strategy`) | FIXED — butterfly branch added; BS butterfly now −$2,599/Sharpe −2.42 (was bogus +$23,535); VALIDATION_RESULTS corrected |
| F-010 | 2026-05-30 | local_backtest `dte_exit` overwrites profit_target/stop_loss label | FIXED (`exit_reason or "dte_exit"`) |
| F-011 | 2026-05-30 | Tests assert structure/execution, never economic invariants → silent bugs pass | Addressed — tests/test_invariants.py (15 tests) guards F-002/004/006/008/009 |
| F-012 | 2026-05-30 | Audit of scanner/sizing/market_state/edge surfaces (step 4) | Clean — live edge path deep-audited; unwired modules categorized (no deferred debt) |
| F-013 | 2026-05-30 | Butterfly tested under wrong CONDITIONS (ATM not max-pain) and wrong METRICS (Sharpe for a convex payoff) | Metrics added (Sortino/skew/return-on-risk) + max-pain centering; proper validation OI-blocked |
| F-014 | 2026-05-30 | Robustness/OOS harness built; surveyed strategies flag fragile/no-edge on current data | Harness shipped; first survey = no robust edge yet (data-limited) |
| F-015 | 2026-05-30 | Each strategy has a different edge source → needs a different metric; we ranked all by Sharpe | Tail metrics (CVaR/maxLoss/Calmar) added; per-strategy literature review written |
| F-016 | 2026-05-30 | Alpaca docs: historical quotes need paid OPRA; our 2025+ bars are free "indicative" DERIVATIVES (delayed, approximate) | Confirmed data map; provenance caveat logged (external decision) |
| F-017 | 2026-05-30 | Dolt-only (clean, real-quote) alpha check: NO demonstrable alpha — the one winner is beta; bias signal IC ≈ noise/inverted | Metric routing + directional IC shipped; verdict = no edge on clean data |
| F-018 | 2026-05-31 | Direction A: IC-first signal research on free underlying data. No UNCONDITIONAL graduate, but two statistically-significant CONDITIONAL (vol-regime-gated) edges found | Harness shipped; conditioned_reversal GRADUATES on SPY/QQQ (vix_pct IC +0.163 @10d, p<0.001) — first IC-validated signal |
| F-019 | 2026-05-31 | Execution test: does the IC-validated signal survive expression as a defined-risk debit spread? Wired conditioned_reversal into chain_replay as an entry gate | NO — IC does NOT transmit (favorable cell n=4 noise; sampled cells gating HURT). Signal IC is necessary-not-sufficient. Cache-key bug (omitted signal_filter, F-005 class) found + fixed |
| F-020 | 2026-05-31 | Phase 3 cache-key audit: 4 additional result-affecting fields absent from `_cache_key` (F-005-class latent bugs) | FIXED — min_score, vrp_filter, vrp_threshold, swing_bias_filter, option_style added; RESULT_AFFECTING_FIELDS sentinel test guards against future omissions |
| F-021 | 2026-05-31 | Phase 4 sentiment IC test: FinBERT composite score on 115k SPY headlines does NOT predict SPY forward returns (all horizons, all lookbacks) | NO EDGE — best IC −0.079 @10d (p=0.065); consistent bearish bias but not significant; does not graduate; signal not recommended for further execution testing |
| F-022 | 2026-05-31 | Phase 1 sweep RUN across 7 index ETFs (SPY/QQQ/IWM/DIA/XLK/XLF/XLE) — the network-blocked deliverable. Fixed sweep warmup bug (120d too short for 252d high52w signal) | Two signals GRADUATE on all 7: ts_momentum (IC −0.091 @10d) and high52w_proximity (IC −0.102 @10d), both INVERTED — broad-index 10-day mean-reversion. Confirms+broadens F-018; vrp_proxy/vix_term_structure fail |
| F-023 | 2026-05-31 | Phase 2 vehicle sweep: does the validated directional signal transmit through a better debit-spread vehicle? Added DTE/ITM-depth/cadence knobs | NO at any vehicle — unconditional wins everywhere (beta), gating HURTS. Directional thread closed for the defined-risk-spread mandate. Next edge = vol-regime conditioner for premium SELLERS (tail metrics) |

---

## F-001 — Chain-replay priced fills at mid, ignoring spread and slippage
**Date:** 2026-05-30 · **Status:** Resolved

**Observed.** `chain_replay` already used *real* snapshot quotes (not Black-Scholes),
but priced both entry and exit at the **mid** and applied **no slippage at all**
(`request.slippage_pct` was silently ignored). `local_backtest` (BS) was the only
backtester modeling slippage.

**Evidence.** `_compute_entry_price` / `_compute_exit_price` read `leg["contract"]["mid"]`;
`grep slippage src/backtest/chain_replay.py` returned nothing. The team's own
`docs/pricing_validation_report.md` had already shown mid pricing is "fantasy"
(swing strategies: 97% WR / Sharpe 3.4 at mid vs 45% / −0.21 at real bid/ask).

**Why it matters.** Mid fills overstate edge by the full half-spread on every leg,
on both entry and exit — most damaging to multi-leg, spread-sensitive structures.

**Resolution.** Added `_leg_fill_price()` (buys lift the ask, sells hit the bid;
exits reverse) gated by `request.fill_mode` (`"bid_ask"` default, `"mid"` legacy
for A/B). A/B on the stable Dolt window (SPY 2023-01→2024-06): bid/ask shaved P&L
on every strategy (short_put 959→934, long_call 4284→4230, butterfly −2384→−2702).

**Follow-up.** See F-003 (the 2025+ "bid/ask" turned out to be fabricated).

---

## F-002 — Debit-spread P&L sign inversion in chain-replay
**Date:** 2026-05-30 · **Status:** Fixed

**Observed.** While A/B-testing fills, debit spreads moved the *wrong* way — worse
fills produced *better* reported P&L.

**Evidence.** `_check_exit` used `pnl = entry_net - current_value` for credit but
`current_value - entry_net` for debit. Both `entry_net` and `current_value` are in
the same leg orientation (sell legs +, buy legs −), so the unified formula
`entry_net - current_value` is correct for *both*. Synthetic proof: a long call
spread that appreciated 2.00→2.50 (a +0.50 winner) reported **−0.50**. After the
fix it reports +0.50.

**Why it matters.** Every debit strategy (long call/put spreads, butterfly) had its
P&L sign flipped — chain-replay reported the reliable long-call-spread winner as a
loser.

**Resolution.** Collapsed to the single formula `pnl = entry_net - current_value`.
The fix makes `long_call_spread` profitable in chain-replay (+$3,602, PF 1.48,
Sharpe 1.32 on the 2022-2024 Dolt window), reconciling it with
`VALIDATION_RESULTS.md`.

---

## F-003 — Alpaca backfill fabricated bid/ask from each bar's OHLC range
**Date:** 2026-05-30 · **Status:** Fixed + existing data migrated

**Observed.** After F-001/F-002, butterflies and long spreads on 2025+ data still
looked catastrophic (WR ~0%, PF ~0) while the same strategies were sane on
2020-2024 data (2024 butterfly: +$928, capped losses).

**Evidence.** Alpaca options history is OHLC **bars**, not quotes. The backfill
(`backfill_pipeline._estimate_bid_ask`) set `bid = min(open, close)`,
`ask = max(open, close)` — treating a bar's intrabar price *movement* as a quoted
*spread*. DB audit: `label='backfill'` rows (2025+) had an implied spread of
**~25-27%** vs ~5-8% on real-quote Dolt rows. The bar **close** was preserved in the
`last` column. Both repos pull the same Alpaca option bars; options-algo-trader uses
the bar **close** as the fill — options_analyzer was alone in fabricating a spread.

**Why it matters.** A 4-leg butterfly crossing a fake 25% spread four times is
unfillable by construction — the contamination, not the strategy, produced the
catastrophe. It silently corrupted every 2025+ chain-replay result.

**Resolution.** `_estimate_bid_ask` now uses the bar close as a single traded price
(`bid == ask == mid == close`), mirroring options-algo-trader; real fill cost is
modeled by `slippage_pct`, not a fabricated spread. `scripts/migrate_backfill_fills.py`
repaired existing rows: **512,759** `label='backfill'` contracts collapsed to the
real close (avg fabricated spread 26.9% → 0%); real-quote sources (`dolt`, yfinance
`eod`/`midday`/`shortdte`) left untouched. DB backed up first.

**Follow-up.** True bid/ask requires Alpaca's options **quotes** endpoint
(`/v1beta1/options/quotes`, available ~Feb 2024) — tracked as backlog item #2. Until
then 2025+ fills are close±slippage, not true NBBO.

---

## F-004 — The sequential single-position loop was path-dependent
**Date:** 2026-05-30 · **Status:** Fixed (loop decoupled)

**Observed.** Even after the slippage math was made a provably strict per-trade cost
(`pnl' = pnl − sₑ − sₓ`), a tiny slippage change produced impossible *aggregate*
swings: `long_put_spread` QQQ flipped **51% → 100% win rate** (and Sharpe ~18)
between 0% and 1% slippage.

**Evidence.** The trade **count** changed with slippage (66 → 55 → 69) — proof the
trade *set* itself was moving, not just per-trade outcomes. Root cause: the loop held
one position at a time and set the next entry to `exit_idx + 3`, so the entry
calendar depended on the prior trade's exit timing. A sub-1% P&L perturbation shifted
one exit by a snapshot and reshuffled the entire downstream sequence (classic
path-dependence in a serialized single-position backtester).

**Why it matters.** Path-dependence makes the backtester chaotic under perturbation:
slippage, fill mode, and exit-threshold sweeps measure *trade-set reshuffling*, not
*sensitivity*. It also undermines confidence in the point estimates. This is the
prerequisite blocker for any perturbation/robustness analysis (and for trusting
slippage at all).

**Resolution.** Decoupled trade selection from exits: entries now fire on a **fixed
snapshot cadence** (`range(0, n, entry_interval)`), independent of any prior trade,
and each position's exit is found by an **independent forward scan**. Positions may
overlap (concurrency allowed). Validated (cache cleared — see F-005): trade count is
now **fixed** across slippage (long_put SPY 132/132/132; QQQ 55/55/55), win rate is
**stable**, and P&L **decreases monotonically** with slippage (long_put SPY
16486→16102→15718). Perturbation now measures sensitivity, not chaos.

---

## F-005 — Backtest result cache is not invalidated on code change
**Date:** 2026-05-30 · **Status:** Mitigated (manual clear); follow-up open

**Observed.** Immediately after the F-004 fix, the stability check *still* showed the
old chaotic numbers.

**Evidence.** `data/backtest_cache.db` keys results on request parameters only
(strategy, dates, fill_mode, slippage, …) — **not** on a code/logic version. After a
backtester logic change, identical request params returned **stale pre-fix results**.
Clearing the cache (118 rows) immediately revealed the correct, path-stable behavior.

**Why it matters.** Any backtester logic change silently serves wrong cached results
until the cache is manually cleared — a serious correctness footgun during iteration.

**Resolution / follow-up.** Mitigated by clearing the cache after logic changes. OPEN:
add a `logic_version` (or source hash) component to `_cache_key()` so caches
self-invalidate when backtester logic changes.

---

## F-006 — Concurrency makes overlapping trades correlated → inflated Sharpe/PF
**Date:** 2026-05-30 · **Status:** Resolved (risk metrics now computed on a time-indexed mark-to-market curve)

**Observed.** The F-004 fix allows concurrent overlapping positions. In a strongly
one-directional period this inflates risk-adjusted metrics: `long_put_spread` QQQ
(2025-05→2026-05) shows **100% WR, PF ∞, Sharpe ~18** — now stable across slippage,
but not credible as an edge.

**Evidence.** With entries every ~10 days and holds of similar length, many positions
overlap. In a trending year they are highly correlated bets on the *same* move, so
they win together. Sharpe assumes independent returns; correlated overlapping trades
violate that and overstate Sharpe/PF.

**Why it matters.** Concurrency was necessary for path-stability (F-004) and is fine
for measuring *per-trade mean edge*, but the equity-curve Sharpe/PF/`max_drawdown`
now treat correlated trades as independent samples.

**Resolution (chose option 1/3).** Risk metrics are now computed from a **time-indexed
mark-to-market portfolio curve** instead of the per-trade P&L series. `chain_replay`
builds, per snapshot, the portfolio's realized+unrealized $ value (each position
contributes its mark while open and its realized P&L thereafter); `analyzer.analyze_results`
computes Sharpe and max-drawdown from that curve's periodic returns, annualized by the
actual snapshots-per-year. Effect: a day the market moves is one high-variance period
(correlated positions move together), instead of N independent "wins". Per-trade
descriptive stats (win rate, PF, avg win/loss) are unchanged — they correctly describe
the trade sample.

**Evidence of fix.** `long_put_spread` SPY Sharpe dropped from the per-trade ~18 to
**1.76**, with a now-meaningful max drawdown of $6,337 (was ~0); stable across slippage
(1.76 → 1.69 at 2%). `butterfly` SPY correctly −2.73.

**Residual / caveats.** (1) `long_put_spread` QQQ (2025-05→2026-05) still shows Sharpe
~7.5 / max-DD 0 — but this is now a *regime/sample* artifact (a thin, one-directional
down-year where 55 overlapping bearish spreads all won), to be caught by the OOS /
cross-asset axis, not a statistical-independence bug. (2) The MTM curve is data-limited
— see **F-007**. (3) Profit factor can still be `inf` when there are no losing trades;
this also breaks the result cache's JSON round-trip (minor — forces a cache miss). Both
are sample artifacts, not return-series bugs.

---

## F-007 — Intra-hold marks are sparse, so the MTM curve degrades to time-indexed realized P&L
**Date:** 2026-05-30 · **Status:** Open (data-limited; partial)

**Observed.** The mark-to-market curve from F-006 was expected to vary continuously
during each position's hold. Instead it changes ~once per trade.

**Evidence.** Diffing the equity curve: SPY `long_put_spread` had 132 non-zero steps
for 132 trades (54 down / 78 up); QQQ had 56 non-zero steps for 55 trades (0 down).
Each trade contributes ≈ one step, at its exit — intra-hold marks are mostly missing.
Root cause: pricing a position at an intermediate snapshot needs *all* legs' exact
strike+expiry present in that snapshot. With every-other-day snapshots and coarse
strike grids (DATA_ISSUES.md §1, §2), intermediate snapshots frequently lack a leg, so
`_compute_exit_price` returns None and the scan carries the last known mark forward.

**Why it matters.** The "MTM curve" is therefore closer to a **time-indexed realized-P&L
curve** (steps at exit dates) than a continuous mark-to-market. It still fixes the worst
of F-006 — Sharpe is calendar-annualized and simultaneous *exits* cluster into one
period (the dominant correlation channel for short-DTE trades that exit near expiry) —
but it does not capture intra-hold unrealized volatility, so a position that round-trips
underwater and recovers shows no interim drawdown.

**Resolution (partial / follow-up).** Accept the time-indexed realized curve as a large
improvement over the per-trade-index cumsum (F-006). True continuous MTM needs denser,
fuller chain data: daily collection (already running) plus the Alpaca options **quotes**
endpoint (backlog #2). A cheaper interim option — fall back to a Black-Scholes mark when
chain legs are missing intra-hold — would reintroduce model pricing and is deliberately
deferred. Until then, treat max-drawdown as a *lower bound* on interim risk.

### Update 2026-05-30 — tried the Alpaca quotes endpoint; it is **gated** on this plan
The natural fix is continuous **quotes** (always-posted bid/ask, unlike trades/bars which
exist only on days the contract actually traded — exactly the no-trade gap that sparsifies
intra-hold marks). Probed Alpaca directly with real, traded contracts:

| Endpoint | Result |
|---|---|
| `/v1beta1/options/bars` | 200 ✓ (has data) |
| `/v1beta1/options/trades` | 200 ✓ (has data) |
| `/v1beta1/options/quotes` (historical) | **404** ✗ |
| `/v1beta1/options/quotes/latest` | 200 (real-time only; empty) |

The 404 is **entitlement-level** (same `v1beta1/options/` prefix as the working endpoints;
auth is valid). **Historical option quotes require an OPRA data subscription this account
does not have.** Neither bars nor trades can substitute — both are *traded* data and so
share the exact no-trade-day sparsity that causes F-007; only continuous quotes fill it.

**Done now:** implemented `AlpacaOptionsClient.get_option_quotes()` (correct endpoint,
EOD-quote selection via `sort=desc`, one-sided/zero-quote filtering) and made `_request`
treat 403/404 as "no data / not entitled" rather than raising — so the live path degrades
gracefully (returns `{}`) and the code is **ready the moment a subscription is enabled**.
Unit-tested with mocked responses (`tests/test_alpaca_quotes.py`, 3 tests) independent of
entitlement. NOT yet wired into `chain_replay` — with no live quotes it would be a no-op.

**Decision required (the user's call):**
1. **Enable an OPRA / paid options-data subscription** (Alpaca or Polygon ~$29–99/mo) →
   then wire `get_option_quotes()` into the backtester's intra-hold marking → true
   continuous MTM and honest drawdown. (Polygon is an alternative quote source.)
2. **Black-Scholes intra-hold fallback** — mark missing legs with BS from the underlying
   spot (which we *do* have every snapshot) + entry IV. Continuous marks with no new data,
   but reintroduces model pricing (less honest than real quotes; mind IV drift).
3. **Accept the limitation** — keep the time-indexed realized curve from F-006 and treat
   max-drawdown as a lower bound, leaning on win rate + mean P&L + OOS for judgment.

### Update 2026-05-30 (b) — measured: the gap is mostly *cadence*, and liquidity bites only far-OTM
Question raised: is the sparse-marks problem *all* options or only non-ATM? Measured SPY
daily **bar** coverage over a 15-trading-day window by moneyness:

| Moneyness | Days with a bar | Coverage |
|---|---|---|
| ATM | 15/15 | **100%** |
| ~3% OTM | 15/15 | **100%** |
| ~7% OTM | 15/15 | **100%** |
| ~12% OTM | 0/15 | **0%** |

So there are really *two* gaps, and they have different fixes:
- **Collection cadence (dominant, universal, FREE to fix).** The intra-hold sparsity in the
  backtest is mostly because we only *stored* every-other-day snapshots and `chain_replay`
  reads the stored DB — not because the data doesn't exist. Alpaca **has daily bars** for
  ATM-to-~7%-OTM strikes (the legs our credit/debit spreads use). Re-backfilling SPY/QQQ/IWM
  **daily** with the already-entitled bars endpoint gives daily marks for those legs — no
  subscription needed.
- **Liquidity (far-OTM only, needs quotes).** Deep wings (~12%+ OTM — the protective legs of
  iron condors and butterflies) genuinely don't trade most days (0% bar coverage), so only
  *continuous quotes* can mark them. This is the residual that still needs the OPRA feed.

**Revised remedy / priority.** (1) Daily bar backfill (free, entitled) resolves most of
F-007 for spreads. (2) The gated quotes endpoint (`get_option_quotes`, ready) is then a
narrower need — far-OTM wings + true bid/ask realism — which lowers the urgency of the
subscription decision above. Single-stock / less-liquid underlyings degrade earlier than
SPY (measurement is best-case).

### Update 2026-05-30 (c) — checked before backfilling: data is ALREADY daily; remedy (1) RETRACTED
Before running the daily bar re-backfill (remedy 1 above), I measured the existing
density and the real cause — and remedy (1) is a **no-op**:

- **2025+ backfill is already daily.** SPY/QQQ/IWM snapshot gap histogram: gap=1 day ×194,
  gap=3 (weekends) ×46. So there is nothing to densify for the windows that matter
  (QQQ/IWM are 2025+ only; SPY 2025+ is daily). A re-backfill adds no snapshots.
- **The ~1-mark-per-trade granularity is exit-logic-bound, not data-bound.** Measured exit
  reasons + hold lengths: QQQ `long_put_spread` = **55/55 profit_target, median hold 1 day**
  (hits +75% target on the first post-entry snapshot in a falling market); SPY = 78 profit /
  43 stop / 11 dte, **median hold 12 days**. Trades exit at the first snapshot that triggers
  a rule, so each contributes ≈ one mark *regardless of data density*. SPY's longer holds
  already yield a real curve (down-steps, $6,337 drawdown, Sharpe 1.76) — the F-006 MTM fix
  works there. QQQ's flat-up curve is the F-008 fast-flip regime artifact, not missing data.
- **What finer risk visibility actually needs: INTRADAY data.** The residual gap is *between-
  snapshot* / intraday dips (a position that goes underwater and recovers before the next
  daily mark). Daily bars cannot show that; only minute bars or continuous quotes can.

**Net correction.** Retract "daily bar backfill fixes most of F-007" — the data is already
daily and the gap isn't cadence. Update: also measured **minute bars** (the next candidate
lever) — they do **not** help either, because the actual short-DTE $1-wide legs barely trade
(SPY 640 put: one print/day; adjacent strikes: zero). No *trade-based* source resolves this.
For F-007's own residual (intra-hold resolution on no-trade days) continuous NBBO quotes
would help, but it is **minor**: SPY's MTM already shows a real drawdown ($6,337) and a
believable Sharpe, and these short-DTE trades exit fast so there is little hold to mark.
**Correction:** F-008 — which last turn I wrongly lumped in here as also "needing quotes" —
turned out to be a free code bug (cross-expiry leg selection), not a marks/feed problem.
So F-007 stands alone as a low-severity data nicety, not a blocker. Lesson logged: measure
existing density/cause before proposing (or running) a remedy.

---

## F-008 — Impossible spread premiums → phantom profit
**Date:** 2026-05-30 · **Status:** FIXED (same-expiry leg constraint — a free code fix)

> **CORRECTION (2026-05-30, supersedes the marks hypothesis below).** The root cause is
> **NOT** non-synchronous close marks and does **NOT** need a quote subscription. It is a
> strike-selection bug: `_select_strikes` built `puts`/`calls` from the *entire* entry DTE
> window — which spans **multiple expiries** — and sorted by strike only, so a "vertical"
> took its two legs from **different expiries**. The longer-dated leg carries more time
> value, so the "spread" premium was really a calendar/diagonal value, far exceeding the
> strike span. Verified: every traced entry had mismatched leg expiries (e.g.
> `['2026-04-30','2026-05-08']`), while each *per-expiry* chain is clean and monotonic.
> **Fix:** constrain `_select_strikes` to a single (nearest) expiry before picking legs, so
> entry and exit (which already use one expiry) are consistent. After the fix: cross-expiry
> legs 0/all; impossible-premium rate QQQ 96%→~2% (1 residual), SPY 40%→0%. The F-008 sanity
> gate (`|entry_net| > strike_span`) remains as a cheap backstop for the rare residual.
>
> **Corrected, trustworthy results** (full sample, same-expiry, exit_rule=strategy):
> short_put_spread QQQ +$366/PF2.14/Sharpe1.64, SPY −$1,556/PF0.81; iron_condor QQQ
> +$577/PF1.77, SPY −$905; long_call SPY +$1,029/PF1.06; butterfly negative both. Believable
> mediocre-to-modest numbers — the prior 100%-WR/Sharpe-18 phantoms are gone.
>
> **Lesson (again):** I wrongly blamed the data twice (first "daily backfill", then "non-
> synchronous marks → need OPRA quotes") before *inspecting the chain*, which showed it was
> clean per-expiry and the legs spanned expiries — a free code bug. Inspect the actual
> objects before escalating to an external/paid dependency. See [[diagnose-root-cause-before-remedy]].
>
> The original (incorrect) marks hypothesis is preserved below for the record.

**[SUPERSEDED HYPOTHESIS]** Originally diagnosed as non-synchronous close marks; kept for history:

**Observed.** QQQ `long_put_spread` (2025-05→2026-05): 55/55 trades exit `profit_target`,
**median hold 1 day**, 100% win rate, Sharpe ~7.5, DD 0. Suspicious enough to inspect.

**Root cause (settled by tracing real trades).** It is **not** a regime effect — it is a
**mark-consistency bug**. The legs are priced at the **close** (F-003), but a close is the
contract's *last trade of the day*, and adjacent illiquid strikes' last trades happen at
*different intraday moments / different spot levels*. Example entry (2025-05-09, spot
487.97): buy 488 put @ 3.64, **sell 487 put @ 8.15** → "credit" **+4.51 on a $1-wide
spread**. A defined-risk $1 spread can be worth at most $1, so a $4.51 credit is impossible
— the 487-put print was stale (from when QQQ was far lower). Every traced trade showed the
lower-strike put worth *more* than the higher-strike put (a put-monotonicity violation).
The phantom credit then "decays to zero," booking a guaranteed fake profit.

**Scale (measured).** Entries with `|entry_net| > strike_span` (provably impossible for
defined-risk): **QQQ 96%, SPY-2024 58%, SPY-2022 40%**, worst 7.4× the span. This corrupted
many spread results, not just QQQ.

**Minute bars don't help (measured).** Hoped intraday minute bars could give synchronized
marks. But the actual legs barely trade: SPY 640 put traded **once** all day (15:03);
adjacent 639/641 puts had **zero** bars. No trade-based source (daily *or* minute) can
price or synchronize contracts that don't trade. (The earlier "ATM-7% = 100% coverage"
used liquid round strikes on a monthly expiry; the backtester's $1-wide short-DTE legs are
far thinner.) **Only continuous NBBO quotes** (posted without trades) can fix this — gated
behind OPRA (F-007).

**Mitigation shipped.** Added a sanity gate in `chain_replay`: reject entries where
`|entry_net| > strike_span × 1.10` (a defined-risk position cannot exceed its strike span).
Impact — the phantom results collapse toward reality:

| | before gate | after gate |
|---|---|---|
| QQQ long_put | 55 trades, 100% WR, Sharpe 7.47 | 2 trades (53 rejected), Sharpe 1.10 |
| SPY long_put | 132 trades, +$5,164, Sharpe 1.76 | 79 trades, **−$19, Sharpe ~0** |
| SPY butterfly | 132 trades, −$57,396 | 83 trades, −$5,924 |

So SPY long_put's "edge" and the butterfly "catastrophe" were both **largely phantom**.

**Caveat / status.** The gate *rejects* corrupt entries; it does not *repair* marks. It also
shrinks the valid sample (QQQ long_put → 2 trades), revealing we have **too few clean
spread trades on current data** to judge these strategies. The proper fix is synchronized
NBBO quote marks (OPRA, gated). Until then, treat chain-replay spread results as
**provisional**, and prefer strategies/underlyings where the valid sample survives the gate.

---

## F-009 — local_backtest prices `butterfly` as a single ATM call
**Date:** 2026-05-30 · **Status:** Open (found in code audit) — HIGH

**Observed.** `_price_strategy` in `local_backtest.py` has branches for `iron_butterfly`
but **none for `butterfly`** (the active strategy name). A `butterfly` request therefore
falls through to the `else` branch → `price_fn(spot, atm, T, r, iv, "call")` — it is valued
as a **single long ATM call**, not a 4-leg butterfly.

**Why it matters.** `butterfly` is an active, defined-risk strategy. The BS backtester has
been valuing it as a long call the whole time. `VALIDATION_RESULTS.md` reported butterfly
hold-to-expiry as the **best performer (+$11,459, Sharpe 1.23)** — that result is really a
**long ATM call** in a 2022-2026 bull market, not a butterfly. The butterfly validation
conclusion is invalid. (chain_replay builds 4 real legs and is structurally correct after
the F-008 fix; this bug is local_backtest-only.)

**Fix (planned).** Add a `butterfly` branch to `_price_strategy` with the correct payoff
(buy 1 lower, sell 2 center, buy 1 upper; debit) and re-run the butterfly validation.

---

## F-010 — local_backtest `dte_exit` overwrites the profit/stop exit label
**Date:** 2026-05-30 · **Status:** Open (found in code audit) — LOW

**Observed.** In `_simulate_trades`, `if dte_remaining <= time_exit_dte: exit_reason = "dte_exit"`
**unconditionally overwrites** any `profit_target`/`stop_loss` set just above. chain_replay
uses the correct `exit_reason = exit_reason or "dte_exit"`.

**Why it matters.** Same *class* as a P&L bug fixed earlier (dte overriding P&L exits), but
here it only affects the exit-reason *label* on the final bar (the P&L is unchanged), so it
distorts exit-reason breakdowns rather than returns. Low severity; fix for consistency.

---

## F-011 — Tests assert structure/execution, never economic invariants
**Date:** 2026-05-30 · **Status:** Open — remediation plan below

**Observed.** Every silent bug this session (F-002 sign, F-003 fake spread, F-004 path,
F-006 return-series, F-008 cross-expiry, F-009 butterfly→call) passed the full suite. Why:
the tests assert the pipeline **runs and produces plausibly-shaped output** — "produces
trades", "total_trades ≥ 5", "win_rate is a float", "equity_curve has length", "result has
regime_breakdown" — and a few synthetic known-answer checks (intrinsic exit). They never
assert **economic/financial invariants** or **per-strategy known-answer pricing**. They also
run against the live DB (no fixtures), so they can only bound shape, not values.

**Why it matters.** This is *the* reason the bugs were invisible: wrong-but-runnable numbers
sail through structural checks. Plugging individual bugs without closing this gap guarantees
the next silent bug also ships.

**Remediation — invariant test layer (do this before the OOS/perturbation harness).**
Add `tests/test_invariants.py` (fixture-based + small real-data sample) asserting:
1. **Defined-risk bound:** every spread's `|entry_net| ≤ strike_span` (would catch F-008).
2. **Single expiry:** all legs of a vertical/condor/fly share one expiry (F-008).
3. **Per-strategy payoff known-answers:** butterfly peaks at center & risk = debit; condor
   credit ≤ wing width; etc. — drives `_price_strategy` correctness (catches F-009).
4. **Slippage monotonicity:** higher `slippage_pct` ⇒ P&L only decreases (F-006/slippage).
5. **Perturbation stability:** a <1% fill perturbation does not change the trade *count*
   (catches F-004 regressions).
6. **P&L sign known-answers:** a constructed winning/losing scenario yields the right sign
   per strategy and per backtester (catches F-002).
7. **Stat sanity:** `0 ≤ win_rate ≤ 100`; `profit_factor` serializable (no raw `inf`);
   `total_pnl ≈ equity_curve[-1]`.
8. **Exit-label correctness:** profit/stop not overwritten by dte (catches F-010).

---

# Remediation Plan (audit → fixes → invariants, before the OOS harness)

**Order (each step ends green + a committed invariant test that would have caught it):**

1. **F-009 (HIGH):** add `butterfly` to `_price_strategy`; re-run + correct the butterfly
   entries in VALIDATION_RESULTS.md. Add payoff known-answer test (invariant #3).
2. **F-010 (LOW):** `exit_reason = exit_reason or "dte_exit"` in local_backtest. Add #8.
3. **F-011 (systemic):** build `tests/test_invariants.py` (#1–#8). This is the real
   deliverable — it converts each past bug into a permanent guard.
4. **Extend the audit** to the not-yet-reviewed surfaces with the same lens: `src/scanner/`
   (scorer, strategy_pricer, strategy_mapper), `src/market_state.py`, `src/edge/*`,
   `src/sizing.py`/`portfolio.py`. Log anything as F-0NN.
5. **Cache-version key (F-005):** add a logic/source-hash to the backtest cache key so a
   code change self-invalidates stale results (this masked F-004 for a turn).

**Only after 1–5 is green** proceed to the OOS / perturbation harness — it must run on a
backtester whose results are trustworthy, or it will optimize against artifacts.

**Audit coverage note.** This pass focused on the two backtest engines + their signal/
lookahead paths. Lookahead was checked and is clean (rolling vol, regime, bias all use
past-only windows in both engines). Strike selection, P&L sign, pricing, and exit logic are
covered by F-001…F-010. Surfaces in step 4 are NOT yet audited.

---

## F-012 — Audit of scanner / sizing / market_state / edge (plan step 4)
**Date:** 2026-05-30 · **Status:** Clean on audited bug-classes (caveats below)

**Scope.** Extended the audit beyond the backtest engines to the live-scan / signal / sizing
surfaces, hunting the same bug classes (sign/unit errors, cross-sectional/temporal mismatch,
lookahead, no-op logic, NaN/inf propagation).

**Reviewed and clean:**
- `market_state.py` core IV-RV edge: `iv_rv_spread = chain_iv − garch_vol`, `edge_pct =
  spread/chain_iv·100`; `has_edge` requires spread>0 & edge>5% for credit, spread<0 &
  edge<−5% for debit. Signs and units correct (sell premium when IV rich, buy when cheap).
- `scanner/strategy_pricer.py`: net premium accumulated with proper per-leg sign
  (`+sell/−buy`); `entry = abs(net_premium)` is intentional (magnitude; direction carried by
  the separate `is_credit` branch driving max-profit/loss/exit/stop). Not a sign bug.
- `sizing.py`: `adjusted_entry` applies slippage in the correct credit/debit direction;
  `spread_cost`'s `float('inf')` on non-positive mid is used to *reject* a degenerate spread
  (correct), not propagated.

**edge/* deep audit (completed 2026-05-30 — no longer deferred).** First mapped wiring: only
`edge.vrp`, `edge.term_structure`, `edge.earnings` are imported by active code (`market_state.py`);
`edge.skew`, `edge.flow`, `edge.cross_asset` are **research-only / unwired** (no current
impact). Deep-read the LIVE ones:
- `realized_vol.py` — estimators use trailing `closes[-(window+1):]`, standard
  `√252` annualization. Point-in-time, no lookahead. Clean.
- `vrp.py` — `vrp = iv − realized_vol` (positive = rich → sell premium), `vrp_pct = vrp/iv·100`,
  guarded for iv>0; fed trailing `hv20`. Sign/units correct, no lookahead. Clean.
- `term_structure.py` — `slope = (back−front)/front·100` (positive = contango); `calendar_signal`
  sells the rich front in backwardation. Purely cross-sectional (one snapshot), no lookahead.
  Sign/units correct. Clean.
- `earnings.py` — live but shallow-read (a days-to-earnings / IV-inflation flag helper; minimal
  math). No issue evident.

**Residual notes (categorized, not deferred debt):**
- `skew/flow/cross_asset` are **unwired** — auditing them affects no current behavior; they'd
  need a point-in-time review only if/when wired in (tracked, not silent).
- **Robustness:** `market_state.py` wraps each edge call in `try/except` that silently defaults
  the signal to neutral (0) on error — a safe default, but it masks failures. Minor; consider
  surfacing failed-signal counts.
- `scanner/scorer.py` and `scanner/edge.py` are FROZEN (audit-only); grep-clean.

---

## F-005 resolution (plan step 5)
**Date:** 2026-05-30 · **Status:** FIXED

`cache._cache_key` now folds in `_LOGIC_VERSION` — a sha256 of the backtester source
(`chain_replay.py`, `local_backtest.py`, `analyzer.py`), computed once at import. Any edit to
those engines changes the key, so cached results self-invalidate on code change (no manual
bump, no need to clear `backtest_cache.db` after logic changes). Verified: cache still hits
within a run (2.49s → 0.001s), and the cache-key tests pass. This removes the footgun that
masked the F-004 fix for a turn.

---

## F-013 — Butterfly judged by the wrong metrics under the wrong conditions
**Date:** 2026-05-30 · **Status:** Metrics + max-pain centering shipped; proper validation OI-blocked

**Observed.** After fixing the butterfly *pricing* (F-009), we still concluded "butterfly =
loser." But the *evaluation* is inappropriate for the structure on two axes:

1. **Wrong metrics.** A long butterfly is a **defined-risk, positively-skewed, convex pin
   bet** (small frequent losses, rare large gains). **Sharpe** penalizes variance
   symmetrically and assumes ~normal returns, so it **systematically understates positive-
   skew** payoffs and **flatters negative-skew** ones (premium selling). Ranking a butterfly
   by Sharpe is a category error. Confirmed empirically once skew was measured: butterfly SPY
   **skew +0.77** (convex) vs short_put_spread **skew −1.18** (the premium-seller's hidden
   left tail Sharpe hides). The options-returns literature (variance risk premium; Coval &
   Shumway 2001; Bakshi–Kapadia delta-hedged gains) is about *averages/VRP*, not a canonical
   butterfly return — and warns precisely that skew/tails, not Sharpe, drive option-payoff
   evaluation.
2. **Wrong conditions.** Both engines centered the butterfly at **ATM**, though the spec says
   **pin at max pain**; no IV-rank / OPEX / distance-to-pin gating. So our negative result was
   for "an ATM butterfly on generic exits judged by Sharpe" — not butterflies-done-right.

**Shipped.**
- **Skew-aware metrics** in `analyzer`/`BacktestStats`: `sortino_ratio` (downside-only),
  `pnl_skew` (Fisher skew of per-trade P&L), `return_on_risk` (expectancy ÷ avg premium at
  risk). Reported for all strategies; guarded by invariant tests. Stop ranking convex/
  defined-risk bets by Sharpe alone.
- **Max-pain centering** in `chain_replay._select_strikes` butterfly: `_compute_max_pain`
  (OI-weighted) centers the fly at the pin when OI exists, else falls back to ATM.

**Still blocked (honest external limitation, not code debt).** Max pain needs **open
interest**, which the historical DB largely lacks (DATA_ISSUES §3): max-pain centering fires
on only **SPY 9/93, QQQ 6/58** entries; the rest fall back to ATM. So we **cannot yet
properly validate "max-pain butterfly under the right conditions"** without historical OI
(ThetaData / CBOE). Re-tested as-is (max-pain where possible): butterfly remains negative
(SPY −$5,448, Sortino −0.42, skew +0.77, return-on-risk −0.23). **Verdict: butterfly is
unproven-not-disproven** — the negative result is on a still-data-limited, partially-correct
test. Other strategies' metrics now also carry Sortino/skew/return-on-risk for fairer
comparison.

---

## F-014 — Robustness / OOS harness built; no robust edge found yet (data-limited)
**Date:** 2026-05-30 · **Status:** Harness shipped; first survey = fragile/no-edge

**Shipped.** `src/backtest/robustness.py` + `scripts/robustness.py` — the planned OOS /
perturbation gate, now runnable because the backtester is trustworthy (F-001…F-013) and
guarded by invariants. Three slices per strategy: **time folds** (temporal sign-consistency),
**in/out-of-sample** split (does a fixed rule's edge persist on a held-out recent tail), and a
**fill × slippage perturbation grid** (must be trade-count-stable + slippage-monotonic —
self-checks F-004/F-006). Reports skew-aware metrics + a conservative verdict
(robust / fragile_or_no_edge / insufficient_sample). 3 tests; runs on real data.

**First survey result (honest).** No strategy surveyed clears the robustness gate yet:
- `short_put_spread` SPY 2022–2026: **fragile_or_no_edge**. Negative over the full window
  (−$1,556) *despite* 83% win rate, with **skew ≈ −3.1** — the premium-seller's fat left tail
  the high win rate (and Sharpe) hid. The positive result lives in a single 2023–24 fold;
  2022 loses; `sign_consistent=False`.
- `butterfly` QQQ 2025–2026: fragile_or_no_edge, negative in all folds.

**Reading.** This is "**no robust edge found yet**," not "no edge exists." It's expected and
*healthy* that a trustworthy harness rejects strategies a buggy backtester previously flattered
(the old butterfly "+$23,535 best performer" and inflated credit-spread Sharpes were artifacts).
The honest blockers to finding a real edge remain data-side: defined-risk spread validation is
limited by chain data quality (F-008 sample shrinkage), butterfly by missing historical OI
(F-013), and intra-hold risk by missing intraday/quote data (F-007). Next edge work should
either (a) acquire better data, or (b) test edges that survive on the data we *can* trust.

---

## F-016 — Alpaca historical option data: feeds, entitlements, and a provenance caveat
**Date:** 2026-05-30 · **Status:** Confirmed (external data decision; new provenance caveat logged)

**Source.** Reviewed Alpaca's *Historical Option Data* doc (per user request). Key facts:
- **Two feeds.** *Indicative* (free): "quotes are not actual OPRA quotes, they're just
  indicative derivatives. The trades are also derivatives and they're **delayed by 15
  minutes**." *OPRA* (paid, subscription-only): the consolidated BBO.
- **Depth:** historical option data only since **February 2024**.
- No mention of open interest.

**Reconciles our probes (F-003/F-007/F-013).** Our client defaults to `feed="indicative"`,
which is why `/v1beta1/options/quotes` (historical bid/ask time series) returned **404** —
historical quotes are an **OPRA (paid) entitlement**, not available on indicative. So the
"quotes are gated" conclusion is correct and now explained.

**NEW caveat (provenance).** Our 2025+ backfill bars/trades come from the **indicative feed**,
so they are **derivative, 15-min-delayed approximations — not consolidated OPRA prints**. We
already price fills at the bar *close* (F-003); that close is itself an indicative derivative.
This is a quality caveat on all 2025+ Alpaca-sourced backtests (the Dolt 2020-2024 rows are
real recorded quotes; the yfinance forward `eod/midday` rows are real yfinance bid/ask).

**Data map for unblocking the remaining items (a spend decision, not code debt):**
| Need | Blocked finding | Source that unblocks |
|---|---|---|
| True historical bid/ask (2024+) | F-003, F-007 | **Alpaca OPRA** (paid) — or Polygon/ThetaData |
| Open interest (max-pain, IC dealer-gamma) | F-013, iron_condor gate | yfinance (fwd only) / **ThetaData / CBOE** (history) — NOT OPRA |
| Intraday marks | F-007 | OPRA quotes or minute bars (but illiquid legs barely trade — F-008/F-013) |
| Earnings calendar | F-015 (#5) | yfinance / a calendar API |

Note OPRA fixes bid/ask but **not** OI — max-pain (F-013) and the IC dealer-gamma gate stay
blocked without a separate OI source.

---

## F-017 — Dolt-only alpha check: no demonstrable edge; the one "winner" is beta
**Date:** 2026-05-30 · **Status:** Tools shipped (metric routing + directional IC); verdict = no clean-data alpha

**Why Dolt-only.** The 2025+ Alpaca data is indicative-feed *derivatives* (F-016); the
Dolt 2020-2024 rows are **real recorded quotes** and SPY 2020-2024 is 100% Dolt — the
cleanest test bed. So we evaluated alpha there.

**Shipped (the tools that make this answerable):**
- **Directional-signal IC** (`signal_eval.compute_directional_ic`): correlation of the bias
  score with the forward underlying return — separates *alpha* (signal predicts) from *beta*
  (just long delta). `ic_verdict` classifies predictive / noise / inverted.
- **Per-strategy metric routing** (`robustness.PRIMARY_METRIC` / `primary_metrics`): each
  strategy judged by its edge-appropriate metric (tail/CVaR/Calmar for sellers; directional
  IC + return-on-risk for debit spreads; return-on-risk + skew for butterfly), not Sharpe.

**Results — DOLT-only, SPY 2020-01→2024-12, real quotes:**

| Strategy | family | n | WR | P&L | Calmar | skew |
|---|---|---|---|---|---|---|
| short_put_spread | tail | 138 | 84.1% | −$650 | −0.03 | −2.45 |
| short_call_spread | tail | 135 | 75.6% | −$4,476 | −0.19 | −2.16 |
| iron_condor | tail | 135 | 65.9% | −$5,454 | −0.17 | −1.22 |
| **long_call_spread** | dir | 138 | 50.7% | **+$7,445** | 0.37 | +0.06 |
| long_put_spread | dir | 138 | 24.6% | −$6,479 | −0.18 | +1.24 |
| butterfly | convex | 138 | 30.4% | −$5,838 | −0.15 | +0.78 |

**The one winner is beta, not alpha (proven two ways):**
1. **Bias-signal IC ≈ 0 / inverted.** SPY/AAPL/NFLX 2020-2024, horizons 3/5/10d: Spearman IC
   ranged ~−0.09…+0.03; only the *inverted* readings were significant (SPY/NFLX 10d, p<0.05).
   The directional signal has **no predictive power** (and is mildly anti-predictive at 10d).
2. **Gating on the signal HURTS.** `long_call_spread` unconditional **+$7,445** → with
   `bias_filter` ON **+$2,670** (return-on-risk 0.144 → 0.093). If the signal carried alpha,
   gating would help; it subtracts. So the +$7,445 is **long delta in a 2020-2024 bull market**
   (beta), not signal edge.

**Sellers lose on clean data**, and the VRP gate doesn't rescue them (short_put_spread
−$650 → −$923 with edge>5%). The 2020 COVID crash + 2022 bear hit the negative-skew left tail
the win rate hides — exactly the documented failure mode (F-015).

**Verdict.** On the cleanest data we have, **the current strategy book + bias signal show no
demonstrable alpha**: premium sellers are net losers (tail-bitten), the directional debits are
pure beta (signal IC is noise), butterfly loses. This is the honest, valuable output of a now-
trustworthy backtester — it refuses to manufacture an edge. **Next edge work must start from a
signal with real IC** (or a genuinely conditioned VRP harvest), not from the current bias score.

---

## F-018 — Direction A: IC-first signal research (signal layer ≠ execution layer)

**Date:** 2026-05-31
**Status:** Harness shipped; first sweep = no unconditional edge, two significant CONDITIONAL leads

**Premise.** F-017 closed with "next edge work must start from a signal with real IC." This is
that work. The reframe (desk-quant style): a tradeable edge is two independent layers with very
different data needs — (1) a **signal** that predicts the UNDERLYING's forward return, which
needs only cheap underlying OHLCV (decades, free), and (2) an **execution** wrapper that harvests
it through options, which needs the scarce/expensive option BBO+OI. Every prior result fused the
two (bias_score → option P&L), so a weak/absent signal was indistinguishable from option
mechanics and beta. The workaround for our data limits is therefore to **research signals on free
underlying data, gate hard by IC, and only let survivors touch the option backtest.**

**Evaluation method (three agents, read-only).** A data-inventory agent confirmed the binding
limit: underlying signal research is wide open (yfinance, ^VIX/^VIX3M, 119k-headline
sentiment_backtest.db) while OI is 79% zeros (max-pain/GEX blocked) and there is no real BBO
without OPRA. A literature agent shortlisted the most orthogonal free/cheap, evidence-backed
signals. A forensic agent established WHY the old bias_detector fails IC: it encodes
mean-reversion as if it were momentum (RSI<30 → bullish) and is otherwise a coincident/lagging
trend descriptor built for regime *classification*, not return *prediction* — keep it as a gate,
don't use it for directional alpha.

**What shipped.**
- `src/backtest/signal_lib.py` — point-in-time signals (trailing-window ⇒ no lookahead):
  `short_term_reversal` (−5d return), `ts_momentum` (63d return / RV20, vol-scaled),
  `vix_term_structure` (VIX/VIX3M−1, z-scored; sign left to the data, not hardcoded).
- `src/backtest/signal_eval.py` — a generic IC engine: `forward_returns`, `ic_at_horizon`
  (Spearman+Pearson with p), `ic_table`, `fold_ic_signs` (time stability), `regime_ic_signs`
  (vol-regime stability), and a **strict graduation gate** `graduate()`: a signal advances only
  if at its best horizon it is significant (p<0.05), economically real (|IC|≥0.03), and
  sign-stable across BOTH time folds AND vol regimes. A consistently negative IC graduates as
  `direction="inverted"` (use −signal).
- `scripts/signal_ic_sweep.py` — pools (signal, forward-return) pairs across symbols (forward
  returns computed per-symbol to avoid fake adjacency), reports pooled + per-symbol + regime-split
  IC, and flags conditional (single-regime) edges.

**Result — SPY/QQQ/AAPL/NFLX, 2020-01-01..2024-12-31 (yfinance):**

| Signal | pooled best IC | p | symbol signs agree | graduates? |
|---|---|---|---|---|
| short_term_reversal | +0.028 @3d | 0.050 | no (1/4 flip) | ❌ |
| ts_momentum | −0.087 @10d | <0.001 | YES (−,−,−,−) | ❌ (1/12 fold flip) |
| vix_term_structure | −0.015 @5d | 0.286 | no | ❌ |

No signal clears the strict UNCONDITIONAL gate. But the regime split surfaces two
statistically-significant CONDITIONAL edges the pooled numbers hide:

1. **Medium-horizon reversal in CALM markets** — `ts_momentum` low-VIX @10d: **IC = −0.107,
   p<0.001, n=2496** (also low-VIX @5d −0.052 p=0.009; high-VIX @10d −0.050 p=0.013). The sign is
   negative in *every* symbol and *both* regimes — i.e. 3-month winners mean-revert over the next
   1–2 weeks, strongest when vol is low. This is the single strongest, most stable relationship in
   the study; it failed the unconditional gate only on 1 of 12 time folds (the COVID V-rebound, a
   momentum-crash regime). This is a genuine IC lead.
2. **Regime-switching short-term reversal** — `short_term_reversal` flips sign by regime:
   low-VIX @5d **IC −0.063 p=0.002** (calm ⇒ short-term *momentum* continues) vs high-VIX @3d
   **+0.047 p=0.019** / @5d **+0.046 p=0.020** (stress ⇒ recent losers *bounce*). Pooled, the two
   halves cancel to ~0; conditioned on VIX, each side is real. Textbook short-horizon
   momentum/long-horizon reversal term structure, modulated by the vol regime.

`vix_term_structure` is noise on its own (best conditional cell only −0.040 p=0.048) — useful as
the *regime gate* for the other two, not as a standalone signal.

**Why it matters.** This is the first **real, IC-validated directional signal** in the project —
the thing F-017 said edge work must start from. It is conditional (vol-regime-gated), not
unconditional, which is itself informative and matches the literature. The strict gate worked as
intended: it refused to graduate beta/noise but pointed precisely at where the signal lives.

**Follow-up (next iteration of A).** Construct a regime-conditioned signal — e.g. calm-market
3-month reversal at 10d, or a VIX-gated reversal that goes momentum in calm / reversal in stress —
and re-run it through the same strict gate as a single conditioned series; if it graduates, only
THEN express it through a 10–14 DTE debit spread on the clean Dolt window and check that gating on
the signal HELPS (the F-017 test the old bias score failed). No deferred debt: the harness, tests,
and docs are complete; the next step is a new experiment, not unfinished work here.

**Iteration 2 (2026-05-31) — the conditioned signal GRADUATES (index-only).** Built
`signal_lib.conditioned_reversal`: −(vol-scaled 63d return) emitted only on calm days, with a
strictly point-in-time gate. VIX data confirmed reliable (yfinance ^VIX/^VIX3M: 1258 trading days
2020-2024, zero NaN, max 4-day gap, VIX range 11.9–82.7 incl. the real COVID spike).

| Universe | gate='contango' (calm 94% of days) | gate='vix_pct' (VIX < trailing median) |
|---|---|---|
| SPY/QQQ/AAPL/NFLX | IC +0.075 @10d p<0.001 — ❌ (1–2 single-name-crash folds flip) | IC +0.114 @10d p<0.001 — ❌ (NFLX-2022 / AAPL folds flip) |
| **SPY/QQQ only** | **IC +0.102 @10d p<0.001 — ✅ GRADUATES** | **IC +0.163 @10d p<0.001 — ✅ GRADUATES** |

The strict gate's only objection at the 4-symbol level was time-instability concentrated in
single-name crash cells (NFLX −70% in 2022, AAPL late-2023) — the textbook reversal/momentum-crash
failure mode (buying a falling knife). Restricting to index ETFs, which lack those idiosyncratic
drawdowns, the signal passes EVERY gate: significant (p<0.001), economically large (rank IC
0.10–0.16 at 10d — high for equity return prediction), and sign-stable across all time folds and
both symbols. The `vix_pct` gate (selects ~58% of days) is materially stronger than `contango`
(barely a gate at 94% calm), so it is the preferred conditioner.

**This is the first IC-validated directional signal in the project** — the thing F-017 said edge
work must start from. Plain statement: *on SPY/QQQ, in low-vol regimes (VIX below its trailing
median), the 3-month laggard reverts up over the next ~10 days.* Tests:
`tests/test_signal_lib.py` now covers the conditioned signal (gate logic, no-lookahead, gated-out
in stress, calm-laggard orientation), 17 passing.

**Next (execution layer — not yet done).** Express the graduated signal on the clean Dolt SPY
window as a ~10–14 DTE long_call_spread entered only on calm-laggard days, and run the F-017 test:
gating on the signal must IMPROVE risk-adjusted performance vs the unconditional long_call_spread
(+$7,445 beta). Only if gating helps is the signal-PLUS-execution edge real; this requires wiring
the signal as an entry filter into chain_replay.

---

## F-019 — Execution test: a validated directional IC does NOT transmit through debit spreads

**Date:** 2026-05-31
**Status:** Done — answer is NO (for defined-risk debit spreads on SPY 2020-2024); two-layer
framework vindicated; cache-key bug found + fixed en route

**What was done.** Wired the F-018 graduated signal into the option backtester. Added
`signal_filter` / `signal_gate` to `BacktestRequest`; `chain_replay._build_conditioned_signal`
precomputes `conditioned_reversal` (date→value) for the window from yfinance underlying + VIX/VIX3M;
the entry loop gates directional debit spreads on its sign (long_call_spread enters only on a
bullish/positive reading, long_put_spread only on bearish). `scripts/signal_execution_test.py`
compares unconditional vs gated on the clean Dolt window. This is the F-017 test the old bias score
failed — does conditioning on the signal beat the unconditional (pure-beta) spread?

**Result (SPY/QQQ, 2020-2024, 10–14 DTE, exit=hold, bid/ask fills):**

| Config | trades | pnl/trade | win | ret-on-risk | profit factor |
|---|---|---|---|---|---|
| long_call unconditional (beta) | 138 | $54 | 50.7% | 0.144 | 1.36 |
| long_call gated, `vix_pct` | **4** | $241 | 75% | 0.671 | 3.58 |
| long_call gated, `contango` | 26 | **−$22** | 46.2% | −0.058 | 0.89 |
| long_put gated, `vix_pct` | 63 | **−$71** | 19.0% | −0.301 | 0.59 |
| QQQ long_call (either) | 0 | — | — | — | — (Dolt QQQ too thin at 10–14 DTE) |

**Verdict — NO, the IC does not transmit.** The single flattering cell (`vix_pct` long_call,
$241/trade, PF 3.58) is **n=4 — statistically meaningless**. Every adequately-sampled
configuration made performance WORSE than the unconditional spread (contango long_call 26 trades
−$22/trade; long_put 63 trades −$71/trade). The long-call side fires rarely because it needs SPY to
be *both* calm *and* a 3-month laggard — uncommon for an index in a secular bull, so the signal's
positive tail is thin precisely where we want to trade it.

**Why a real signal still fails here (the lesson).** The IC (+0.163) is measured on the
UNDERLYING's *sign-of-move* at a fixed 10-day horizon. A defined-risk **debit spread** needs
*magnitude and timing*, and crosses the bid/ask twice. A sign-only edge of IC ≈ 0.16 (the
underlying drifts the right way slightly more than half the time) is swamped by the spread's cost
structure and its dependence on a sufficiently large move within DTE. **Directional IC on the
underlying is NECESSARY BUT NOT SUFFICIENT for an options edge** — the signal and execution layers
are independent gates, exactly as the F-017/F-018 framing posited. The framework worked: the signal
layer found real alpha, the execution layer correctly refused to monetize it through the wrong
vehicle.

**Bug found + fixed (F-005 class).** `cache._cache_key` did not include `signal_filter` /
`signal_gate`, so the first gated run silently returned the cached UNCONDITIONAL result (identical
to the penny — the tell). Added both to the key; added `test_cache_key_includes_signal_filter`
regression test. (`vrp_filter`/`swing_bias_filter` are likewise absent from the key — flagged for a
follow-up audit; they are unused in current runs so no result is presently wrong, but the key
should enumerate every result-affecting field.)

**Where this points (not a dead end).** The signal is real; the *vehicle* is wrong. A directional
IC of 0.16 is naturally expressed in a delta-1 / underlying position (no magnitude hurdle, no
double spread cost), or possibly a longer-dated / deeper-ITM structure with more delta and less
cost drag — but the project's mandate is short-DTE defined-risk spreads, for which this signal is
not the edge. The durable takeaways (golden params, the necessary-not-sufficient lesson, and the
endorsed regime-specific-strategy direction) are saved to persistent memory.

---

## F-020 — Phase 3 cache-key audit: four result-affecting fields absent from `_cache_key`

**Date:** 2026-05-31
**Status:** FIXED — all four fields added; RESULT_AFFECTING_FIELDS sentinel test prevents recurrence

**Observed.** A targeted audit of `src/backtest/cache._cache_key` against every field on
`BacktestRequest` found four result-affecting fields that were keyed on `signal_filter` (fixed in
F-019) but NOT on four others introduced later: `min_score`, `vrp_filter`, `vrp_threshold`,
`swing_bias_filter`, and `option_style`.

**Evidence.** Manual cross-check of `BacktestRequest.model_fields` against `key_data` dict in
`_cache_key`. All five were present on the model and all five alter backtest P&L:
- `min_score` — score threshold gate on entry; different min_score → different trade set
- `vrp_filter / vrp_threshold` — VRP regime gate; same params but different VRP threshold silently
  returned the same cached result
- `swing_bias_filter` — regime directional bias filter
- `option_style` — european vs american early-exercise affects theoretical P&L in local_backtest

**Why it matters.** This is the F-005 failure class: two runs with different filter configurations
silently return the same result because the cache key is identical. The bug is latent — it only
bites when those specific filters are exercised in back-to-back runs where the first result is
already cached. Exactly the same silent corruption as the original F-005 engine-hash bug, just
on request-parameter axes.

**Resolution.**
- Added all five fields to `_cache_key`'s `key_data` dict with inline comments explaining each
- Added `RESULT_AFFECTING_FIELDS` frozenset to `cache.py` (canonical allow-list)
- Added sentinel regression test `test_cache_key_sentinel_all_result_affecting_fields_present`
  in `tests/test_signal_lib.py`: iterates `RESULT_AFFECTING_FIELDS` against
  `BacktestRequest.model_fields`, fails if any listed field is absent from the model — catches
  future cases where a field is added to the allow-list but misspelled, or removed from the model
- Added `test_cache_key_covers_vrp_and_swing_bias_filters` and
  `test_cache_key_covers_option_style_and_min_score`: verify each new field actually changes the
  key (not just that it appears in the dict)

**Lesson.** The F-005 fix (logic-version hash) protects against *code* changes but not against
*new result-affecting request fields* being added without updating the key. The sentinel test is
the correct structural fix: it fails at test time, not silently at runtime.

---

## F-021 — Phase 4 sentiment IC test: FinBERT composite score does NOT predict SPY returns

**Date:** 2026-05-31
**Status:** NO EDGE — signal does not graduate; not recommended for execution testing

**What was done.** Built `scripts/sentiment_ic_test.py`: a fully offline IC test for the FinBERT
sentiment archive in `data/sentiment_backtest.db`. Strictly follows design rules from
`.claude/rules/sentiment.md`:
- **Zero imports from `src/sentiment/`** — reads scored headlines directly from SQLite
- **Point-in-time construction** — for each snapshot date t, only headlines with
  `published_at ≤ t` (within a rolling lookback window) contribute to the signal
- **Offline price data** — uses SPY spot prices from `data/chain_snapshots.db` (no yfinance,
  no network required)
- Signal = exponentially-decayed weighted mean of `(positive − negative)` over the lookback
  window (halflife = 96 h / 4 days)
- Same `signal_eval` IC engine (`ic_table`, `fold_ic_signs`, `graduate`) as `signal_ic_sweep.py`
- Regime split uses trailing 63-day close vol (proxy for VIX, since VIX not available offline)

**Dataset.** 115,552 scored SPY headlines (min_confidence ≥ 0.5), overlap with chain_snapshots
price data: 2020-01-04 → 2024-03-04, n=556 trading days.

**Results (default 7d lookback, min_confidence=0.5):**

| Horizon | Spearman IC | p-value | n |
|---------|------------|---------|---|
| 3d | −0.0562 | 0.1875 | 552 |
| 5d | −0.0365 | 0.3933 | 550 |
| 10d | −0.0662 | 0.1229 | 545 |

Regime split (low vs high trailing vol):

| Horizon | low-vol IC | n | high-vol IC | n |
|---------|-----------|---|------------|---|
| 3d | −0.069 | 244 | −0.101 | 244 |
| 5d | −0.010 | 243 | −0.103 | 243 |
| 10d | −0.115 | 241 | −0.156 | 240 |

Verdict: ❌ no edge. Best: 10d IC=−0.066, p=0.123, direction=inverted, reason=not significant.

**Sensitivity across lookback/confidence settings:**

| lookback | min_conf | best_h | IC | p | verdict |
|----------|----------|--------|----|---|---------|
| 3d | 0.70 | 5d | −0.071 | 0.098 | ❌ not significant |
| 7d | 0.50 | 10d | −0.066 | 0.123 | ❌ not significant |
| 14d | 0.50 | 10d | −0.079 | 0.065 | ❌ not significant (closest) |

**Verdict — NO EDGE.** The signal consistently fails to graduate across all lookback windows and
confidence thresholds. Key observations:
1. **Consistent bearish bias.** All ICs are negative — higher (more positive) FinBERT composite
   score weakly predicts *lower* SPY forward returns, the opposite of the hypothesised direction.
   This may reflect a "bad news travels faster" asymmetry in news headlines, or that positive
   sentiment is a lagging sentiment indicator that follows moves upward (sentiment = noise on
   an index-level).
2. **Stronger in high-vol regimes.** The negative IC is consistently larger in absolute terms
   during high-vol periods. A contrarian interpretation (high positive sentiment after a stress
   event → fading into a rebound) might have merit, but with p-values all above 0.06 the effect
   is too weak to act on.
3. **None pass the graduation gate** (p < 0.05 AND |IC| ≥ 0.03, sign-stable). The best single
   run (14d lookback, 10d horizon) gets p=0.065, just outside significance.
4. **No execution test warranted.** The F-018/F-019 experience showed that a signal with IC=+0.163
   (p<0.001) still failed to transmit through debit spreads. A signal with IC≈−0.07 (p≈0.10)
   at best, in the wrong direction, has no viable path to an options edge.

**Why index-level sentiment likely doesn't work here.** FinBERT headlines aggregate broad market
sentiment; SPY price already incorporates this news almost instantly (Fama 1970). The 7-day
lookback window is likely too long for the efficient-price-discovery regime, and too short to
build a reliable mean-reversion signal. Single-stock headlines, especially for less-covered
names, might show higher IC — but that is outside the current mandate (SPY/index ETFs).

**Follow-up / what to test instead.** If sentiment is to be revisited: (1) test on individual
high-coverage single names (AAPL, TSLA) where sentiment may move price rather than follow it;
(2) test intraday sentiment → same-day return (faster signal decay); (3) test on volatility
rather than direction (positive FinBERT composite → lower VIX next day?). None of these are
blocked by missing data, but they are outside current scope.

---

## F-022 — Phase 1 sweep across 7 index ETFs: broad-index 10-day mean-reversion graduates

**Date:** 2026-05-31
**Status:** Done — the network-blocked Phase-1 deliverable now RUN; two signals graduate; one
sweep bug fixed

**Context.** Dispatch added two new signals (`vrp_proxy`, `high52w_proximity`) and unit tests but
could NOT run the actual multi-ticker IC sweep — yfinance was unavailable in its sandbox. Run here
(network available) across SPY/QQQ/IWM/DIA/XLK/XLF/XLE, 2020-01-01..2024-12-31.

**Bug fixed first.** `signal_ic_sweep.WARMUP_DAYS` was 120 calendar days (~82 trading) — too short
for `high52w_proximity`'s 252-day rolling high, which would have been NaN through most of 2020 and
skipped the COVID regime (silent under-sampling). Raised to 420 calendar days (~290 trading,
covers 252 + slack). After the fix, the 10d pooled n is 8736 (≈1248/symbol × 7) — full window used.

**Results (pooled across 7 ETFs, strict gate):**

| Signal | best pooled IC | p | symbols agree | graduates? |
|---|---|---|---|---|
| **ts_momentum** | −0.091 @10d | <0.001 | 7/7 (all −) | ✅ inverted |
| **high52w_proximity** | −0.102 @10d | <0.001 | 7/7 (all −) | ✅ inverted |
| short_term_reversal | +0.028 @3d pooled | — | no | ❌ (regime-split: +0.055 high-VIX / −0.035 low-VIX — conditional only) |
| vix_term_structure | +0.016 @3d | 0.124 | no | ❌ noise |
| vrp_proxy | −0.035 @10d | 0.001 | no (signs mixed) | ❌ time-unstable |

**Interpretation — it's ONE phenomenon, not two edges.** Both graduates are *inverted* and both
are essentially "how extended is price": `ts_momentum` = 3-month trailing return (inverted ⇒ fade
winners), `high52w_proximity` = closeness to the 52-week high (inverted ⇒ fade near-highs). They
measure the same thing and are NOT orthogonal. The robust, cross-sectional finding is **medium-
horizon (10-day) mean-reversion of extended index ETFs**, significant on all 7 underlyings in both
vol regimes. This confirms and broadens F-018 (which found it on SPY/QQQ via `conditioned_reversal`)
to a 7-ETF cross-section, and it survives multiple-testing scrutiny (7/7 same sign at p<0.001 — not
a lucky cell among the 5×7×2×3 grid).

**Notable negatives.**
- `high52w_proximity` graduates with the OPPOSITE sign to its literature hypothesis (George-Hwang
  2004 = near-high *continuation*). On these index ETFs in 2020-2024, reversion dominates
  continuation at 10d. Honest, regime/era-specific result — the sign is measured, not assumed.
- `vrp_proxy` does NOT work as a *directional* underlying signal (sign flips across symbols/folds).
  This does not rule out VRP as a *volatility/regime* conditioner for premium sellers — that is a
  different test (Phase 2, tail metrics), not a directional IC.
- `short_term_reversal` remains regime-conditional (works in high-VIX, inverts in calm) — a lead,
  not an unconditional edge.

**What this changes for Phase 2.** The directional edge to carry forward is medium-horizon index
mean-reversion (use `ts_momentum`-inverted or `high52w`-inverted; they are redundant — pick one,
`ts_momentum` is cleaner). CAVEAT from F-019: a directional IC of ~0.10 did NOT transmit through
10–14 DTE debit spreads (cost + magnitude). So Phase 2 must test a more cost-efficient vehicle
(higher-delta / longer-dated) and demand ≥30 trades before believing any result. Do NOT re-derive
the signal layer — it is settled; the open question is purely execution.

---

## F-023 — Phase 2 vehicle sweep: the directional edge does NOT transmit at ANY vehicle

**Date:** 2026-05-31
**Status:** Done — definitive NO across DTE × ITM-depth × cadence × both gates. Directional-signal
thread is closed for the defined-risk-spread mandate.

**What was done.** F-019 showed the mean-reversion signal failed through a narrow ATM debit spread,
but on n=4 — possibly just sample. Phase 2 added three vehicle knobs to the backtester (F-023) to
test the "wrong vehicle, not wrong signal" hypothesis and to fix the sample problem:
- `entry_interval` (BacktestRequest) — entry cadence; smaller ⇒ more entries (sample-size knob).
- `debit_itm_pct` — places the LONG leg that far ITM (more delta, less theta drag).
- `debit_width_pct` — debit-spread width as a fraction of spot.
All default to the legacy narrow-ATM behaviour (verified by `tests/test_vehicle_knobs.py`); all
three added to `_cache_key` + `RESULT_AFFECTING_FIELDS` (auto-guarded by the sentinel test).
`scripts/signal_vehicle_sweep.py` sweeps DTE {10-14, 21-35, 30-45} × ITM {0, 3%, 6%} (width 5%),
gated vs unconditional long_call_spread, on SPY 2020-2024, both gates.

**Result — NO vehicle rescues it (SPY, width 5%):**

| | unconditional $/trade (ror) | gated $/trade (ror) | n (gated) |
|---|---|---|---|
| 10-14 DTE, ATM | +101 (0.185) | +60 (0.095) | 62 |
| 21-35 DTE, ATM | +164 (0.223) | +1 (0.001) | 65 |
| 30-45 DTE, ATM | +327 (0.400) | −176 (−0.194) | 5 |
| 10-14 DTE, 6% ITM | +36 (0.019) | +142 (0.091) | 62 |

(contango gate, entry_interval=2; vix_pct/interval=1 gives the same picture with smaller n.)

**Verdict — the directional IC does NOT transmit, and gating HURTS.** Three robust observations:
1. **Unconditional is positive in every cell** ($36–$374/trade) — the bull-market beta of being
   long delta (F-017), strongest at longer DTE where the spread carries more delta to the drift.
2. **Gating subtracts value in almost every cell** (gated < unconditional). The signal selects
   post-drawdown "laggard in calm" days and discards the high-beta up-drift days where the long
   call actually earns; the residual reversion can't cover the spread's bid/ask + theta cost.
3. **The lone "✅" (contango/10-14/6% ITM, gated $142 > unconditional $36) is an artifact** — gating
   "wins" only because the deep-ITM unconditional baseline collapsed there (ror 0.019); the same
   gate/ITM at 21-35 DTE is −$98. Not a real, structure-robust edge.

Longer DTE *widening* the unconditional-minus-gated gap is the tell: this is delta/beta, not signal.

**Conclusion.** Across DTE, ITM depth, spread width, entry cadence and both vol gates, the validated
medium-horizon mean-reversion signal (real IC ~0.10 on the underlying, F-018/F-022) has **no
expression as a short-DTE defined-risk debit spread that beats simply being long**. This closes the
DIRECTIONAL thread for the project's mandate: a sign-only edge of that size is structurally
unmonetizable through debit spreads (it would need a delta-1 / underlying position — out of mandate;
see [[signal-ic-necessary-not-sufficient]]). The two-layer framework is now fully demonstrated: the
signal layer found genuine alpha, the execution layer conclusively rejects it for this vehicle class.

**Where edge research goes next (NOT directional).** The untested family is the VOLATILITY/regime
edge for PREMIUM SELLERS: use a vol-regime signal (VRP / term structure) to CONDITION
short_put_spread / iron_condor and judge on TAIL metrics (CVaR/Calmar/max-loss), not directional IC.
`vrp_proxy` failed as a *directional* signal (F-022) but was never tested as a *seller's vol
conditioner* — that is the open Phase-2(b)/Phase-5 question, and it is a different test entirely.

