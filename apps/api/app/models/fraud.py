"""Fraud assessments, per-signal findings, evidence matches.

R2: there is NO is_fraud/is_genuine column anywhere — assessments carry
signals, explanations and residual uncertainty only. ``evc`` is a Phase 4
placeholder that must remain NULL until Phase 4 defines it; no code may read
or write it before then.

Signals are persisted as ``fraud_findings`` child rows (one per signal) so
humans can disposition each independently; the assessment keeps a denorma-
lized snapshot in ``signals`` for point-in-time reading.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import FindingDisposition, MatchStatus


class FraudAssessment(TimestampMixin, Base):
    __tablename__ = "fraud_assessments"
    __table_args__ = (
        Index("ix_fa_org_invoice", "organization_id", "invoice_id"),
        Index("ix_fa_org_risk", "organization_id", "risk_level"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    invoice_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    # 0..100, meaningful only within model_version; NULL when not computable.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Feature + scoring version that produced this row.
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Every computed feature with its inputs and evidence references.
    feature_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Denormalized snapshot of the child findings at assessment time:
    # [{type, severity, field_refs, evidence_refs, message}].
    signals: Mapped[list] = mapped_column(JSON, nullable=False)
    # Ordered human-readable reasons — the "explainable" deliverable.
    explanation: Mapped[list] = mapped_column(JSON, nullable=False)
    # Phase 4 placeholder; must remain NULL until Phase 4 defines it.
    evc: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    triggered_by_user_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class FraudFinding(TimestampMixin, Base):
    """One signal of one assessment, independently dispositionable by a human.

    Severity floors (docs/ARCHITECTURE.md §8): bank_account_unverified may
    not be downgraded below ``high``; missing_evidence may not exceed
    ``medium``. The scoring service enforces this; the DB stores what the
    service wrote.
    """

    __tablename__ = "fraud_findings"
    __table_args__ = (
        Index("ix_ff_org_assessment", "organization_id", "assessment_id"),
        Index("ix_ff_org_type", "organization_id", "signal_type"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    assessment_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fraud_assessments.id"), nullable=False
    )
    invoice_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    field_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    disposition: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FindingDisposition.OPEN.value
    )
    dispositioned_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    dispositioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EvidenceMatch(TimestampMixin, Base):
    """A match between two entities with its evidence and human disposition.

    Replaces the Phase-1 ``duplicate_matches`` design: the duplicate kinds
    (invoice_number, near_duplicate, field_overlap) keep their semantics, and
    registry matches (bank_account, vendor, purchase_order) record how an
    invoice's printed details matched the trusted registries.
    """

    __tablename__ = "evidence_matches"
    __table_args__ = (
        CheckConstraint(
            "NOT (source_entity_type = 'invoice' AND target_entity_type = 'invoice'"
            " AND source_entity_id = target_entity_id)",
            name="ck_em_not_self",
        ),
        Index("ix_em_org_source", "organization_id", "source_entity_type",
              "source_entity_id"),
        Index("ix_em_org_target", "organization_id", "target_entity_type",
              "target_entity_id"),
        Index("ix_em_org_kind", "organization_id", "match_kind"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # e.g. ("invoice", <invoice_id>) matched to ("vendor_bank_accounts", <id>).
    source_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # 0..1.
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Which fields matched and with which values (audit-safe, masked values).
    matched_fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Which module created this row (fraud, vendors, procurement...).
    created_by_module: Mapped[str] = mapped_column(String(32), nullable=False)
    # Human disposition.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MatchStatus.OPEN.value
    )
    reviewed_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
