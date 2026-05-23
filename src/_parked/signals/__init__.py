"""
Intraday signal layer for 0 DTE options.

Modules:
    day_classifier  — Range vs trend day classification (most important 0 DTE signal)
    move_exhaustion — How much of expected daily move has been consumed
    intraday_gex    — Recompute dealer positioning from intraday chain snapshots
    intraday_state  — Build complete IntradayState from all signal sources
"""
