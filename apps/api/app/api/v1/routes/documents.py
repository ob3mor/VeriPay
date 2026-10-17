"""Document routes: upload (validated), reads, protected download, processing.

Roles: upload/process = org_admin, finance_officer, reviewer; reads = any
authenticated member; field review (confirm/correct) = reviewer, org_admin
(R3: humans flip verification, machine extraction never self-verifies);
downloads resolve storage keys from the DB row only (never from client
paths) and are org-scoped (cross-org → 404).

Processing runs inline (settings.processing_backend): upload → validation →
storage → pending → inline OCR-extraction job → completed, all recorded in
durable processing_jobs rows. Retries are idempotent via the idempotency key.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import DocumentKind, JobType, ProcessingStatus, UserRole
from app.modules.audit.service import AuditContext, record_audit
from app.modules.documents import schemas, service
from app.models import User
from app.modules.extraction import service as extraction_service
from app.modules.processing import service as processing_service
from app.tenancy.deps import get_current_user
from app.tenancy.permissions import CAN_CONTRIBUTE, require_roles

router = APIRouter(prefix="/documents", tags=["documents"])

_contributor = require_roles(*CAN_CONTRIBUTE)

_Db = Annotated[Session, Depends(get_db)]
_PageLimit = Annotated[int, Query(ge=1, le=100)]
_PageOffset = Annotated[int, Query(ge=0)]


def _doc_out(doc) -> schemas.DocumentOut:
    return schemas.DocumentOut(
        id=doc.id,
        organization_id=doc.organization_id,
        kind=doc.kind,
        vendor_id=doc.vendor_id,
        file_name=doc.file_name,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        sha256=doc.sha256,
        processing_status=doc.processing_status,
        uploaded_by=doc.uploaded_by,
    )


def _field_out(field) -> schemas.ExtractionFieldOut:
    return schemas.ExtractionFieldOut(
        id=field.id,
        field_name=field.field_name,
        field_value=field.field_value,
        confidence=field.confidence,
        evidence_spans=field.evidence_spans,
        verification_status=field.verification_status,
        verified_value=field.verified_value,
        normalized_value=field.normalized_value,
        verified_by=field.verified_by,
        verified_at=field.verified_at,
    )


@router.post("", response_model=schemas.ProcessedDocumentOut, status_code=201)
def upload_document(
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
    response: Response,
    file: Annotated[UploadFile, File()],
    kind: Annotated[DocumentKind, Form()] = DocumentKind.OTHER,
    vendor_id: Annotated[uuid.UUID | None, Form()] = None,
) -> schemas.ProcessedDocumentOut:
    """Validate + store one document, then run extraction inline.

    Identical bytes re-uploaded within the org return 200 with the existing
    document (per-org content dedup) — deduplicated=true.
    """
    document, created = service.ingest_upload(
        db,
        org_id=actor.organization_id,
        actor=actor,
        upload=file,
        kind=kind,
        vendor_id=vendor_id,
    )
    record_audit(
        db,
        action="document.uploaded",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="document",
        entity_id=document.id,
        detail={
            "kind": document.kind,
            "mime": document.mime_type,
            "size": document.size_bytes,
            "sha256_prefix": document.sha256[:12],
            "deduplicated": not created,
        },
        context=AuditContext.from_request(request),
    )

    job = None
    if created:
        job, _new = processing_service.enqueue(
            db,
            org_id=actor.organization_id,
            job_type=JobType.OCR_EXTRACTION,
            idempotency_key=f"ocr:{document.id}:{extraction_service.EXTRACTION_VERSION}",
            document_id=document.id,
        )
        processing_service.run_job(
            db,
            job,
            lambda session, _job: extraction_service.run_extraction(
                session, org_id=actor.organization_id, document_id=document.id
            ),
        )
        db.refresh(document)

    # Build the response AFTER processing so the status is the final one.
    # Dedup is a success-read of an existing resource, not a creation:
    # docs/API.md §2 fixes it at 200 ("identical bytes ... return 200 with
    # the existing document"), so the route's 201 only applies to creation.
    if not created:
        response.status_code = 200
    return schemas.ProcessedDocumentOut(
        **_doc_out(document).model_dump(),
        deduplicated=not created,
        job_id=job.id if job is not None else None,
        job_status=job.status if job is not None else None,
    )


@router.get("", response_model=list[schemas.DocumentOut])
def list_documents(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
    limit: _PageLimit = 25,
    offset: _PageOffset = 0,
) -> list[schemas.DocumentOut]:
    rows, _total = service.list_documents(
        db, org_id=actor.organization_id, limit=limit, offset=offset
    )
    return [_doc_out(d) for d in rows]


@router.get("/{document_id}", response_model=schemas.DocumentOut)
def get_document(
    document_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> schemas.DocumentOut:
    return _doc_out(service.get_document(db, org_id=actor.organization_id, document_id=document_id))


@router.get("/{document_id}/file")
def download_document(
    document_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Protected download: org-scoped 404 first, then the stored bytes with
    the recorded content type."""
    document = service.get_document(
        db, org_id=actor.organization_id, document_id=document_id
    )
    stream = service.open_document_bytes(db, document)
    return StreamingResponse(
        stream,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.file_name}"'
        },
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: uuid.UUID,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(require_roles(UserRole.ORG_ADMIN))],
) -> Response:
    """Hard delete (org_admin only — destructive; docs/DATABASE.md §1: no soft
    delete). Refused with 409 while the document is referenced by a purchase
    order, an invoice, or a bank account's R5 verification record. The stored
    object is deleted through the StorageProvider seam; extraction results,
    fields and the document's own processing jobs go with it."""
    document = service.delete_document(
        db, org_id=actor.organization_id, document_id=document_id
    )
    record_audit(
        db,
        action="document.deleted",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="document",
        entity_id=document.id,
        detail={"file_name": document.file_name, "sha256_prefix": document.sha256[:12]},
        context=AuditContext.from_request(request),
    )
    return Response(status_code=204)


