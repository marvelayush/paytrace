"""Application settings, read from environment variables (and an optional .env file)."""

from functools import lru_cache

from pydantic import Field, field_validator
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

    # Comma-separated list of frontend origins allowed to call the API with cookies.
    frontend_origin: str = "http://localhost:3000"

    # Interactive API docs (/docs). Off in production unless explicitly enabled.
    enable_docs: bool = True

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Hosted Postgres (Neon, Render) hands out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.frontend_origin.split(",") if origin.strip()]

    max_upload_mb: int = 50
    # Where uploaded files wait between inspection and processing (deleted after processing).
    upload_dir: str = "uploads"

    # A8/A23: days after a return within which the warehouse must scan it in.
    return_receipt_days: int = 7

    login_max_attempts: int = 5
    login_window_seconds: int = 60

    gemini_api_key: str | None = None
    # gemini-2.5-flash is closed to new API keys (404). flash-lite: as accurate on our layouts, faster, larger free quota.
    gemini_model: str = "gemini-3.1-flash-lite"
    # Empty for models without a thinking setting.
    gemini_thinking_level: str | None = "low"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
