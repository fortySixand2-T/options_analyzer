"""
Options scanner configuration.
All settings are read from environment variables with sensible defaults.
Calibrated for 0-14 DTE index options.
"""
import os

# ── Pricing ───────────────────────────────────────────────────────────────────
RISK_FREE_RATE  = float(os.getenv("OPTIONS_RISK_FREE_RATE", "0.045"))

# ── Monte Carlo ───────────────────────────────────────────────────────────────
MC_NUM_PATHS = int(os.getenv("OPTIONS_MC_PATHS", "5000"))
MC_NUM_STEPS = int(os.getenv("OPTIONS_MC_STEPS", "252"))
MC_SEED      = int(os.getenv("OPTIONS_MC_SEED",  "42"))

# ── Strategy parameters ────────────────────────────────────────────────────────
OPTION_STOP_PCT  = float(os.getenv("OPTIONS_STOP_PCT",       "0.50"))
BIAS_THRESHOLD   = int(os.getenv("OPTIONS_BIAS_THRESHOLD",   "3"))

# DTE windows for 0-14 DTE index options
OUTLOOKS: dict = {
    "short":  {"min_dte": 0,  "max_dte": 5},
    "medium": {"min_dte": 5,  "max_dte": 10},
    "long":   {"min_dte": 10, "max_dte": 14},
}

# ── Chain scanner defaults ─────────────────────────────────────────────
CHAIN_SCANNER_CONFIG = {
    "filter": {
        "min_dte": int(os.getenv("SCANNER_MIN_DTE", "0")),
        "max_dte": int(os.getenv("SCANNER_MAX_DTE", "14")),
        "min_delta": 0.15,
        "max_delta": 0.50,
        "min_open_interest": 100,
        "max_spread_pct": 15.0,
        "moneyness_range": [0.85, 1.15],
    },
    "garch": {
        "history_days": 120,
        "min_returns": 30,
    },
    "scoring_weights": {
        "vol_regime": 0.20,
        "directional": 0.20,
        "dealer_regime": 0.20,
        "garch_edge": 0.15,
        "iv_rank": 0.10,
        "liquidity": 0.10,
        "greeks": 0.05,
    },
}
