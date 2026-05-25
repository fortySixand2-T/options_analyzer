"""Auth API endpoints — register, login, refresh, logout, me."""

import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
import jwt

limiter = Limiter(key_func=get_remote_address)

from src.auth.database import (
    cleanup_expired_tokens,
    create_user,
    enforce_session_limit,
    get_refresh_token,
    get_user_by_email,
    revoke_all_user_tokens,
    revoke_refresh_token,
    store_refresh_token,
)
from src.auth.dependencies import get_current_user
from src.auth.models import (
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from src.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from src.auth.config import JWT_REFRESH_EXPIRE_DAYS

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(request: Request, body: UserCreate):
    """Create a new user account and return tokens."""
    email = unicodedata.normalize("NFKC", body.email).lower()
    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    password_hash = get_password_hash(body.password)
    user = create_user(email, password_hash, body.display_name)

    access_token = create_access_token(user["id"], user["email"])
    refresh_token = create_refresh_token(user["id"], user["email"])

    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)).isoformat()
    store_refresh_token(user["id"], hash_token(refresh_token), expires_at)
    enforce_session_limit(user["id"])

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, body: UserLogin):
    """Authenticate with email/password and return tokens."""
    email = unicodedata.normalize("NFKC", body.email).lower()
    user = get_user_by_email(email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")

    access_token = create_access_token(user["id"], user["email"])
    refresh_token = create_refresh_token(user["id"], user["email"])

    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)).isoformat()
    store_refresh_token(user["id"], hash_token(refresh_token), expires_at)
    enforce_session_limit(user["id"])

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
def refresh(request: Request, body: RefreshRequest):
    """Exchange a valid refresh token for a new token pair."""
    try:
        payload = decode_token(body.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    token_hash = hash_token(body.refresh_token)
    stored = get_refresh_token(token_hash)
    if stored is None:
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found")

    expires_at = datetime.fromisoformat(stored["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        revoke_refresh_token(token_hash)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    revoke_refresh_token(token_hash)

    user_id = payload["id"]
    email = payload["email"]
    new_access = create_access_token(user_id, email)
    new_refresh = create_refresh_token(user_id, email)

    from datetime import timedelta
    new_expires = (datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)).isoformat()
    store_refresh_token(user_id, hash_token(new_refresh), new_expires)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
def logout(user: dict = Depends(get_current_user)):
    """Revoke all refresh tokens for the current user."""
    revoke_all_user_tokens(user["id"])


@router.get("/me", response_model=UserResponse)
def get_me(user: dict = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        tier=user.get("tier", "free"),
        is_active=bool(user.get("is_active", True)),
    )
