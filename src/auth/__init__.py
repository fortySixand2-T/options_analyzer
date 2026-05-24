"""Authentication package — JWT-based user auth for the Options Scanner."""

from src.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from src.auth.database import init_auth_db, get_user_by_email, create_user
from src.auth.models import UserCreate, UserResponse, TokenResponse

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_password_hash",
    "verify_password",
    "init_auth_db",
    "get_user_by_email",
    "create_user",
    "UserCreate",
    "UserResponse",
    "TokenResponse",
]
