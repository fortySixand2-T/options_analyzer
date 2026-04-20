#!/usr/bin/env bash
#
# Build and run the Options Scanner app in Docker.
#
# Usage:
#   ./scripts/run.sh              # Start the full app (API + UI)
#   ./scripts/run.sh build        # Build Docker images only
#   ./scripts/run.sh test         # Run test suite
#   ./scripts/run.sh scan         # Run one-off scan
#   ./scripts/run.sh backtest     # Run one-off backtest
#   ./scripts/run.sh shell        # Interactive dev shell
#   ./scripts/run.sh stop         # Stop all services
#   ./scripts/run.sh logs         # Tail logs

set -euo pipefail
cd "$(dirname "$0")/.."

CMD="${1:-up}"

# Create .env from example if it doesn't exist
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "[*] Created .env from .env.example — edit it with your credentials"
fi

# Ensure data directory exists for SQLite DBs
mkdir -p data

case "$CMD" in
    build)
        echo "[*] Building Docker images..."
        docker-compose build
        ;;
    up|start)
        echo "[*] Starting Options Scanner (API on :8000)..."
        docker-compose up --build app
        ;;
    test)
        echo "[*] Running test suite..."
        docker-compose build test
        docker-compose run --rm test
        ;;
    scan)
        shift || true
        echo "[*] Running scan..."
        docker-compose run --rm scan ${@:-}
        ;;
    backtest)
        shift || true
        echo "[*] Running backtest..."
        docker-compose run --rm backtest ${@:-}
        ;;
    shell)
        echo "[*] Starting dev shell..."
        docker-compose run --rm shell
        ;;
    stop)
        echo "[*] Stopping all services..."
        docker-compose down
        ;;
    logs)
        docker-compose logs -f
        ;;
    *)
        echo "Usage: $0 {build|up|test|scan|backtest|shell|stop|logs}"
        exit 1
        ;;
esac
