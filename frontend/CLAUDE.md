# CLAUDE.md — Frontend

React + Vite app. Served by FastAPI in Docker.

## Components

| Component | Purpose | Status |
|---|---|---|
| RegimeDashboard.jsx | VIX, term structure, IV rank, dealer regime badge | Live, needs GEX display |
| Scanner.jsx | Scan results with checklist, bias, dealer regime | Built, needs dealer data |
| Backtest.jsx | Backtest runner + results | Built, needs major expansion |
| GreeksExplorer.jsx | Interactive greeks visualization | Built |
| Journal.jsx | Trade journal | Built |

## API base

All calls go to `/api/` (proxied via Vite config to FastAPI on port 8000).

Key endpoints:
- `GET /api/regime` — current vol regime + dealer data
- `GET /api/scan` — run scanner, returns ranked opportunities
- `GET /api/backtest/{strategy}` — backtest with filter params
- `GET /api/backtest/compare` — multi-strategy comparison

## Styling

Dashboard.css handles the regime dashboard. Use CSS variables for theming.
No Tailwind — plain CSS modules.

## Rules

- Do not add npm dependencies without justification.
- Keep components under 400 lines. Extract hooks to `src/hooks/`.
- API calls go through `src/hooks/useApi.js`.
- Only show 4 active strategies in dropdowns: iron_condor, credit_spread, debit_spread, butterfly.
