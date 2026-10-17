"""Application settings (pydantic-settings, ``VERIPAY_`` env prefix).

The JWT secret carries a dev-only default, but the application refuses to
start when ``VERIPAY_ENV=production`` without a real secret (validator below).
PostgreSQL is canonical; ``sqlite:///./veripay.db`` is the no-Docker dev/test
fallback (docs/ARCHITECTURE.md §6, ADR 0002).
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"

# Cookie names/headers shared by the API and the static frontend (the frontend
# reads the csrf cookie and echoes it in the header on mutating requests).
SESSION_COOKIE_NAME = "veripay_session"
CSRF_COOKIE_NAME = "veripay_csrf"
CSRF_HEADER_NAME = "x-csrf-token"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERIPAY_", extra="ignore")

    # "development" | "test" | "production" — normalized (see _normalize_env):
    # case/whitespace-insensitive, and "prod" maps to "production" so the
    # production-only guards below cannot be bypassed by spelling variants.
    env: str = "development"
    app_version: str = APP_VERSION

    # PostgreSQL canonical; SQLite dev/test fallback.
    database_url: str = "sqlite:///./veripay.db"

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    # Short-lived Bearer token for programmatic clients; browser sessions use
    # the httpOnly cookie below and POST /auth/refresh.
    access_token_expire_minutes: int = 30

    # Cookie session (the browser auth strategy; no tokens in localStorage).
    session_ttl_days: int = 7
    # True behind HTTPS (PROFILE B); local dev over http keeps False.
    cookie_secure: bool = False

    # Uploads (documents module): hard size ceiling + validation allowlist.
    upload_max_bytes: int = 10 * 1024 * 1024  # 10 MiB

    # ProcessingBackend seam: "inline" (default; scale-to-zero friendly) or
    # "celery" (optional PROFILE A worker over Redis).
    processing_backend: str = "inline"

    # R3 confidence gate: extracted values at/above this threshold are usable
    # as evidence; below (or NULL) they emit unverified_input instead.
    ocr_confidence_threshold: float = 0.85

    # OcrProvider seam: "stub" (Phase 2) — real engines plug in later.
    ocr_provider: str = "stub"

    # Throttling of the public auth endpoints (app/core/ratelimit.py): sliding
    # windows per client IP, plus a failed-login lockout per (IP, email).
    rate_limit_login_per_minute: int = 20
    rate_limit_register_per_minute: int = 10
    login_lockout_max_failures: int = 5
    login_lockout_window_seconds: int = 900

    @field_validator("env")
    @classmethod
    def _normalize_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "prod":
            normalized = "production"
        return normalized

    # Allowlist of known frontend origins only; wildcards are rejected in
    # review (docs/API.md §1).
    cors_origins: list[str] = ["http://localhost:3000"]

    # Provider-agnostic storage seam (docs/ARCHITECTURE.md §7.1).
    storage_backend: Literal["local", "minio"] = "local"
    storage_local_root: str = "./data/documents"
    storage_s3_endpoint_url: str | None = None
    storage_s3_bucket: str = "veripay-documents"
    storage_s3_access_key_id: str | None = None
    storage_s3_secret_access_key: str | None = None
    storage_s3_region: str | None = None

    @model_validator(mode="after")
    def _refuse_insecure_production_secret(self) -> "Settings":
        if self.env == "production" and (
            not self.jwt_secret
            or self.jwt_secret == DEV_JWT_SECRET
            or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "VERIPAY_JWT_SECRET must be set to a strong value (at least 32 "
                "characters, and not the built-in development default) when "
                "VERIPAY_ENV=production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
