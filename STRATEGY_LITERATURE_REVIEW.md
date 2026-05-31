<!--
  STRATEGY_LITERATURE_REVIEW.md
  In-depth comparison of each active strategy against the options literature:
  edge source, expected-return view, the CORRECT evaluation metric (different
  per strategy), what we currently do, our measured result, and the gap.
  Companion to FINDINGS.md (F-013 butterfly metrics, F-014 robustness harness,
  F-015 this review) and VALIDATION_RESULTS.md.
  Author: Claude — 2026-05-30.
-->

# Strategy ↔ Literature Review

**Thesis: there is no single performance metric.** Each strategy earns (or
loses) from a *different source* — variance risk premium, directional drift, or
pinning — so each must be judged by a *different primary metric* under
*different conditions*. Ranking them all by Sharpe (as we did) is a category
error, most dangerously for the negative-skew premium sellers. This review does
for every strategy what F-013 did for the butterfly.

Numbers below: chain-replay, SPY 2022-01→2026-05, real bid/ask, per-strategy
exits, single-expiry legs (post-F-008), priced honestly (post F-001…F-009).

| Strategy | WR | P&L | Sharpe | **skew** | **CVaR95** | **maxLoss** | Calmar |
|---|---|---|---|---|---|---|---|
| short_put_spread | 83.1% | −1,556 | −0.26 | **−3.09** | −815 | −1,097 | −0.14 |
| short_call_spread | 80.8% | +794 | 0.23 | **−2.80** | −513 | −698 | 0.13 |
| long_call_spread | 49.6% | +1,029 | 0.12 | **+0.31** | −509 | −571 | 0.08 |
| long_put_spread | 32.1% | −650 | −0.08 | **+1.28** | −359 | −407 | −0.02 |
| iron_condor | 71.3% | −905 | −0.14 | **−1.86** | −736 | −1,026 | −0.08 |
| butterfly | 26.4% | −5,448 | −0.75 | **+0.77** | −443 | −579 | −0.23 |

The **skew column alone** tells the story: the three premium sellers are sharply
*negative*-skew (high win rate hiding a fat left tail); the directional debits
and the butterfly are *positive*-skew (low win rate, convex). One metric cannot
fairly rank both families.

---

## Edge sources (why the metric must differ)

- **Variance risk premium (VRP):** options are priced above subsequent realized
  vol on average (Carr–Wu 2009; Bakshi–Kapadia 2003 — negative delta-hedged
  gains; Coval–Shumway 2001 — short-vol pays). *Sellers* harvest it; *buyers*
  pay it. → credit spreads, iron condor.
- **Directional / drift edge:** the trade needs the underlying to move a way,
  paying the VRP drag to do it. → long call/put spreads.
- **Pinning / convergence:** profits if the underlying *stays put* at a strike.
  → butterfly (F-013).

---

## 1. Short put spread — credit, bullish (VRP + drift + put-skew)

**Payoff / skew.** Capped both ways; **negative skew** (we measure −3.09): many
small wins, rare full-width loss. Short gamma, short vega.

