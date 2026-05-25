"""Shared test fixtures."""

import os
import tempfile

os.environ.setdefault("AUTH_DB_PATH", os.path.join(tempfile.mkdtemp(), "test_users.db"))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-tests")
os.environ.setdefault("USER_DB_PATH", os.path.join(tempfile.mkdtemp(), "test_user_db.db"))

import pytest
from fastapi.testclient import TestClient
from src.auth.router import limiter
from src.auth.database import init_auth_db
from src.data.user_db import init_user_tables


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset slowapi rate limiter between tests so limits don't carry over."""
    yield
    limiter.reset()


def get_auth_headers(client: TestClient, email="testuser@example.com", password="testpass123", display_name="Test") -> dict:
    """Register a user and return Authorization headers with a valid JWT."""
    init_auth_db()
    init_user_tables()
    res = client.post("/api/auth/register", json={
        "email": email, "password": password, "display_name": display_name,
    })
    if res.status_code == 409:
        res = client.post("/api/auth/login", json={"email": email, "password": password})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
