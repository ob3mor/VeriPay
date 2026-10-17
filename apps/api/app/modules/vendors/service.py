"""Vendor-domain business logic: registry, contacts, bank accounts, changes.

R5 enforcement (structural, not advisory):
- ``create_bank_account`` ALWAYS creates a ``pending`` account.
- ``approve_bank_account`` requires verification_method AND (a text reference
  or a verification document) AND the acting human — there is no other code
  path that writes status=approved, and no caller besides the verify route.
- Uploaded documents, invoices and assessments have NO code path into this
  module's approval functions.
- ``approve_change_request`` is the ONLY route that creates an already-
  approved account (the reviewer's decision IS the independent verification
  record), and it too stamps verified_by/verified_at/method/reference.

Full account numbers are fingerprinted (SHA-256 over a digits-only
normalization) and never persisted.
"""

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    BankAccountStatus,
    BankAccountVerificationMethod,
    ChangeRequestStatus,
    VendorStatus,
)
from app.core.errors import AppError, ErrorCode
from app.models import (
    BankAccountChangeRequest,
    User,
    Vendor,
    VendorAuthorizedContact,
    VendorBankAccount,
)


def normalize_account_number(raw: str) -> str:
    """Digits-only normalization for fingerprinting (IBANs, spaces, dashes)."""
    return re.sub(r"\D", "", raw)


def fingerprint_account(raw: str) -> str:
    return hashlib.sha256(normalize_account_number(raw).encode("utf-8")).hexdigest()


def mask_tax_id(tax_id: str | None) -> str | None:
    """Keep the last 2 characters visible; matching-only context."""
    if not tax_id:
        return None
    return "**" + tax_id[-2:] if len(tax_id) > 2 else "**"


def normalize_vendor_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.strip().lower()).strip()


# ----------------------------------------------------------------- vendors ---
def create_vendor(
    db: Session, *, org_id: object, actor: User, display_name: str,
    legal_name: str | None, tax_id: str | None, notes: str | None,
) -> Vendor:
    normalized = normalize_vendor_name(display_name)
    existing = db.scalar(
        select(Vendor).where(
            Vendor.organization_id == org_id,
            Vendor.normalized_name == normalized,
        )
    )
    if existing is not None:
        raise AppError(ErrorCode.CONFLICT, "A vendor with this name already exists.")
    vendor = Vendor(
        organization_id=org_id,
        display_name=display_name.strip(),
        legal_name=legal_name,
        normalized_name=normalized,
        tax_id=tax_id,
        notes=notes,
        created_by=actor.id,
    )
    db.add(vendor)
    try:
        db.commit()
    except IntegrityError as exc:  # race on the org+normalized_name unique
        db.rollback()
        raise AppError(ErrorCode.CONFLICT, "A vendor with this name already exists.") from exc
    return vendor


def get_vendor(db: Session, *, org_id: object, vendor_id: object) -> Vendor:
    """Org-scoped get — a foreign org's id is a plain 404 (no existence leak)."""
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id, Vendor.organization_id == org_id
        )
    )
    if vendor is None:
        raise AppError(ErrorCode.NOT_FOUND, "Vendor not found.")
    return vendor


def list_vendors(db: Session, *, org_id: object, limit: int, offset: int) -> tuple[list[Vendor], int]:
    base = select(Vendor).where(Vendor.organization_id == org_id)
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(Vendor.created_at.desc(), Vendor.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


# ---------------------------------------------------------------- accounts ---
def create_bank_account(
    db: Session, *, org_id: object, vendor_id: object, actor: User,
    holder: str, account_number: str, bank_name: str | None,
    bank_country: str | None, make_current: bool,
) -> VendorBankAccount:
    get_vendor(db, org_id=org_id, vendor_id=vendor_id)  # 404 on cross-org
    fingerprint = fingerprint_account(account_number)
    last4 = normalize_account_number(account_number)[-4:] or None
    if make_current:
        _retire_current_account(db, org_id=org_id, vendor_id=vendor_id)
    account = VendorBankAccount(
        organization_id=org_id,
        vendor_id=vendor_id,
        account_holder_name=holder.strip(),
        bank_name=bank_name,
        bank_country=bank_country,
        account_number_last4=last4,
        account_fingerprint=fingerprint,
        status=BankAccountStatus.PENDING.value,  # R5: always starts pending
        is_current=bool(make_current),
        created_by=actor.id,
    )
    db.add(account)
    db.commit()
    return account


def _retire_current_account(db: Session, *, org_id: object, vendor_id: object) -> None:
    current = db.scalars(
        select(VendorBankAccount).where(
            VendorBankAccount.organization_id == org_id,
            VendorBankAccount.vendor_id == vendor_id,
            VendorBankAccount.is_current.is_(True),
        )
    ).all()
    for row in current:
        row.is_current = False


def get_bank_account(
    db: Session, *, org_id: object, vendor_id: object, account_id: object
) -> VendorBankAccount:
    account = db.scalar(
        select(VendorBankAccount).where(
            VendorBankAccount.id == account_id,
            VendorBankAccount.organization_id == org_id,
            VendorBankAccount.vendor_id == vendor_id,
        )
    )
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND, "Bank account not found.")
    return account


