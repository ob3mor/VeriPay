"""Evidence-match recording shared by modules (procurement, fraud)."""

from sqlalchemy.orm import Session

from app.core.enums import MatchKind, MatchStatus
from app.models import EvidenceMatch, Invoice


def record_duplicate_number_match(
    db: Session, *, source: Invoice, target: Invoice, module: str
) -> EvidenceMatch:
    """Same (org, vendor, invoice_number) on two invoices — a fraud signal.

    Idempotent per (source, target, kind): the match row exists once even if
    resolution or assessment re-runs the check.
    """
    existing = db.query(EvidenceMatch).filter(
        EvidenceMatch.organization_id == source.organization_id,
        EvidenceMatch.source_entity_id == source.id,
        EvidenceMatch.target_entity_id == target.id,
        EvidenceMatch.match_kind == MatchKind.INVOICE_NUMBER.value,
    ).first()
    if existing is not None:
        return existing
    row = EvidenceMatch(
        organization_id=source.organization_id,
        source_entity_type="invoice",
        source_entity_id=source.id,
        target_entity_type="invoice",
        target_entity_id=target.id,
        match_kind=MatchKind.INVOICE_NUMBER.value,
        similarity_score=1.0,
        matched_fields={
            "invoice_number": source.invoice_number,
            "vendor_id": str(source.vendor_id),
        },
        created_by_module=module,
        status=MatchStatus.OPEN.value,
    )
    db.add(row)
    db.flush()
    return row
