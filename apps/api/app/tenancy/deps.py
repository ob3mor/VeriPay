"""Org-scoped identity resolution and role guards (docs/API.md §5).

The tenant source is the token/cookie, only. ``organization_id`` is read from
the authenticated principal — never from a header, query parameter, path
segment, or body. Authentication resolves in this order:

1. ``Authorization: Bearer <JWT>`` (programmatic clients; jti revocation
   applies),
2. the ``veripay_session`` httpOnly cookie (browser; durable server-side
   session).
"""

import uuid

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import SESSION_COOKIE_NAME
from app.core.db import get_db
from app.core.enums import UserRole, UserStatus
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.core.token_store import revoked_tokens
from app.models import User
from app.modules.auth import sessions as session_service

# Points FastAPI's "Authorize" button at the OAuth2 password-form login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_INVALID = "Invalid or expired authentication token."


def _load_active_user(db: Session, user_id: uuid.UUID, org_claim: str | None) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)
    # A token minted for another org (or pre-dating an org change) is invalid.
    if org_claim is not None and str(org_claim) != str(user.organization_id):
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)
    return user


def _user_from_bearer(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID) from None

    # Server-side sign-out: a jti revoked by POST /auth/logout is dead even
    # though its signature and expiry are still valid.
    jti = payload.get("jti")
    if jti and revoked_tokens.is_revoked(str(jti)):
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)

    sub = payload.get("sub")
    if not sub:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)
    try:
        user_id = uuid.UUID(str(sub))
    except ValueError:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID) from None
    return _load_active_user(db, user_id, payload.get("org_id"))


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the Bearer token or the session cookie to an active user.

    The role is read fresh from the user row, so role changes take effect on
    the next request without waiting for token expiry.
    """
    if token:
        return _user_from_bearer(db, token)

    raw_session = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_session:
        row = session_service.validate_session(db, raw_session)
        if row is not None:
            return db.get(User, row.user_id)  # type: ignore[return-value]
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)

    raise AppError(ErrorCode.UNAUTHORIZED, "Missing authentication credentials.")
