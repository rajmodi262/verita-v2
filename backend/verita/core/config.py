"""Application settings, loaded from ``VERITA_*`` environment variables (and ``.env`` in dev).

Settings are validated once at startup; an invalid production configuration refuses to boot
instead of failing on the first request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERITA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = "dev"
    database_url: str = "sqlite+pysqlite:///./verita-dev.sqlite"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    session_ttl_minutes: int = Field(default=480, ge=5, le=7 * 24 * 60)
    login_max_failures: int = Field(default=5, ge=1, le=50)
    login_lockout_minutes: int = Field(default=15, ge=1, le=24 * 60)

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def cookie_secure(self) -> bool:
        """Cookies are Secure everywhere except local dev/test over plain HTTP."""
        return self.is_prod

    @model_validator(mode="after")
    def _prod_requires_postgres(self) -> Settings:
        if self.is_prod and not self.database_url.startswith("postgresql"):
            msg = "VERITA_DATABASE_URL must be a PostgreSQL URL when VERITA_ENV=prod"
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
