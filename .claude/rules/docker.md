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

## Rebuild after code changes
```bash
docker compose down
docker compose build --no-cache app
docker compose up app
```
The `--no-cache` is important when provider code changes — Docker layer
caching can serve stale Python files.

## Environment
- `.env` file at project root (created from .env.example on first run)
- FLASHALPHA_API_KEY: optional, chain-based fallback works without it
- Port 8000 internal, may be mapped to 9000 externally

## Data persistence
- `./data/` volume mount for SQLite databases
- Backtest cache lives in `src/backtest/cache.py`
