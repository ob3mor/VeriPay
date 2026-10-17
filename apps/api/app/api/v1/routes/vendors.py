"""Vendor-domain routes (docs/API.md §6): registry, contacts, bank accounts.

Roles: contribute (org_admin, finance_officer) creates vendors/contacts/
accounts/change requests; verify-level (org_admin, reviewer) approves,
rejects and revokes accounts and decides change requests (R5).

Every response is masked per docs/API.md §5.8: no full account numbers
(nowhere stored), no fingerprints, no verification provenance outside the
reviewer/org_admin detail surface.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import VendorStatus
from app.modules.audit.service import AuditContext, record_audit
from app.modules.vendors import schemas, service
from app.models import User
from app.tenancy.deps import get_current_user
from app.tenancy.permissions import CAN_CONTRIBUTE, CAN_VERIFY_ACCOUNTS, require_roles

router = APIRouter(prefix="/vendors", tags=["vendors"])

_contributor = require_roles(*CAN_CONTRIBUTE)
_verifier = require_roles(*CAN_VERIFY_ACCOUNTS)

_Db = Annotated[Session, Depends(get_db)]
_PageLimit = Annotated[int, Query(ge=1, le=100)]
_PageOffset = Annotated[int, Query(ge=0)]


def _vendor_out(vendor) -> schemas.VendorOut:
    return schemas.VendorOut(
        id=vendor.id,
        organization_id=vendor.organization_id,
        display_name=vendor.display_name,
        legal_name=vendor.legal_name,
        tax_id_masked=service.mask_tax_id(vendor.tax_id),
        status=VendorStatus(vendor.status),
    )


def _account_out(account) -> schemas.BankAccountOut:
    return schemas.BankAccountOut(
        id=account.id,
        vendor_id=account.vendor_id,
        account_holder_name=account.account_holder_name,
        bank_name=account.bank_name,
        bank_country=account.bank_country,
        account_number_last4=account.account_number_last4,
        status=account.status,
        is_current=account.is_current,
    )


def _account_detail(account) -> schemas.BankAccountDetail:
    return schemas.BankAccountDetail(
        **_account_out(account).model_dump(),
        verification_method=account.verification_method,
        verification_reference=account.verification_reference,
        verification_document_id=account.verification_document_id,
        verified_by=account.verified_by,
    )


@router.post("", response_model=schemas.VendorOut, status_code=201)
def create_vendor(
    payload: schemas.VendorIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> schemas.VendorOut:
    vendor = service.create_vendor(
        db,
        org_id=actor.organization_id,
        actor=actor,
        display_name=payload.display_name,
        legal_name=payload.legal_name,
        tax_id=payload.tax_id,
        notes=payload.notes,
    )
    record_audit(
        db,
        action="vendor.created",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor",
        entity_id=vendor.id,
        detail={"display_name": vendor.display_name},
        context=AuditContext.from_request(request),
    )
    return _vendor_out(vendor)


@router.get("", response_model=list[schemas.VendorOut])
def list_vendors(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
    limit: _PageLimit = 25,
    offset: _PageOffset = 0,
) -> list[schemas.VendorOut]:
    rows, _total = service.list_vendors(
        db, org_id=actor.organization_id, limit=limit, offset=offset
    )
    return [_vendor_out(v) for v in rows]


@router.get("/{vendor_id}", response_model=schemas.VendorOut)
def get_vendor(
    vendor_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> schemas.VendorOut:
    vendor = service.get_vendor(db, org_id=actor.organization_id, vendor_id=vendor_id)
    return _vendor_out(vendor)


# -------------------------------------------------------------- contacts ---
@router.post(
    "/{vendor_id}/contacts", response_model=schemas.ContactOut, status_code=201
)
def create_contact(
    vendor_id: uuid.UUID,
    payload: schemas.ContactIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> schemas.ContactOut:
    contact = service.create_contact(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        actor=actor,
        full_name=payload.full_name,
        role_title=payload.role_title,
        email=payload.email,
        phone=payload.phone,
        is_primary=payload.is_primary,
        notes=payload.notes,
    )
    record_audit(
        db,
        action="vendor.contact.created",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor_authorized_contact",
        entity_id=contact.id,
        detail={"vendor_id": str(vendor_id)},
        context=AuditContext.from_request(request),
    )
    return schemas.ContactOut.model_validate(contact)


@router.get("/{vendor_id}/contacts", response_model=list[schemas.ContactOut])
def list_contacts(
    vendor_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> list[schemas.ContactOut]:
    rows = service.list_contacts(
        db, org_id=actor.organization_id, vendor_id=vendor_id
    )
    return [schemas.ContactOut.model_validate(c) for c in rows]


# ----------------------------------------------------------- bank accounts ---
@router.post(
    "/{vendor_id}/bank-accounts",
    response_model=schemas.BankAccountOut,
    status_code=201,
)
def create_bank_account(
    vendor_id: uuid.UUID,
    payload: schemas.BankAccountIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> schemas.BankAccountOut:
    """Register a bank account — ALWAYS born ``pending`` (R5).

    The raw account number exists only in this request body: the service
    fingerprints it, stores the hash + last4, and the value never lands in
    the database, the audit log, or any response.
    """
    account = service.create_bank_account(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        actor=actor,
        holder=payload.account_holder_name,
        account_number=payload.account_number,
        bank_name=payload.bank_name,
        bank_country=payload.bank_country,
        make_current=payload.make_current,
    )
    record_audit(
        db,
        action="vendor.account.registered",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor_bank_account",
        entity_id=account.id,
        detail={"vendor_id": str(vendor_id), "status": account.status,
                "last4": account.account_number_last4},
        context=AuditContext.from_request(request),
    )
    return _account_out(account)


@router.get("/{vendor_id}/bank-accounts")
def list_bank_accounts(
    vendor_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> list[schemas.BankAccountOut | schemas.BankAccountDetail]:
    """Masked account list. reviewer/org_admin additionally receive the R5
    verification provenance (the investigation view); other roles do not."""
    rows = service.list_bank_accounts(
        db, org_id=actor.organization_id, vendor_id=vendor_id
    )
    role = actor.role
    if role in ("org_admin", "reviewer"):
        return [_account_detail(a) for a in rows]
    return [_account_out(a) for a in rows]


@router.post(
    "/{vendor_id}/bank-accounts/{account_id}/verify",
    response_model=schemas.BankAccountDetail,
)
def verify_bank_account(
    vendor_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: schemas.VerifyAccountIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> schemas.BankAccountDetail:
    """Human approval (R5): method + reference/document + verifier mandatory."""
    account = service.approve_bank_account(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        account_id=account_id,
        actor=actor,
        method=payload.verification_method,
        reference=payload.verification_reference,
        verification_document_id=payload.verification_document_id,
    )
    record_audit(
        db,
        action="vendor.account.approved",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor_bank_account",
        entity_id=account.id,
        detail={"vendor_id": str(vendor_id), "method": account.verification_method},
        context=AuditContext.from_request(request),
    )
    return _account_detail(account)


@router.post(
    "/{vendor_id}/bank-accounts/{account_id}/reject",
    response_model=schemas.BankAccountDetail,
)
def reject_bank_account(
    vendor_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: schemas.RejectAccountIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> schemas.BankAccountDetail:
    account = service.reject_bank_account(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        account_id=account_id,
        actor=actor,
        note=payload.resolution_note,
    )
    record_audit(
        db,
        action="vendor.account.rejected",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor_bank_account",
        entity_id=account.id,
        detail={"vendor_id": str(vendor_id)},
        context=AuditContext.from_request(request),
    )
    return _account_detail(account)


@router.post(
    "/{vendor_id}/bank-accounts/{account_id}/revoke",
    response_model=schemas.BankAccountDetail,
)
def revoke_bank_account(
    vendor_id: uuid.UUID,
    account_id: uuid.UUID,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> schemas.BankAccountDetail:
    account = service.revoke_bank_account(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        account_id=account_id,
        actor=actor,
    )
    record_audit(
        db,
        action="vendor.account.revoked",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="vendor_bank_account",
        entity_id=account.id,
        detail={"vendor_id": str(vendor_id)},
        context=AuditContext.from_request(request),
    )
    return _account_detail(account)


# --------------------------------------------------------- change requests ---
@router.post(
    "/{vendor_id}/change-requests",
    response_model=schemas.ChangeRequestOut,
    status_code=201,
)
def create_change_request(
    vendor_id: uuid.UUID,
    payload: schemas.ChangeRequestIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> schemas.ChangeRequestOut:
    change = service.create_change_request(
        db,
        org_id=actor.organization_id,
        vendor_id=vendor_id,
        actor=actor,
        holder=payload.account_holder_name,
        account_number=payload.account_number,
        bank_name=payload.bank_name,
        bank_country=payload.bank_country,
        reason=payload.reason,
    )
    record_audit(
        db,
        action="vendor.change.requested",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="bank_account_change_request",
        entity_id=change.id,
        detail={"vendor_id": str(vendor_id), "reason": change.reason[:200]},
        context=AuditContext.from_request(request),
    )
    return schemas.ChangeRequestOut.model_validate(change)


@router.get(
    "/{vendor_id}/change-requests", response_model=list[schemas.ChangeRequestOut]
)
def list_change_requests(
    vendor_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> list[schemas.ChangeRequestOut]:
    rows = service.list_change_requests(
        db, org_id=actor.organization_id, vendor_id=vendor_id
    )
    return [schemas.ChangeRequestOut.model_validate(c) for c in rows]


@router.post(
    "/{vendor_id}/change-requests/{request_id}/approve",
    response_model=schemas.ChangeRequestOut,
)
def approve_change_request(
    vendor_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: schemas.ChangeRequestDecisionIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> schemas.ChangeRequestOut:
    """Reviewer decision (R5): on approval the service creates the already-
    approved account stamped with the deciding human."""
    change = service.approve_change_request(
        db,
        org_id=actor.organization_id,
        request_id=request_id,
        actor=actor,
        note=payload.resolution_note,
    )
    record_audit(
        db,
        action="vendor.change.approved",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="bank_account_change_request",
        entity_id=change.id,
        detail={"vendor_id": str(vendor_id),
                "resulting_account_id": str(change.resulting_account_id)},
        context=AuditContext.from_request(request),
    )
    return schemas.ChangeRequestOut.model_validate(change)


@router.post(
    "/{vendor_id}/change-requests/{request_id}/reject",
    response_model=schemas.ChangeRequestOut,
)
def reject_change_request(
    vendor_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: schemas.ChangeRequestDecisionIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> schemas.ChangeRequestOut:
    change = service.reject_change_request(
        db,
        org_id=actor.organization_id,
        request_id=request_id,
        actor=actor,
        note=payload.resolution_note,
    )
    record_audit(
        db,
        action="vendor.change.rejected",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="bank_account_change_request",
        entity_id=change.id,
        detail={"vendor_id": str(vendor_id)},
        context=AuditContext.from_request(request),
    )
    return schemas.ChangeRequestOut.model_validate(change)
