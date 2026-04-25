# CLAUDE.md — Index Options Scanner

0-14 DTE defined-risk options scanner. Three-layer signal architecture.
Docker deployment. FastAPI + React. Runs on `localhost:9000`.

**Read SIGNALS.md before touching any signal logic.**

## Architecture

```
Watchlist → ChainProvider → [Vol Regime → Bias → Dealer] → Decision Matrix → Strategy + Conviction Score
```

Three signal layers decide every trade:
1. **Vol regime** (V1-V5): sell premium or buy it? → HIGH_IV / MODERATE_IV / LOW_IV / SPIKE
2. **Directional bias** (D1-D8): which way? → STRONG_BULLISH → STRONG_BEARISH
3. **Dealer positioning** (F1-F7): where does price stick? → LONG_GAMMA / SHORT_GAMMA

## Stack

- Python 3.11+, FastAPI, Pydantic v2
- React + Vite frontend
- Docker via `./start.sh` (compose on port 8000, proxied to 9000)
- yfinance for chain data, chain-based GEX fallback (no FlashAlpha key needed)
- `ruff` for linting, `pytest` for tests

## Five strategies (defined-risk only)

| Strategy | Regime | DTE |
|---|---|---|
| Iron condor | HIGH_IV + LONG_GAMMA | 7-14 |
| Short put spread | HIGH_IV + bullish bias | 3-10 |
| Short call spread | HIGH_IV + bearish bias | 3-10 |
| Long call/put spread | LOW/MODERATE_IV + directional | 3-14 |
| Butterfly | MODERATE/LOW_IV, pin at max pain | 0-7 |

No calendars, diagonals, strangles, straddles, or naked options.
Deferred strategies live in `src/strategies/_deferred/` for a future swing tab.

## Key files

| Purpose | File |
|---|---|
| Signal definitions | `SIGNALS.md` |
| User guide | `HOWTO.md` |
| Config + weights | `src/config.py` |
| Vol regime | `src/regime/detector.py`, `src/scanner/iv_rank.py` |
| Directional bias | `src/bias_detector.py` |
| Dealer positioning | `src/scanner/providers/flashalpha_client.py` |
| Decision matrix | `src/scanner/strategy_mapper.py` |
| Conviction scoring | `src/scanner/scorer.py` |
| Strike placement | `src/scanner/strategy_pricer.py` |
| Scan orchestration | `src/scanner/scanner.py`, `src/strategy_scanner.py` |
| Backtesting | `src/backtest/local_backtest.py`, `src/backtest/analyzer.py` |
| API server | `src/ui/app.py` |
| Frontend entry | `frontend/src/App.jsx` |

## Frozen files — never modify logic

```
src/models/black_scholes.py
src/monte_carlo/gbm_simulator.py
src/monte_carlo/garch_vol.py
src/monte_carlo/jump_diffusion.py
src/monte_carlo/american_mc.py
src/monte_carlo/mc_greeks.py
src/monte_carlo/risk_metrics.py
src/scanner/edge.py
src/scanner/scorer.py
src/scanner/providers/base.py
src/scanner/providers/cached_provider.py
```

## Dev rules

1. Read `SIGNALS.md` before implementing any signal logic.
2. Do not modify frozen files.
3. One step at a time. Test before moving on.
4. Pydantic v2 for all new models.
5. Conviction weights live in `src/config.py` `CHAIN_SCANNER_CONFIG.scoring_weights`.
6. All strategies are defined-risk. No naked exposure.
7. `./start.sh` is the single entry point. `./start.sh test` runs the suite.

## Current status

- App running in Docker on localhost:9000
- Regime dashboard live with VIX data
- Chain-based GEX fallback committed (no FlashAlpha key needed)
- Dealer positioning may show "unavailable" — rebuild with `docker compose build --no-cache app`

## What's next

See `.claude/rules/` for path-scoped implementation details.
Priority order:
1. Verify dealer data displays after Docker rebuild
2. Verify regime classification thresholds (63rd pctl → HIGH_IV?)
3. Build backtest UI with compare mode, signal filter toggles, DTE breakdown
4. Run 6 validation backtests from SIGNALS.md
