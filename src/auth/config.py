"""Auth configuration — loaded from environment."""

import logging
import os
import secrets

logger = logging.getLogger(__name__)

_WEAK_SECRETS = {"dev-secret-change-in-production", "change-this-to-a-random-secret-in-production", ""}

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if not JWT_SECRET_KEY or JWT_SECRET_KEY in _WEAK_SECRETS:
    if os.getenv("ENV", "development") == "production":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a secure random value in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    JWT_SECRET_KEY = secrets.token_hex(32)
    logger.warning("JWT_SECRET_KEY not set — using ephemeral random secret (tokens won't survive restart)")

JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = 30
JWT_REFRESH_EXPIRE_DAYS = 7

AUTH_DB_PATH = os.getenv(
    "AUTH_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "users.db"),
)
