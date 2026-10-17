"""Dashboard aggregates for one organization (docs/IMPLEMENTATION_PLAN.md,
Phase 6 "dashboards": assessments by risk, open cases, processing failures).

Read-only, org-scoped; every query filters on ``organization_id`` (API.md §5).
Counts are decision-support numbers only — they never imply genuineness (R2).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import CaseStatus, InvoiceStatus, ProcessingStatus
from app.models import FraudAssessment, InvestigationCase, Invoice, ProcessingJob

# Risk levels the dashboard counts as "high risk". rules-v0.1 never emits
# critical; including it keeps the aggregate correct the day a future model
# does (R6 criticals are the strongest review obligation).
_HIGH_RISK_LEVELS = ("high", "critical")


def dashboard_counts(db: Session, *, org_id: object) -> dict:
    """Return the org's headline counts for the Overview cards.

    ``high_risk_invoices`` counts DISTINCT invoices whose LATEST assessment
    is high/critical (append-only assessment history — an old ``high`` that a
    newer ``none`` assessment superseded must not keep the invoice red).
    """
    invoices = db.scalars(
        select(Invoice).where(Invoice.organization_id == org_id)
    ).all()
    cases = db.scalars(
        select(InvestigationCase).where(InvestigationCase.organization_id == org_id)
    ).all()
    assessments = db.scalars(
        select(FraudAssessment).where(FraudAssessment.organization_id == org_id)
    ).all()

    latest_by_invoice: dict[object, FraudAssessment] = {}
    for assessment in assessments:
        current = latest_by_invoice.get(assessment.invoice_id)
        if current is None or (
            assessment.created_at is not None
            and current.created_at is not None
            and assessment.created_at > current.created_at
        ):
            latest_by_invoice[assessment.invoice_id] = assessment
    high_risk = sum(
        1 for a in latest_by_invoice.values() if a.risk_level in _HIGH_RISK_LEVELS
    )

    processing_failures = (
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.organization_id == org_id,
                ProcessingJob.status == ProcessingStatus.FAILED.value,
            )
        )
        or 0
    )

    return {
        "organization_id": org_id,
        "total_invoices": len(invoices),
        "needs_review_invoices": sum(
            1
            for i in invoices
            if i.status == InvoiceStatus.NEEDS_REVIEW.value
        ),
        "open_cases": sum(
            1 for c in cases if c.status != CaseStatus.CLOSED.value
        ),
        "high_risk_invoices": high_risk,
        "processing_failures": int(processing_failures),
    }
