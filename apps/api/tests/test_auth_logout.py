"""POST /auth/logout revokes the presented access token server-side
(core/token_store.py consulted by tenancy.deps on every request)."""

from sqlalchemy import select

from app.models import AuditEvent
from helpers import bearer, db_query, login, register


def test_logout_revokes_the_presented_token(client):
    registered = register(client)
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200

    response = client.post("/api/v1/auth/logout", headers=bearer(token))

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}
    # The exact token that signed out is dead server-side.
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_logout_is_scoped_to_the_presented_token(client):
    registered = register(client)
    assert registered.status_code == 201
    token_a = registered.json()["access_token"]
    logged_in = login(client)
    assert logged_in.status_code == 200
    token_b = logged_in.json()["access_token"]

    assert client.post("/api/v1/auth/logout", headers=bearer(token_a)).status_code == 200

    # A different session of the same user keeps working.
    assert client.get("/api/v1/auth/me", headers=bearer(token_b)).status_code == 200


def test_logout_requires_auth(client):
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_logout_writes_an_audit_event(client):
    registered = register(client)
    assert registered.status_code == 201
    token = registered.json()["access_token"]

    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code == 200

    def _logs(session):
        return list(session.scalars(select(AuditEvent)).all())

    logs = db_query(_logs)
    logouts = [log for log in logs if log.action == "user.logout"]
    assert len(logouts) == 1
    assert str(logouts[0].actor_user_id) == registered.json()["user"]["id"]
    assert logouts[0].detail["email"] == "dana@acme.example"
