#!/usr/bin/env bash
#
# Index Options Scanner — one-command launcher
#
# Usage:
#   ./start.sh                  # Launch the app (detached, stays running)
#   ./start.sh scan             # Run a quick scan from CLI
#   ./start.sh backtest         # Run a backtest
#   ./start.sh collect          # Collect daily chain snapshots
#   ./start.sh collect-stats    # Show snapshot DB statistics
#   ./start.sh test             # Run test suite
#   ./start.sh shell            # Interactive dev shell
#   ./start.sh dev              # Foreground with hot-reload
#   ./start.sh stop             # Stop everything
#   ./start.sh logs             # Tail app logs
#   ./start.sh build            # Rebuild Docker images
#   ./start.sh restart          # Stop + rebuild + start
#   ./start.sh status           # Show running containers
#   ./start.sh clean            # Stop + remove containers/images
#
# First run will:
#   1. Create .env from .env.example (edit with your TT credentials)
#   2. Create data/ directory for SQLite databases
#   3. Build Docker images (~2-3 min first time)
#   4. Start the app on http://localhost:8000

set -euo pipefail

# Always run from project root regardless of where script is called from
cd "$(dirname "$0")"
# If we're in scripts/, go up one level
[[ "$(basename "$(pwd)")" == "scripts" ]] && cd ..

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

CMD="${1:-up}"

banner() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   ${NC}Index Options Scanner              ${BLUE}║${NC}"
    echo -e "${BLUE}║   ${NC}Short-term options decision tool   ${BLUE}║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
    echo ""
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is not installed.${NC}"
        echo "  Install Docker Desktop: https://www.docker.com/products/docker-desktop"
        exit 1
    fi
    if ! docker info &> /dev/null 2>&1; then
        echo -e "${RED}Error: Docker daemon is not running.${NC}"
        echo "  Start Docker Desktop and try again."
        exit 1
    fi
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v docker-compose &> /dev/null 2>&1; then
        COMPOSE="docker-compose"
    else
        echo -e "${RED}Error: docker compose not available.${NC}"
        exit 1
    fi
}

setup_env() {
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            echo -e "${YELLOW}Created .env from .env.example${NC}"
            echo ""
            echo -e "${YELLOW}To use live Tastytrade data, edit .env and add:${NC}"
            echo "  TT_USERNAME=your_username"
            echo "  TT_PASSWORD=your_password"
            echo ""
            echo -e "Without credentials, the scanner uses ${GREEN}yfinance (delayed data)${NC} as fallback."
            echo ""
        else
            echo -e "${RED}No .env.example found — cannot create .env${NC}"
            exit 1
        fi
    fi
    mkdir -p data
}

wait_for_healthy() {
    local max_wait=30
    local waited=0
    echo -ne "  Waiting for server"
    while [ $waited -lt $max_wait ]; do
        if ! $COMPOSE ps app 2>/dev/null | grep -q "Up\|running"; then
            sleep 1
            waited=$((waited + 1))
            echo -n "."
            continue
        fi
        if curl -sf http://localhost:8000/docs > /dev/null 2>&1; then
            echo ""
            echo -e "  ${GREEN}✓ Server is up${NC}"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
        echo -n "."
    done
    echo ""
    echo -e "  ${YELLOW}Server may still be starting — check: ./start.sh logs${NC}"
}

check_docker

