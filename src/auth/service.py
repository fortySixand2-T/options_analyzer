"""Core auth service — password hashing, JWT creation and validation."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from src.auth import config as auth_config


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=auth_config.JWT_ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, auth_config.JWT_SECRET_KEY, algorithm=auth_config.JWT_ALGORITHM)


def create_refresh_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=auth_config.JWT_REFRESH_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "refresh",
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, auth_config.JWT_SECRET_KEY, algorithm=auth_config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode a JWT and return payload. Raises JWTError on invalid/expired."""
    try:
        payload = jwt.decode(token, auth_config.JWT_SECRET_KEY, algorithms=[auth_config.JWT_ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        token_type = payload.get("type")
        if user_id is None or email is None:
            raise JWTError("Missing claims")
        return {"id": int(user_id), "email": email, "type": token_type}
    except JWTError:
        raise


def hash_token(token: str) -> str:
    """SHA-256 hash for storing refresh tokens in DB."""
    return hashlib.sha256(token.encode()).hexdigest()
