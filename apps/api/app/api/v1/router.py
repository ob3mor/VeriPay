"""Composition of the /api/v1 router (no business logic here — D4)."""

from fastapi import APIRouter

from app.api.v1.routes import (
    audit_events,
    auth,
    documents,
    health,
    investigations,
    procurement,
    vendors,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(vendors.router)
api_router.include_router(documents.router)
api_router.include_router(procurement.router)
api_router.include_router(investigations.router)
api_router.include_router(audit_events.router)
