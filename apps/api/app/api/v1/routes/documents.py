"""Document routes: upload (validated), reads, protected download, processing.

Roles: upload/process = org_admin, finance_officer, reviewer; reads = any
authenticated member; downloads resolve storage keys from the DB row only
(never from client paths) and are org-scoped (cross-org → 404).

Processing runs inline (settings.processing_backend): upload → validation →
storage → pending → inline OCR-extraction job → completed, all recorded in
durable processing_jobs rows. Retries are idempotent via the idempotency key.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import DocumentKind, JobType, ProcessingStatus
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


@router.post("", response_model=schemas.ProcessedDocumentOut, status_code=201)
def upload_document(
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
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
        schemas.ExtractionFieldOut(
            id=f.id,
            field_name=f.field_name,
            field_value=f.field_value,
            confidence=f.confidence,
            evidence_spans=f.evidence_spans,
            verification_status=f.verification_status,
            verified_value=f.verified_value,
        )
        for f in extraction_service.list_fields(db, result_id=result.id)
    ]


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
