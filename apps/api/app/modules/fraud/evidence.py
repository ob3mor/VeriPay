"""Evidence-match recording shared by modules (procurement, fraud).

Every machine-detected correspondence between two entities lands here with
its provenance, so a human can disposition it (MatchStatus). Rows are
idempotent per (source, target, kind): re-running resolution, intake or an
assessment never duplicates match rows.

EVC v1 uses this for all duplicate axes (invoice_number, near_duplicate,
field_overlap) and for bank-account collisions with non-approved accounts.
"""

from sqlalchemy.orm import Session

from app.core.enums import MatchKind, MatchStatus
from app.models import EvidenceMatch, Invoice


def record_evidence_match(
    db: Session,
    *,
    org_id: object,
    source_type: str,
    source_id: object,
    target_type: str,
    target_id: object,
    match_kind: str,
    similarity: float,
    matched_fields: dict,
    module: str,
) -> EvidenceMatch:
    """Idempotent get-or-create of one evidence match (org-scoped by the
    caller's rows; both entities necessarily belong to the same org)."""
    existing = db.query(EvidenceMatch).filter(
        EvidenceMatch.organization_id == org_id,
        EvidenceMatch.source_entity_type == source_type,
        EvidenceMatch.source_entity_id == source_id,
        EvidenceMatch.target_entity_type == target_type,
        EvidenceMatch.target_entity_id == target_id,
        EvidenceMatch.match_kind == match_kind,
    ).first()
    if existing is not None:
        return existing
    row = EvidenceMatch(
        organization_id=org_id,
        source_entity_type=source_type,
        source_entity_id=source_id,
        target_entity_type=target_type,
        target_entity_id=target_id,
        match_kind=match_kind,
        similarity_score=float(min(1.0, max(0.0, similarity))),
        matched_fields=matched_fields,
        created_by_module=module,
        status=MatchStatus.OPEN.value,
    )
    db.add(row)
    db.flush()
    return row


def record_duplicate_number_match(
    db: Session, *, source: Invoice, target: Invoice, module: str
) -> EvidenceMatch:
    """Same (org, vendor, invoice_number) on two invoices — a fraud signal.

    Kept as a named wrapper: the intake path (procurement) and vendor
    resolution re-run exactly this check (docs/DATABASE.md §9)."""
    return record_evidence_match(
        db,
        org_id=source.organization_id,
        source_type="invoice",
        source_id=source.id,
        target_type="invoice",
        target_id=target.id,
        match_kind=MatchKind.INVOICE_NUMBER.value,
        similarity=1.0,
        matched_fields={
            "invoice_number": source.invoice_number,
            "vendor_id": str(source.vendor_id),
        },
        module=module,
    )
