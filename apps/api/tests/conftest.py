"""Pytest fixtures: env overrides MUST be set before any `app` import â€”
settings and the DB engine are built at import time. In-memory SQLite with a
StaticPool keeps tests hermetic: no network, no Docker, no files.

Throttle limits are lowered in the test env so the rate-limit tests can
exhaust a window with a handful of real requests; the per-test autouse
fixture resets every in-memory registry (throttles, lockouts, revoked jti
tokens) because only the DB is recreated between tests."""

import os

# A file-backed test database with WAL (per core/db.py pragmas) instead of
# :memory:+StaticPool: the app's request sessions and the tests' own
# db_query sessions then behave like real concurrent connections instead of
# interleaving on one shared connection ("database table is locked").
_TEST_DB = os.path.join(os.path.dirname(__file__), "_veripay_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
for suffix in ("-wal", "-shm"):
    if os.path.exists(_TEST_DB + suffix):
        os.remove(_TEST_DB + suffix)
os.environ["VERIPAY_ENV"] = "test"
os.environ["VERIPAY_DATABASE_URL"] = "sqlite:///" + _TEST_DB.replace("\\", "/")
os.environ["VERIPAY_RATE_LIMIT_LOGIN_PER_MINUTE"] = "10"
os.environ["VERIPAY_RATE_LIMIT_REGISTER_PER_MINUTE"] = "4"

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  â€” registers every model on Base.metadata
from app.core.db import Base, engine
from app.main import app as fastapi_app

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class SessionClient(TestClient):
    """TestClient that behaves like the real SPA: once the server sets the
    veripay_csrf cookie, every mutating request echoes it in X-CSRF-Token.

    Dedicated CSRF-enforcement tests use a bare TestClient instead, so the
    guard itself stays under test.
    """

    def request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if method.upper() in _MUTATING:
            headers = dict(kwargs.get("headers") or {})
            token = self.cookies.get("veripay_csrf")
            if token and "X-CSRF-Token" not in headers:
                headers["X-CSRF-Token"] = token
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture()
def client():
    """TestClient with a fresh schema per test."""
    Base.metadata.create_all(bind=engine)
    with SessionClient(fastapi_app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_in_memory_auth_state():
    """Throttles/lockouts/revocations live in process memory and would leak
    between tests (each test gets a fresh DB; these registries do not)."""
    from app.core.ratelimit import reset_all
    from app.core.token_store import revoked_tokens

    reset_all()
    revoked_tokens.reset()
    yield
    reset_all()
    revoked_tokens.reset()
