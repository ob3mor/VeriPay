"""Settings: dev defaults accepted; production refuses the dev secret."""

import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings


def test_development_defaults_are_accepted():
    settings = Settings()
    assert settings.jwt_secret == DEV_JWT_SECRET
    assert settings.database_url


def test_production_without_real_secret_is_refused():
    with pytest.raises(ValidationError):
        Settings(env="production")  # keeps the dev-only default secret
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret=DEV_JWT_SECRET)
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret="too-short")


def test_production_with_strong_secret_is_accepted():
    settings = Settings(env="production", jwt_secret="a" * 48)
    assert settings.env == "production"


def test_production_env_is_matched_case_insensitively():
    """Spelling variants must not bypass the production JWT-secret guard."""
    for raw in ("PRODUCTION", "Production", "PROD", "prod", " production "):
        with pytest.raises(ValidationError):
            Settings(env=raw)  # keeps the dev-only default secret
        accepted = Settings(env=raw, jwt_secret="a" * 48)
        assert accepted.env == "production"


def test_non_production_env_variants_are_normalized_but_not_production():
    assert Settings(env="Test").env == "test"
    assert Settings(env=" DEVELOPMENT ").env == "development"
    # Unrecognized values stay non-production for the guard (no false block),
    # normalized the same way.
    assert Settings(env="Staging").env == "staging"


def test_compose_minio_env_names_are_accepted(monkeypatch):
    """PROFILE A compose + .env.example speak the VERIPAY_MINIO_* dialect;
    pydantic extra='ignore' would silently DROP them (endpoint=None, no
    credentials). The alias choices must map them onto the storage_s3_*
    fields (the auditor's DOCKER-PATH DEFECT 1)."""
    monkeypatch.setenv("VERIPAY_MINIO_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("VERIPAY_MINIO_ACCESS_KEY", "veripay")
    monkeypatch.setenv("VERIPAY_MINIO_SECRET_KEY", "veripay-dev-change-me")
    monkeypatch.setenv("VERIPAY_MINIO_BUCKET", "veripay-documents")
    settings = Settings()
    assert settings.storage_s3_endpoint_url == "http://minio:9000"
    assert settings.storage_s3_access_key_id == "veripay"
    assert settings.storage_s3_secret_access_key == "veripay-dev-change-me"
    assert settings.storage_s3_bucket == "veripay-documents"


def test_canonical_storage_s3_env_names_win_over_minio_aliases(monkeypatch):
    monkeypatch.setenv("VERIPAY_STORAGE_S3_ENDPOINT_URL", "http://s3.internal:9000")
    monkeypatch.setenv("VERIPAY_MINIO_ENDPOINT", "http://minio:9000")
    assert Settings().storage_s3_endpoint_url == "http://s3.internal:9000"


def test_minio_settings_build_the_s3_provider():
    """DOCKER-PATH DEFECT 2 regression: the keyword-only MinIOS3Provider is
    built from settings without a TypeError (boto3 stays lazy — no SDK here)."""
    from app.adapters.storage.s3 import MinIOS3Provider
    from app.modules.documents.service import _build_storage

    settings = Settings(
        storage_backend="minio",
        storage_s3_endpoint_url="http://minio:9000",
        storage_s3_bucket="veripay-documents",
        storage_s3_access_key_id="veripay",
        storage_s3_secret_access_key="veripay-dev-change-me",
    )
    provider = _build_storage(settings)
    assert isinstance(provider, MinIOS3Provider)
    assert provider._bucket == "veripay-documents"
    assert provider._endpoint_url == "http://minio:9000"


def test_postgresql_driver_is_declared_in_package_dependencies():
    """DOCKER-PATH DEFECT 3 regression: the compose URLs are
    postgresql+psycopg:// — the package must declare the driver or the
    Dockerfile's `pip install .` produces an API that cannot connect."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = " ".join(data["project"]["dependencies"]).lower()
    assert "psycopg" in deps
