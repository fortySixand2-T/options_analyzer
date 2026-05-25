"""FastAPI dependencies for JWT-based route protection."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt

from src.auth.database import get_user_by_id
from src.auth.service import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Validate JWT and return user dict. Raises 401 if invalid."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(payload["id"])
    if user is None or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(token: str = Depends(oauth2_scheme)) -> dict | None:
    """Return user if token is valid, None otherwise. For mixed-access routes."""
    if token is None:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        return get_user_by_id(payload["id"])
    except jwt.PyJWTError:
        return None
