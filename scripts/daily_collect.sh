#!/usr/bin/env bash
#
# Daily chain snapshot collector — runs after market close.
# Add to crontab: crontab -e
#   37 16 * * 1-5 /Users/sirius/projects/options_analyzer/scripts/daily_collect.sh >> /Users/sirius/projects/options_analyzer/data/collect.log 2>&1
#
# Collects: SPY, QQQ, FAANG (META, AAPL, AMZN, NFLX, GOOG)

set -euo pipefail
cd /Users/sirius/projects/options_analyzer

TICKERS="SPY,QQQ,^SPX,^NDX,IWM,META,AAPL,AMZN,NFLX,GOOG"
MAX_DTE=60

echo ""
echo "=========================================="
echo "Chain collection — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Use docker-compose (whichever is available)
if docker compose version &> /dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "ERROR: docker compose not available"
    exit 1
fi

$COMPOSE run --rm collect python scripts/collect_chains.py "$TICKERS" --max-dte "$MAX_DTE"

echo "Collection finished at $(date '+%H:%M:%S')"
