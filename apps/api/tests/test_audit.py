"""Audit trail: register, successful login AND failed login are written to
audit_events by the audit service (DATABASE.md Â§15 vocabulary)."""

from sqlalchemy import select

from app.models import AuditEvent
from helpers import db_query, login, register


def _all_logs():
    return db_query(lambda session: list(session.scalars(select(AuditEvent)).all()))


def test_audit_rows_written_for_register_and_both_login_outcomes(client):
    registered = register(client)
    assert registered.status_code == 201
    body = registered.json()
    user_id = body["user"]["id"]
    org_id = body["organization"]["id"]

    assert login(client).status_code == 200  # success
    assert login(client, password="definitely-wrong").status_code == 401  # failure

    logs = _all_logs()
    actions = {log.action for log in logs}
    assert {"user.registered", "user.login_succeeded", "user.login_failed"} <= actions

    registered_log = next(log for log in logs if log.action == "user.registered")
    assert str(registered_log.organization_id) == org_id
    assert str(registered_log.actor_user_id) == user_id
    assert registered_log.entity_type == "user"
    assert str(registered_log.entity_id) == user_id
    assert registered_log.detail["email"] == "dana@acme.example"

    succeeded_log = next(log for log in logs if log.action == "user.login_succeeded")
    assert str(succeeded_log.organization_id) == org_id
    assert str(succeeded_log.actor_user_id) == user_id

    failed_log = next(log for log in logs if log.action == "user.login_failed")
    # Known account: the failed attempt carries tenant context.
    assert str(failed_log.organization_id) == org_id
    # Not authenticated â€” no actor attribution.
    assert failed_log.actor_user_id is None
    assert failed_log.detail["reason"] == "invalid_credentials"


def test_failed_login_unknown_email_has_no_tenant(client):
    from helpers import REGISTER_DEFAULTS

    assert register(client).status_code == 201
    response = login(client, username="ghost@nowhere.example", password="x-not-it")
    assert response.status_code == 401

    failed = [
        log
        for log in _all_logs()
        if log.action == "user.login_failed"
        and log.detail is not None
        and log.detail.get("email") == "ghost@nowhere.example"
    ]
    assert len(failed) == 1
    assert failed[0].organization_id is None
    assert failed[0].actor_user_id is None


def test_password_hash_never_in_audit_detail(client):
    assert register(client).status_code == 201

    for log in _all_logs():
        blob = str(log.detail)
        assert "correct-horse-battery-staple" not in blob
        assert "$2b$" not in blob
