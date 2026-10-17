"""Retrieval routes: citable evidence for an invoice (Prompt-03 §7).

``GET /invoices/{invoice_id}/evidence`` — org-scoped (the tenant comes only
from the principal; a foreign org's invoice id is a plain 404, API.md §5.4)
and role-guarded like the other invoice reads: any authenticated canonical
role may read evidence, exactly like ``GET /invoices`` and ``GET /invoices/{id}``
(reads never mutate; GETs must never mutate — API.md §5).
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.retrieval import schemas, service
from app.models import User
from app.tenancy.deps import get_current_user

router = APIRouter(tags=["retrieval"])

_Db = Annotated[Session, Depends(get_db)]


def _location_out(hit) -> schemas.DocumentLocationOut | None:
    if hit.location is None:
        return None
    bbox = hit.location.get("bbox")
    return schemas.DocumentLocationOut(
        document_id=uuid.UUID(hit.location["document_id"])
        if hit.location.get("document_id")
        else None,
        page=hit.location.get("page"),
        bbox=[float(v) for v in bbox] if bbox else None,
    )


def _evidence_item_out(hit) -> schemas.EvidenceItemOut:
    return schemas.EvidenceItemOut(
        entity_type=hit.entity_type,
        entity_id=uuid.UUID(hit.entity_id),
        title=hit.title,
        matched_field=hit.matched_field,
        match_explanation=hit.explanation,
        trust_status=hit.trust_tier.value,
        retrieval_score=hit.final_score,
        fused_score=hit.fused_score,
        techniques=hit.techniques,
        document_location=_location_out(hit),
        provenance=hit.provenance,
        record_version=hit.record_version,
    )


@router.get(
    "/invoices/{invoice_id}/evidence",
    response_model=schemas.InvoiceEvidenceOut,
)
def get_invoice_evidence(
    invoice_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> schemas.InvoiceEvidenceOut:
    result = service.get_invoice_evidence(
        db, org_id=actor.organization_id, invoice_id=invoice_id
    )
    return schemas.InvoiceEvidenceOut(
        evidence=[_evidence_item_out(h) for h in result["evidence"]],
        gaps=[schemas.GraphGapOut(**g) for g in result["gaps"]],
        contradictions=[schemas.GraphGapOut(**g) for g in result["contradictions"]],
        meta=schemas.EvidenceMetaOut(**result["meta"]),
    )
