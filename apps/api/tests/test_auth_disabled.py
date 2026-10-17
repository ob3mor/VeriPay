"""A disabled user must not be able to sign in.

tenancy.deps.get_current_user already rejects non-active users on every
request; the login layer must agree â€” same 401 (no account enumeration), a
``user.login_failed`` audit event with reason ``account_disabled``, and no
fresh ``user.login_succeeded`` row (DATABASE.md Â§5: active | disabled)."""

from sqlalchemy import select

from app.models import AuditEvent, User
from helpers import bearer, db_query, login, register


def _disable_default_user() -> None:
    def _set_disabled(session) -> None:
        user = session.scalar(select(User).where(User.email == "dana@acme.example"))
        user.status = "disabled"
        session.commit()

    db_query(_set_disabled)


def test_disabled_user_login_is_401_with_generic_message(client):
    assert register(client).status_code == 201
    _disable_default_user()

    response = login(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    # Identical message as unknown email / wrong password â€” no enumeration.
    unknown = login(client, username="ghost@nowhere.example", password="x-not-it")
    assert response.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_disabled_login_audits_failure_and_never_success(client):
    assert register(client).status_code == 201
    _disable_default_user()

    assert login(client).status_code == 401

    def _logs(session):
        return list(session.scalars(select(AuditEvent)).all())

    logs = db_query(_logs)
    succeeded = [log for log in logs if log.action == "user.login_succeeded"]
    # The register flow never writes login_succeeded; the disabled login must
    # not add one.
    assert succeeded == []
    disabled_failures = [
        log
        for log in logs
        if log.action == "user.login_failed"
        and log.detail is not None
        and log.detail.get("reason") == "account_disabled"
    ]
    assert len(disabled_failures) == 1
    assert disabled_failures[0].detail["email"] == "dana@acme.example"
    # Known account: the failed attempt carries its tenant context.
    assert disabled_failures[0].organization_id is not None


def test_disabled_user_existing_token_is_rejected(client):
    registered = register(client)
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200

    _disable_default_user()

    # The token-verification layer (unchanged behavior) disables the session.
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
