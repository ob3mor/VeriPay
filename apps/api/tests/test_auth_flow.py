"""Auth happy path + registration conflicts (docs/API.md Â§4)."""

from helpers import bearer, login, register


def test_register_login_me_happy_path(client):
    registered = register(client)
    assert registered.status_code == 201, registered.text
    body = registered.json()

    assert body["user"]["email"] == "dana@acme.example"
    assert body["user"]["role"] == "org_admin"
    assert body["user"]["organization_id"] == body["organization"]["id"]
    assert body["organization"]["name"] == "Acme GmbH"
    assert body["organization"]["slug"] == "acme-gmbh"
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == body["user"]["id"]
    assert me.json()["user"]["email"] == "dana@acme.example"
    assert me.json()["organization"]["id"] == body["organization"]["id"]

    # Login (OAuth2 password form) issues a token that also resolves /me.
    logged_in = login(client)
    assert logged_in.status_code == 200
    assert logged_in.json()["token_type"] == "bearer"
    me2 = client.get("/api/v1/auth/me", headers=bearer(logged_in.json()["access_token"]))
    assert me2.status_code == 200
    assert me2.json()["user"]["id"] == body["user"]["id"]


def test_register_duplicate_email_returns_conflict(client):
    assert register(client).status_code == 201
    second = register(client, full_name="Someone Else", organization_name="Other Org")

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


def test_missing_fields_return_validation_error_envelope(client):
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]
    assert isinstance(error["details"], list) and error["details"]


def test_unknown_email_and_wrong_password_identical_401(client):
    register(client)
    wrong_password = login(client, password="definitely-wrong")
    unknown_email = login(client, username="ghost@nowhere.example", password="definitely-wrong")

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == "unauthorized"
    # Same message for both â€” no account enumeration (docs/API.md Â§4).
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


def test_me_requires_token(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_last_login_at_updated_on_login(client):
    from datetime import datetime

    from sqlalchemy import select

    from app.models import User
    from helpers import db_query

    assert register(client).status_code == 201
    assert login(client).status_code == 200

    user = db_query(
        lambda s: s.scalar(select(User).where(User.email == "dana@acme.example"))
    )
    assert isinstance(user.last_login_at, datetime)
