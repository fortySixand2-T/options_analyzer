#!/usr/bin/env bash
#
# Morning short-DTE chain snapshot — 1-7 DTE index options only.
# Captures intraday IV state for the contracts our system actually trades.
#
# Crontab entry:
#   7 10 * * 1-5 /Users/sirius/projects/options_analyzer/scripts/daily_collect_shortdte.sh >> /Users/sirius/projects/options_analyzer/data/collect.log 2>&1
#
# Runs at 10:07 AM weekdays (after spreads tighten post-open).

set -euo pipefail
cd /Users/sirius/projects/options_analyzer

TICKERS="^SPX,SPY,^NDX,QQQ"
MIN_DTE=1
MAX_DTE=7

echo ""
echo "=========================================="
echo "Short-DTE collection — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

if docker compose version &> /dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "ERROR: docker compose not available"
    exit 1
fi

$COMPOSE run --rm collect python scripts/collect_chains.py "$TICKERS" \
    --min-dte "$MIN_DTE" --max-dte "$MAX_DTE" --label shortdte

echo "Short-DTE collection finished at $(date '+%H:%M:%S')"
