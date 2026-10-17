"""EVC — Evidence-based Vendor Consistency (v1.0).

An explainable 0-100 consistency score composed of six features:

    bank_account_consistency, identity_consistency, duplicate_indicators,
    po_mismatch, historical_anomalies, untrusted_source_indicators

Design contract (docs/ARCHITECTURE.md §8, normative; Prompt-04):

- **Uncertainty states per feature:** every feature ends in exactly one of
  ``verified_agreement`` / ``confirmed_discrepancy`` / ``insufficient_evidence``.
  Only ``confirmed_discrepancy`` contributes to the score
  (weight × severity factor). ``insufficient_evidence`` contributes ZERO and
  is reported as uncertainty — unknown is never scored as safe or fraudulent.
- **The score is never a fraud probability** (R2): it measures how much
  *confirmed material inconsistency* exists against trusted evidence. No
  feature, override or explanation ever claims genuineness.
- **Machine-enforced overrides (may not be downgraded):**
    * unverified payment destination → mandatory review
      (needs_review + bank_account_unverified floor high, §8.5);
    * critical OCR uncertainty → manual-verification flag (R3);
    * unknown vendor → review required (unresolved vendors are never guessed);
    * missing trusted records → insufficient_evidence states (R4 — the
      missing_evidence severity stays capped at medium);
    * document-appearance similarity NEVER yields authenticity — near-
      duplicate overlap is a duplicate indicator only.
- **Result states:** no_material_discrepancies / review_required /
  high_risk_discrepancy map onto risk_level and force invoices.status.

Every number in the persisted ``evc`` payload traces to a feature value, a
policy weight and evidence refs — explainability over cleverness.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    BankAccountStatus,
    ExtractionFieldVerificationStatus,
    ProcessingStatus,
    RiskLevel,
    SignalType,
)
from app.models import (
    Document,
    ExtractionField,
    ExtractionResult,
    Invoice,
    InvoiceLineItem,
    PurchaseOrder,
    Vendor,
    VendorBankAccount,
)
from app.modules.fraud.duplicates import (
    CORRECTED_VERSION_CANDIDATE,
    DuplicateHit,
    DUPLICATE_UPLOAD,
    FIELD_OVERLAP,
    NEAR_DUPLICATE,
)
from app.modules.fraud.policy import (
    RESULT_ORDER,
    RESULT_STATES,
    SEVERITY_ORDER,
    Policy,
    load_policy,
)
from app.modules.retrieval.normalize import names_equivalent, normalize_identifier
from app.modules.vendors.service import find_approved_account_by_fingerprint

MODEL_VERSION_PREFIX = "evc"

# Columns whose value drives the payment decision; an uncertain OCR read of
# any of them is critical OCR uncertainty (manual verification flag).
CRITICAL_PAYMENT_COLUMNS = ("invoice_number", "total_amount", "remittance_account_raw")

# Signal → override name (machine-enforced; the policy file must mirror it,
# policy.py refuses policies that diverge).
_OVERRIDES = {
    SignalType.BANK_ACCOUNT_UNVERIFIED.value: "unverified_payment_destination",
    SignalType.UNKNOWN_VENDOR.value: "unknown_vendor",
    SignalType.OCR_UNCERTAIN.value: "ocr_uncertain",
}


@dataclass(frozen=True)
class Signal:
    """One explainable finding of one assessment (the §8 vocabulary)."""

    signal_type: SignalType
    severity: str
    message: str
    field_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "type": self.signal_type.value,
            "severity": self.severity,
            "message": self.message,
            "field_refs": list(self.field_refs),
            "evidence_refs": list(self.evidence_refs),
        }


def _clamp_severity(signal: SignalType, severity: str, policy: Policy) -> str:
    """Apply the invariant floor/cap for the signal type (machine-enforced)."""
    floor = policy.floor_for(signal.value)
    cap = policy.cap_for(signal.value)
    level = SEVERITY_ORDER.get(severity, 0)
    if floor is not None and level < SEVERITY_ORDER[floor]:
        level = SEVERITY_ORDER[floor]
    if cap is not None and level > SEVERITY_ORDER[cap]:
        level = SEVERITY_ORDER[cap]
    return {v: k for k, v in SEVERITY_ORDER.items()}[level]


def _signal(
    signal_type: SignalType, severity: str, message: str, policy: Policy,
    field_refs: tuple[str, ...] = (), evidence_refs: tuple[str, ...] = (),
) -> Signal:
    return Signal(
        signal_type=signal_type,
        severity=_clamp_severity(signal_type, severity, policy),
        message=message,
        field_refs=field_refs,
        evidence_refs=evidence_refs,
    )


# --------------------------------------------------------------------------
@dataclass
class FeatureOutcome:
    """One feature's uncertainty state with its full scoring provenance."""

    key: str
    state: str  # verified_agreement | confirmed_discrepancy | insufficient_evidence
    explanation: str
    signals: list[Signal] = field(default_factory=list)
    observations: dict = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    @property
    def severity(self) -> str | None:
        if not self.signals:
            return None
        return max((s.severity for s in self.signals), key=lambda x: SEVERITY_ORDER.get(x, 0))

    @property
    def signal_types(self) -> list[str]:
        return sorted({s.signal_type.value for s in self.signals})


