"""Tests for tier middleware — src/auth/tier_middleware.py"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from src.auth.tier_middleware import get_tier_limits, require_tier, TIER_LIMITS


class TestGetTierLimits:
    def test_free_user(self):
        limits = get_tier_limits({"tier": "free"})
        assert limits["watchlist_max"] == 3
        assert limits["alerts_max"] == 5
        assert limits["scheduled_scans"] is False

    def test_pro_user(self):
        limits = get_tier_limits({"tier": "pro"})
        assert limits["watchlist_max"] == 999
        assert limits["scheduled_scans"] is True

    def test_missing_tier_defaults_to_free(self):
        limits = get_tier_limits({})
        assert limits == TIER_LIMITS["free"]

    def test_unknown_tier_defaults_to_free(self):
        limits = get_tier_limits({"tier": "enterprise"})
        assert limits == TIER_LIMITS["free"]


class TestRequireTier:
    def test_returns_callable(self):
        dep = require_tier("pro")
        assert callable(dep)

    def test_free_user_blocked_from_pro(self):
        from fastapi import HTTPException
        dep = require_tier("pro")
        with pytest.raises(HTTPException) as exc:
            dep(user={"id": 1, "tier": "free"})
        assert exc.value.status_code == 403

    def test_pro_user_passes_pro_check(self):
        dep = require_tier("pro")
        result = dep(user={"id": 1, "tier": "pro"})
        assert result["tier"] == "pro"

    def test_pro_user_passes_free_check(self):
        dep = require_tier("free")
        result = dep(user={"id": 1, "tier": "pro"})
        assert result["tier"] == "pro"

    def test_free_user_passes_free_check(self):
        dep = require_tier("free")
        result = dep(user={"id": 1, "tier": "free"})
        assert result["tier"] == "free"
