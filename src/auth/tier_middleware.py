"""Tier-based access control — restrict features by user tier (free/pro)."""

from functools import wraps
from fastapi import Depends, HTTPException

from src.auth.dependencies import get_current_user

TIER_LIMITS = {
    "free": {
        "watchlist_max": 3,
        "alerts_max": 5,
        "backtests_per_day": 10,
        "positions_max": 10,
        "scheduled_scans": False,
    },
    "pro": {
        "watchlist_max": 999,
        "alerts_max": 999,
        "backtests_per_day": 999,
        "positions_max": 999,
        "scheduled_scans": True,
    },
}


def get_tier_limits(user: dict) -> dict:
    """Get limits for user's current tier."""
    tier = user.get("tier", "free")
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def require_tier(min_tier: str):
    """Dependency that checks user has at least the specified tier."""
    tier_order = {"free": 0, "pro": 1}

    def dependency(user: dict = Depends(get_current_user)):
        user_level = tier_order.get(user.get("tier", "free"), 0)
        required_level = tier_order.get(min_tier, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {min_tier} tier. Current tier: {user.get('tier', 'free')}",
            )
        return user

    return dependency
