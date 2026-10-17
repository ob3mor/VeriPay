"""Shared test helpers.

``db_query`` opens a short-lived session; with the StaticPool there is a
single connection, so DB assertions must run AFTER client requests finish.
"""

from collections.abc import Callable
from typing import Any

from app.core.db import SessionLocal

REGISTER_DEFAULTS: dict[str, str] = {
    "email": "dana@acme.example",
    "password": "correct-horse-battery-staple",
    "full_name": "Dana Reyes",
    "organization_name": "Acme GmbH",
}

# Deterministic client provenance for audit-context assertions.
USER_AGENT = "veripay-tests/1.0"
_HEADERS = {"User-Agent": USER_AGENT}


def register(client, **overrides: str):
    payload = {**REGISTER_DEFAULTS, **overrides}
    return client.post("/api/v1/auth/register", json=payload, headers=_HEADERS)


def login(client, username: str = REGISTER_DEFAULTS["email"], password: str = REGISTER_DEFAULTS["password"]):
    return client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
        headers=_HEADERS,
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def db_query(fn: Callable[[Any], Any]) -> Any:
    with SessionLocal() as session:
        return fn(session)
