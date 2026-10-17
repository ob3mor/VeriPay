"""Append-only audit service (docs/ARCHITECTURE.md §9, docs/DATABASE.md §15).

Every module writes audit events through ``record_audit`` — never by hand.
The signature is the seam; persistence is the ``audit_events`` table.

Append-only: no update/delete paths exist for audit rows.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.models import AuditEvent

# Bound provenance fields so one oversized header cannot bloat audit rows.
_USER_AGENT_MAX_CHARS = 400


@dataclass(frozen=True)
class AuditContext:
    """Request provenance captured at the HTTP boundary.

    DATABASE.md §15: the ``detail`` column carries ``ip, user_agent,
    request_id, before/after`` so failed-login forensics can attribute
    attempts; ``request_id`` additionally lands in the dedicated column and
    matches the ``request_id`` of the API error envelope (core/errors.py).
    """

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "AuditContext":
        user_agent = request.headers.get("user-agent")
        return cls(
            ip=request.client.host if request.client is not None else None,
            user_agent=user_agent[:_USER_AGENT_MAX_CHARS] if user_agent else None,
            request_id=getattr(request.state, "request_id", None),
        )


def record_audit(
    db: Session,
    *,
    action: str,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_type: ActorType | str = ActorType.USER,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
    context: AuditContext | None = None,
) -> AuditEvent:
    """Append one audit event and commit it.

    Committing here is deliberate: audit rows must survive even when the
    caller raises right after (e.g. a failed login that ends in a 401).

    ``context`` (when given) enriches ``detail`` with ip / user_agent /
    request_id — caller-supplied ``detail`` keys win. An explicit
    ``request_id`` argument always wins over the context's.
    """
    merged_detail = dict(detail or {})
    if context is not None:
        if context.ip is not None:
            merged_detail.setdefault("ip", context.ip)
        if context.user_agent is not None:
            merged_detail.setdefault("user_agent", context.user_agent)
        if context.request_id is not None:
            merged_detail.setdefault("request_id", context.request_id)
            request_id = request_id or context.request_id

    row = AuditEvent(
        action=action,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type=(
            actor_type.value if isinstance(actor_type, ActorType) else actor_type
        ),
        entity_type=entity_type,
        entity_id=entity_id,
        detail=merged_detail,
        request_id=request_id,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return row
