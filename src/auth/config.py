"""Auth configuration — loaded from environment."""

import os

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = 30
JWT_REFRESH_EXPIRE_DAYS = 7

AUTH_DB_PATH = os.getenv(
    "AUTH_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "users.db"),
)
