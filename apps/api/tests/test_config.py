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
