"""Functional tests for auth system — end-to-end user workflows."""

import os
import tempfile

os.environ["AUTH_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_functional_users.db")
os.environ["JWT_SECRET_KEY"] = "functional-test-secret"

import pytest
from fastapi.testclient import TestClient

from src.auth.database import init_auth_db, get_connection
from src.ui.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    init_auth_db()
    conn = get_connection()
    conn.execute("DELETE FROM refresh_tokens")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    yield


def register(email="user@test.com", password="password123", display_name="Test User"):
    return client.post("/api/auth/register", json={
        "email": email, "password": password, "display_name": display_name,
    })


def login(email="user@test.com", password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


class TestFullRegistrationFlow:
    """User registers, gets tokens, accesses protected resource, refreshes, logs out."""

    def test_complete_lifecycle(self):
        # 1. Register
        res = register()
        assert res.status_code == 201
        tokens = res.json()
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]

        # 2. Access protected endpoint
        me = client.get("/api/auth/me", headers=auth_header(access))
        assert me.status_code == 200
        assert me.json()["email"] == "user@test.com"

        # 3. Refresh tokens
        refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert refresh_res.status_code == 200
        new_tokens = refresh_res.json()
        new_access = new_tokens["access_token"]
        new_refresh = new_tokens["refresh_token"]

        # 4. New access token works
        me2 = client.get("/api/auth/me", headers=auth_header(new_access))
        assert me2.status_code == 200

        # 5. Old refresh token is revoked
        old_refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert old_refresh_res.status_code == 401

        # 6. Logout
        logout_res = client.post("/api/auth/logout", headers=auth_header(new_access))
        assert logout_res.status_code == 204

        # 7. New refresh token is now revoked
        post_logout = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
        assert post_logout.status_code == 401


class TestMultipleUsers:
    """Multiple users can coexist without interfering."""

    def test_two_users_independent_sessions(self):
        r1 = register("alice@test.com", "alicepass1", "Alice")
        r2 = register("bob@test.com", "bobpass123", "Bob")
        assert r1.status_code == 201
        assert r2.status_code == 201

        t1 = r1.json()["access_token"]
        t2 = r2.json()["access_token"]

        me1 = client.get("/api/auth/me", headers=auth_header(t1))
        me2 = client.get("/api/auth/me", headers=auth_header(t2))

        assert me1.json()["email"] == "alice@test.com"
        assert me2.json()["email"] == "bob@test.com"
        assert me1.json()["id"] != me2.json()["id"]

    def test_logout_one_user_doesnt_affect_other(self):
        r1 = register("alice@test.com", "alicepass1", "Alice")
        r2 = register("bob@test.com", "bobpass123", "Bob")

        t1 = r1.json()["access_token"]
        t2 = r2.json()["access_token"]
        refresh2 = r2.json()["refresh_token"]

        # Alice logs out
        client.post("/api/auth/logout", headers=auth_header(t1))

        # Bob's tokens still work
        me = client.get("/api/auth/me", headers=auth_header(t2))
        assert me.status_code == 200

        ref = client.post("/api/auth/refresh", json={"refresh_token": refresh2})
        assert ref.status_code == 200


class TestMultipleSessions:
    """A single user can have multiple active sessions."""

    def test_multiple_logins_create_multiple_sessions(self):
        register()

        login1 = login()
        login2 = login()
        login3 = login()

        t1 = login1.json()["access_token"]
        t2 = login2.json()["access_token"]
        t3 = login3.json()["access_token"]

        # All three sessions are valid
        assert client.get("/api/auth/me", headers=auth_header(t1)).status_code == 200
        assert client.get("/api/auth/me", headers=auth_header(t2)).status_code == 200
        assert client.get("/api/auth/me", headers=auth_header(t3)).status_code == 200

    def test_logout_revokes_all_sessions(self):
        register()
        l1 = login()
        l2 = login()

        r1 = l1.json()["refresh_token"]
        r2 = l2.json()["refresh_token"]
        t1 = l1.json()["access_token"]

        # Logout revokes ALL refresh tokens
        client.post("/api/auth/logout", headers=auth_header(t1))

        assert client.post("/api/auth/refresh", json={"refresh_token": r1}).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": r2}).status_code == 401


