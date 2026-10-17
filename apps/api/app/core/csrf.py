"""CSRF protection for cookie-authenticated state-changing requests.

Threat model: a session cookie is *ambient authority* — a malicious page
could make the victim's browser send it along. Two independent defenses:

1. **Token check** (double submit): a mutating request that authenticates via
   the session cookie must carry header ``X-CSRF-Token`` equal to the
   readable ``veripay_csrf`` cookie. A cross-origin attacker can force the
   cookies to travel but cannot read them, so it cannot echo the token.
2. **Origin check**: when the browser supplies ``Origin``/``Referer`` (it
   does on cross-site and same-site POSTs), their origin must be in the CORS
   allowlist.

Bearer-token requests are exempt from the token check — an Authorization
header is not ambient authority (the attacker cannot force it), so CSRF does
not apply. Pre-auth endpoints (login/register/refresh) skip the token check
(no session yet) but still get the Origin check.
"""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_settings,
)
from app.core.errors import error_payload

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(value: str) -> str | None:
    """scheme://host[:port] of an Origin or Referer header value."""
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _origin_allowed(origin: str, allowed: list[str]) -> bool:
    return origin in allowed


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in _MUTATING_METHODS and request.url.path.startswith("/api/"):
            settings = get_settings()

            raw = request.headers.get("origin") or request.headers.get("referer")
            if raw:
                origin = _origin_of(raw)
                if origin is not None and not _origin_allowed(origin, settings.cors_origins):
                    return JSONResponse(
                        status_code=403,
                        content=error_payload(
                            "forbidden",
                            "Request origin is not allowed.",
                            request_id=getattr(request.state, "request_id", None),
                        ),
                    )

            via_bearer = "authorization" in request.headers
            if not via_bearer and SESSION_COOKIE_NAME in request.cookies:
                header_token = request.headers.get(CSRF_HEADER_NAME)
                cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
                if (
                    not header_token
                    or not cookie_token
                    or header_token != cookie_token
                ):
                    return JSONResponse(
                        status_code=403,
                        content=error_payload(
                            "forbidden",
                            "Missing or invalid CSRF token.",
                            request_id=getattr(request.state, "request_id", None),
                        ),
                    )
        return await call_next(request)


def install_csrf_middleware(app: FastAPI) -> None:
    app.add_middleware(CsrfMiddleware)
