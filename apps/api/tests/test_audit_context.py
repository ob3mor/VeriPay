"""Auth audit events carry request provenance (DATABASE.md Â§15: detail holds
ip / user_agent / request_id) and the audit request_id matches the error
envelope's, so failed-login attempts can be attributed and correlated."""

from sqlalchemy import select

from app.models import AuditEvent
from helpers import USER_AGENT, db_query, login, register


def _all_logs():
    return db_query(lambda session: list(session.scalars(select(AuditEvent)).all()))


def test_auth_audit_events_carry_ip_user_agent_and_request_id(client):
    assert register(client).status_code == 201
    assert login(client).status_code == 200

    logs = _all_logs()
    assert logs
    for log in logs:
        assert log.detail is not None
        assert log.detail.get("ip") == "testclient"
        assert log.detail.get("user_agent") == USER_AGENT
        assert log.detail.get("request_id")
        assert log.request_id == log.detail["request_id"]


def test_failed_login_request_id_matches_error_envelope(client):
    assert register(client).status_code == 201

    response = login(client, password="definitely-wrong")
    assert response.status_code == 401
    envelope_request_id = response.json()["error"]["request_id"]

    failures = [
        log
        for log in _all_logs()
        if log.action == "user.login_failed"
        and log.detail is not None
        and log.detail.get("reason") == "invalid_credentials"
    ]
    assert len(failures) == 1
    assert failures[0].request_id == envelope_request_id


def test_error_envelope_carries_the_request_id_header(client):
    assert register(client).status_code == 201

    response = login(client, password="definitely-wrong")
    header_request_id = response.headers["X-Request-ID"]

    assert header_request_id == response.json()["error"]["request_id"]