class TestPasswordSecurity:
    """Password edge cases and security behaviors."""

    def test_password_exactly_8_chars(self):
        res = register(password="12345678")
        assert res.status_code == 201

    def test_password_7_chars_rejected(self):
        res = register(password="1234567")
        assert res.status_code == 422

    def test_password_128_chars_accepted(self):
        res = register(password="a" * 128)
        assert res.status_code == 201

    def test_password_129_chars_rejected(self):
        res = register(password="a" * 129)
        assert res.status_code == 422

    def test_password_with_special_chars(self):
        res = register(password="p@$$w0rd!#%^&*(){}[]|\\:\";<>?,./~`")
        assert res.status_code == 201
        login_res = login(password="p@$$w0rd!#%^&*(){}[]|\\:\";<>?,./~`")
        assert login_res.status_code == 200

    def test_password_with_unicode(self):
        res = register(password="contraseña_ñ_日本語")
        assert res.status_code == 201
        login_res = login(password="contraseña_ñ_日本語")
        assert login_res.status_code == 200

    def test_password_case_sensitive(self):
        register(password="Password123")
        assert login(password="Password123").status_code == 200
        assert login(password="password123").status_code == 401
        assert login(password="PASSWORD123").status_code == 401


class TestEmailValidation:
    """Email format validation and normalization."""

    def test_valid_emails(self):
        valid = [
            "simple@test.com",
            "very.common@test.com",
            "x@example.com",
        ]
        for i, email in enumerate(valid):
            res = register(email=email, display_name=f"User {i}")
            assert res.status_code == 201, f"Expected 201 for {email}, got {res.status_code}"

    def test_invalid_emails(self):
        invalid = [
            "not-an-email",
            "@no-local.com",
            "no-domain@",
            "spaces in@email.com",
            "",
        ]
        for email in invalid:
            res = client.post("/api/auth/register", json={
                "email": email, "password": "password123", "display_name": "X",
            })
            assert res.status_code == 422, f"Expected 422 for '{email}', got {res.status_code}"

    def test_email_case_insensitive_login(self):
        register(email="User@Test.COM")
        # Pydantic EmailStr normalizes to lowercase
        res = login(email="user@test.com")
        assert res.status_code == 200


class TestTokenSecurity:
    """Token manipulation and security edge cases."""

    def test_access_token_cannot_be_used_as_refresh(self):
        reg = register()
        access = reg.json()["access_token"]
        res = client.post("/api/auth/refresh", json={"refresh_token": access})
        assert res.status_code == 401

    def test_refresh_token_cannot_access_protected_routes(self):
        reg = register()
        refresh = reg.json()["refresh_token"]
        res = client.get("/api/auth/me", headers=auth_header(refresh))
        assert res.status_code == 401

    def test_empty_bearer_token(self):
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer "})
        assert res.status_code == 401

    def test_malformed_auth_header(self):
        res = client.get("/api/auth/me", headers={"Authorization": "NotBearer token"})
        assert res.status_code == 401

    def test_no_auth_header(self):
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_token_from_different_secret_rejected(self):
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        import uuid

        fake_token = pyjwt.encode(
            {"sub": "1", "email": "a@b.com", "type": "access",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1), "jti": uuid.uuid4().hex,
             "iss": "options-analyzer", "aud": "options-analyzer"},
            "wrong-secret-key",
            algorithm="HS256",
        )
        res = client.get("/api/auth/me", headers=auth_header(fake_token))
        assert res.status_code == 401

    def test_token_with_tampered_user_id(self):
        import jwt as pyjwt
        from src.auth import config as cfg
        from datetime import datetime, timedelta, timezone
        import uuid

        fake_token = pyjwt.encode(
            {"sub": "9999", "email": "fake@test.com", "type": "access",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1), "jti": uuid.uuid4().hex,
             "iss": "options-analyzer", "aud": "options-analyzer"},
            cfg.JWT_SECRET_KEY,
            algorithm=cfg.JWT_ALGORITHM,
        )
        res = client.get("/api/auth/me", headers=auth_header(fake_token))
        assert res.status_code == 401  # user not found


