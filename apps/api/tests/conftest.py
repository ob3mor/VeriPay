"""Pytest fixtures: env overrides MUST be set before any `app` import â€”
settings and the DB engine are built at import time. In-memory SQLite with a
StaticPool keeps tests hermetic: no network, no Docker, no files.

Throttle limits are lowered in the test env so the rate-limit tests can
exhaust a window with a handful of real requests; the per-test autouse
fixture resets every in-memory registry (throttles, lockouts, revoked jti
tokens) because only the DB is recreated between tests."""

import os
import time

# A file-backed test database with WAL (per core/db.py pragmas) instead of
# :memory:+StaticPool: the app's request sessions and the tests' own
# db_query sessions then behave like real concurrent connections instead of
# interleaving on one shared connection ("database table is locked").
# VERIPAY_TEST_DB overrides the location so two suites on one machine (two
# worktrees/CI legs) can run without deleting each other's database file;
# the default is unchanged.
_TEST_DB = os.environ.get("VERIPAY_TEST_DB") or os.path.join(
    os.path.dirname(__file__), "_veripay_test.db"
)


def _remove_test_db_files() -> None:
    """Delete the previous run's database files before the engine is built.

    On Windows this delete is raced by holders that outlive the previous run
    only briefly: teardown of a lingering pytest process, or Defender scanning
    the multi-MB WAL sidecar. A bare os.remove then raises PermissionError
    (WinError 32) at conftest import, aborting collection before a single
    test runs (pytest exit 4). Retry for a bounded window; if the file is
    still locked after that, fail loudly naming the file — the suite must
    never run against a stale database, so this cleanup is a hard
    precondition, not a best effort."""

    deadline = time.monotonic() + 15.0
    delay = 0.1
    for suffix in ("", "-wal", "-shm"):
        path = _TEST_DB + suffix
        while os.path.exists(path):
            try:
                os.remove(path)
                break
            except FileNotFoundError:
                break  # raced away — nothing left to clean
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"test database {path!r} is still locked by another "
                        "process — a previous test run (or its teardown) has "
                        "not released it; close that process and re-run"
                    ) from None
                time.sleep(delay)
                delay = min(delay * 2, 1.0)


_remove_test_db_files()
os.environ["VERIPAY_ENV"] = "test"
# setdefault, not overwrite: CI may preset VERIPAY_DATABASE_URL (e.g. the
# PostgreSQL leg in .github/workflows/ci.yml) and it must be honored; the
# default stays the file-backed SQLite DB above.
os.environ.setdefault(
    "VERIPAY_DATABASE_URL", "sqlite:///" + _TEST_DB.replace("\\", "/")
)
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
    # Drop with FK enforcement OFF on the SAME connection drop_all uses:
    # use_alter FKs (extraction_fields.invoice_id, bank-account document
    # links) are invisible to metadata's table sort, so a plain drop_all can
    # DROP a parent table while child rows still reference it — which would
    # fail and leave the file-backed DB dirty for every following test.
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(bind=conn)
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()


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


def pytest_sessionfinish(session, exitstatus):
    """Close every pooled connection before the test process exits.

    Request sessions hand their connections back to the engine's pool, which
    keeps the file-backed SQLite handles open until the process dies. The run
    then exits without SQLite's clean last-connection close: the -wal/-shm
    sidecars are left behind (a multi-MB WAL after a finished suite) and any
    process that lingers past the run holds the DB locked — the next run's
    pre-test cleanup then fails with WinError 32. Disposing the engine closes
    all pooled connections (checkpointing the WAL away) and releases every
    handle; the database files are deleted before the next run anyway, so
    nothing is lost."""

    engine.dispose()
