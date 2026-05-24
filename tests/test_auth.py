"""Unit tests for the auth service and database layer."""

import os
import tempfile
import time

import pytest

os.environ["AUTH_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_users.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use"

from src.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from src.auth.database import (
    create_user,
    get_connection,
    get_refresh_token,
    get_user_by_email,
    get_user_by_id,
    init_auth_db,
    revoke_all_user_tokens,
    revoke_refresh_token,
    store_refresh_token,
)
from jose import JWTError


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh auth DB for each test."""
    init_auth_db()
    conn = get_connection()
    conn.execute("DELETE FROM refresh_tokens")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    yield


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "SecurePassword123!"
        hashed = get_password_hash(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        hashed = get_password_hash("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_different_hashes_for_same_password(self):
        pw = "same-password"
        h1 = get_password_hash(pw)
        h2 = get_password_hash(pw)
        assert h1 != h2  # bcrypt uses random salt


class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(42, "user@test.com")
        payload = decode_token(token)
        assert payload["id"] == 42
        assert payload["email"] == "user@test.com"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(7, "admin@test.com")
        payload = decode_token(token)
        assert payload["id"] == 7
        assert payload["email"] == "admin@test.com"
        assert payload["type"] == "refresh"

    def test_invalid_token_raises(self):
        with pytest.raises(JWTError):
            decode_token("this.is.not.a.valid.token")

    def test_tampered_token_raises(self):
        token = create_access_token(1, "a@b.com")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_expired_token_raises(self):
        from src.auth import config as cfg

        original = cfg.JWT_ACCESS_EXPIRE_MINUTES
        cfg.JWT_ACCESS_EXPIRE_MINUTES = 0
        try:
            # Create a token that expires immediately (0 minutes from now)
            from datetime import datetime, timedelta, timezone
            from jose import jwt as jose_jwt
            expire = datetime.now(timezone.utc) - timedelta(seconds=10)
            payload = {"sub": "1", "email": "x@y.com", "type": "access", "exp": expire, "jti": "test"}
            token = jose_jwt.encode(payload, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)
            with pytest.raises(JWTError):
                decode_token(token)
        finally:
            cfg.JWT_ACCESS_EXPIRE_MINUTES = original


class TestUserDatabase:
    def test_create_and_get_user(self):
        user = create_user("test@example.com", "hashed_pw", "Test User")
        assert user["email"] == "test@example.com"
        assert user["display_name"] == "Test User"
        assert user["tier"] == "free"
        assert user["is_active"] is True
        assert "id" in user

    def test_get_user_by_email(self):
        create_user("find@me.com", "hash", "Find Me")
        found = get_user_by_email("find@me.com")
        assert found is not None
        assert found["email"] == "find@me.com"
        assert found["display_name"] == "Find Me"

    def test_get_user_by_email_not_found(self):
        assert get_user_by_email("nobody@nowhere.com") is None

    def test_get_user_by_id(self):
        user = create_user("id@test.com", "hash", "ID User")
        found = get_user_by_id(user["id"])
        assert found is not None
        assert found["email"] == "id@test.com"

    def test_duplicate_email_raises(self):
        create_user("dup@test.com", "hash1", "User1")
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            create_user("dup@test.com", "hash2", "User2")


class TestRefreshTokenStorage:
    def test_store_and_retrieve(self):
        user = create_user("rt@test.com", "hash", "RT User")
        token_hash = hash_token("some-refresh-token")
        store_refresh_token(user["id"], token_hash, "2099-01-01T00:00:00+00:00")

        stored = get_refresh_token(token_hash)
        assert stored is not None
        assert stored["user_id"] == user["id"]
        assert stored["revoked"] == 0

    def test_revoke_token(self):
        user = create_user("rev@test.com", "hash", "Rev User")
        token_hash = hash_token("to-be-revoked")
        store_refresh_token(user["id"], token_hash, "2099-01-01T00:00:00+00:00")

        revoke_refresh_token(token_hash)
        assert get_refresh_token(token_hash) is None  # revoked tokens not returned

    def test_revoke_all_user_tokens(self):
        user = create_user("all@test.com", "hash", "All User")
        h1 = hash_token("token-1")
        h2 = hash_token("token-2")
        store_refresh_token(user["id"], h1, "2099-01-01T00:00:00+00:00")
        store_refresh_token(user["id"], h2, "2099-01-01T00:00:00+00:00")

        revoke_all_user_tokens(user["id"])
        assert get_refresh_token(h1) is None
        assert get_refresh_token(h2) is None