**Edge (literature).** The canonical positive-EV-with-a-left-tail trade. It
collects three premia: the VRP, the **equity-index put-skew premium** (index
puts are systematically expensive — Bondarenko's "put-return puzzle"), and a
drift tailwind (puts decay as the market grinds up). The CBOE **PUT** index
(systematic put-writing) historically earns ~equity returns at lower volatility
— *but with crash risk* (it's short the tail everyone is paying to hedge).

**Correct primary metric.** **Tail-aware, not Sharpe.** Win rate is vanity
(83% here and still a loser); Sharpe looks fine right up until a tail event.
Judge by **CVaR / expected shortfall, max single loss, max drawdown, Calmar,
and the frequency of full-width losses**. Sortino is a partial improvement;
CVaR is the point.

**What we do.** Regime gate {HIGH_IV, MODERATE_IV, SPIKE}; optional bullish-bias
and edge>5% (IV-RV) gates; exit 50% profit / 200% loss / 1 DTE.

**Our result.** 83% WR but **−$1,556**, skew −3.09, **CVaR95 −$815, max loss
−$1,097**. The 2022 bear hit exactly the left tail the win rate hides — which is
*the* documented failure mode, now visible in the tail metrics (was invisible in
Sharpe ≈ 0).

**Gap.** (a) We gate on IV regime but not consistently on **VRP/IV-rank**, which
*is* the edge condition. (b) No **earnings/event blackout** (events dominate
short-vol tails). (c) We ranked it by Sharpe — should be **CVaR/Calmar**.

---

## 2. Short call spread — credit, bearish (VRP, but fights drift)

**Payoff / skew.** Capped; **negative skew** (−2.80). Short gamma.

**Edge (literature).** Weaker than put-selling on two counts: index **call skew
is flatter** (calls aren't bid up like puts, so less premium to harvest), and
you **fight the equity risk premium** (upward drift). Call-overwriting (CBOE
**BXM**) underperforms buy-and-hold in bull markets (it caps upside); naked
call-selling is generally negative-EV over a full cycle due to drift and
occasional melt-ups.

**Correct primary metric.** Tail-aware (as #1) **plus a drift benchmark** — it
must beat *not trading* / a short-delta baseline, because the structural
headwind means a positive raw P&L can still be worse than the alternative.

**What we do.** Regime {HIGH_IV, SPIKE} + bearish bias; same exits as #1.

**Our result.** 80.8% WR, **+$794** (Sharpe 0.23), skew −2.80, CVaR −$513. The
*positive* result is **period-specific** — the 2022 bear rewarded bearish
call-selling. Over a full cycle expect the documented headwind; the OOS harness
(F-014) is the guard against trusting this single window.

**Gap.** Period/regime-fit risk; no benchmark vs drift; tail metrics now present
but conditioning on a *bearish* regime + VRP is missing.

---

## 3. Long call spread — debit, bullish, DIRECTIONAL

**Payoff / skew.** Capped; **positive skew** (+0.31): lower win rate (49.6%),
defined loss = debit, occasional capped win.

**Edge (literature).** **Not a vol harvest — a directional bet** that must
overcome the VRP drag (long options lose on average). The short leg sells some
premium back, reducing the drag vs a naked long call. So the edge = **the
quality of the directional/entry signal**, full stop.

**Correct primary metric.** **Information coefficient / hit-rate of the entry
signal vs a baseline**, and **expectancy / return-on-debit**. Positive skew
means Sharpe is *less* wrong here, but it's still secondary. Crucially: **attribute
P&L to direction vs beta** — in a bull market a bullish debit makes money even
with *no* signal edge (it's just long delta).

**What we do.** Regime {LOW_IV, MODERATE_IV} (cheap to buy) + bullish bias; exit
75% profit / 100% loss / 2 DTE.

**Our result.** 49.6% WR, **+$1,029**, **skew +0.31** — the only clearly
positive, positive-skew strategy. But this is likely **beta, not alpha**: a
bullish bet in a 2022-2026 market that rose.

**Gap.** We never measure whether our **bias signal actually predicts** (an IC
or hit-rate-vs-random). Without that, +$1,029 is indistinguishable from "long
delta in an up market." This is the single most important missing measurement
for the directional strategies.

---

## 4. Long put spread — debit, bearish, DIRECTIONAL / hedge

**Payoff / skew.** Capped; **positive skew** (+1.28) — convex, low win rate.

**Edge (literature).** Standalone it pays both the VRP *and* fights drift, so
long-put structures have **negative average standalone returns** (you're buying
the expensive, high-skew insurance). Their real value is as a **portfolio hedge**
(negative correlation, crash convexity), which is a *portfolio-level* property,
not a standalone P&L.

**Correct primary metric.** As a standalone directional bet: directional IC +
expectancy. **As a hedge: portfolio-level** — beta, crash-beta, the effect on
the *portfolio's* drawdown/CVaR, not the put's own P&L.

**What we do.** {LOW_IV, MODERATE_IV} + bearish bias; 75/100/2-DTE. Evaluated
**standalone**.

**Our result.** 32% WR, **−$650**, skew +1.28 — loses standalone (bearish in an
up market), exactly as literature predicts.

**Gap.** We judge a hedge as if it were an alpha source. It needs a
**portfolio/hedge framing** (does it cut portfolio drawdown per dollar of drag?)
or a genuinely predictive bearish signal — neither exists today.

---

## 5. Iron condor — credit, neutral (VRP + range + pin)

**Payoff / skew.** Capped both sides, **two tails**, **strongly negative skew**
(−1.86). Short gamma *and* short vega — the most tail-exposed structure we run.

**Edge (literature).** Profits when **realized vol < implied AND price stays in
range**. The CBOE **CNDR** index documents the archetype: slow, steady premium
collection punctuated by sharp losses when a tail move blows through a wing.
"Picking up pennies in front of a steamroller," doubled.

**Correct primary metric.** **The most tail-sensitive of all** — CVaR/ES, max
loss, worst-month, **frequency of full-width losses**, Calmar/Ulcer. Win rate is
the *most* deceptive here. Conditioning: VRP positive, low realized vol,
range-bound, and **dealer long-gamma** (price pins).

**What we do.** Regime {HIGH_IV, SPIKE} + **dealer LONG_GAMMA requirement** (a
genuinely sophisticated condition) + optional neutral-bias; 50/200/1-DTE.

**Our result.** 71.3% WR, **−$905**, skew −1.86, **CVaR −$736, max loss
−$1,026**. Loses with a clear tail — the textbook IC failure.

**Gap.** The **LONG_GAMMA gate is a no-op historically** (needs OI we lack —
DATA_ISSUES §3 / F-013); not conditioned on **realized < implied**; ranked by
Sharpe. Needs OI data + VRP/range conditioning + tail-primary metrics.

---

## 6. Butterfly — debit, pin (convergence) — see F-013

Convex, **positive skew** (+0.77); judged by **return-on-risk / EV / skew**, not
Sharpe; centered at **max pain** (now implemented) under **elevated-IV + pin**
conditions. Proper validation is **OI-blocked** (F-013). Currently negative as
data allows.

---

## What we are missing (consolidated)

**Added this review (F-015):** tail-risk metrics now on every result —
`cvar_95` (expected shortfall), `max_single_loss`, `calmar_ratio`. These are the
*correct primary lens* for the negative-skew sellers (#1, #2, #5) and were the
biggest blind spot: a high win rate + Sharpe ≈ 0 hid −$800-ish CVaR and
−$1,000-ish worst trades.

**Still missing (prioritized):**
1. **Per-strategy primary-metric routing.** Stop ranking everything by Sharpe.
   Credit/IC → CVaR + Calmar + max-loss; directional debits → signal IC +
   expectancy; butterfly → return-on-risk + skew. (Reporting/ranking change.)
2. **Directional-signal predictive power (IC / hit-rate vs baseline)** for #3/#4
   — to separate *alpha* from *beta*. Without it, long_call_spread's +$1,029 is
   probably just long delta in an up market.
3. **VRP-conditioned segmentation** for #1/#2/#5 — report performance bucketed by
   IV-RV (edge_pct) at entry; the edge *is* the VRP, so results should be
   sliced by it (we filter on it but don't segment).
4. **Benchmark comparison** — vs buy-and-hold and/or the CBOE strategy-index
   analogue (PUT, BXM, CNDR, BFLY) and vs random-entry, so "positive P&L" is
   judged against the right alternative (esp. #2, #3).
5. **Event/earnings blackout** in the backtest — events dominate short-vol tails
   (#1, #2, #5); we have none.
6. **Portfolio/hedge framing for long puts (#4)** — evaluate drawdown reduction
   per dollar of drag, not standalone P&L.

**Data-blocked (external, not code debt):** #5 needs an earnings calendar; the IC
dealer-gamma condition and butterfly max-pain need historical OI; true intra-hold
tail risk needs intraday/quote data (F-007). See the Alpaca historical-data review.

---

*2026-05-30. The headline: our strategies split into negative-skew VRP sellers and
positive-skew directional/pin bets; we were measuring both with the seller-flattering
Sharpe. Tail metrics added; per-strategy metric routing + signal-IC + benchmarking remain.*
