"""Passwords are bcrypt-hashed in the database â€” never plaintext."""

from sqlalchemy import select

from app.core.security import verify_password
from app.models import User
from helpers import REGISTER_DEFAULTS, db_query, register


def test_passwords_are_bcrypt_hashed(client):
    assert register(client).status_code == 201

    user = db_query(
        lambda session: session.scalar(
            select(User).where(User.email == REGISTER_DEFAULTS["email"])
        )
    )
    plaintext = REGISTER_DEFAULTS["password"]

    assert user.password_hash != plaintext
    assert plaintext not in user.password_hash
    assert user.password_hash.startswith("$2b$")
    assert verify_password(plaintext, user.password_hash)
    assert not verify_password("not-the-password", user.password_hash)
