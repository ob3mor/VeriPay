"""Application settings (pydantic-settings, ``VERIPAY_`` env prefix).

The JWT secret carries a dev-only default, but the application refuses to
start when ``VERIPAY_ENV=production`` without a real secret (validator below).
PostgreSQL is canonical; ``sqlite:///./veripay.db`` is the no-Docker dev/test
fallback (docs/ARCHITECTURE.md §6, ADR 0002).
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"

# Cookie names/headers shared by the API and the static frontend (the frontend
# reads the csrf cookie and echoes it in the header on mutating requests).
SESSION_COOKIE_NAME = "veripay_session"
CSRF_COOKIE_NAME = "veripay_csrf"
CSRF_HEADER_NAME = "x-csrf-token"


class Settings(BaseSettings):
    # populate_by_name: the storage_s3_* fields carry validation aliases
    # (the VERIPAY_MINIO_* compose dialect) — field-name kwargs must keep
    # working for tests and in-code construction.
    model_config = SettingsConfigDict(
        env_prefix="VERIPAY_", extra="ignore", populate_by_name=True
    )

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

    # OcrProvider seam: "text_layer" (default — reads the embedded digital
    # text of PDFs, so documents with a real text layer never need pixel
    # OCR) | "tesseract" (local pixel OCR; optional [ocr] extra + binary) |
    # "azure" (Azure Document Intelligence; optional [azure-ocr] extra) |
    # "stub". An unavailable engine falls back to the stub with an explicit
    # reason persisted in provider_meta (never silently).
    ocr_provider: str = "text_layer"

    # Tesseract language packs: Arabic + English read together.
    tesseract_lang: str = "ara+eng"

    # Azure Document Intelligence (VERIPAY_AZURE_DI_ENDPOINT / KEY). F0
    # free-tier contract: at most azure_di_page_cap pages per document are
    # analyzed; the cap is honored, never raised by code (no tier upgrades).
    azure_di_endpoint: str | None = None
    azure_di_key: str | None = None
    azure_di_model: str = "prebuilt-invoice"
    azure_di_page_cap: int = 2
    azure_di_timeout_seconds: float = 30.0
    azure_di_max_retries: int = 3

    # Throttling of the public auth endpoints (app/core/ratelimit.py): sliding
    # windows per client IP, plus a failed-login lockout per (IP, email).
    rate_limit_login_per_minute: int = 20
    rate_limit_register_per_minute: int = 10
    login_lockout_max_failures: int = 5
    login_lockout_window_seconds: int = 900

    # Retrieval / evidence search (app/modules/retrieval). Hybrid ranking fuses
    # per-technique ranked lists with Reciprocal Rank Fusion; the weights are
    # configurable so lexical-only and exact-only baselines are expressible.
    retrieval_fusion_k: int = 60
    retrieval_weight_exact: float = 1.0
    retrieval_weight_text: float = 1.0
    retrieval_weight_trigram: float = 0.8
    retrieval_weight_vector: float = 0.6
    # Fuzzy-match floor for the trigram techniques (portable Dice coefficient
    # and pg_trgm similarity() share the 0..1 scale).
    retrieval_trigram_threshold: float = 0.3
    # Trust tiers: a trusted record not updated within this many days ranks as
    # "stale" (explicit score multiplier, never hidden from search).
    retrieval_stale_days: int = 180
    # OPTIONAL pgvector path (Prompt-03): off by default and never required.
    # When enabled AND the runtime dialect is PostgreSQL AND the vector
    # extension exists, embedding search joins the hybrid fusion; any other
    # combination degrades gracefully to the non-vector techniques. The
    # companion migration (0002) creates the extension + embedding table ONLY
    # when this flag is set, so default deployments (and CI) never touch it.
    retrieval_pgvector_enabled: bool = False
    retrieval_embedding_dim: int = 384

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
    # MinIO/S3 connection. The compose stack (infrastructure/local/ +
    # .env.example) speaks the VERIPAY_MINIO_* dialect, so those names are
    # accepted as aliases alongside the canonical VERIPAY_STORAGE_S3_* ones —
    # a minio-configured API must not silently lose its endpoint/credentials
    # (pydantic-settings extra="ignore" would otherwise drop them).
    # VERIPAY_MINIO_SECURE is intentionally not mapped: the endpoint URL
    # already carries the scheme (http vs https).
    storage_s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIPAY_STORAGE_S3_ENDPOINT_URL", "VERIPAY_MINIO_ENDPOINT"
        ),
    )
    storage_s3_bucket: str = Field(
        default="veripay-documents",
        validation_alias=AliasChoices(
            "VERIPAY_STORAGE_S3_BUCKET", "VERIPAY_MINIO_BUCKET"
        ),
    )
    storage_s3_access_key_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIPAY_STORAGE_S3_ACCESS_KEY_ID", "VERIPAY_MINIO_ACCESS_KEY"
        ),
    )
    storage_s3_secret_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIPAY_STORAGE_S3_SECRET_ACCESS_KEY", "VERIPAY_MINIO_SECRET_KEY"
        ),
    )
    storage_s3_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIPAY_STORAGE_S3_REGION", "VERIPAY_MINIO_REGION"
        ),
    )

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
