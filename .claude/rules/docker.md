# Docker & Deployment Rules
# Applies when working with: Dockerfile, docker-compose.yml, start.sh, .env

## Quick commands
```bash
./start.sh              # Launch app on localhost:8000
./start.sh test         # Run pytest suite
./start.sh scan         # CLI scan: SPY,QQQ,IWM
./start.sh backtest     # Run backtest
./start.sh shell        # Interactive dev shell
./start.sh stop         # Stop everything
./start.sh clean        # Stop + remove containers/images
```

## Image reuse — IMPORTANT
Only two images: `options_analyzer:prod` and `options_analyzer:dev`.
All services reference one of these via `image:`. Only `app` (prod) and
`test` (dev) have `build:` blocks. Never add `build:` to new services.

## Rebuild after code changes
```bash
docker compose down
docker compose build --no-cache app   # rebuilds options_analyzer:prod
docker compose up app
```
The `--no-cache` is important when provider code changes — Docker layer
caching can serve stale Python files.

## When rebuild is NOT needed
- `config/agents.yaml` — bind-mounted at runtime
- `./data/` — bind-mounted volume
- `.env` — read at container start

## Environment
- `.env` file at project root (created from .env.example on first run)
- FLASHALPHA_API_KEY: optional, chain-based fallback works without it
- Port 8000 internal, may be mapped to 9000 externally

## Data persistence
- `./data/` volume mount for SQLite databases
- Backtest cache lives in `src/backtest/cache.py`
