"""JWT handling: tampered, expired, and garbage tokens are all rejected."""

from datetime import timedelta

from helpers import bearer, register


def _token_for(client) -> str:
    response = register(client)
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_missing_token_is_unauthorized(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_garbage_token_is_unauthorized(client):
    response = client.get("/api/v1/auth/me", headers=bearer("not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_tampered_token_is_unauthorized(client):
    token = _token_for(client)
    tampered = token[:-4] + "AAAA"

    response = client.get("/api/v1/auth/me", headers=bearer(tampered))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_expired_token_is_unauthorized(client):
    response = register(client)
    assert response.status_code == 201
    body = response.json()

    from app.core.security import create_access_token

    expired = create_access_token(
        user_id=body["user"]["id"],
        organization_id=body["organization"]["id"],
        role=body["user"]["role"],
        expires_delta=timedelta(seconds=-60),
    )

    me = client.get("/api/v1/auth/me", headers=bearer(expired))

    assert me.status_code == 401
    assert me.json()["error"]["code"] == "unauthorized"
