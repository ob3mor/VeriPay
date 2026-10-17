"""Vendors, authorized contacts, bank accounts, change requests.

R5 lives here: a bank account starts ``pending`` and ONLY a human approves it
with an independent verification record; a change request is approved by a
human and never by an upload, invoice, or assessment. Full account numbers
and IBANs are NEVER stored — only a SHA-256 fingerprint and the last four
digits (data minimization).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import (
    BankAccountStatus,
    ChangeRequestStatus,
    VendorStatus,
)


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "normalized_name", name="uq_vendors_org_normalized_name"
        ),
        Index("ix_vendors_org_status", "organization_id", "status"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # lowercased, punctuation-collapsed matching key for vendor resolution.
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Masked in API responses; matching-only access.
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=VendorStatus.ACTIVE.value
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL if ingested.
    created_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class VendorAuthorizedContact(TimestampMixin, Base):
    """A contact at the vendor a callback verification can cite.

    R5's ``callback_to_known_contact`` needs a *known* contact to call — this
    is that record, kept structured so verification provenance is citable.
    """

    __tablename__ = "vendor_authorized_contacts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "vendor_id", "email", name="uq_vac_org_vendor_email"
        ),
        Index("ix_vac_org_vendor", "organization_id", "vendor_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    vendor_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class VendorBankAccount(TimestampMixin, Base):
    """A bank account on file for a vendor (the trusted-registry record).

    Invariant R5 (docs/ARCHITECTURE.md §8.5): ``status`` starts ``pending``;
    only a human moves it to ``approved`` and ONLY with an independent
    verification record (method + reference/document + verified_by). There is
    no time-, score-, or volume-based auto-approval, and an uploaded invoice
    can never approve an account.
    """

    __tablename__ = "vendor_bank_accounts"
    __table_args__ = (
        # One current on-file account per vendor per org — historical accounts
        # (is_current=False) coexist. The predicate must be declared for BOTH
        # dialects: with only postgresql_where, SQLite renders a FULL unique
        # index and the is_current history flow breaks (docs/DATABASE.md §1).
        Index(
            "uq_vba_one_current",
            "organization_id",
            "vendor_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("ix_vba_org_vendor", "organization_id", "vendor_id"),
        Index("ix_vba_org_fingerprint", "organization_id", "account_fingerprint"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    vendor_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    account_holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ISO 3166-1 alpha-2.
    bank_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Display only.
    account_number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # SHA-256 of the normalized full account identifier; full numbers/IBANs
    # are never stored anywhere (data minimization).
    account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BankAccountStatus.PENDING.value
    )
    # Independent verification record — mandatory together when approved.
    verification_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_reference: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    # Structured link to the supporting document (bank letter/statement).
    # use_alter: documents ↔ vendors reference each other (vendor_id above).
    verification_document_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", use_alter=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set by the human who verified.
    verified_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Marks the vendor's current on-file account.
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class BankAccountChangeRequest(TimestampMixin, Base):
    """A human-reviewed request to change a vendor's bank account.

    Flow: a finance_officer/org_admin requests the change with a reason; a
    reviewer/org_admin independently approves or rejects it. On approval the
    service (never the requester's client) creates/approves the account
    record. No document upload, invoice, or assessment can touch this table's
    status — that is R5's structural guarantee.
    """

    __tablename__ = "bank_account_change_requests"
    __table_args__ = (
        Index("ix_bacr_org_vendor", "organization_id", "vendor_id"),
        Index("ix_bacr_org_status", "organization_id", "status"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    vendor_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    current_account_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendor_bank_accounts.id"), nullable=True
    )
    # Proposed details — same minimization as the account record itself.
    proposed_holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    proposed_account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    proposed_bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    proposed_bank_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ChangeRequestStatus.PENDING.value
    )
    requested_by: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewed_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set on approval: the account record this change produced. use_alter:
    # vendor_bank_accounts is defined above but this is still a same-module
    # cycle through a table created later in the migration.
    resulting_account_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("vendor_bank_accounts.id", use_alter=True),
        nullable=True,
    )
