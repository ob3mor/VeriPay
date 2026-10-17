"""Durable browser sessions (the httpOnly-cookie auth strategy).

The raw cookie value is a random opaque token; only its SHA-256 hash is
stored (``sessions.token_hash``), so a database leak cannot mint sessions.
Validation is a single indexed lookup plus expiry/revocation/user-active
checks. This replaces the Phase 1 in-process token store for cookie
sessions — revocation is durable and replica-safe.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.core.security import generate_session_token, hash_session_token
from app.models import Session, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes for DateTime(timezone=True) columns;
    every comparison normalizes through this helper."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def create_session(
    db: DBSession, *, user: User, ip: str | None = None, user_agent: str | None = None
) -> tuple[str, Session]:
    """Create a session row and return (raw cookie token, row)."""
    raw = generate_session_token()
    ttl_days = get_settings().session_ttl_days
    row = Session(
        user_id=user.id,
        token_hash=hash_session_token(raw),
        expires_at=_now() + timedelta(days=ttl_days),
        last_used_at=_now(),
        ip=ip[:64] if ip else None,
        user_agent=user_agent[:400] if user_agent else None,
    )
    db.add(row)
    db.commit()
    return raw, row


def validate_session(db: DBSession, raw_token: str) -> Session | None:
    """Return the live session row for a raw cookie token, or None.

    Rejects unknown, expired, revoked sessions and sessions whose user is no
    longer active. Updates ``last_used_at`` (sliding activity marker).
    """
    if not raw_token:
        return None
    row = db.scalar(select(Session).where(Session.token_hash == hash_session_token(raw_token)))
    if row is None:
        return None
    now = _now()
    if _aware(row.expires_at) <= now or row.revoked_at is not None:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    row.last_used_at = now
    db.commit()
    return row


def revoke_session(db: DBSession, raw_token: str) -> bool:
    """Revoke one session by its raw cookie token. Idempotent."""
    row = db.scalar(select(Session).where(Session.token_hash == hash_session_token(raw_token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    db.commit()
    return True


def revoke_all_for_user(db: DBSession, user_id: object) -> int:
    """Revoke every live session of a user (e.g. account disabled)."""
    rows = db.scalars(
        select(Session).where(
            Session.user_id == user_id, Session.revoked_at.is_(None)
        )
    ).all()
    for row in rows:
        row.revoked_at = _now()
    if rows:
        db.commit()
    return len(rows)
