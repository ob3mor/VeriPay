"""Investigation cases: human review workflow (R6).

- ONLY the fraud module auto-opens cases, and only for ``critical``
  assessments (system actor). Rule model v0.1 never emits critical, so the
  hook is dormant but wired (docs/ARCHITECTURE §8.6).
- Humans may open cases manually (reviewer/org_admin).
- Closing requires outcome + resolution_summary — enforced in the service
  AND by the ck_icase_close CHECK constraint. Nothing auto-closes.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    CaseOutcome,
    CaseSeverity,
    CaseStatus,
    ReviewActionType,
)
from app.core.errors import AppError, ErrorCode
from app.models import (
    FraudAssessment,
    InvestigationCase,
    ReviewAction,
    User,
)
from app.modules.audit.service import AuditContext, record_audit


def get_case(db: Session, *, org_id: object, case_id: object) -> InvestigationCase:
    case = db.scalar(
        select(InvestigationCase).where(
            InvestigationCase.id == case_id,
            InvestigationCase.organization_id == org_id,
        )
    )
    if case is None:
        raise AppError(ErrorCode.NOT_FOUND, "Case not found.")
    return case


def _next_case_number(db: Session, org_id: object) -> str:
    """Human-friendly per-org sequence. The uq_icase_org_number constraint is
    the race arbiter: concurrent inserts retry on the uniqueness violation."""
    year = datetime.now(timezone.utc).year
    prefix = f"CASE-{year}-"
    last = db.scalar(
        select(InvestigationCase.case_number)
        .where(
            InvestigationCase.organization_id == org_id,
            InvestigationCase.case_number.like(f"{prefix}%"),
        )
        .order_by(InvestigationCase.case_number.desc())
        .limit(1)
    )
    seq = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def open_case(
    db: Session, *, org_id: object, actor: User | None, title: str,
    severity: str, invoice_id: object | None = None,
    vendor_id: object | None = None, description: str | None = None,
    triggering_assessment_id: object | None = None,
    sla_days: int = 5,
) -> InvestigationCase:
    if invoice_id is None and vendor_id is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "A case must reference an invoice or a vendor.",
        )
    for attempt in range(5):
        case = InvestigationCase(
            organization_id=org_id,
            case_number=_next_case_number(db, org_id),
            invoice_id=invoice_id,
            vendor_id=vendor_id,
            triggering_assessment_id=triggering_assessment_id,
            title=title.strip(),
            description=description,
            severity=severity,
            status=CaseStatus.OPEN.value,
            opened_by=actor.id if actor else None,
            sla_due_at=datetime.now(timezone.utc) + timedelta(days=sla_days),
        )
        db.add(case)
        try:
            db.commit()
        except IntegrityError:  # concurrent case-number race — retry
            db.rollback()
            continue
        record_audit(
            db,
            action="case.opened",
            organization_id=org_id,
            actor_user_id=actor.id if actor else None,
            actor_type="user" if actor else "system",
            entity_type="investigation_case",
            entity_id=case.id,
            detail={"case_number": case.case_number, "severity": severity,
                    "title": case.title},
        )
        db.add(
            ReviewAction(
                organization_id=org_id,
                case_id=case.id,
                actor_user_id=actor.id if actor else None,
                action_type=ReviewActionType.STATUS_CHANGE.value,
                body="Case opened." if actor else
                "Case auto-opened by a critical fraud assessment (system).",
                payload={"status": CaseStatus.OPEN.value},
            )
        )
        db.commit()
        return case
    raise AppError(
        ErrorCode.CONFLICT, "Could not allocate a case number; please retry."
    )


def open_case_for_critical_assessment(
    db: Session, *, assessment: FraudAssessment, context: AuditContext | None = None
) -> InvestigationCase | None:
    """R6 hook — called by the assessment service after commit. Idempotent:
    an assessment triggers at most one case (checked on read)."""
    if assessment.risk_level != "critical":
        return None
    existing = db.scalar(
        select(InvestigationCase).where(
            InvestigationCase.triggering_assessment_id == assessment.id
        )
    )
    if existing is not None:
        return existing
    return open_case(
        db,
        org_id=assessment.organization_id,
        actor=None,
        title="Critical fraud assessment requires human investigation",
        severity=CaseSeverity.CRITICAL.value,
        invoice_id=assessment.invoice_id,
        triggering_assessment_id=assessment.id,
        description="Auto-opened by the fraud module (R6).",
    )


def list_cases(
    db: Session, *, org_id: object, limit: int, offset: int
) -> tuple[list[InvestigationCase], int]:
    base = select(InvestigationCase).where(
        InvestigationCase.organization_id == org_id
    )
    total = len(db.scalars(base).all())
    # offset/limit belong on the SELECT — chaining them on ScalarResult raises
    # (this 500'd the case list whenever any case existed).
    rows = db.scalars(
        base.order_by(InvestigationCase.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), total


def assign_case(
    db: Session, *, org_id: object, case_id: object, actor: User, assignee: User
) -> InvestigationCase:
    case = get_case(db, org_id=org_id, case_id=case_id)
    if case.status == CaseStatus.CLOSED.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION, "A closed case cannot be reassigned."
        )
    case.assigned_to = assignee.id
    db.add(
        ReviewAction(
            organization_id=org_id,
            case_id=case.id,
            actor_user_id=actor.id,
            action_type=ReviewActionType.ASSIGNMENT.value,
            body=f"Assigned to {assignee.full_name} ({assignee.email}).",
            payload={"assignee_id": str(assignee.id)},
        )
    )
    db.commit()
    return case


def close_case(
    db: Session, *, org_id: object, case_id: object, actor: User,
    outcome: str, resolution_summary: str,
) -> InvestigationCase:
    """Human-only close (R6): outcome + summary mandatory; nothing auto-closes."""
    if outcome not in {o.value for o in CaseOutcome}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown case outcome.")
    case = get_case(db, org_id=org_id, case_id=case_id)
    if case.status == CaseStatus.CLOSED.value:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "The case is already closed.")
    case.status = CaseStatus.CLOSED.value
    case.outcome = outcome
    case.resolution_summary = resolution_summary
    case.closed_at = datetime.now(timezone.utc)
    db.add(
        ReviewAction(
            organization_id=org_id,
            case_id=case.id,
            actor_user_id=actor.id,
            action_type=ReviewActionType.DECISION.value,
            body=f"Case closed with outcome '{outcome}'.",
            payload={"outcome": outcome},
        )
    )
    record_audit(
        db,
        action="case.closed",
        organization_id=org_id,
        actor_user_id=actor.id,
        entity_type="investigation_case",
        entity_id=case.id,
        detail={"case_number": case.case_number, "outcome": outcome},
    )
    db.commit()
    return case


def add_review_action(
    db: Session, *, org_id: object, case_id: object, actor: User | None,
    action_type: str, body: str, payload: dict | None = None,
) -> ReviewAction:
    case = get_case(db, org_id=org_id, case_id=case_id)
    if action_type not in {t.value for t in ReviewActionType}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown review action type.")
    row = ReviewAction(
        organization_id=org_id,
        case_id=case.id,
        actor_user_id=actor.id if actor else None,
        action_type=action_type,
        body=body,
        payload=payload,
    )
    db.add(row)
    db.commit()
    return row


def record_override_action(
    db: Session, *, org_id: object, actor: User | None, body: str,
    payload: dict | None = None, case_id: object | None = None,
    action_type: str = ReviewActionType.DECISION.value,
) -> ReviewAction:
    """One human override record (finding disposition / match review).

    ``case_id`` optional: given, it is org-scoped and validated; absent (no
    case context exists), the action is still written with a NULL case and
    its payload names the exact entity overridden. Used by the fraud
    module's disposition flow (EVC v1 mandatory-reason overrides)."""
    if action_type not in {t.value for t in ReviewActionType}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown review action type.")
    if case_id is not None:
        get_case(db, org_id=org_id, case_id=case_id)  # org-scoped 404 guard
    row = ReviewAction(
        organization_id=org_id,
        case_id=case_id,
        actor_user_id=actor.id if actor else None,
        action_type=action_type,
        body=body,
        payload=payload,
    )
    db.add(row)
    db.flush()
    return row


def list_review_actions(
    db: Session, *, org_id: object, case_id: object, limit: int, offset: int
) -> tuple[list[ReviewAction], int]:
    base = select(ReviewAction).where(
        ReviewAction.organization_id == org_id,
        ReviewAction.case_id == case_id,
    )
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(ReviewAction.created_at).offset(offset).limit(limit)
    ).all()
    return list(rows), total