@dataclass
class EvcResult:
    """The complete, persistable assessment computation."""

    policy_version: str
    score: float
    result_state: str
    risk_level: str
    features: list[FeatureOutcome]
    overrides: list[dict]
    manual_verification_required: bool
    insufficient_features: list[str]
    weights: dict[str, float]

    @property
    def signals(self) -> list[Signal]:
        out: list[Signal] = []
        for feature in self.features:
            out.extend(feature.signals)
        return out

    @property
    def force_review(self) -> bool:
        return self.result_state != RESULT_STATES[0]

    def payload(self) -> dict:
        """The structure stored in fraud_assessments.evc (features, weights,
        contributions, policy_version — the Phase-4 moment of that column)."""
        features_payload: dict[str, dict] = {}
        for feature in self.features:
            weight = self.weights[feature.key]
            severity = feature.severity
            if feature.state == "confirmed_discrepancy" and severity:
                factor_policy = load_policy().severity_factor(severity)
                contribution = round(weight * factor_policy, 2)
            else:
                contribution = 0.0
            features_payload[feature.key] = {
                "state": feature.state,
                "weight": weight,
                "contribution": contribution,
                "severity": severity,
                "signals": feature.signal_types,
                "evidence_refs": list(feature.evidence_refs),
                "observations": feature.observations,
                "explanation": feature.explanation,
            }
        return {
            "policy_version": self.policy_version,
            "score": self.score,
            "score_max": 100.0,
            "result_state": self.result_state,
            "risk_level": self.risk_level,
            "weights": dict(self.weights),
            "thresholds": {
                "review_required": load_policy().review_threshold,
                "high_risk": load_policy().high_threshold,
            },
            "manual_verification_required": self.manual_verification_required,
            "overrides": list(self.overrides),
            "features": features_payload,
            "uncertainty": {
                "features_insufficient": list(self.insufficient_features),
                "note": (
                    "Features in insufficient_evidence contribute zero to the "
                    "score: unknown is scored neither safe nor fraudulent."
                ),
            },
        }


# --------------------------------------------------------------------------
# Document / extraction context
# --------------------------------------------------------------------------
@dataclass
class _DocContext:
    """Gate-aware view of the invoice's bound document (R3)."""

    document: Document | None
    extraction: ExtractionResult | None
    # field_name → (value, gate_passed) for the named extraction fields.
    gate_fields: dict[str, tuple[str | None, bool]] = field(default_factory=dict)
    ocr_failed: bool = False
    ocr_incomplete: bool = False


