"""Versioned error envelope (docs/API.md §2).

Every non-2xx response uses::

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}

Handlers are implemented once here; routes raise ``AppError`` and never a
naked ``HTTPException``. ``message`` is safe to display to end users;
``request_id`` correlates with server logs.
"""

import logging
import uuid
from enum import Enum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("veripay.errors")


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    BUSINESS_RULE_VIOLATION = "business_rule_violation"
    RATE_LIMITED = "rate_limited"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INTERNAL = "internal"


STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.BUSINESS_RULE_VIOLATION: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.INTERNAL: 500,
}

_HTTP_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    429: ErrorCode.RATE_LIMITED,
}


def error_payload(
    code: ErrorCode | str,
    message: str,
    details: list[dict[str, str]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value if isinstance(code, ErrorCode) else str(code),
            "message": message,
            "details": details or [],
            # Correlates with audit_logs.request_id (DATABASE.md §15) and the
            # X-Request-ID response header. Falls back to a fresh id only when
            # no request context is available (payloads built off-request).
            "request_id": request_id or str(uuid.uuid4()),
        }
    }


class AppError(Exception):
    """Raise from services/routes; rendered into the versioned envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: list[dict[str, str]] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []
        self.status_code = status_code or STATUS_BY_CODE[code]


def _request_id(request: Request) -> str | None:
    """The id stamped by RequestIdMiddleware (main.py), when present."""
    return getattr(request.state, "request_id", None)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                exc.code, exc.message, exc.details, request_id=_request_id(request)
            ),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[dict[str, str]] = []
        for err in exc.errors():
            loc = [
                str(part)
                for part in err.get("loc", ())
                if part not in ("body", "query", "path", "header")
            ]
            details.append(
                {
                    "field": ".".join(loc) or "body",
                    "message": str(err.get("msg", "invalid value")),
                }
            )
        return JSONResponse(
            status_code=422,
            content=error_payload(
                ErrorCode.VALIDATION_ERROR,
                "Request body failed validation.",
                details,
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL)
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code, str(exc.detail), request_id=_request_id(request)
            ),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never include stack traces or driver errors in the response.
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content=error_payload(
                ErrorCode.INTERNAL,
                "Internal server error.",
                request_id=_request_id(request),
            ),
        )