case "$CMD" in
    up|start|"")
        banner
        setup_env
        echo -e "${GREEN}Building and starting Options Scanner...${NC}"
        $COMPOSE up -d --build app
        echo ""
        echo -e "  Backend API:  ${BLUE}http://localhost:8000${NC}"
        echo -e "  API docs:     ${BLUE}http://localhost:8000/docs${NC}"
        echo -e "  Web UI:       ${BLUE}http://localhost:8000${NC}"
        echo ""
        wait_for_healthy
        echo ""
        echo -e "  ${GREEN}App is running in the background.${NC}"
        echo -e "  Logs:    ${YELLOW}./start.sh logs${NC}"
        echo -e "  Stop:    ${YELLOW}./start.sh stop${NC}"
        echo -e "  Rebuild: ${YELLOW}./start.sh restart${NC}"
        echo ""
        ;;

    dev)
        banner
        setup_env
        echo -e "${GREEN}Starting in dev mode (foreground, hot-reload)...${NC}"
        echo -e "  Backend API:  ${BLUE}http://localhost:8000${NC}"
        echo -e "  Frontend dev: ${BLUE}http://localhost:3000${NC} (if running npm dev separately)"
        echo ""
        echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
        echo ""
        $COMPOSE run --rm --service-ports -e PYTHONPATH=/app/src shell \
            python -m uvicorn ui.app:app --host 0.0.0.0 --port 8000 --reload
        ;;

    fg|foreground)
        banner
        setup_env
        echo -e "${GREEN}Starting in foreground (Ctrl+C to stop)...${NC}"
        echo -e "  Backend API:  ${BLUE}http://localhost:8000${NC}"
        echo ""
        $COMPOSE up --build app
        ;;

    scan)
        setup_env
        shift || true
        ARGS="${*:-SPY,QQQ,IWM --strategies --top 10}"
        echo -e "${GREEN}Running scan: ${NC}$ARGS"
        $COMPOSE run --rm scan python scripts/scan.py $ARGS
        ;;

    backtest)
        setup_env
        shift || true
        ARGS="${*:---strategy iron_condor --symbol SPY}"
        echo -e "${GREEN}Running backtest: ${NC}$ARGS"
        $COMPOSE run --rm backtest python scripts/run_backtest.py $ARGS
        ;;

    collect-intraday)
        setup_env
        shift || true
        MODE="${1:-bars}"
        shift || true
        ARGS="$*"
        echo -e "${GREEN}Intraday collection (${MODE}): ${NC}$ARGS"
        $COMPOSE run --rm collect-intraday python scripts/collect_intraday.py $MODE $ARGS
        ;;

    collect)
        setup_env
        shift || true
        ARGS="${*:-SPY,QQQ,IWM}"
        echo -e "${GREEN}Collecting chain snapshots: ${NC}$ARGS"
        $COMPOSE run --rm collect python scripts/collect_chains.py $ARGS
        ;;

    collect-stats)
        setup_env
        echo -e "${GREEN}Chain snapshot database stats:${NC}"
        $COMPOSE run --rm collect python scripts/collect_chains.py --stats
        ;;

    test)
        echo -e "${GREEN}Running test suite...${NC}"
        $COMPOSE run --rm test
        ;;

    shell)
        setup_env
        echo -e "${GREEN}Starting dev shell...${NC}"
        echo -e "  PYTHONPATH is set to /app/src"
        echo -e "  Try: python scripts/scan.py SPY --top 5"
        echo ""
        $COMPOSE run --rm shell
        ;;

    build)
        echo -e "${GREEN}Building Docker images (no cache)...${NC}"
        $COMPOSE build --no-cache
        echo -e "${GREEN}Build complete. Run ./start.sh to launch.${NC}"
        ;;

    restart)
        echo -e "${YELLOW}Restarting...${NC}"
        $COMPOSE down
        $COMPOSE up -d --build app
        wait_for_healthy
        echo -e "${GREEN}Restarted.${NC}"
        ;;

    stop)
        echo -e "${YELLOW}Stopping all services...${NC}"
        $COMPOSE down
        echo -e "${GREEN}Stopped.${NC}"
        ;;

    logs)
        $COMPOSE logs -f app
        ;;

    status)
        $COMPOSE ps
        ;;

    clean)
        echo -e "${RED}Stopping and removing all containers + images...${NC}"
        $COMPOSE down --rmi local --volumes --remove-orphans
        echo -e "${GREEN}Cleaned.${NC}"
        ;;

    *)
        echo "Usage: ./start.sh [command]"
        echo ""
        echo "Commands:"
        echo "  (none), up    Start the app detached (stays running)"
        echo "  dev           Start with hot-reload (foreground)"
        echo "  fg            Start in foreground (Ctrl+C to stop)"
        echo "  scan          Run a CLI scan (pass args after command)"
        echo "  backtest      Run a backtest (pass args after command)"
        echo "  collect       Collect daily chain snapshots (pass tickers after)"
        echo "  collect-stats Show chain snapshot database statistics"
        echo "  test          Run the test suite"
        echo "  shell         Interactive dev shell"
        echo "  build         Rebuild Docker images (no cache)"
        echo "  restart       Stop + rebuild + start"
        echo "  stop          Stop all services"
        echo "  logs          Tail app logs"
        echo "  status        Show running containers"
        echo "  clean         Stop + remove everything"
        echo ""
        echo "Examples:"
        echo "  ./start.sh                    # start detached"
        echo "  ./start.sh scan SPY,QQQ --strategies --top 5"
        echo "  ./start.sh backtest --strategy iron_condor --symbol SPY"
        echo "  ./start.sh collect SPY,QQQ,IWM --max-dte 30"
        echo "  ./start.sh collect-stats"
        echo "  ./start.sh restart            # rebuild + relaunch"
        exit 1
        ;;
esac
