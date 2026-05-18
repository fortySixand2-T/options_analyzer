"""
Options scanner configuration.
All settings are read from environment variables with sensible defaults.
Four DTE tiers: chain (0-14), swing (14-60), medium-term (30-90), long-term (90-180).
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

# ── Swing scanner defaults (14-60 DTE) ──────────────────────────────────
SWING_SCANNER_CONFIG = {
    "filter": {
        "min_dte": 14,
        "max_dte": 60,
        "min_delta": 0.10,
        "max_delta": 0.50,
        "min_open_interest": 200,
        "max_spread_pct": 12.0,
        "moneyness_range": [0.85, 1.15],
    },
    # Calibrated from Phase 5 regression (SPY 2022-2026):
    #   iv_at_entry significant for calendar/diagonal (t~1.7)
    #   swing_bias significant for iron_butterfly (t=1.69)
    #   edge_pct significant for long_straddle (t=-2.04, negative = buy vol cheap)
    #   VRP needs real chain data — keep weight but can't validate yet
    "scoring_weights": {
        "vol_regime": 0.25,
        "vrp": 0.20,
        "term_structure": 0.15,
        "garch_edge": 0.15,
        "directional": 0.10,
        "dealer_regime": 0.10,
        "liquidity": 0.05,
    },
}

# ── Medium-term scanner (30-90 DTE) ────────────────────────────────────
# VRP is the primary edge at this horizon (Sharpe 0.5-0.6, Carr & Wu 2009).
# Skew and cross-asset signals become actionable here.
MEDIUM_TERM_SCANNER_CONFIG = {
    "filter": {
        "min_dte": 30,
        "max_dte": 90,
        "min_delta": 0.10,
        "max_delta": 0.50,
        "min_open_interest": 500,
        "max_spread_pct": 10.0,
        "moneyness_range": [0.85, 1.15],
    },
    "scoring_weights": {
        "vrp": 0.25,
        "skew": 0.15,
        "term_structure": 0.15,
        "cross_asset": 0.10,
        "flow": 0.10,
        "vol_regime": 0.10,
        "directional": 0.10,
        "liquidity": 0.05,
    },
}

# ── Long-term scanner (90-180 DTE) ─────────────────────────────────────
# Correlation premium and cross-asset divergences dominate at this horizon.
# VRP still relevant but slower-moving. Flow signals have longer lead times.
LONG_TERM_SCANNER_CONFIG = {
    "filter": {
        "min_dte": 90,
        "max_dte": 180,
        "min_delta": 0.10,
        "max_delta": 0.45,
        "min_open_interest": 300,
        "max_spread_pct": 8.0,
        "moneyness_range": [0.85, 1.15],
    },
    "scoring_weights": {
        "vrp": 0.20,
        "cross_asset": 0.20,
        "skew": 0.15,
        "flow": 0.15,
        "term_structure": 0.10,
        "vol_regime": 0.10,
        "directional": 0.05,
        "liquidity": 0.05,
    },
}
