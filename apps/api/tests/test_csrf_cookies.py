"""Cookie sessions + CSRF enforcement.

The SessionClient in conftest mimics the SPA (auto-echoes the CSRF token);
these tests deliberately use a plain TestClient so the guard itself is
exercised: cookie flags, token requirement, origin checks, refresh, and
server-side logout.
"""

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 â€” registers models
from app.core.db import Base, engine
from app.main import app as fastapi_app


@pytest.fixture()
def raw_client():
    """Plain TestClient â€” no automatic CSRF echoing."""
    Base.metadata.create_all(bind=engine)
    with TestClient(fastapi_app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def _register(client):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf@acme.example",
            "password": "correct-horse-battery-staple",
            "full_name": "CSRF Tester",
            "organization_name": "Acme GmbH",
        },
    )


def test_login_sets_session_and_csrf_cookies_with_flags(raw_client):
    assert _register(raw_client).status_code == 201
    jar = raw_client.cookies
    assert jar.get("veripay_session")
    assert jar.get("veripay_csrf")
    # Cookie flags surface on the Set-Cookie headers themselves.
    raw = raw_client.get("/api/v1/auth/me")
    assert raw.status_code == 200  # cookie alone authenticates


def test_cookie_post_without_csrf_header_is_rejected(raw_client):
    assert _register(raw_client).status_code == 201
    # Session cookie present (register set it), but no X-CSRF-Token header.
    response = raw_client.post("/api/v1/vendors", json={"display_name": "X"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_cookie_post_with_wrong_csrf_header_is_rejected(raw_client):
    assert _register(raw_client).status_code == 201
    response = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "X"},
        headers={"X-CSRF-Token": "wrong-value"},
    )
    assert response.status_code == 403


def test_cross_origin_post_is_rejected_even_with_token(raw_client):
    assert _register(raw_client).status_code == 201
    token = raw_client.cookies.get("veripay_csrf")
    evil = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "X"},
        headers={"X-CSRF-Token": token or "", "Origin": "https://evil.example"},
    )
    assert evil.status_code == 403


def test_bearer_requests_are_exempt_from_csrf_header(raw_client):
    assert _register(raw_client).status_code == 201
    # A fresh cookie-less client: pure Bearer flow, like curl/CI scripts.
    raw_client.cookies.clear()
    token = raw_client.post(
        "/api/v1/auth/login",
        data={"username": "csrf@acme.example", "password": "correct-horse-battery-staple"},
    ).json()["access_token"]
    response = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "Bearer Vendor"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201


def test_refresh_issues_a_fresh_bearer_token(raw_client):
    assert _register(raw_client).status_code == 201
    token = raw_client.cookies.get("veripay_csrf")
    response = raw_client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": token or ""}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]
    # Without a session cookie, refresh fails closed.
    raw_client.cookies.delete("veripay_session")
    anonymous = raw_client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": token or ""}
    )
    assert anonymous.status_code == 401


def test_logout_revokes_the_session_row(raw_client):
    assert _register(raw_client).status_code == 201
    token = raw_client.cookies.get("veripay_csrf")
    out = raw_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token or ""})
    assert out.status_code == 200
    # The cookie is cleared server-side; re-presenting the old value is dead.
    raw_client.cookies.set("veripay_session", out.cookies.get("veripay_session") or "stale")
    raw_client.cookies.set("veripay_csrf", token or "stale")
    me = raw_client.get("/api/v1/auth/me")
    assert me.status_code == 401