def _load_doc_context(db: Session, invoice: Invoice) -> _DocContext:
    ctx = _DocContext(document=None, extraction=None)
    if invoice.source_document_id is None:
        return ctx
    ctx.document = db.get(Document, invoice.source_document_id)
    if ctx.document is None:
        return ctx
    if ctx.document.processing_status == ProcessingStatus.FAILED.value:
        ctx.ocr_failed = True
    from app.modules.extraction import service as extraction_service

    ctx.extraction = extraction_service.get_result(
        db, org_id=invoice.organization_id, document_id=invoice.source_document_id
    )
    if (
        not ctx.ocr_failed
        and ctx.extraction is not None
        and ctx.extraction.status in (ProcessingStatus.FAILED.value,)
    ):
        ctx.ocr_failed = True
    if (
        not ctx.ocr_failed
        and (ctx.extraction is None
             or ctx.extraction.status
             in (ProcessingStatus.PENDING.value, ProcessingStatus.PROCESSING.value))
    ):
        ctx.ocr_incomplete = True

    if ctx.extraction is not None:
        threshold = get_settings().ocr_confidence_threshold
        rows = (
            db.scalars(
                select(ExtractionField).where(
                    ExtractionField.organization_id == invoice.organization_id,
                    ExtractionField.extraction_result_id == ctx.extraction.id,
                    ExtractionField.field_name.in_(
                        ["vendor_name", "vendor_tax_id"]
                    ),
                )
            )
            .unique()
            .all()
        )
        for row in rows:
            gate_passed = row.verification_status in (
                ExtractionFieldVerificationStatus.CONFIRMED.value,
                ExtractionFieldVerificationStatus.CORRECTED.value,
            ) or (row.confidence is not None and row.confidence >= threshold)
            ctx.gate_fields[row.field_name] = (row.field_value, gate_passed)
    return ctx


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------
def _feature_bank_account(
    db: Session, invoice: Invoice, vendor: Vendor | None, policy: Policy
) -> FeatureOutcome:
    observations: dict = {"fingerprint_present": invoice.remittance_account_fingerprint is not None}
    if not invoice.remittance_account_fingerprint:
        return FeatureOutcome(
            key="bank_account_consistency",
            state="insufficient_evidence",
            explanation=(
                "The invoice carries no printed pay-to bank details; the "
                "destination cannot be compared (the record may simply not "
                "exist in VeriPay)."
            ),
            signals=[
                _signal(
                    SignalType.MISSING_EVIDENCE, "medium",
                    "The invoice carries no printed pay-to bank details; the "
                    "record may simply not exist in VeriPay.", policy,
                    field_refs=("remittance_account_raw",),
                )
            ],
            observations=observations,
        )

    approved = find_approved_account_by_fingerprint(
        db, org_id=invoice.organization_id,
        fingerprint=invoice.remittance_account_fingerprint,
    )
    if approved is not None:
        observations["matched_account_id"] = str(approved.id)
        observations["verification_method"] = approved.verification_method
        return FeatureOutcome(
            key="bank_account_consistency",
            state="verified_agreement",
            explanation=(
                "The printed remittance details match the vendor's APPROVED "
                "bank account"
                + (
                    f" (independently verified via {approved.verification_method})"
                    if approved.verification_method else ""
                )
                + "."
            ),
            evidence_refs=(str(approved.id),),
            observations=observations,
        )

    # No approved match — the R5 floor finding. Record WHICH non-approved
    # account collides (provenance for the human), never a guess.
    has_any_account = vendor is not None and db.scalar(
        select(VendorBankAccount.id).where(
            VendorBankAccount.organization_id == invoice.organization_id,
            VendorBankAccount.vendor_id == vendor.id,
        )
    ) is not None
    collisions = (
        db.scalars(
            select(VendorBankAccount).where(
                VendorBankAccount.organization_id == invoice.organization_id,
                VendorBankAccount.account_fingerprint
                == invoice.remittance_account_fingerprint,
                VendorBankAccount.status != BankAccountStatus.APPROVED.value,
            )
        )
        .unique()
        .all()
    )
    observations["non_approved_collisions"] = [
        {"account_id": str(a.id), "status": a.status, "vendor_id": str(a.vendor_id)}
        for a in collisions
    ]
    if collisions:
        detail = (
            "the printed details match an on-file account whose status is "
            + ", ".join(sorted({a.status for a in collisions}))
            + " — that account was never approved"
        )
        evidence_refs = tuple(str(a.id) for a in collisions)
    elif not has_any_account:
        detail = "no bank accounts are on file for this vendor"
        evidence_refs = ()
    else:
        detail = "no APPROVED bank account matches the printed pay-to details"
        evidence_refs = ()
    message = (
        f"The remittance account is unverified: {detail}. New bank accounts "
        "require independent human verification."
    )
    return FeatureOutcome(
        key="bank_account_consistency",
        state="confirmed_discrepancy",
        explanation=(
            "The printed remittance details match no APPROVED account — the "
            "payment destination is unverified (override: mandatory review)."
        ),
        signals=[
            _signal(
                SignalType.BANK_ACCOUNT_UNVERIFIED, "high", message, policy,
                field_refs=("remittance_account_raw",),
                evidence_refs=evidence_refs,
            )
        ],
        evidence_refs=evidence_refs,
        observations=observations,
    )