def approve_bank_account(
    db: Session, *, org_id: object, vendor_id: object, account_id: object,
    actor: User, method: str, reference: str | None,
    verification_document_id: object | None,
) -> VendorBankAccount:
    """THE human verification step (R5). Requires an independent record."""
    if method not in {m.value for m in BankAccountVerificationMethod}:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "Unknown verification method.",
        )
    if not reference and verification_document_id is None:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "Independent verification requires a reference or a verification document.",
        )
    account = get_bank_account(db, org_id=org_id, vendor_id=vendor_id, account_id=account_id)
    if account.status == BankAccountStatus.REVOKED.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION, "A revoked account cannot be approved."
        )
    account.status = BankAccountStatus.APPROVED.value
    account.verification_method = method
    account.verification_reference = reference
    account.verification_document_id = verification_document_id
    account.verified_at = datetime.now(timezone.utc)
    account.verified_by = actor.id
    db.commit()
    return account


def reject_bank_account(
    db: Session, *, org_id: object, vendor_id: object, account_id: object,
    actor: User, note: str | None,
) -> VendorBankAccount:
    account = get_bank_account(db, org_id=org_id, vendor_id=vendor_id, account_id=account_id)
    if account.status == BankAccountStatus.APPROVED.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "An approved account cannot be rejected — revoke it instead.",
        )
    account.status = BankAccountStatus.REJECTED.value
    account.verification_reference = note
    account.verified_by = actor.id
    account.verified_at = datetime.now(timezone.utc)
    db.commit()
    return account


def revoke_bank_account(
    db: Session, *, org_id: object, vendor_id: object, account_id: object,
    actor: User,
) -> VendorBankAccount:
    account = get_bank_account(db, org_id=org_id, vendor_id=vendor_id, account_id=account_id)
    account.status = BankAccountStatus.REVOKED.value
    account.is_current = False
    db.commit()
    return account


