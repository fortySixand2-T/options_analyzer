#!/usr/bin/env bash
#
# Shadow trade checker — scan for new trades, check exits on open trades.
# Runs after EOD chain collection.
#
# Crontab entry:
#   42 16 * * 1-5 /Users/sirius/projects/options_analyzer/scripts/shadow_check.sh >> /Users/sirius/projects/options_analyzer/data/shadow.log 2>&1

set -euo pipefail
cd /Users/sirius/projects/options_analyzer

TICKERS="SPY,QQQ,IWM"

echo ""
echo "=========================================="
echo "Shadow check — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
COMPOSE="docker-compose"

if ! docker info &>/dev/null 2>&1; then
    echo "ERROR: Docker is not running — skipping shadow check"
    exit 1
fi

# Only scan and log — exit checking is handled by the shadow-monitor service
$COMPOSE run --rm collect python scripts/shadow_check.py --scan-and-log "$TICKERS"

echo "Shadow check finished at $(date '+%H:%M:%S')"