class TestDisplayName:
    """Display name validation."""

    def test_display_name_required(self):
        res = client.post("/api/auth/register", json={
            "email": "x@test.com", "password": "password123", "display_name": "",
        })
        assert res.status_code == 422

    def test_display_name_max_100(self):
        res = register(display_name="A" * 100)
        assert res.status_code == 201

    def test_display_name_over_100_rejected(self):
        res = register(display_name="A" * 101)
        assert res.status_code == 422

    def test_display_name_with_unicode(self):
        res = register(display_name="José García 日本")
        assert res.status_code == 201
        token = res.json()["access_token"]
        me = client.get("/api/auth/me", headers=auth_header(token))
        assert me.json()["display_name"] == "José García 日本"


class TestRateLimitingAndEdgeCases:
    """Edge cases that a real deployment would encounter."""

    def test_rapid_sequential_logins(self):
        register()
        tokens = []
        for _ in range(5):
            res = login()
            assert res.status_code == 200
            tokens.append(res.json()["access_token"])

        # All tokens should be valid and unique
        assert len(set(tokens)) == 5
        for t in tokens:
            assert client.get("/api/auth/me", headers=auth_header(t)).status_code == 200

    def test_rapid_sequential_refreshes(self):
        reg = register()
        refresh = reg.json()["refresh_token"]

        for _ in range(5):
            res = client.post("/api/auth/refresh", json={"refresh_token": refresh})
            assert res.status_code == 200
            refresh = res.json()["refresh_token"]

        # Final token still works
        final_access = res.json()["access_token"]
        assert client.get("/api/auth/me", headers=auth_header(final_access)).status_code == 200

    def test_register_login_different_case_email(self):
        register(email="MyEmail@Test.Com")
        # Should be able to login with normalized email
        res = login(email="myemail@test.com")
        assert res.status_code == 200

    def test_concurrent_registrations_different_emails(self):
        results = []
        for i in range(3):
            res = register(email=f"user{i}@test.com", display_name=f"User {i}")
            results.append(res.status_code)
        assert all(s == 201 for s in results)

    def test_empty_json_body(self):
        res = client.post("/api/auth/login", json={})
        assert res.status_code == 422

    def test_missing_fields(self):
        res = client.post("/api/auth/register", json={"email": "a@b.com"})
        assert res.status_code == 422

    def test_extra_fields_ignored(self):
        res = client.post("/api/auth/register", json={
            "email": "extra@test.com",
            "password": "password123",
            "display_name": "Extra",
            "admin": True,
            "tier": "enterprise",
            "hacker_field": "drop tables",
        })
        assert res.status_code == 201
        token = res.json()["access_token"]
        me = client.get("/api/auth/me", headers=auth_header(token))
        assert me.json()["tier"] == "free"  # didn't escalate


class TestProtectedEndpointsWithAuth:
    """Verify existing API endpoints still work with JWT auth."""

    def _auth(self):
        res = register(email="apitest@test.com", display_name="API Test")
        return auth_header(res.json()["access_token"])

    def test_regime_endpoint_accessible(self):
        headers = self._auth()
        res = client.get("/api/regime", headers=headers)
        assert res.status_code in (200, 500)  # 500 if no market data, but not 401

    def test_greeks_endpoint_accessible(self):
        headers = self._auth()
        res = client.post("/api/greeks", json={
            "spot": 100, "strike": 100, "dte": 30, "iv": 0.25,
        }, headers=headers)
        assert res.status_code == 200

    def test_scan_endpoint_accessible(self):
        headers = self._auth()
        res = client.get("/api/scan", headers=headers)
        assert res.status_code in (200, 500)  # may fail without market data, not 401