def _feature_identity(
    invoice: Invoice, vendor: Vendor | None, doc: _DocContext, policy: Policy
) -> FeatureOutcome:
    observations: dict = {
        "vendor_resolved": vendor is not None,
    }
    if vendor is None:
        return FeatureOutcome(
            key="identity_consistency",
            state="insufficient_evidence",
            explanation=(
                "The vendor is unresolved — identity is unknown and never "
                "guessed; review is required before any reliance."
            ),
            signals=[
                _signal(
                    SignalType.UNKNOWN_VENDOR, "medium",
                    "The invoice's vendor is unresolved; vendor resolution is "
                    "a human decision and review is required.", policy,
                    field_refs=("vendor_id",),
                )
            ],
            observations=observations,
        )

    observations["vendor_id"] = str(vendor.id)
    name_value, name_gated = doc.gate_fields.get("vendor_name", (None, False))
    tax_value, tax_gated = doc.gate_fields.get("vendor_tax_id", (None, False))
    observations["gate_passable_identity_fields"] = {
        "vendor_name": bool(name_gated),
        "vendor_tax_id": bool(tax_gated),
    }

    signals: list[Signal] = []
    if name_gated and name_value and not (
        names_equivalent(name_value, vendor.display_name)
        or (vendor.legal_name and names_equivalent(name_value, vendor.legal_name))
    ):
        signals.append(
            _signal(
                SignalType.FIELD_PROVENANCE_CONFLICT, "medium",
                f"The document's extracted vendor name '{name_value}' disagrees "
                f"with the registry vendor '{vendor.display_name}'.",
                policy, field_refs=("vendor_id",),
            )
        )
        observations["extracted_vendor_name"] = name_value
    if tax_gated and tax_value and vendor.tax_id:
        if normalize_identifier(tax_value) != normalize_identifier(vendor.tax_id):
            signals.append(
                _signal(
                    SignalType.FIELD_PROVENANCE_CONFLICT, "high",
                    "The document's extracted tax id disagrees with the "
                    "registry vendor's tax id.",
                    policy, field_refs=("vendor_id",),
                )
            )
            observations["tax_id_disagreement"] = True

    if signals:
        return FeatureOutcome(
            key="identity_consistency",
            state="confirmed_discrepancy",
            explanation=(
                "Gate-passed document identity fields disagree with the "
                "vendor registry record."
            ),
            signals=signals,
            observations=observations,
        )
    if not (name_gated or tax_gated):
        return FeatureOutcome(
            key="identity_consistency",
            state="insufficient_evidence",
            explanation=(
                "No gate-passed identity fields on the document to compare "
                "against the registry — identity consistency is unknown, "
                "never assumed."
            ),
            observations=observations,
        )
    return FeatureOutcome(
        key="identity_consistency",
        state="verified_agreement",
        explanation=(
            "Gate-passed document identity fields agree with the vendor "
            "registry."
        ),
        observations=observations,
    )


