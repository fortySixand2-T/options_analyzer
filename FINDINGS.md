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
| F-005 | 2026-05-30 | Backtest result cache not invalidated on code change | Mitigated; follow-up open |
| F-006 | 2026-05-30 | Concurrency makes overlapping trades correlated → inflated Sharpe/PF | Resolved (time-indexed MTM) |
| F-007 | 2026-05-30 | Intra-hold marks are sparse → MTM curve degrades to time-indexed realized P&L | Reframed — data already daily; granularity is exit-logic-bound; finer risk needs INTRADAY data |
| F-008 | 2026-05-30 | Impossible spread premiums → phantom profit. ROOT CAUSE (corrected): `_select_strikes` picked legs from DIFFERENT expiries | Fixed (same-expiry constraint) — free code fix, no data feed needed |

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