@router.get("/{document_id}/extraction", response_model=schemas.ExtractionResultOut | None)
def get_extraction(
    document_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> schemas.ExtractionResultOut | None:
    service.get_document(db, org_id=actor.organization_id, document_id=document_id)
    result = extraction_service.get_result(
        db, org_id=actor.organization_id, document_id=document_id
    )
    if result is None:
        return None
    return schemas.ExtractionResultOut(
        id=result.id,
        document_id=result.document_id,
        extraction_version=result.extraction_version,
        ocr_provider=result.ocr_provider,
        status=result.status,
        error=result.error,
        provider_meta=result.provider_meta,
        validation_summary=result.validation_summary,
    )


@router.get("/{document_id}/fields", response_model=list[schemas.ExtractionFieldOut])
def list_extraction_fields(
    document_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> list[schemas.ExtractionFieldOut]:
    document = service.get_document(
        db, org_id=actor.organization_id, document_id=document_id
    )
    result = extraction_service.get_result(
        db, org_id=actor.organization_id, document_id=document.id
    )
    if result is None:
        return []
    return [
        _field_out(f)
        for f in extraction_service.list_fields(db, result_id=result.id)
    ]


_reviewer = require_roles(UserRole.ORG_ADMIN, UserRole.REVIEWER)


@router.patch(
    "/{document_id}/fields/{field_id}",
    response_model=schemas.ExtractionFieldOut,
)
def review_extraction_field(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: schemas.ExtractionFieldReviewIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_reviewer)],
) -> schemas.ExtractionFieldOut:
    """Human field review (R3): confirm or correct one extracted field.

    Only ``reviewer``/``org_admin`` (docs/API.md §5 role matrix — the same
    roles that verify bank accounts). ``confirm`` marks the extracted value
    human-verified; ``correct`` requires a non-empty ``verified_value`` and
    preserves the original extraction untouched. Both stamp verified_by/at
    and write an audit event.
    """
    field = extraction_service.review_field(
        db,
        org_id=actor.organization_id,
        document_id=document_id,
        field_id=field_id,
        actor=actor,
        action=payload.action,
        verified_value=payload.verified_value,
    )
    record_audit(
        db,
        action=(
            "document.field_corrected"
            if payload.action == "correct"
            else "document.field_confirmed"
        ),
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="extraction_field",
        entity_id=field.id,
        detail={
            "document_id": str(document_id),
            "field_name": field.field_name,
            "original_value": field.field_value,
            "verified_value": field.verified_value,
            "action": payload.action,
        },
        context=AuditContext.from_request(request),
    )
    return _field_out(field)


@router.post("/{document_id}/process", response_model=schemas.ProcessedDocumentOut)
def reprocess_document(
    document_id: uuid.UUID,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> schemas.ProcessedDocumentOut:
    """Idempotent retry: enqueue (or re-enqueue) the extraction job."""
    document = service.get_document(
        db, org_id=actor.organization_id, document_id=document_id
    )
    job, _created = processing_service.enqueue(
        db,
        org_id=actor.organization_id,
        job_type=JobType.OCR_EXTRACTION,
        idempotency_key=f"ocr:{document.id}:{extraction_service.EXTRACTION_VERSION}",
        document_id=document.id,
    )
    # An already-completed job is returned as-is (idempotency); only a
    # pending/reset job executes.
    if job.status == ProcessingStatus.PENDING.value:
        processing_service.run_job(
            db,
            job,
            lambda session, _job: extraction_service.run_extraction(
                session, org_id=actor.organization_id, document_id=document.id
            ),
        )
    record_audit(
        db,
        action="document.process_requested",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="document",
        entity_id=document.id,
        detail={"job_id": str(job.id), "job_status": job.status},
        context=AuditContext.from_request(request),
    )
    db.refresh(document)
    return schemas.ProcessedDocumentOut(
        **_doc_out(document).model_dump(),
        job_id=job.id,
        job_status=job.status,
    )
