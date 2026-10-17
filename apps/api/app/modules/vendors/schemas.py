"""Vendor-domain schemas.

Masking rules (docs/API.md §5.8, R5): ordinary responses carry only the last
four digits — never a full account number (it is not even stored), never the
``account_fingerprint`` (server-side matching key), and never the
verification provenance (method/reference/document) — that record is visible
only in the reviewer/org_admin detail view, where proving independent
verification is the point.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    BankAccountStatus,
    ChangeRequestStatus,
    VendorStatus,
)


# ---------------------------------------------------------------- vendors ---
class VendorIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    display_name: str
    legal_name: str | None
    tax_id_masked: str | None
    status: VendorStatus
    created_at: str | None = None
    updated_at: str | None = None


# -------------------------------------------------------------- contacts ---
class ContactIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    role_title: str | None = Field(default=None, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    is_primary: bool = False
    notes: str | None = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    full_name: str
    role_title: str | None
    email: str
    phone: str | None
    is_primary: bool


# ---------------------------------------------------------- bank accounts ---
class BankAccountIn(BaseModel):
    """Create a pending bank account. ``account_number`` (or IBAN) is the
    ONLY place the full value may appear — the service fingerprints it and
    stores the hash; the raw value never touches the database or logs."""

    account_holder_name: str = Field(min_length=1, max_length=200)
    account_number: str = Field(min_length=4, max_length=64)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_country: str | None = Field(default=None, min_length=2, max_length=2)
    make_current: bool = True


class BankAccountOut(BaseModel):
    """Ordinary view — masked (see module docstring)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    account_holder_name: str
    bank_name: str | None
    bank_country: str | None
    account_number_last4: str | None
    status: BankAccountStatus
    is_current: bool


class BankAccountDetail(BankAccountOut):
    """Reviewer/org_admin investigation view — adds the R5 verification
    provenance (still never the fingerprint or any full number)."""

    verification_method: str | None
    verification_reference: str | None
    verification_document_id: uuid.UUID | None
    verified_at: str | None = None
    verified_by: uuid.UUID | None = None


class VerifyAccountIn(BaseModel):
    """Human approval (R5). Exactly one of reference/document proof must be
    supplied together with the method; there is no approval without one."""

    verification_method: str = Field(max_length=32)
    verification_reference: str | None = Field(default=None, max_length=200)
    verification_document_id: uuid.UUID | None = None


class RejectAccountIn(BaseModel):
    resolution_note: str | None = None


# --------------------------------------------------------- change requests ---
class ChangeRequestIn(BaseModel):
    """Request a bank-account change for a vendor. Requires a reason; the
    proposed account number is fingerprinted exactly like a direct account."""

    account_holder_name: str = Field(min_length=1, max_length=200)
    account_number: str = Field(min_length=4, max_length=64)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_country: str | None = Field(default=None, min_length=2, max_length=2)
    reason: str = Field(min_length=1)


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    current_account_id: uuid.UUID | None
    proposed_holder_name: str
    proposed_account_last4: str | None
    proposed_bank_name: str | None
    proposed_bank_country: str | None
    reason: str
    status: ChangeRequestStatus
    requested_by: uuid.UUID
    reviewed_by: uuid.UUID | None
    resolution_note: str | None


class ChangeRequestDecisionIn(BaseModel):
    resolution_note: str | None = None