def _feature_duplicates(hits: list[DuplicateHit], policy: Policy) -> FeatureOutcome:
    if not hits:
        return FeatureOutcome(
            key="duplicate_indicators",
            state="verified_agreement",
            explanation=(
                "No duplicate indicator fired on any axis (content, number, "
                "vendor entity, amount/date, field overlap)."
            ),
            observations={"hits": 0},
        )
    signals: list[Signal] = []
    evidence_refs: list[str] = []
    classifications: list[str] = []
    for hit in hits:
        classifications.append(hit.classification)
        evidence_refs.append(str(hit.target.id))
        if hit.classification == CORRECTED_VERSION_CANDIDATE:
            message = (
                "An earlier invoice with the same normalized number exists "
                "and the amount differs with a later date — possible "
                "corrected re-issue. A human must confirm which version is "
                "current."
            )
        elif hit.classification == DUPLICATE_UPLOAD:
            message = (
                "This invoice duplicates an earlier one "
                f"({hit.kind.replace('_', ' ')}; similarity "
                f"{hit.similarity:.2f}) — possible duplicate upload or "
                "re-billing; a human must disposition it."
            )
        elif hit.classification == NEAR_DUPLICATE:
            message = (
                "A near-identical earlier invoice exists (equal amount, "
                f"{hit.similarity:.0%} field overlap, close date) under a "
                "different number — possible duplicate billing; a human must "
                "disposition it."
            )
        else:  # FIELD_OVERLAP
            message = (
                "An earlier invoice shares key fields (pay-to account, date) "
                "but carries a different number and amount — possible altered "
                "re-billing; a human must disposition it."
            )
        signals.append(
            _signal(
                SignalType.DUPLICATE_CANDIDATE, hit.severity, message, policy,
                evidence_refs=(str(hit.target.id),),
            )
        )
    worst = max((s.severity for s in signals), key=lambda x: SEVERITY_ORDER.get(x, 0))
    return FeatureOutcome(
        key="duplicate_indicators",
        state="confirmed_discrepancy",
        explanation=(
            "Duplicate indicators fired: " + ", ".join(sorted(set(classifications)))
            + ". Appearance/content similarity is a duplicate indicator only — "
            "it is never evidence of authenticity."
        ),
        signals=signals,
        evidence_refs=tuple(evidence_refs),
        observations={"hits": len(hits), "classifications": sorted(set(classifications))},
    )


def _compare_po(
    invoice: Invoice, po: PurchaseOrder | None,
    observations: dict, policy: Policy,
) -> FeatureOutcome:
    if po is None:
        return FeatureOutcome(
            key="po_mismatch",
            state="insufficient_evidence",
            explanation="The linked purchase order could not be loaded.",
            signals=[
                _signal(
                    SignalType.MISSING_EVIDENCE, "medium",
                    "The linked purchase order record is unavailable; the "
                    "comparison is uncertain.", policy,
                    field_refs=("purchase_order_id",),
                )
            ],
            observations=observations,
        )
    observations["po_amount"] = str(po.amount) if po.amount is not None else None
    observations["po_currency"] = po.currency
    invoice_amount = (
        Decimal(str(invoice.total_amount)) if invoice.total_amount is not None else None
    )
    po_amount = Decimal(str(po.amount)) if po.amount is not None else None
    observations["invoice_amount"] = (
        str(invoice.total_amount) if invoice.total_amount is not None else None
    )
    if invoice_amount is None or po_amount is None:
        return FeatureOutcome(
            key="po_mismatch",
            state="insufficient_evidence",
            explanation=(
                "The PO comparison is incomplete: the invoice or the PO "
                "carries no amount — a record gap, not a discrepancy."
            ),
            signals=[
                _signal(
                    SignalType.MISSING_EVIDENCE, "medium",
                    "The invoice/PO amount comparison is incomplete — one "
                    "side carries no amount.", policy,
                    field_refs=("total_amount",),
                )
            ],
            observations=observations,
        )
    if invoice_amount != po_amount:
        return FeatureOutcome(
            key="po_mismatch",
            state="confirmed_discrepancy",
            explanation=(
                f"The invoice total ({invoice_amount}) differs from the "
                f"purchase-order amount ({po_amount})."
            ),
            signals=[
                _signal(
                    SignalType.AMOUNT_MISMATCH, "high",
                    f"Invoice total {invoice_amount} differs from the "
                    f"purchase-order amount {po_amount}.", policy,
                    field_refs=("total_amount",),
                )
            ],
            observations=observations,
        )
    currencies_differ = (
        invoice.currency is not None
        and po.currency is not None
        and invoice.currency != po.currency
    )
    if currencies_differ:
        return FeatureOutcome(
            key="po_mismatch",
            state="confirmed_discrepancy",
            explanation=(
                f"Amounts match but currencies differ "
                f"({invoice.currency} vs {po.currency})."
            ),
            signals=[
                _signal(
                    SignalType.AMOUNT_MISMATCH, "medium",
                    f"Invoice currency {invoice.currency} differs from the "
                    f"purchase-order currency {po.currency} (amounts match).",
                    policy, field_refs=("currency",),
                )
            ],
            observations=observations,
        )
    return FeatureOutcome(
        key="po_mismatch",
        state="verified_agreement",
        explanation="Invoice total and currency agree with the purchase order.",
        observations=observations,
    )


