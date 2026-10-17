"""Investigation cases and review actions (docs/DATABASE.md §15).

R6: only the fraud module (system actor) auto-creates cases; cases cannot
close without a human outcome + resolution summary (ck_icase_close). Every
human decision on a case lands in ``review_actions`` — the investigation
record — not in free-floating notes.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import CaseStatus


class InvestigationCase(TimestampMixin, Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        CheckConstraint(
            "invoice_id IS NOT NULL OR vendor_id IS NOT NULL", name="ck_icase_target"
        ),
        CheckConstraint(
            "status <> 'closed' OR (outcome IS NOT NULL AND "
            "resolution_summary IS NOT NULL)",
            name="ck_icase_close",
        ),
        UniqueConstraint(
            "organization_id", "case_number", name="uq_icase_org_number"
        ),
        Index("ix_icase_org_status", "organization_id", "status"),
        Index("ix_icase_org_assignee", "organization_id", "assigned_to"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # Human-friendly per-org sequence, e.g. CASE-2026-0001.
    case_number: Mapped[str] = mapped_column(String(32), nullable=False)
    # Vendor-scoped cases have NULL invoice_id.
    invoice_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", use_alter=True), nullable=True
    )
    vendor_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    # The assessment that opened the case (R6 provenance); the latest
    # assessment can differ — composed views anchor here, falling back to
    # the latest.
    triggering_assessment_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fraud_assessments.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mirrored from the triggering assessment.
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CaseStatus.OPEN.value
    )
    # Set only by a human at close (R2 — a disposition, not a genuineness claim).
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_to: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # NULL when auto-opened by the fraud module (system actor).
    opened_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Required when closing.
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReviewAction(TimestampMixin, Base):
    """The human investigation record: every comment, decision, assignment,
    status change, field verification, and bank-account action on a case —
    and, since EVC v1, finding dispositions / match reviews made outside a
    case context (``case_id`` NULL; the payload names the exact finding or
    match). Every human override carries its mandatory reason in ``body``."""

    __tablename__ = "review_actions"
    __table_args__ = (
        Index("ix_ra_org_case", "organization_id", "case_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # NULL for override records written outside a case context (e.g. a
    # finding dispositioned on an invoice with no investigation case yet).
    case_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_cases.id"), nullable=True
    )
    # NULL = system-generated action (e.g. auto-open reason).
    actor_user_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured payload: before/after, linked entities, verification details.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
