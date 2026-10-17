"""Explainable fraud assessment â€” EVC (Evidence-based Vendor Consistency) v1.

Business invariants enforced here (docs/ARCHITECTURE.md Â§8 â€” normative):

- R2: no genuineness verdict exists anywhere â€” signals + explanations +
  residual uncertainty only. The EVC score measures confirmed material
  inconsistency, never a fraud probability.
- R3: only manual values or extracted values with confidence â‰¥ threshold are
  usable; below-gate inputs emit ``unverified_input`` (low), never a claim,
  and critical OCR uncertainty raises the manual-verification flag.
- R4: absence (no PO, no accounts on file, no history) is
  ``insufficient_evidence`` with ``missing_evidence`` capped at ``medium`` â€”
  never high/critical, and it contributes zero to the score.
- R5: any remittance fingerprint that does not match an APPROVED account â†’
  ``bank_account_unverified`` with severity floor ``high`` and the
  unverified-destination override â†’ mandatory review. No code path here can
  approve an account.
- R6: critical assessments (â‰¥ 2 distinct high-severity discrepancies) open a
  case automatically (system actor); nothing but a human closes it.

Every assessment persists: the feature values with weights, contributions and
evidence refs (``fraud_assessments.evc`` + ``feature_snapshot``), the policy
version that produced it, and the ordered explanations. Assessments are
append-only â€” human dispositions are annotations on findings (with mandatory
reasons, recorded as review actions); the original assessment and evidence
are never rewritten.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    FindingDisposition,
    InvoiceStatus,
    MatchStatus,
)
from app.core.errors import AppError, ErrorCode
from app.models import (
    EvidenceMatch,
    FraudAssessment,
    FraudFinding,
    Invoice,
    User,
)
from app.modules.audit.service import AuditContext, record_audit
from app.modules.cases.service import open_case_for_critical_assessment
from app.modules.fraud.duplicates import DuplicateHit, find_duplicate_candidates
from app.modules.fraud.evidence import record_evidence_match
from app.modules.fraud.evc import MODEL_VERSION_PREFIX, Signal, build_explanation, compute_evc
from app.modules.fraud.policy import load_policy

# Informational default; the authoritative version stored on each assessment
# is "<prefix>-<policy_version>" from the loaded policy.
MODEL_VERSION = "evc-1.0"

def get_latest_assessment(db: Session, *, org_id: object, invoice_id: object) -> FraudAssessment | None:
    return db.scalar(
        select(FraudAssessment)
        .where(
            FraudAssessment.organization_id == org_id,
            FraudAssessment.invoice_id == invoice_id,
        )
        .order_by(FraudAssessment.created_at.desc())
    )


def list_findings(db: Session, *, assessment_id: object) -> list[FraudFinding]:
    return list(
        db.scalars(
            select(FraudFinding)
            .where(FraudFinding.assessment_id == assessment_id)
            .order_by(FraudFinding.created_at)
        )
    )


# ------------------------------------------------------ human dispositions ---
def get_finding(db: Session, *, org_id: object, finding_id: object) -> FraudFinding:
    finding = db.scalar(
        select(FraudFinding).where(
            FraudFinding.id == finding_id, FraudFinding.organization_id == org_id
        )
    )
    if finding is None:
        raise AppError(ErrorCode.NOT_FOUND, "Finding not found.")
    return finding


def _latest_case_id_for_invoice(db: Session, *, org_id: object, invoice_id: object) -> object | None:
    from app.models import InvestigationCase

    return db.scalar(
        select(InvestigationCase.id)
        .where(
            InvestigationCase.organization_id == org_id,
            InvestigationCase.invoice_id == invoice_id,
        )
        .order_by(InvestigationCase.created_at.desc())
    )


def disposition_finding(
    db: Session, *, org_id: object, finding_id: object, actor: User,
    disposition: str, reason: str, case_id: object | None = None,
) -> FraudFinding:
    """Human disposition of one signal â€” the override flow (reviewer/org_admin).

    A NON-EMPTY reason is mandatory; the override is recorded as a
    ``review_actions`` row (on the given case, the invoice's latest case, or
    with a NULL case when no case context exists yet) so the investigation
    record carries every human decision. The disposition never mutates
    severity, the assessment, or the invoice status â€” the original automated
    assessment + evidence are preserved immutably (the Â§8 severity floors and
    forcing rules are not dispositioned away).
    """
    if disposition not in {d.value for d in FindingDisposition}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Unknown finding disposition; expected open/acknowledged/dismissed.",
        )
    if not (reason or "").strip():
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "A disposition reason is mandatory â€” overrides without a recorded "
            "reason are not accepted.",
        )
    finding = get_finding(db, org_id=org_id, finding_id=finding_id)
    previous = finding.disposition
    finding.disposition = disposition
    finding.dispositioned_by = actor.id
    finding.dispositioned_at = datetime.now(timezone.utc)

    resolved_case_id = case_id
    if resolved_case_id is None:
        resolved_case_id = _latest_case_id_for_invoice(
            db, org_id=org_id, invoice_id=finding.invoice_id
        )
    from app.modules.cases.service import record_override_action

    record_override_action(
        db,
        org_id=org_id,
        actor=actor,
        case_id=resolved_case_id,
        body=reason.strip(),
        payload={
            "finding_id": str(finding.id),
            "assessment_id": str(finding.assessment_id),
            "signal_type": finding.signal_type,
            "from": previous,
            "to": disposition,
        },
    )
    db.commit()
    record_audit(
        db,
        action="finding.dispositioned",
        organization_id=org_id,
        actor_user_id=actor.id,
        entity_type="fraud_finding",
        entity_id=finding.id,
        detail={
            "signal_type": finding.signal_type,
            "assessment_id": str(finding.assessment_id),
            "from": previous,
            "to": disposition,
            "reason": reason.strip(),
            "case_id": str(resolved_case_id) if resolved_case_id else None,
        },
    )
    return finding


def get_match(db: Session, *, org_id: object, match_id: object) -> EvidenceMatch:
    match = db.scalar(
        select(EvidenceMatch).where(
            EvidenceMatch.id == match_id, EvidenceMatch.organization_id == org_id
        )
    )
    if match is None:
        raise AppError(ErrorCode.NOT_FOUND, "Evidence match not found.")
    return match


def _match_invoice_id(match: EvidenceMatch) -> object | None:
    if match.source_entity_type == "invoice":
        return match.source_entity_id
    if match.target_entity_type == "invoice":
        return match.target_entity_id
    return None


def review_match(
    db: Session, *, org_id: object, match_id: object, actor: User,
    status: str, reason: str, case_id: object | None = None,
) -> EvidenceMatch:
    """Human review decision on one evidence match (e.g. a duplicate).

    ``status`` is a decision â€” dismissed or confirmed; ``open`` is not a
    decision and cannot be written. A NON-EMPTY reason is mandatory and the
    decision is recorded as a ``review_actions`` row. The match's underlying
    detection evidence is never altered.
    """
    if status not in {MatchStatus.DISMISSED.value, MatchStatus.CONFIRMED.value}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Unknown match status; expected dismissed/confirmed.",
        )
    if not (reason or "").strip():
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "A review reason is mandatory â€” match decisions without a "
            "recorded reason are not accepted.",
        )
    match = get_match(db, org_id=org_id, match_id=match_id)
    previous = match.status
    match.status = status
    match.reviewed_by = actor.id
    match.reviewed_at = datetime.now(timezone.utc)

    invoice_id = _match_invoice_id(match)
    resolved_case_id = case_id
    if resolved_case_id is None and invoice_id is not None:
        resolved_case_id = _latest_case_id_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    from app.modules.cases.service import record_override_action

    record_override_action(
        db,
        org_id=org_id,
        actor=actor,
        case_id=resolved_case_id,
        body=reason.strip(),
        payload={
            "match_id": str(match.id),
            "match_kind": match.match_kind,
            "from": previous,
            "to": status,
        },
    )
    db.commit()
    record_audit(
        db,
        action="match.reviewed",
        organization_id=org_id,
        actor_user_id=actor.id,
        entity_type="evidence_match",
        entity_id=match.id,
        detail={
            "match_kind": match.match_kind,
            "from": previous,
            "to": status,
            "reason": reason.strip(),
            "case_id": str(resolved_case_id) if resolved_case_id else None,
        },
    )
    return match


def assess_invoice(
    db: Session, *, org_id: object, invoice_id: object, actor: User | None,
    context: AuditContext | None = None,
) -> FraudAssessment:
    """Compute the EVC assessment and persist it (append-only)."""
    from app.modules.procurement.service import get_invoice

    policy = load_policy()
    invoice = get_invoice(db, org_id=org_id, invoice_id=invoice_id)

    # Duplicate detection first: its hits feed both the evidence_matches
    # rows and the duplicate_indicators feature.
    hits: list[DuplicateHit] = find_duplicate_candidates(db, invoice=invoice)
    for hit in hits:
        record_evidence_match(
            db,
            org_id=invoice.organization_id,
            source_type="invoice",
            source_id=invoice.id,
            target_type="invoice",
            target_id=hit.target.id,
            match_kind=hit.kind,
            similarity=hit.similarity,
            matched_fields=hit.matched_fields,
            module="fraud",
        )

    result = compute_evc(db, invoice=invoice, duplicate_hits=hits, policy=policy)
    signals = result.signals

    # Bank-account collisions (printed details match a NON-approved on-file
    # account) are recorded as evidence matches so the human sees exactly
    # WHICH account collides â€” provenance for the R5 finding, never a guess.
    bank_feature = next(
        (f for f in result.features if f.key == "bank_account_consistency"), None
    )
    if bank_feature is not None:
        for collision in bank_feature.observations.get("non_approved_collisions", []):
            record_evidence_match(
                db,
                org_id=invoice.organization_id,
                source_type="invoice",
                source_id=invoice.id,
                target_type="vendor_bank_account",
                # Observations are JSON (string ids) â€” coerce back for the
                # Uuid(as_uuid=True) column binding.
                target_id=UUID(str(collision["account_id"])),
                match_kind="bank_account",
                similarity=1.0,
                matched_fields={
                    "axis": "remittance fingerprint",
                    "account_status": collision["status"],
                    "vendor_id": collision["vendor_id"],
                },
                module="fraud",
            )

    assessment = FraudAssessment(
        organization_id=org_id,
        invoice_id=invoice.id,
        risk_level=result.risk_level,
        risk_score=result.score,
        model_version=f"{MODEL_VERSION_PREFIX}-{result.policy_version}",
        feature_snapshot=_feature_snapshot(invoice, result),
        signals=[s.to_dict() for s in signals],
        explanation=build_explanation(result),
        # Phase-4 moment: the reserved column now carries the full EVC
        # structure (features, weights, contributions, policy_version).
        evc=result.payload(),
        status="complete",
        triggered_by_user_id=actor.id if actor else None,
    )
    db.add(assessment)
    db.flush()

    for s in signals:
        db.add(
            FraudFinding(
                organization_id=org_id,
                assessment_id=assessment.id,
                invoice_id=invoice.id,
                signal_type=s.signal_type.value,
                severity=s.severity,
                message=s.message,
                field_refs=list(s.field_refs),
                evidence_refs=list(s.evidence_refs),
                disposition=FindingDisposition.OPEN.value,
            )
        )

    # Forcing rules (Â§8 via the result states): review_required and
    # high_risk_discrepancy set needs_review (machine-set, audited); the
    # closed status is never overwritten by a machine.
    if result.force_review and invoice.status in (
        InvoiceStatus.RECEIVED.value, InvoiceStatus.PROCESSING.value,
    ):
        invoice.status = InvoiceStatus.NEEDS_REVIEW.value

    db.commit()

    # R6 hook: critical assessments open a case (system actor); idempotent.
    open_case_for_critical_assessment(db, assessment=assessment, context=context)

    record_audit(
        db,
        action="assessment.created",
        organization_id=org_id,
        actor_user_id=actor.id if actor else None,
        actor_type="system" if actor is None else "user",
        entity_type="fraud_assessment",
        entity_id=assessment.id,
        detail={
            "invoice_id": str(invoice.id),
            "risk_level": assessment.risk_level,
            "model_version": assessment.model_version,
            "policy_version": result.policy_version,
            "result_state": result.result_state,
            "score": result.score,
            "signals": [s.signal_type.value for s in signals],
        },
        context=context,
    )
    return assessment


def _feature_snapshot(invoice: Invoice, result) -> dict:
    """The input values + per-feature raw observations at assessment time
    (the feature half of the provenance contract; ``evc`` carries weights and
    contributions)."""
    return {
        "invoice_id": str(invoice.id),
        "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
        "purchase_order_id": (
            str(invoice.purchase_order_id) if invoice.purchase_order_id else None
        ),
        "total_amount": (
            str(invoice.total_amount) if invoice.total_amount is not None else None
        ),
        "currency": invoice.currency,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "remittance_fingerprint_present": invoice.remittance_account_fingerprint is not None,
        "source_document_id": (
            str(invoice.source_document_id) if invoice.source_document_id else None
        ),
        "policy_version": result.policy_version,
        "weights": dict(result.weights),
        "features": {
            f.key: {"state": f.state, "observations": f.observations}
            for f in result.features
        },
    }
