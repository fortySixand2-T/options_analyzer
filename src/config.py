"""
Options scanner configuration.
All settings are read from environment variables with sensible defaults
so they integrate cleanly with Trading Copilot's existing .env pattern.
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

# DTE windows per outlook
OUTLOOKS: dict = {
    "short":  {"min_dte": 7,   "max_dte": 21},
    "medium": {"min_dte": 30,  "max_dte": 60},
    "long":   {"min_dte": 61,  "max_dte": 120},
}

# ── Chain scanner defaults ─────────────────────────────────────────────
CHAIN_SCANNER_CONFIG = {
    "filter": {
        "min_dte": int(os.getenv("SCANNER_MIN_DTE", "20")),
        "max_dte": int(os.getenv("SCANNER_MAX_DTE", "60")),
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
        "edge": 0.40,
        "iv_rank": 0.25,
        "liquidity": 0.20,
        "greeks": 0.15,
    },
}
