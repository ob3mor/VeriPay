"""FastAPI application factory (docs/ARCHITECTURE.md §3.1).

CORS allowlists the known frontend origins only (local dev origin now; the
SWA origin for PROFILE B) — wildcards are rejected in review (docs/API.md §1).

Every request gets a request id (X-Request-ID response header) that the error
envelope and the audit trail share, so a failed login can be attributed and
correlated across logs, audit_logs.request_id and error responses.
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.errors import install_error_handlers


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp a per-request id: request.state.request_id + X-Request-ID header.

    audit_logs.request_id (String(64)) and the error envelope both carry it.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex  # 32 chars — fits audit_logs.request_id
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VeriPay API",
        version=settings.app_version,
        description=(
            "VeriPay — AI-powered invoice & payment fraud prevention. "
            "Decision-support only: this API never authorizes payments and "
            "never claims an invoice is genuine."
        ),
    )
    # Middleware order (last added = outermost): CORS handles preflight
    # OPTIONS outside everything; RequestId stamps the id before error
    # responses are built; CSRF is innermost so its 403 envelopes still carry
    # the stamped request_id.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
