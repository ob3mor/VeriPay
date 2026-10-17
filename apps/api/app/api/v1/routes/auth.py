"""Auth routes (docs/API.md §4): Bearer JWTs AND httpOnly cookie sessions.

- POST /auth/register: creates the organization + its org_admin user, 201,
  sets veripay_session (httpOnly) + veripay_csrf cookies.
- POST /auth/login: OAuth2 password form (username=<email>) so FastAPI's
  "Authorize" button works out of the box. Throttled per client IP with a
  failed-attempt lockout per (IP, email) — core/ratelimit.py. Sets both
  cookies and returns the short-lived Bearer token.
- POST /auth/refresh: session cookie (+ Origin check) → a fresh Bearer token.
- GET /auth/me: Bearer or session cookie; identity resolved org-scoped.
- POST /auth/logout: Bearer → revokes the token jti; cookie → revokes the
  durable session row; clears both cookies.

Every endpoint forwards request provenance (ip / user agent / request_id) to
the audit trail via AuditContext (docs/DATABASE.md §15).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    get_settings,
)
from app.core.db import get_db
from app.core.enums import UserStatus
from app.core.errors import AppError, ErrorCode
from app.core.ratelimit import (
    login_lockout,
    login_rate_limiter,
    register_rate_limiter,
)
from app.core.security import (
    create_access_token,
    csrf_token_for,
    decode_access_token,
)
from app.core.token_store import revoked_tokens
from app.models import User
from app.modules.auth import schemas
from app.modules.auth import sessions as session_service
from app.modules.auth import service as auth_service
from app.modules.audit.service import AuditContext, record_audit
from app.tenancy.deps import get_current_user, oauth2_scheme

router = APIRouter(prefix="/auth", tags=["auth"])

_DbSession = Annotated[Session, Depends(get_db)]

_INVALID = "Invalid or expired authentication token."
_LOGIN_THROTTLED = "Too many sign-in attempts. Please try again later."
_ACCOUNT_LOCKED = (
    "Too many failed sign-in attempts for this account. Please try again later."
)
_REGISTER_THROTTLED = "Too many registration attempts. Please try again later."


def client_ip(request: Request) -> str:
    """Socket peer as the client identity (see core/ratelimit.py for why this
    is deliberately not X-Forwarded-For)."""
    return request.client.host if request.client is not None else "unknown"


def lockout_key(request: Request, username: str) -> tuple[str, str]:
    """Failed-attempt lockout is per (client IP, normalized email) — a single
    source cannot brute-force one account, and sprayed failures from many IPs
    cannot mass-lock victim accounts."""
    return (client_ip(request), username.strip().lower())


def _set_session_cookies(response: Response, session_token: str) -> None:
    """veripay_session: httpOnly, SameSite=Lax (the ambient authority).
    veripay_csrf: readable by JS so the SPA can echo it in X-CSRF-Token.

    The csrf cookie deliberately does NOT carry the session token: it is
    readable by any script on the page, so a script that reads it must not
    obtain a replayable session credential. It carries a DERIVED value —
    HMAC of the session token (core/security.csrf_token_for) — which the
    double-submit check and the middleware's stateless pairing verification
    accept, while ``sessions.validate_session`` keeps validating only the
    raw httpOnly value.
    """
    settings = get_settings()
    max_age = settings.session_ttl_days * 24 * 3600
    common = {"samesite": "lax", "secure": settings.cookie_secure, "path": "/"}
    response.set_cookie(
        SESSION_COOKIE_NAME, session_token, max_age=max_age, httponly=True, **common
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token_for(session_token),
        max_age=max_age,
        httponly=False,
        **common,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def enforce_register_throttle(request: Request) -> None:
    if not register_rate_limiter.check(f"register:{client_ip(request)}"):
        raise AppError(ErrorCode.RATE_LIMITED, _REGISTER_THROTTLED)


def enforce_login_throttle(
    request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> None:
    if not login_rate_limiter.check(f"login:{client_ip(request)}"):
        raise AppError(ErrorCode.RATE_LIMITED, _LOGIN_THROTTLED)
    if login_lockout.is_locked(lockout_key(request, form.username)):
        raise AppError(ErrorCode.RATE_LIMITED, _ACCOUNT_LOCKED)


@router.post(
    "/register",
    response_model=schemas.RegisterResponse,
    status_code=201,
    dependencies=[Depends(enforce_register_throttle)],
)
def register(
    payload: schemas.RegisterRequest,
    db: _DbSession,
    request: Request,
    response: Response,
) -> schemas.RegisterResponse:
    org, user, token, session_token = auth_service.register_organization_and_owner(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        context=AuditContext.from_request(request),
    )
    _set_session_cookies(response, session_token)
    return schemas.RegisterResponse(
        user=schemas.UserOut.model_validate(user),
        organization=schemas.OrganizationOut.model_validate(org),
        access_token=token,
    )


@router.post("/login", response_model=schemas.TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: _DbSession,
    request: Request,
    response: Response,
    _throttle: None = Depends(enforce_login_throttle),
) -> schemas.TokenResponse:
    account = lockout_key(request, form.username)
    try:
        _user, token, session_token = auth_service.login(
            db,
            username=form.username,
            password=form.password,
            context=AuditContext.from_request(request),
        )
    except AppError as exc:
        # Failed credentials (including a disabled account) count toward the
        # per-account lockout; throttling responses do not.
        if exc.code == ErrorCode.UNAUTHORIZED:
            login_lockout.record_failure(account)
        raise
    login_lockout.clear(account)
    _set_session_cookies(response, session_token)
    return schemas.TokenResponse(access_token=token)


@router.post("/refresh", response_model=schemas.TokenResponse)
def refresh(
    request: Request,
    db: _DbSession,
) -> schemas.TokenResponse:
    """Exchange the live session cookie for a fresh short-lived Bearer token.

    Throttled like login. The CSRF middleware has already enforced the
    Origin/Referer allowlist for this mutating, cookie-authenticated request.
    """
    if not login_rate_limiter.check(f"refresh:{client_ip(request)}"):
        raise AppError(ErrorCode.RATE_LIMITED, _LOGIN_THROTTLED)
    raw_session = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_session:
        raise AppError(ErrorCode.UNAUTHORIZED, "Missing session cookie.")
    row = session_service.validate_session(db, raw_session)
    if row is None:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)
    user = db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AppError(ErrorCode.UNAUTHORIZED, _INVALID)
    token = create_access_token(
        user_id=user.id, organization_id=user.organization_id, role=user.role
    )
    return schemas.TokenResponse(access_token=token)


@router.get("/me", response_model=schemas.MeResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> schemas.MeResponse:
    return schemas.MeResponse(
        user=schemas.UserOut.model_validate(current_user),
        organization=schemas.OrganizationOut.model_validate(current_user.organization),
    )


@router.post("/logout", response_model=schemas.LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: _DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> schemas.LogoutResponse:
    """Revoke the presented credential server-side and clear cookies.

    Bearer → the token's jti joins the revocation registry until expiry.
    Session cookie → the durable session row is revoked.
    """
    via = []
    if token:
        payload = decode_access_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp is not None:
            revoked_tokens.revoke(str(jti), float(exp))
            via.append("bearer")
    raw_session = request.cookies.get(SESSION_COOKIE_NAME)
    session_revoked = False
    if raw_session:
        session_revoked = session_service.revoke_session(db, raw_session)
        if session_revoked:
            via.append("session")
    record_audit(
        db,
        action="user.logout",
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
        detail={"email": current_user.email, "via": via},
        context=AuditContext.from_request(request),
    )
    _clear_session_cookies(response)
    return schemas.LogoutResponse()
