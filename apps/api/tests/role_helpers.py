"""Multi-role test helpers.

register() always creates an org_admin (the org creator). Other roles are
inserted directly into the same organization, then used via login().
"""

import uuid

from app.core.security import hash_password
from app.models import User

from helpers import REGISTER_DEFAULTS, db_query, login, register  # noqa: F401


def add_user(org_id: str, email: str, role: str, password: str = "correct-horse-battery-staple") -> str:
    """Insert a user of any role into an existing organization (idempotent)."""

    def _create(session):
        existing = session.query(User).filter(User.email == email).first()
        if existing is not None:
            return str(existing.id)
        user = User(
            organization_id=uuid.UUID(str(org_id)),
            email=email,
            password_hash=hash_password(password),
            full_name=f"User {role}",
            role=role,
        )
        session.add(user)
        session.commit()
        return str(user.id)

    return db_query(_create)


def login_as(client, email: str, password: str = "correct-horse-battery-staple"):
    """Login as a specific user (SessionClient carries the CSRF header)."""
    return login(client, username=email, password=password)


def register_second_org(client, email: str = "other@corp.example"):
    return register(
        client,
        email=email,
        organization_name="Other Corp",
        full_name="Other Admin",
    )