def list_bank_accounts(
    db: Session, *, org_id: object, vendor_id: object, limit: int, offset: int
) -> tuple[list[VendorBankAccount], int]:
    base = select(VendorBankAccount).where(
        VendorBankAccount.organization_id == org_id,
        VendorBankAccount.vendor_id == vendor_id,
    )
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(VendorBankAccount.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


def find_approved_account_by_fingerprint(
    db: Session, *, org_id: object, fingerprint: str
) -> VendorBankAccount | None:
    """The remittance-matching lookup used by the fraud features."""
    return db.scalar(
        select(VendorBankAccount).where(
            VendorBankAccount.organization_id == org_id,
            VendorBankAccount.account_fingerprint == fingerprint,
            VendorBankAccount.status == BankAccountStatus.APPROVED.value,
        )
    )


# ---------------------------------------------------------- change requests ---
def create_change_request(
    db: Session, *, org_id: object, vendor_id: object, actor: User,
    holder: str, account_number: str, bank_name: str | None,
    bank_country: str | None, reason: str,
) -> BankAccountChangeRequest:
    get_vendor(db, org_id=org_id, vendor_id=vendor_id)
    current = db.scalar(
        select(VendorBankAccount).where(
            VendorBankAccount.organization_id == org_id,
            VendorBankAccount.vendor_id == vendor_id,
            VendorBankAccount.is_current.is_(True),
        )
    )
    request = BankAccountChangeRequest(
        organization_id=org_id,
        vendor_id=vendor_id,
        current_account_id=current.id if current else None,
        proposed_holder_name=holder.strip(),
        proposed_account_fingerprint=fingerprint_account(account_number),
        proposed_account_last4=normalize_account_number(account_number)[-4:] or None,
        proposed_bank_name=bank_name,
        proposed_bank_country=bank_country,
        reason=reason,
        status=ChangeRequestStatus.PENDING.value,
        requested_by=actor.id,
    )
    db.add(request)
    db.commit()
    return request


def get_change_request(
    db: Session, *, org_id: object, request_id: object
) -> BankAccountChangeRequest:
    request = db.scalar(
        select(BankAccountChangeRequest).where(
            BankAccountChangeRequest.id == request_id,
            BankAccountChangeRequest.organization_id == org_id,
        )
    )
    if request is None:
        raise AppError(ErrorCode.NOT_FOUND, "Change request not found.")
    return request


def list_change_requests(
    db: Session, *, org_id: object, vendor_id: object | None = None,
    limit: int, offset: int,
) -> tuple[list[BankAccountChangeRequest], int]:
    query = select(BankAccountChangeRequest).where(
        BankAccountChangeRequest.organization_id == org_id
    )
    if vendor_id is not None:
        query = query.where(BankAccountChangeRequest.vendor_id == vendor_id)
    total = len(db.scalars(query).all())
    rows = db.scalars(
        query.order_by(BankAccountChangeRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), total


def _decide_change_request(
    db: Session, *, org_id: object, request_id: object, actor: User,
    approve: bool, note: str | None,
) -> BankAccountChangeRequest:
    request = get_change_request(db, org_id=org_id, request_id=request_id)
    if request.status != ChangeRequestStatus.PENDING.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "This change request has already been decided.",
        )
    request.status = (
        ChangeRequestStatus.APPROVED.value if approve else ChangeRequestStatus.REJECTED.value
    )
    request.reviewed_by = actor.id
    request.reviewed_at = datetime.now(timezone.utc)
    request.resolution_note = note
    if approve:
        # The reviewer's decision IS the independent verification record
        # (R5): the account is born approved, stamped with the deciding human.
        _retire_current_account(db, org_id=org_id, vendor_id=request.vendor_id)
        account = VendorBankAccount(
            organization_id=request.organization_id,
            vendor_id=request.vendor_id,
            account_holder_name=request.proposed_holder_name,
            bank_name=request.proposed_bank_name,
            bank_country=request.proposed_bank_country,
            account_number_last4=request.proposed_account_last4,
            account_fingerprint=request.proposed_account_fingerprint,
            status=BankAccountStatus.APPROVED.value,
            verification_method=BankAccountVerificationMethod.WRITTEN_CONFIRMATION.value,
            verification_reference=f"change-request:{request.id}",
            verified_at=datetime.now(timezone.utc),
            verified_by=actor.id,
            is_current=True,
            created_by=actor.id,
        )
        db.add(account)
        db.flush()
        request.resulting_account_id = account.id
    db.commit()
    return request


def approve_change_request(
    db: Session, *, org_id: object, request_id: object, actor: User, note: str | None,
) -> BankAccountChangeRequest:
    return _decide_change_request(
        db, org_id=org_id, request_id=request_id, actor=actor, approve=True, note=note
    )


def reject_change_request(
    db: Session, *, org_id: object, request_id: object, actor: User, note: str | None,
) -> BankAccountChangeRequest:
    return _decide_change_request(
        db, org_id=org_id, request_id=request_id, actor=actor, approve=False, note=note
    )


# ---------------------------------------------------------------- contacts ---
def create_contact(
    db: Session, *, org_id: object, vendor_id: object, actor: User,
    full_name: str, role_title: str | None, email: str, phone: str | None,
    is_primary: bool, notes: str | None,
) -> VendorAuthorizedContact:
    get_vendor(db, org_id=org_id, vendor_id=vendor_id)
    if is_primary:
        existing_primary = db.scalars(
            select(VendorAuthorizedContact).where(
                VendorAuthorizedContact.organization_id == org_id,
                VendorAuthorizedContact.vendor_id == vendor_id,
                VendorAuthorizedContact.is_primary.is_(True),
            )
        ).all()
        for row in existing_primary:
            row.is_primary = False
    contact = VendorAuthorizedContact(
        organization_id=org_id,
        vendor_id=vendor_id,
        full_name=full_name.strip(),
        role_title=role_title,
        email=email.strip().lower(),
        phone=phone,
        is_primary=is_primary,
        notes=notes,
        created_by=actor.id,
    )
    db.add(contact)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(ErrorCode.CONFLICT, "This contact already exists for the vendor.") from exc
    return contact


def list_contacts(
    db: Session, *, org_id: object, vendor_id: object, limit: int, offset: int
) -> tuple[list[VendorAuthorizedContact], int]:
    base = select(VendorAuthorizedContact).where(
        VendorAuthorizedContact.organization_id == org_id,
        VendorAuthorizedContact.vendor_id == vendor_id,
    )
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(VendorAuthorizedContact.is_primary.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total
