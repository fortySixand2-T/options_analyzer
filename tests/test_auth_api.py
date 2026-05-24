"""Integration tests for auth API endpoints."""

import os
import tempfile

os.environ["AUTH_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_api_users.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-api"

import pytest
from fastapi.testclient import TestClient

from src.auth.database import init_auth_db
from src.ui.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset the auth DB between tests."""
    init_auth_db()
    from src.auth.database import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM refresh_tokens")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    yield


def register_user(email="test@example.com", password="password123", display_name="Test"):
    return client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "display_name": display_name,
    })


class TestRegister:
    def test_register_success(self):
        res = register_user()
        assert res.status_code == 201
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self):
        register_user()
        res = register_user()
        assert res.status_code == 409
        assert "already registered" in res.json()["detail"]

    def test_register_short_password(self):
        res = client.post("/api/auth/register", json={
            "email": "short@test.com",
            "password": "1234567",
            "display_name": "Short",
        })
        assert res.status_code == 422

    def test_register_invalid_email(self):
        res = client.post("/api/auth/register", json={
            "email": "not-an-email",
            "password": "password123",
            "display_name": "Bad",
        })
        assert res.status_code == 422

    def test_register_missing_display_name(self):
        res = client.post("/api/auth/register", json={
            "email": "no@name.com",
            "password": "password123",
            "display_name": "",
        })
        assert res.status_code == 422


class TestLogin:
    def test_login_success(self):
        register_user()
        res = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "password123",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_wrong_password(self):
        register_user()
        res = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "wrongpassword",
        })
        assert res.status_code == 401
        assert "Incorrect" in res.json()["detail"]

    def test_login_nonexistent_user(self):
        res = client.post("/api/auth/login", json={
            "email": "nobody@test.com",
            "password": "password123",
        })
        assert res.status_code == 401


class TestRefresh:
    def test_refresh_success(self):
        reg_res = register_user()
        refresh_token = reg_res.json()["refresh_token"]

        res = client.post("/api/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["refresh_token"] != refresh_token  # rotated

    def test_refresh_with_invalid_token(self):
        res = client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.token.here",
        })
        assert res.status_code == 401

    def test_refresh_reuse_revoked_token(self):
        reg_res = register_user()
        refresh_token = reg_res.json()["refresh_token"]

        # First refresh works
        client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

        # Second use of same token fails (already revoked)
        res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 401


class TestMe:
    def test_get_me_authenticated(self):
        reg_res = register_user(email="me@test.com", display_name="Me User")
        token = reg_res.json()["access_token"]

        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "me@test.com"
        assert data["display_name"] == "Me User"
        assert data["tier"] == "free"
        assert data["is_active"] is True

    def test_get_me_unauthenticated(self):
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_get_me_invalid_token(self):
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
        assert res.status_code == 401


class TestLogout:
    def test_logout_revokes_tokens(self):
        reg_res = register_user()
        access = reg_res.json()["access_token"]
        refresh = reg_res.json()["refresh_token"]

        # Logout
        res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
        assert res.status_code == 204

        # Refresh should now fail
        res = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert res.status_code == 401
