# Backtest Rules
# Applies when working in: src/backtest/, frontend/src/components/Backtest.jsx

## Backend API endpoints needed
- `GET /api/backtest/{strategy}` — query params: regime_filter, bias_filter,
  dealer_filter, edge_threshold, exit_rule (50pct|hold)
- `GET /api/backtest/compare` — strategies param (comma-separated), same date range
- Response shape: { stats, equity_curve, regime_breakdown, dte_breakdown,
  pnl_distribution (histogram buckets), trades (individual trade list) }

## Frontend Backtest.jsx features to build
1. Strategy dropdown: only 4 active strategies (iron_condor, credit_spread,
   debit_spread, butterfly). Remove deferred strategies from the list.
2. Compare mode: side-by-side 2-3 strategies, combined equity curve (colored lines),
   stat comparison table.
3. Signal filter toggles (ON/OFF each):
   - Regime filter, Bias filter, Dealer regime filter, GARCH edge filter
   These answer "does each signal layer add value?"
4. DTE bucket breakdown: 0-3, 3-5, 5-7, 7-10, 10-14 DTE groups
5. P&L distribution histogram
6. Exit rule comparison: 50% profit target vs hold-to-expiry
7. Trade table: date, entry/exit price, P&L, DTE, regime, bias, dealer regime. Sortable.

## 6 validation backtests (from SIGNALS.md)
1. Iron condors: LONG_GAMMA filter ON vs OFF
2. Iron condors: HIGH_IV filter ON vs OFF
3. Credit spreads: bias filter ON vs OFF
4. Credit spreads: GARCH edge > 5% vs all
5. Iron condors: DTE bucket comparison
6. All strategies: 50% profit target vs hold-to-expiry

Use results to calibrate conviction weights. Reduce weight if filter doesn't help.
