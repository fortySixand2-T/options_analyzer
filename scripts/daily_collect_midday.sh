#!/usr/bin/env bash
#
# Midday chain snapshot — all 10 tickers, short-DTE focus.
# Captures IV/OI state near market close for comparison with morning snapshot.
#
# Crontab entry:
#   23 12 * * 1-5 /Users/sirius/projects/options_analyzer/scripts/daily_collect_midday.sh >> /Users/sirius/projects/options_analyzer/data/collect.log 2>&1
#
# Runs at 12:23 PM PDT weekdays (~3:23 PM ET, 37 min before close).

set -euo pipefail
cd /Users/sirius/projects/options_analyzer

TICKERS="SPY,QQQ,^SPX,^NDX,IWM,META,AAPL,AMZN,NFLX,GOOG"
MIN_DTE=0
MAX_DTE=14

echo ""
echo "=========================================="
echo "Midday collection — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
COMPOSE="docker-compose"

if ! docker info &>/dev/null 2>&1; then
    echo "ERROR: Docker is not running — skipping midday collection"
    exit 1
fi

$COMPOSE run --rm collect python scripts/collect_chains.py "$TICKERS" \
    --min-dte "$MIN_DTE" --max-dte "$MAX_DTE" --label midday

echo "Midday collection finished at $(date '+%H:%M:%S')"
