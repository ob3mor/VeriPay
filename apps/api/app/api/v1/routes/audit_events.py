"""Audit trail endpoint — org_admin / auditor only (read-only, org-scoped)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import _domain_schemas as ds
from app.core.db import get_db
from app.models import AuditEvent, User
from app.tenancy.deps import get_current_user
from app.tenancy.permissions import CAN_VIEW_AUDIT, require_roles

router = APIRouter(prefix="/audit-events", tags=["audit"])

_viewer = require_roles(*CAN_VIEW_AUDIT)

_Db = Annotated[Session, Depends(get_db)]
_PageLimit = Annotated[int, Query(ge=1, le=100)]
_PageOffset = Annotated[int, Query(ge=0)]


@router.get("", response_model=ds.PageOut[ds.AuditEventOut])
def list_audit_events(
    db: _Db,
    actor: Annotated[User, Depends(_viewer)],
    limit: _PageLimit = 50,
    offset: _PageOffset = 0,
    action: Annotated[str | None, Query(max_length=100)] = None,
) -> ds.PageOut[ds.AuditEventOut]:
    """The tenant's audit trail, newest first. Append-only — there is no
    write, update, or delete path anywhere."""
    base = select(AuditEvent).where(AuditEvent.organization_id == actor.organization_id)
    if action:
        base = base.where(AuditEvent.action == action)
    # Same filter for the count and the page (docs/API.md §3: total is a
    # COUNT over the same org-scoped filter).
    total = len(db.scalars(base).all())
    rows = (
        db.scalars(
            base.order_by(AuditEvent.occurred_at.desc()).offset(offset).limit(limit)
        ).all()
    )
    return ds.PageOut(
        items=[
            ds.AuditEventOut(
                id=e.id,
                organization_id=e.organization_id,
                actor_user_id=e.actor_user_id,
                actor_type=e.actor_type,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                detail=e.detail,
                occurred_at=e.occurred_at.isoformat() if e.occurred_at else None,
            )
            for e in rows
        ],
        pagination=ds.PaginationOut(limit=limit, offset=offset, total=total),
    )
