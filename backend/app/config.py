"""Application settings, read from environment variables (and an optional .env file)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Local default matches docker-compose.yml; production sets DATABASE_URL.
    database_url: str = "postgresql+psycopg://paytrace:paytrace@localhost:5432/paytrace"

    # JWT_SECRET has no default on purpose: the app refuses to start without one.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 8 * 60
    cookie_name: str = "paytrace_session"
    cookie_secure: bool = False
    cookie_samesite: str = Field(default="lax", pattern="^(lax|strict|none)$")

    frontend_origin: str = "http://localhost:3000"

    max_upload_mb: int = 50

    login_max_attempts: int = 5
    login_window_seconds: int = 60

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