def _feature_history(
    db: Session, invoice: Invoice, vendor: Vendor | None, policy: Policy
) -> FeatureOutcome:
    rules = policy.history
    if vendor is None:
        return FeatureOutcome(
            key="historical_anomalies",
            state="insufficient_evidence",
            explanation="No resolved vendor — no trusted history to compare against.",
            observations={"prior_invoices": None},
        )
    priors = (
        db.scalars(
            select(Invoice).where(
                Invoice.organization_id == invoice.organization_id,
                Invoice.vendor_id == vendor.id,
                Invoice.id != invoice.id,
                Invoice.total_amount.is_not(None),
            )
        )
        .unique()
        .all()
    )
    observations = {"prior_invoices": len(priors)}
    if len(priors) < int(rules["min_invoices"]):
        return FeatureOutcome(
            key="historical_anomalies",
            state="insufficient_evidence",
            explanation=(
                f"Only {len(priors)} comparable prior invoice(s) — fewer than "
                f"the {rules['min_invoices']} needed; absence of history is "
                "not fraud (R4), it is uncertainty."
            ),
            observations=observations,
        )
    amounts = sorted(Decimal(str(p.total_amount)) for p in priors)
    mid = len(amounts) // 2
    median = (
        amounts[mid] if len(amounts) % 2 else (amounts[mid - 1] + amounts[mid]) / 2
    )
    observations["median_prior_amount"] = str(median)
    current = Decimal(str(invoice.total_amount)) if invoice.total_amount is not None else None
    if current is None:
        return FeatureOutcome(
            key="historical_anomalies",
            state="insufficient_evidence",
            explanation="The invoice carries no total to compare with history.",
            observations=observations,
        )
    factor = float(rules["amount_jump_factor"])
    if median > 0 and current > median * Decimal(str(factor)):
        return FeatureOutcome(
            key="historical_anomalies",
            state="confirmed_discrepancy",
            explanation=(
                f"The amount ({current}) exceeds {factor}× the vendor's "
                f"median historical amount ({median})."
            ),
            signals=[
                _signal(
                    SignalType.AMOUNT_MISMATCH, "medium",
                    f"Invoice total {current} exceeds {factor}× the vendor's "
                    f"median historical amount ({median}) — a statistical "
                    "anomaly for human attention, not a PO comparison.",
                    policy, field_refs=("total_amount",),
                )
            ],
            observations=observations,
        )
    return FeatureOutcome(
        key="historical_anomalies",
        state="verified_agreement",
        explanation="The amount is consistent with the vendor's history.",
        observations=observations,
    )


