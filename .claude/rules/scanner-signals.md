# Scanner & Signal Rules
# Applies when working in: src/scanner/, src/regime/, src/bias_detector.py

## Regime thresholds (iv_rank.py)
Three regimes + spike. No ELEVATED or NORMAL.
- HIGH_IV: IV rank > 50, VIX < 25, contango
- MODERATE_IV: IV rank 30-50, VIX < 20
- LOW_IV: IV rank < 30, VIX < 18
- SPIKE: VIX > 30 or backwardation

VIX at 63rd percentile with contango → HIGH_IV, not MODERATE_IV.

## Bias detector (bias_detector.py)
Input: pandas DataFrame of daily OHLCV. NOT a pre-computed signal dict.
Output: BiasResult(label, score, detail)
Signals: EMA 9/21, RSI(14), MACD histogram, prior candle, 2-day momentum, ATR percentile.
NO SMA 50/200, golden cross, or stochastic. Those are swing-timeframe signals.

## Dealer positioning
Primary: FlashAlpha API (if key configured).
Fallback: compute from chain data — max pain from OI, P/C ratio, basic GEX from gamma×OI.
Signals F1-F7 defined in SIGNALS.md.
Output: LONG_GAMMA or SHORT_GAMMA.

## Decision matrix (strategy_mapper.py)
Three inputs: (regime, bias, dealer_regime) → strategy.
Full matrix in SIGNALS.md § Decision matrix.
Override: SHORT_GAMMA → never sell iron condor.

## Strategy pricer (strategy_pricer.py)
Use GEX walls (F3/F4) and max pain (F5) for strike placement.
Do NOT use fixed delta increments when dealer data is available.

## Conviction scoring
Weights in src/config.py CHAIN_SCANNER_CONFIG.scoring_weights:
vol_regime=20%, directional=20%, dealer_regime=20%, garch_edge=15%,
iv_rank=10%, liquidity=10%, greeks=5%.
Show score if >= 60. Highlight if >= 75.
