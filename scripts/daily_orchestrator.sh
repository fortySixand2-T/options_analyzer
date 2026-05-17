#!/usr/bin/env bash
#
# Multi-agent orchestrator — daily paper trading cycle.
# Runs Mon-Fri at market open + 30min (10:00 AM ET / 7:00 AM PDT).
#
# Crontab entry:
#   0 7 * * 1-5 /Users/sirius/projects/options_analyzer/scripts/daily_orchestrator.sh >> /Users/sirius/projects/options_analyzer/data/orchestrator.log 2>&1

set -euo pipefail
cd /Users/sirius/projects/options_analyzer

echo ""
echo "=========================================="
echo "Orchestrator cycle — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
COMPOSE="docker-compose"

if ! docker info &>/dev/null 2>&1; then
    echo "ERROR: Docker is not running — skipping orchestrator cycle"
    exit 1
fi

$COMPOSE run --rm orchestrator python scripts/run_orchestrator.py

echo "Orchestrator cycle finished at $(date '+%H:%M:%S')"
