#!/usr/bin/env bash
# build.sh — Setup and verify the options pricing project
#
# Usage:
#   ./build.sh              # setup + run all tests
#   ./build.sh --demo       # also run example demos
#   ./build.sh --mc         # also run MC CLI smoke test
#   ./build.sh --full       # everything
#   ./build.sh --help

set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────
VENV_PATH="/Users/sirius/projects/environments/options_env"
PYTHON_MIN="3.8"
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Flags ──────────────────────────────────────────────────────────────────
RUN_DEMO=false
RUN_MC=false

for arg in "$@"; do
  case "$arg" in
    --demo) RUN_DEMO=true ;;
    --mc)   RUN_MC=true ;;
    --full) RUN_DEMO=true; RUN_MC=true ;;
    --help)
      echo "Usage: ./build.sh [--demo] [--mc] [--full] [--help]"
      echo "  --demo   Run example demos after tests"
      echo "  --mc     Run MC CLI smoke test after tests"
      echo "  --full   Run everything (demos + MC smoke test)"
      exit 0 ;;
    *)
      echo "Unknown flag: $arg  (use --help for usage)"
      exit 1 ;;
  esac
done

# ── Helpers ────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${YELLOW}▶${NC} $*"; }
fail() { echo -e "${RED}✗ $*${NC}"; exit 1; }
hr()   { echo "────────────────────────────────────────────────────────────"; }

cd "$PROJECT_ROOT"

echo ""
hr
echo "  Options Pricing System — Build"
hr
echo ""

# ── 1. Python check ────────────────────────────────────────────────────────
info "Checking Python..."
if ! command -v python3 &>/dev/null; then
  fail "python3 not found. Install Python ${PYTHON_MIN}+."
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python ${PY_VER} found"

# ── 2. Virtual environment ────────────────────────────────────────────────
info "Setting up virtual environment..."
if [[ ! -d "$VENV_PATH" ]]; then
  info "Creating new venv at ${VENV_PATH}..."
  python3 -m venv "$VENV_PATH"
  ok "venv created"
else
  ok "venv exists: ${VENV_PATH}"
fi

# shellcheck disable=SC1090
source "${VENV_PATH}/bin/activate"
ok "venv activated ($(python --version))"

# ── 3. Dependencies ────────────────────────────────────────────────────────
info "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed"

# ── 4. Verify imports ─────────────────────────────────────────────────────
info "Verifying key imports..."
python - <<'PYCHECK'
import sys
sys.path.insert(0, 'src')

import numpy, scipy, pandas, matplotlib
from models.black_scholes import black_scholes_price
from monte_carlo.gbm_simulator import simulate_gbm_paths, run_monte_carlo
from monte_carlo.risk_metrics import compute_var, compute_cvar
from utils.config import load_config_from_json
print("  All imports OK")
PYCHECK
ok "Imports verified"

# ── 5. Create required directories ────────────────────────────────────────
info "Ensuring output directories exist..."
mkdir -p analysis_results/mc_demo mc_results exports
ok "Output directories ready"

# ── 6. Run tests ──────────────────────────────────────────────────────────
info "Running test suite..."
echo ""
python -m pytest tests/ -v --tb=short
echo ""
ok "All tests passed"

# ── 7. Optional: MC CLI smoke test ────────────────────────────────────────
if [[ "$RUN_MC" == true ]]; then
  hr
  info "Running MC CLI smoke test..."
  python src/mc_runner.py \
    --json config/mc_config.json \
    --num_paths 2000 \
    --seed 42 \
    --export_dir ./mc_results
  ok "MC CLI smoke test passed"
fi

# ── 8. Optional: demos ────────────────────────────────────────────────────
if [[ "$RUN_DEMO" == true ]]; then
  hr
  info "Running Monte Carlo demo..."
  python examples/monte_carlo_demo.py
  ok "Demo complete — plots saved to analysis_results/mc_demo/"

  info "Running basic BS usage demo..."
  python examples/basic_usage.py
  ok "Basic usage demo complete"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
hr
echo -e "${GREEN}  Build successful.${NC}"
hr
echo ""
echo "  Next steps:"
echo "    python src/mc_runner.py --json config/mc_config.json --plot"
echo "    python src/options_test_runner.py --json config/option_configs.json"
echo "    python examples/monte_carlo_demo.py"
echo ""
