"""Investigation routes: fraud assessments, cases, review actions.

Roles: run assessments / work cases = org_admin, finance_officer, reviewer;
closing a case (R6 decision) and dispositions = org_admin, reviewer.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.routes import _domain_schemas as ds
from app.core.db import get_db
from app.modules.audit.service import AuditContext, record_audit
from app.modules.cases import service as cases_service
from app.modules.fraud import service as fraud_service
from app.models import User
from app.tenancy.deps import get_current_user
from app.tenancy.permissions import (
    CAN_CONTRIBUTE,
    CAN_VERIFY_ACCOUNTS,
    require_roles,
)

router = APIRouter(tags=["investigations"])

_contributor = require_roles(*CAN_CONTRIBUTE)
_verifier = require_roles(*CAN_VERIFY_ACCOUNTS)

_Db = Annotated[Session, Depends(get_db)]
_PageLimit = Annotated[int, Query(ge=1, le=100)]
_PageOffset = Annotated[int, Query(ge=0)]


def _finding_out(f) -> ds.FraudFindingOut:
    return ds.FraudFindingOut(
        id=f.id,
        signal_type=f.signal_type,
        severity=f.severity,
        message=f.message,
        field_refs=f.field_refs,
        evidence_refs=f.evidence_refs,
        disposition=f.disposition,
        dispositioned_by=f.dispositioned_by,
        dispositioned_at=(
            f.dispositioned_at.isoformat() if f.dispositioned_at else None
        ),
    )


def _assessment_out(a) -> ds.FraudAssessmentOut:
    return ds.FraudAssessmentOut(
        id=a.id,
        invoice_id=a.invoice_id,
        risk_level=a.risk_level,
        risk_score=a.risk_score,
        model_version=a.model_version,
        signals=a.signals,
        explanation=a.explanation,
        status=a.status,
        evc=a.evc,
        findings=[_finding_out(f) for f in a.findings] if hasattr(a, "findings") else [],
    )


@router.post("/invoices/{invoice_id}/assess", response_model=ds.FraudAssessmentOut)
def assess_invoice(
    invoice_id: uuid.UUID,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.FraudAssessmentOut:
    """EVC assessment (Evidence-based Vendor Consistency): an explainable
    0-100 consistency score over six features, each carrying an uncertainty
    state (verified_agreement / confirmed_discrepancy / insufficient_evidence).

    Persists the full structure in ``fraud_assessments.evc`` (features,
    weights, contributions, policy_version) + per-signal findings; review_required
    and high_risk_discrepancy force ``needs_review`` (machine-set, audited);
    critical assessments auto-open a case (R6). Never claims genuineness (R2).
    """
    assessment = fraud_service.assess_invoice(
        db,
        org_id=actor.organization_id,
        invoice_id=invoice_id,
        actor=actor,
        context=AuditContext.from_request(request),
    )
    findings = fraud_service.list_findings(db, assessment_id=assessment.id)
    out = _assessment_out(assessment)
    out.findings = [_finding_out(f) for f in findings]
    return out


@router.get("/invoices/{invoice_id}/assessment", response_model=ds.FraudAssessmentOut | None)
def latest_assessment(
    invoice_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> ds.FraudAssessmentOut | None:
    # Org-scope the INVOICE first: a foreign id must be a 404 (no existence
    # leak), while a known invoice without an assessment is a 200/None.
    from app.modules.procurement.service import get_invoice

    get_invoice(db, org_id=actor.organization_id, invoice_id=invoice_id)
    assessment = fraud_service.get_latest_assessment(
        db, org_id=actor.organization_id, invoice_id=invoice_id
    )
    if assessment is None:
        return None
    findings = fraud_service.list_findings(db, assessment_id=assessment.id)
    out = _assessment_out(assessment)
    out.findings = [_finding_out(f) for f in findings]
    return out


# --------------------------------------------------------------- findings ---
@router.post(
    "/findings/{finding_id}/disposition", response_model=ds.FraudFindingOut
)
def disposition_finding(
    finding_id: uuid.UUID,
    payload: ds.FindingDispositionIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> ds.FraudFindingOut:
    """Human disposition of one signal (reviewer/org_admin; audited).

    A non-empty reason is MANDATORY and the override is recorded as a
    review_actions row (on the given case, the invoice's latest case, or
    case-less). A disposition is an annotation — it never rewrites severity,
    the assessment, or the invoice status (the §8 forcing rules are not a
    disposition away), and the original automated assessment is preserved
    immutably.
    """
    finding = fraud_service.disposition_finding(
        db,
        org_id=actor.organization_id,
        finding_id=finding_id,
        actor=actor,
        disposition=payload.disposition,
        reason=payload.reason or payload.note or "",
        case_id=payload.case_id,
    )
    return _finding_out(finding)


# ---------------------------------------------------------------- matches ---
def _match_out(m) -> ds.EvidenceMatchOut:
    return ds.EvidenceMatchOut(
        id=m.id,
        source_entity_type=m.source_entity_type,
        source_entity_id=m.source_entity_id,
        target_entity_type=m.target_entity_type,
        target_entity_id=m.target_entity_id,
        match_kind=m.match_kind,
        similarity_score=m.similarity_score,
        matched_fields=m.matched_fields,
        status=m.status,
        reviewed_by=m.reviewed_by,
        reviewed_at=m.reviewed_at.isoformat() if m.reviewed_at else None,
    )


@router.get("/matches/{match_id}", response_model=ds.EvidenceMatchOut)
def get_match(
    match_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> ds.EvidenceMatchOut:
    return _match_out(
        fraud_service.get_match(db, org_id=actor.organization_id, match_id=match_id)
    )


@router.post("/matches/{match_id}/review", response_model=ds.EvidenceMatchOut)
def review_match(
    match_id: uuid.UUID,
    payload: ds.MatchReviewIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> ds.EvidenceMatchOut:
    """Human review decision on one evidence match (reviewer/org_admin;
    audited). This is the disposition path the duplicate_candidate finding
    points at via its ``evidence_refs``. A non-empty reason is MANDATORY and
    the decision is recorded as a review_actions row; the underlying
    detection evidence is never altered."""
    match = fraud_service.review_match(
        db,
        org_id=actor.organization_id,
        match_id=match_id,
        actor=actor,
        status=payload.status,
        reason=payload.reason or payload.note or "",
        case_id=payload.case_id,
    )
    return _match_out(match)


# -------------------------------------------------------------------- cases ---
@router.post("/cases", response_model=ds.CaseOut, status_code=201)
def open_case(
    payload: ds.CaseIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> ds.CaseOut:
    case = cases_service.open_case(
        db,
        org_id=actor.organization_id,
        actor=actor,
        title=payload.title,
        severity=payload.severity,
        invoice_id=payload.invoice_id,
        vendor_id=payload.vendor_id,
        description=payload.description,
    )
    return ds.CaseOut.model_validate(case)


@router.get("/cases", response_model=list[ds.CaseOut])
def list_cases(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
    limit: _PageLimit = 25,
    offset: _PageOffset = 0,
) -> list[ds.CaseOut]:
    rows, _t = cases_service.list_cases(
        db, org_id=actor.organization_id, limit=limit, offset=offset
    )
    return [ds.CaseOut.model_validate(c) for c in rows]


@router.get("/cases/{case_id}", response_model=ds.CaseOut)
def get_case(
    case_id: uuid.UUID, db: _Db, actor: Annotated[User, Depends(get_current_user)]
) -> ds.CaseOut:
    return ds.CaseOut.model_validate(
        cases_service.get_case(db, org_id=actor.organization_id, case_id=case_id)
    )


@router.post("/cases/{case_id}/assign", response_model=ds.CaseOut)
def assign_case(
    case_id: uuid.UUID,
    payload: ds.CaseAssignIn,
    db: _Db,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.CaseOut:
    assignee = db.get(User, payload.user_id)
    if assignee is None or assignee.organization_id != actor.organization_id:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.NOT_FOUND, "User not found in your organization.")
    case = cases_service.assign_case(
        db,
        org_id=actor.organization_id,
        case_id=case_id,
        actor=actor,
        assignee=assignee,
    )
    return ds.CaseOut.model_validate(case)


@router.post("/cases/{case_id}/close", response_model=ds.CaseOut)
def close_case(
    case_id: uuid.UUID,
    payload: ds.CaseCloseIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_verifier)],
) -> ds.CaseOut:
    """Human-only close (R6): outcome + resolution summary mandatory."""
    case = cases_service.close_case(
        db,
        org_id=actor.organization_id,
        case_id=case_id,
        actor=actor,
        outcome=payload.outcome,
        resolution_summary=payload.resolution_summary,
    )
    return ds.CaseOut.model_validate(case)


@router.post("/cases/{case_id}/actions", response_model=ds.ReviewActionOut, status_code=201)
def add_review_action(
    case_id: uuid.UUID,
    payload: ds.ReviewActionIn,
    db: _Db,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.ReviewActionOut:
    row = cases_service.add_review_action(
        db,
        org_id=actor.organization_id,
        case_id=case_id,
        actor=actor,
        action_type=payload.action_type,
        body=payload.body,
        payload=payload.payload,
    )
    return ds.ReviewActionOut.model_validate(row)


@router.get("/cases/{case_id}/actions", response_model=list[ds.ReviewActionOut])
def list_review_actions(
    case_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> list[ds.ReviewActionOut]:
    rows = cases_service.list_review_actions(
        db, org_id=actor.organization_id, case_id=case_id
    )
    return [ds.ReviewActionOut.model_validate(r) for r in rows]
