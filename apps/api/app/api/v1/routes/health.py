"""GET /api/v1/health — public liveness (docs/API.md §4)."""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "veripay-api",
        "version": settings.app_version,
    }
