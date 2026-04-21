# Signal Architecture & Decision Matrix
# 0-14 DTE Index Options — Basics Only

## Five strategies, three decisions

**Strategies (5 total):**
1. Iron condor — neutral credit, defined risk
2. Short put spread — bullish credit, defined risk
3. Short call spread — bearish credit, defined risk
4. Long call/put spread — directional debit, defined risk
5. Butterfly — pin play near max pain, defined risk

No calendar spreads, no diagonals, no strangles, no naked straddles. Everything is defined risk. Longer-timeframe strategies are deferred to `src/strategies/_deferred/` for a future swing-trade tab.

**Three decisions in order:**
1. Vol regime → sell premium or buy it?
2. Directional bias → which way?
3. Dealer positioning → where does price stick or accelerate?

---

## Layer 1: Vol regime

| # | Signal | Sell premium when | Buy premium when | Source |
|---|---|---|---|---|
| V1 | VIX level | < 20 | > 30 | yfinance |
| V2 | VIX term structure (VIX/VIX3M) | < 0.95 (contango) | > 1.05 (backwardation) | yfinance |
| V3 | IV rank (52-week) | > 50 (rich) | < 25 (cheap) | scanner/iv_rank.py |
| V4 | IV vs HV20 spread | Positive (overpriced) | Negative (underpriced) | scanner/edge.py |
| V5 | GARCH vol vs chain IV | GARCH < IV | GARCH > IV | monte_carlo/garch_vol.py |

**Regime output:**

| Condition | Label | Action |
|---|---|---|
| IV rank > 50, VIX < 25, contango | HIGH_IV | Sell premium (credit strategies) |
| IV rank 30-50, VIX < 20 | MODERATE_IV | Either side, weaker edge |
| IV rank < 30, VIX < 18 | LOW_IV | Buy premium (debit strategies) |
| VIX > 30 or backwardation | SPIKE | Small debit only or stand aside |

---

## Layer 2: Directional bias

All signals calibrated for 1-14 day moves. No SMA 200, no golden cross, no stochastic.

| # | Signal | Bullish (+) | Bearish (-) | Weight |
|---|---|---|---|---|
| D1 | EMA 9 vs EMA 21 (daily) | 9 above 21 | 9 below 21 | 2 |
| D2 | EMA 9 slope (3-bar) | Rising | Falling | 1 |
| D3 | RSI(14) | 50-65 | 35-50 | 1 |
| D4 | RSI(14) extreme | < 30 (bounce) | > 70 (fade) | 1 |
| D5 | MACD histogram | Positive + rising | Negative + falling | 2 |
| D6 | MACD zero cross | Cross above | Cross below | 1 |
| D7 | Prior day candle | Close near high | Close near low | 1 |
| D8 | 2-day momentum | Higher close | Lower close | 1 |

**Bias output:**

| Score | Label |
|---|---|
| >= +4 | STRONG_BULLISH |
| +2 to +3 | LEAN_BULLISH |
| -1 to +1 | NEUTRAL |
| -3 to -2 | LEAN_BEARISH |
| <= -4 | STRONG_BEARISH |

**ATR percentile** (not directional — modifies strategy): high ATR (> 60th pctl) = trending, favor directional. Low ATR (< 25th) = ranging, favor neutral credit.

---

## Layer 3: Dealer positioning

| # | Signal | What it tells you | Source |
|---|---|---|---|
| F1 | Net GEX sign | Positive = range-bound (sell premium). Negative = trending (avoid selling). | FlashAlpha or compute from chain |
| F2 | Gamma flip level | Above = pinned. Below = volatile. | FlashAlpha |
| F3 | Call wall | Resistance — place short calls at/near | FlashAlpha or max call OI strike |
| F4 | Put wall | Support — place short puts at/near | FlashAlpha or max put OI strike |
| F5 | Max pain | Price magnet into expiry. Center butterflies here. | Compute from OI |
| F6 | Put/call OI ratio | > 1.5 = contrarian bullish. < 0.5 = contrarian bearish. | Chain data |
| F7 | Dealer regime | LONG_GAMMA (range-bound) or SHORT_GAMMA (trending) | Derived from F1+F2 |

**Dealer output:** LONG_GAMMA or SHORT_GAMMA.

---

## Decision matrix

| Regime | Bias | Dealer | Strategy | DTE |
|---|---|---|---|---|
| HIGH_IV | NEUTRAL | LONG_GAMMA | Iron condor | 7-14 |
| HIGH_IV | LEAN_BULLISH | any | Short put spread | 5-10 |
| HIGH_IV | LEAN_BEARISH | any | Short call spread | 5-10 |
| HIGH_IV | STRONG_BULLISH | any | Short put spread (tighter) | 3-7 |
| HIGH_IV | STRONG_BEARISH | any | Short call spread (tighter) | 3-7 |
| MODERATE_IV | NEUTRAL | LONG_GAMMA | Butterfly (at max pain) | 3-7 |
| MODERATE_IV | LEAN_BULLISH | any | Long call spread | 5-14 |
| MODERATE_IV | LEAN_BEARISH | any | Long put spread | 5-14 |
| LOW_IV | NEUTRAL | any | Butterfly (at max pain) | 3-7 |
| LOW_IV | LEAN_BULLISH | any | Long call spread | 5-10 |
| LOW_IV | LEAN_BEARISH | any | Long put spread | 5-10 |
| LOW_IV | STRONG_BULLISH | any | Long call spread (tight) | 3-5 |
| LOW_IV | STRONG_BEARISH | any | Long put spread (tight) | 3-5 |
| SPIKE | any | any | Small debit spread or stand aside | 3-5 |

**Override rules:**
- SHORT_GAMMA → never sell iron condor. Switch to directional or stand aside.
- Within 24h of FOMC/CPI → no new credit. Debit only, small size.
- Price below gamma flip → reduce credit size by 50%.

---

## Exit rules

| Strategy | Profit target | Stop loss | Time exit |
|---|---|---|---|
| Iron condor | 50% of credit | 2x credit | Close at 1 DTE |
| Credit spread | 50% of credit | 2x credit | Close at 1 DTE |
| Debit spread | 50-75% of debit | 50% of debit | Close at 2 DTE |
| Butterfly | 100%+ of debit | Full debit (let expire) | Close at 0 DTE close |

---

## Conviction score

| Component | Weight |
|---|---|
| Vol regime alignment | 20% |
| Directional conviction | 20% |
| Dealer regime alignment | 20% |
| GARCH edge magnitude | 15% |
| IV rank in sweet spot | 10% |
| Liquidity (spread + OI) | 10% |
| Greeks quality (theta/vega) | 5% |

Show if >= 60. Highlight if >= 75.

---

## Backtest priority

1. Iron condors: LONG_GAMMA filter vs all conditions
2. Iron condors: HIGH_IV filter vs all conditions
3. Credit spreads: with vs without directional bias filter
4. Credit spreads: GARCH edge > 5% vs all
5. Iron condors: 3-5 vs 5-7 vs 7-10 vs 10-14 DTE
6. All strategies: 50% profit target vs hold to expiry
