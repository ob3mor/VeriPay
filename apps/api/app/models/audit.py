"""Append-only audit events (docs/DATABASE.md §15).

``organization_id`` is the one intentional exception to mandatory org scoping:
pre-auth events (e.g. failed login for an unknown email) have no tenant.
``entity_id`` carries no FK so the log survives entity deletion. Rows are
never updated in practice; the service layer enforces append-only.

Renamed from Phase 1's ``audit_logs`` to the canonical ``audit_events``.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import ActorType


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_ae_org", "organization_id"),
        Index("ix_ae_action", "action"),
        Index("ix_ae_occurred", "occurred_at"),
        Index("ix_ae_entity", "entity_type", "entity_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    # Nullable on purpose (pre-auth events); rows WITH tenant context MUST
    # carry it.
    organization_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # NULL for system actors.
    actor_user_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ActorType.USER.value
    )
    # Dotted names: user.registered, user.login_succeeded, user.login_failed,
    # vendor.account.approved, document.uploaded, assessment.created, ...
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # Polymorphic.
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # No FK — the log survives entity deletion.
    entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # ip, user_agent, request_id, before/after (secrets redacted).
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Correlates with the API error envelope.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Event time — the source of truth.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
