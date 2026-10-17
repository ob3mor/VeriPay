"""Security primitives: bcrypt password hashing + HS256 JWT with expiry.

Phase 1 uses a symmetric server-side secret; switching to asymmetric keys
later does not change the bearer-header contract (docs/API.md §1).
"""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID, uuid4

import bcrypt
import jwt

from app.core.config import get_settings


def generate_session_token() -> str:
    """Opaque browser-session cookie value (256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> str:
    """The sessions table stores only this SHA-256 hex of the cookie value."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

# bcrypt operates on at most 72 bytes of password input; requests are
# validated against this so hashing never fails mid-request.
PASSWORD_MAX_BYTES = 72


class PasswordTooLongError(ValueError):
    pass


def ensure_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise PasswordTooLongError(
            f"Password must be at most {PASSWORD_MAX_BYTES} bytes."
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        return False


def create_access_token(
    *,
    user_id: UUID | str,
    organization_id: UUID | str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": str(user_id),
        "org_id": str(organization_id),
        "role": role,
        "type": "access",
        # Unique per token — the key POST /auth/logout uses to revoke this
        # token server-side (core/token_store.py).
        "jti": uuid4().hex,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode + verify signature/expiry. Raises ``jwt.PyJWTError`` on failure.

    The ``exp`` claim is mandatory: PyJWT only verifies ``exp`` when present,
    and versions below 3 ignore the ``require=`` kwarg entirely, so a
    validly-signed token without it would otherwise never expire.
    """
    settings = get_settings()
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("exp") is None:
        raise jwt.InvalidTokenError("Missing exp claim.")
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Wrong token type.")
    return payload
