"""Explainable fraud assessment (deterministic rules v0.1; EVC = Phase 4).

Business invariants enforced here (docs/ARCHITECTURE.md §8 — normative):

- R3: only manual values or extracted values with confidence ≥ threshold are
  usable; below-gate inputs emit ``unverified_input`` (low), never a claim.
- R4: absence (no PO, no accounts on file) is ``missing_evidence`` capped at
  ``medium`` — never high/critical.
- R5: any remittance fingerprint that does not match an APPROVED account →
  ``bank_account_unverified`` with severity floor ``high``; forces
  ``needs_review``. No code path here can approve an account.
- R2: no genuineness verdict exists anywhere — signals + explanations only.
  Rule v0.1 never emits ``critical``; the R6 auto-case hook is wired for the
  day a future model does.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    FindingDisposition,
    InvoiceStatus,
    RiskLevel,
    SignalType,
)
from app.models import (
    FraudAssessment,
    FraudFinding,
    Invoice,
    PurchaseOrder,
    User,
    Vendor,
    VendorBankAccount,
)
from app.modules.audit.service import AuditContext, record_audit
from app.modules.cases.service import open_case_for_critical_assessment
from app.modules.fraud.evidence import record_duplicate_number_match
from app.modules.vendors.service import find_approved_account_by_fingerprint

MODEL_VERSION = "rules-v0.1"

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class _Signal:
    signal_type: SignalType
    severity: str
    message: str
    field_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


def _default_severity(signal: SignalType) -> str:
    return {
        SignalType.MISSING_EVIDENCE: "medium",
        SignalType.UNVERIFIED_INPUT: "low",
        SignalType.FIELD_PROVENANCE_CONFLICT: "medium",
        SignalType.DUPLICATE_CANDIDATE: "medium",
        SignalType.AMOUNT_MISMATCH: "high",
        SignalType.BANK_ACCOUNT_UNVERIFIED: "high",
    }[signal]


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


def assess_invoice(
    db: Session, *, org_id: object, invoice_id: object, actor: User | None,
    context: AuditContext | None = None,
) -> FraudAssessment:
    """Compute the deterministic assessment and persist it (append-only)."""
    from app.modules.procurement.service import get_invoice

    invoice = get_invoice(db, org_id=org_id, invoice_id=invoice_id)
    signals = _compute_signals(db, invoice)
    risk_level = _level_from(signals)
    risk_score = _score_from(signals)

    assessment = FraudAssessment(
        organization_id=org_id,
        invoice_id=invoice.id,
        risk_level=risk_level,
        risk_score=risk_score,
        model_version=MODEL_VERSION,
        feature_snapshot=_feature_snapshot(invoice),
        signals=[
            {
                "type": s.signal_type.value,
                "severity": s.severity,
                "message": s.message,
                "field_refs": list(s.field_refs),
                "evidence_refs": list(s.evidence_refs),
            }
            for s in signals
        ],
        explanation=_explain(invoice, signals),
        evc=None,  # Phase 4 placeholder — stays NULL (docs/ARCHITECTURE §8.6)
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

    # Forcing rules (§8): high ⇒ needs_review (machine-set, audited).
    if any(s.severity in ("high", "critical") for s in signals):
        if invoice.status in (InvoiceStatus.RECEIVED.value, InvoiceStatus.PROCESSING.value):
            invoice.status = InvoiceStatus.NEEDS_REVIEW.value

    db.commit()

    # R6 hook: when a future model emits critical, a case opens (system actor).
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
            "model_version": MODEL_VERSION,
            "signals": [s.signal_type.value for s in signals],
        },
        context=context,
    )
    return assessment


def _compute_signals(db: Session, invoice: Invoice) -> list[_Signal]:
    signals: list[_Signal] = []
    threshold = get_settings().ocr_confidence_threshold

    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None

    # --- R4: missing PO is a neutral gap -----------------------------------
    if invoice.purchase_order_id is None:
        signals.append(
            _Signal(
                SignalType.MISSING_EVIDENCE,
                "medium",
                "No purchase order is linked to this invoice; the record may "
                "simply not exist in VeriPay.",
                field_refs=("purchase_order_id",),
            )
        )
    else:
        po = db.get(PurchaseOrder, invoice.purchase_order_id)
        # --- amount mismatch (high) ----------------------------------------
        if (
            po is not None
            and invoice.total_amount is not None
            and po.amount is not None
            and po.currency == (invoice.currency or po.currency)
            and Decimal(str(invoice.total_amount)) != Decimal(str(po.amount))
        ):
            signals.append(
                _Signal(
                    SignalType.AMOUNT_MISMATCH,
                    "high",
                    f"Invoice total {invoice.total_amount} differs from the "
                    f"purchase-order amount {po.amount}.",
                    field_refs=("total_amount",),
                )
            )

    # --- R5: pay-to destination vs approved accounts -----------------------
    has_accounts = vendor is not None and db.scalar(
        select(VendorBankAccount.id).where(
            VendorBankAccount.organization_id == invoice.organization_id,
            VendorBankAccount.vendor_id == vendor.id,
        )
    ) is not None

    if invoice.remittance_account_fingerprint:
        approved = find_approved_account_by_fingerprint(
            db,
            org_id=invoice.organization_id,
            fingerprint=invoice.remittance_account_fingerprint,
        )
        if approved is None:
            detail = (
                "no bank accounts are on file for this vendor"
                if not has_accounts
                else "no APPROVED bank account matches the printed pay-to details"
            )
            signals.append(
                _Signal(
                    SignalType.BANK_ACCOUNT_UNVERIFIED,
                    "high",  # floor — may not be downgraded
                    f"The remittance account is unverified: {detail}. New bank "
                    "accounts require independent human verification.",
                    field_refs=("remittance_account_raw",),
                )
            )
    else:
        signals.append(
            _Signal(
                SignalType.MISSING_EVIDENCE,
                "medium",
                "The invoice carries no printed pay-to bank details; the "
                "record may simply not exist in VeriPay.",
                field_refs=("remittance_account_raw",),
            )
        )

    # --- R3: provenance gate ------------------------------------------------
    sources = invoice.field_sources or {}
    unverified_fields: list[str] = []
    conflicts: list[str] = []
    for column, meta in sources.items():
        origin = meta.get("origin")
        if origin == "manual":
            continue
        confidence = meta.get("confidence")
        if origin == "extracted" and (confidence is None or confidence < threshold):
            unverified_fields.append(column)
        if origin == "extracted" and meta.get("extracted_value") is not None:
            current = getattr(invoice, column, None)
            if current is not None and str(current) != str(meta["extracted_value"]):
                conflicts.append(column)
    if unverified_fields:
        signals.append(
            _Signal(
                SignalType.UNVERIFIED_INPUT,
                "low",
                "Machine-extracted values below the confidence gate were "
                "excluded from strong evidence: " + ", ".join(unverified_fields),
                field_refs=tuple(unverified_fields),
            )
        )
    for column in conflicts:
        signals.append(
            _Signal(
                SignalType.FIELD_PROVENANCE_CONFLICT,
                "medium",
                f"The invoice column '{column}' disagrees with its extracted "
                "provenance value; the column value is authoritative.",
                field_refs=(column,),
            )
        )

    # --- duplicates ---------------------------------------------------------
    if vendor is not None:
        others = db.scalars(
            select(Invoice).where(
                Invoice.organization_id == invoice.organization_id,
                Invoice.vendor_id == vendor.id,
                Invoice.invoice_number == invoice.invoice_number,
                Invoice.id != invoice.id,
            )
        ).all()
        for other in others:
            record_duplicate_number_match(db, source=invoice, target=other, module="fraud")
            signals.append(
                _Signal(
                    SignalType.DUPLICATE_CANDIDATE,
                    "medium",
                    "Another invoice with the same vendor and number already "
                    "exists — possible duplicate or re-billing with altered "
                    "amounts; a human must disposition it.",
                    evidence_refs=(str(other.id),),
                )
            )

    return signals


def _level_from(signals: list[_Signal]) -> str:
    worst = max(
        (_SEVERITY_ORDER.get(s.severity, 0) for s in signals), default=0
    )
    # rules-v0.1 never emits critical (docs/ARCHITECTURE §8.6 note).
    return {0: RiskLevel.NONE.value, 1: RiskLevel.LOW.value, 2: RiskLevel.MEDIUM.value, 3: RiskLevel.HIGH.value}[worst]


def _score_from(signals: list[_Signal]) -> float:
    weights = {"low": 15.0, "medium": 35.0, "high": 70.0}
    return float(min(100.0, sum(weights.get(s.severity, 0.0) for s in signals)))


def _feature_snapshot(invoice: Invoice) -> dict:
    return {
        "invoice_id": str(invoice.id),
        "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
        "purchase_order_id": (
            str(invoice.purchase_order_id) if invoice.purchase_order_id else None
        ),
        "total_amount": str(invoice.total_amount) if invoice.total_amount is not None else None,
        "currency": invoice.currency,
        "remittance_fingerprint_present": invoice.remittance_account_fingerprint is not None,
        "model_version": MODEL_VERSION,
    }


def _explain(invoice: Invoice, signals: list[_Signal]) -> list[str]:
    """Ordered human-readable reasons — the explainable deliverable."""
    if not signals:
        return [
            "No fraud signals were produced by the current rule set. This is "
            "NOT a statement that the invoice is genuine."
        ]
    ordered = sorted(
        signals, key=lambda s: -_SEVERITY_ORDER.get(s.severity, 0)
    )
    lines = [
        f"[{s.severity}] {s.signal_type.value}: {s.message}" for s in ordered
    ]
    lines.append(
        "VeriPay provides risk signals only; it never authorizes payments "
        "and never certifies an invoice as genuine."
    )
    return lines
