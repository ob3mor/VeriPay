"""Auth business logic: registration, authentication, token issuance.

Org-scoping rules (docs/API.md §5): the tenant is stamped server-side; the
client never supplies ``organization_id``. Successful AND failed logins are
audit events. Unknown email and wrong password return the same 401 message —
no account enumeration.

Layer agreement: a login may only mint a token for an ACTIVE user — the same
rule tenancy.deps.get_current_user enforces on every request (DATABASE.md §5:
``active | disabled``). A disabled account fails login with the identical 401
(no account enumeration), writes a ``user.login_failed`` audit event, and
never receives a fresh ``user.login_succeeded`` row.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import UserStatus, UserRole
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    PasswordTooLongError,
    create_access_token,
    ensure_password_length,
    hash_password,
    verify_password,
)
from app.models import Organization, User
from app.modules.auth.sessions import create_session
from app.modules.audit.service import AuditContext, record_audit

_EMAIL_ALREADY_EXISTS = "An account with this email already exists."
_INVALID_CREDENTIALS = "Invalid email or password."
_PASSWORD_MAX_BYTES = 72

# Burned on unknown-email lookups so known and unknown emails take the same
# ~one-bcrypt-round path — response timing must not distinguish them (the
# equal-message contract in API.md §4 covers the body; this covers the clock).
_DUMMY_HASH = hash_password("veripay-timing-equalizer")


def slugify(value: str) -> str:
    """URL-safe slug: lowercase, punctuation-collapsed (e.g. "Acme GmbH" ->
    "acme-gmbh")."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "organization"


def _unique_organization_slug(db: Session, name: str) -> str:
    base = slugify(name)[:96]
    candidate = base
    suffix = 2
    while (
        db.scalar(select(Organization.id).where(Organization.slug == candidate))
        is not None
    ):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def register_organization_and_owner(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    context: AuditContext | None = None,
) -> tuple[Organization, User, str, str]:
    """Create a new organization and its org_admin user; return (org, user,
    access token, session cookie token)."""
    normalized_email = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise AppError(ErrorCode.CONFLICT, _EMAIL_ALREADY_EXISTS)

    try:
        ensure_password_length(password)
    except PasswordTooLongError as exc:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Password must be at most {_PASSWORD_MAX_BYTES} bytes.",
        ) from exc

    try:
        org = Organization(
            name=organization_name.strip(),
            slug=_unique_organization_slug(db, organization_name),
        )
        db.add(org)
        # Assign org.id now (default=uuid4 fires at flush) so the owner's
        # organization_id FK captures the real value, not NULL.
        db.flush()
        user = User(
            organization_id=org.id,
            email=normalized_email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            role=UserRole.ORG_ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        db.add(user)
        db.commit()
    except IntegrityError as exc:
        # Race on the unique email/slug constraints.
        db.rollback()
        raise AppError(ErrorCode.CONFLICT, _EMAIL_ALREADY_EXISTS) from exc

    record_audit(
        db,
        action="user.registered",
        organization_id=org.id,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        detail={
            "email": user.email,
            "organization_name": org.name,
            "organization_slug": org.slug,
        },
        context=context,
    )
    token = create_access_token(
        user_id=user.id, organization_id=org.id, role=user.role
    )
    session_token, _row = create_session(
        db,
        user=user,
        ip=context.ip if context else None,
        user_agent=context.user_agent if context else None,
    )
    return org, user, token, session_token


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Verify credentials only — account status is enforced in :func:`login`."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)  # timing equalizer; result unused
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def login(
    db: Session,
    *,
    username: str,
    password: str,
    context: AuditContext | None = None,
) -> tuple[User, str, str]:
    """Authenticate; audit BOTH outcomes; return (user, access token, session
    cookie token).

    Unknown email and wrong password raise the identical 401 — no enumeration
    (the body AND the timing — see _DUMMY_HASH). A disabled account raises
    that same 401 and never mints a token or a session.
    """
    user = authenticate(db, email=username, password=password)
    if user is None:
        # A failed attempt against a known account carries its tenant context
        # (DATABASE.md §15); an unknown email has none.
        attempted = db.scalar(
            select(User).where(User.email == username.strip().lower())
        )
        record_audit(
            db,
            action="user.login_failed",
            organization_id=attempted.organization_id if attempted else None,
            actor_user_id=None,
            entity_type="user" if attempted else None,
            entity_id=attempted.id if attempted else None,
            detail={"email": username[:320], "reason": "invalid_credentials"},
            context=context,
        )
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID_CREDENTIALS)

    # Keep the two auth layers in agreement (tenancy.deps rejects non-active
    # users): a disabled account must not authenticate here.
    if user.status != UserStatus.ACTIVE.value:
        record_audit(
            db,
            action="user.login_failed",
            organization_id=user.organization_id,
            actor_user_id=None,
            entity_type="user",
            entity_id=user.id,
            detail={"email": user.email, "reason": "account_disabled"},
            context=context,
        )
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID_CREDENTIALS)

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(
        db,
        action="user.login_succeeded",
        organization_id=user.organization_id,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email},
        context=context,
    )
    token = create_access_token(
        user_id=user.id, organization_id=user.organization_id, role=user.role
    )
    session_token, _row = create_session(
        db,
        user=user,
        ip=context.ip if context else None,
        user_agent=context.user_agent if context else None,
    )
    return user, token, session_token