def _feature_untrusted_source(
    invoice: Invoice, doc: _DocContext, policy: Policy
) -> FeatureOutcome:
    sources = invoice.field_sources or {}
    threshold = get_settings().ocr_confidence_threshold
    unverified_fields: list[str] = []
    conflicts: list[str] = []
    # Below-gate OCR confidence on a payment-critical column — even when the
    # human-entered column wins — is critical OCR uncertainty: the machine
    # cannot tell whether the column or the OCR read is wrong.
    critical_below_gate: list[str] = []
    for column, meta in sources.items():
        origin = meta.get("origin")
        confidence = meta.get("confidence_at_ingest", meta.get("confidence"))
        if origin == "extracted":
            if confidence is None or confidence < threshold:
                unverified_fields.append(column)
        if (
            column in CRITICAL_PAYMENT_COLUMNS
            and confidence is not None
            and confidence < threshold
        ):
            critical_below_gate.append(column)
        extracted_value = meta.get("extracted_value")
        if extracted_value is not None:
            current = getattr(invoice, column, None)
            if current is not None and str(current) != str(extracted_value):
                conflicts.append(column)

    signals: list[Signal] = []
    for column in conflicts:
        signals.append(
            _signal(
                SignalType.FIELD_PROVENANCE_CONFLICT, "medium",
                f"The invoice column '{column}' disagrees with its extracted "
                "provenance value; the column value is authoritative.",
                policy, field_refs=(column,),
            )
        )
    for column in unverified_fields:
        signals.append(
            _signal(
                SignalType.UNVERIFIED_INPUT, "low",
                f"Machine-extracted value for '{column}' is below the "
                "confidence gate and was excluded from strong evidence (R3).",
                policy, field_refs=(column,),
            )
        )

    observations: dict = {
        "unverified_fields": unverified_fields,
        "provenance_conflicts": conflicts,
        "critical_below_gate": critical_below_gate,
        "ocr_failed": doc.ocr_failed,
        "ocr_incomplete": doc.ocr_incomplete,
    }

    # Critical OCR uncertainty: the extraction failed, or a payment-critical
    # column's only/alternative read is below-gate OCR → manual verification.
    critical_uncertain = bool(
        set(unverified_fields) & set(CRITICAL_PAYMENT_COLUMNS)
    ) or bool(critical_below_gate)
    if doc.ocr_failed or critical_uncertain:
        if doc.ocr_failed:
            reason = "the document's OCR/extraction failed"
        else:
            uncertain = sorted(
                set(unverified_fields) & set(CRITICAL_PAYMENT_COLUMNS)
            ) or critical_below_gate
            reason = (
                "payment-critical fields exist only through below-gate OCR: "
                + ", ".join(uncertain)
            )
        signals.append(
            _signal(
                SignalType.OCR_UNCERTAIN, "medium",
                f"Critical OCR uncertainty: {reason}. Manual verification is "
                "required before the affected values can be relied on (R3).",
                policy,
                field_refs=tuple(
                    sorted(set(unverified_fields) & set(CRITICAL_PAYMENT_COLUMNS))
                ),
            )
        )

    if any(s.signal_type == SignalType.FIELD_PROVENANCE_CONFLICT for s in signals):
        return FeatureOutcome(
            key="untrusted_source_indicators",
            state="confirmed_discrepancy",
            explanation=(
                "Invoice columns disagree with their gate-passed extracted "
                "provenance."
            ),
            signals=signals,
            observations=observations,
        )
    if doc.ocr_failed or critical_uncertain or unverified_fields or doc.ocr_incomplete:
        return FeatureOutcome(
            key="untrusted_source_indicators",
            state="insufficient_evidence",
            explanation=(
                "Some inputs are excluded or uncertain (below-gate OCR, "
                "incomplete or failed extraction) — the affected comparisons "
                "are uncertain, not discrepant."
            ),
            signals=signals,
            observations=observations,
        )
    return FeatureOutcome(
        key="untrusted_source_indicators",
        state="verified_agreement",
        explanation=(
            "All machine-extracted inputs in play are gate-passed and agree "
            "with the invoice columns."
        ),
        observations=observations,
    )


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------
def compute_evc(
    db: Session, *, invoice: Invoice, duplicate_hits: list[DuplicateHit],
    policy: Policy | None = None,
) -> EvcResult:
    """Compute the full EVC result for one invoice (read-only; persistence is
    the service's job)."""
    policy = policy or load_policy()
    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    doc = _load_doc_context(db, invoice)

    po = None
    if invoice.purchase_order_id is not None:
        po = db.get(PurchaseOrder, invoice.purchase_order_id)

    features = [
        _feature_bank_account(db, invoice, vendor, policy),
        _feature_identity(invoice, vendor, doc, policy),
        _feature_duplicates(duplicate_hits, policy),
        _compare_po(
            invoice, po,
            {"purchase_order_id": (
                str(invoice.purchase_order_id)
                if invoice.purchase_order_id else None
            )},
            policy,
        ),
        _feature_history(db, invoice, vendor, policy),
        _feature_untrusted_source(invoice, doc, policy),
    ]

    # --- score: only confirmed discrepancies contribute ---------------------
    score = 0.0
    for feature in features:
        if feature.state != "confirmed_discrepancy" or feature.severity is None:
            continue
        weight = policy.weight(feature.key)
        score += weight * policy.severity_factor(feature.severity)
    score = round(min(100.0, score), 1)

    # --- overrides (machine-enforced minima) --------------------------------
    overrides: list[dict] = []
    manual_verification_required = False
    for signal in (s for f in features for s in f.signals):
        override_name = _OVERRIDES.get(signal.signal_type.value)
        if override_name is None:
            continue
        overrides.append(
            {
                "override": override_name,
                "signal": signal.signal_type.value,
                "minimum_result": policy.override_minimum_result(
                    signal.signal_type.value
                ),
                "message": signal.message,
            }
        )
        if signal.signal_type == SignalType.OCR_UNCERTAIN:
            manual_verification_required = True

    # --- result state: max(bands from score, severities, overrides) ---------
    def _band_from_score() -> str:
        if score >= policy.high_threshold:
            return "high_risk_discrepancy"
        if score >= policy.review_threshold:
            return "review_required"
        return "no_material_discrepancies"

    all_signals = [s for f in features for s in f.signals]

    # Materiality per §8: ANY high+ severity is material by itself; a medium
    # signal forces review only when its TYPE forces (missing_evidence,
    # unverified_input and field_provenance_conflict are informational —
    # "humans decide whether to look", never machine-forced).
    forcing_map = policy.forcing_signals()

    def _material(signal: Signal) -> bool:
        if SEVERITY_ORDER.get(signal.severity, 0) >= SEVERITY_ORDER["high"]:
            return True
        return forcing_map.get(signal.signal_type.value, False)

    material_signals = [s for s in all_signals if _material(s)]
    max_severity = max(
        (SEVERITY_ORDER.get(s.severity, 0) for s in material_signals), default=0
    )

    def _band_from_severity() -> str:
        if max_severity >= SEVERITY_ORDER["high"]:
            return "high_risk_discrepancy"
        if max_severity >= SEVERITY_ORDER["medium"]:
            return "review_required"
        return "no_material_discrepancies"

    def _band_from_overrides() -> str:
        worst = RESULT_ORDER["no_material_discrepancies"]
        for override in overrides:
            minimum = override.get("minimum_result")
            if minimum in RESULT_ORDER:
                worst = max(worst, RESULT_ORDER[minimum])
        return RESULT_STATES[worst]

    result_state = max(
        _band_from_score(),
        _band_from_severity(),
        _band_from_overrides(),
        key=lambda state: RESULT_ORDER[state],
    )

    # --- risk level (R6 criticality included) -------------------------------
    high_signal_types = {
        s.signal_type.value
        for s in all_signals
        if SEVERITY_ORDER.get(s.severity, 0) >= SEVERITY_ORDER["high"]
    }
    if len(high_signal_types) >= policy.critical_min_high_signals:
        risk_level = RiskLevel.CRITICAL.value
    elif result_state == "high_risk_discrepancy":
        risk_level = RiskLevel.HIGH.value
    elif result_state == "review_required":
        risk_level = RiskLevel.MEDIUM.value
    else:
        risk_level = (
            RiskLevel.LOW.value
            if any(f.state == "insufficient_evidence" for f in features)
            else RiskLevel.NONE.value
        )

    return EvcResult(
        policy_version=policy.policy_version,
        score=score,
        result_state=result_state,
        risk_level=risk_level,
        features=features,
        overrides=overrides,
        manual_verification_required=manual_verification_required,
        insufficient_features=[
            f.key for f in features if f.state == "insufficient_evidence"
        ],
        weights=policy.weights,
    )


def build_explanation(result: EvcResult) -> list[str]:
    """Ordered human-readable reasons: discrepancies worst-first, then the
    uncertainty notes, then the invariant closing disclaimer (R2)."""
    signals = sorted(
        result.signals,
        key=lambda s: -SEVERITY_ORDER.get(s.severity, 0),
    )
    lines = [
        f"[{s.severity}] {s.signal_type.value}: {s.message}" for s in signals
    ]
    if result.insufficient_features:
        lines.append(
            "Uncertainty (not scored): " + ", ".join(result.insufficient_features)
            + " could not be verified for lack of trusted records — this is "
            "neither evidence of fraud nor of correctness."
        )
    if result.manual_verification_required:
        lines.append(
            "Manual verification of the affected document values is required "
            "before any reliance (critical OCR uncertainty)."
        )
    lines.append(
        "VeriPay provides risk signals only; it never authorizes payments "
        "and never certifies an invoice as genuine."
    )
    return lines
