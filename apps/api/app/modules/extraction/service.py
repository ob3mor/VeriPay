"""Extraction: OCR output → durable extraction results with evidence (R3).

Runs inside a processing job. The same ``extraction_version`` on the same
document upserts (result row reused, field rows replaced in place); different
versions coexist.

Stub output carries zero pages and confidence ``None`` everywhere — the stub
can never produce fraud evidence (R3). Real providers fill the same shapes.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ocr.base import OcrDocument, build_ocr_provider
from app.core.config import get_settings
from app.core.enums import ProcessingStatus
from app.core.errors import AppError, ErrorCode
from app.models import Document, ExtractionField, ExtractionResult

EXTRACTION_VERSION = "stub-v1"


def get_or_create_result(
    db: Session, *, org_id: object, document: Document
) -> tuple[ExtractionResult, bool]:
    version = EXTRACTION_VERSION
    existing = db.scalar(
        select(ExtractionResult).where(
            ExtractionResult.organization_id == org_id,
            ExtractionResult.document_id == document.id,
            ExtractionResult.extraction_version == version,
        )
    )
    if existing is not None:
        # Upsert-in-place: clear this version's fields; they are replaced.
        for row in db.scalars(
            select(ExtractionField).where(
                ExtractionField.extraction_result_id == existing.id
            )
        ):
            db.delete(row)
        existing.status = ProcessingStatus.PROCESSING.value
        existing.error = None
        existing.started_at = datetime.now(timezone.utc)
        existing.completed_at = None
        db.commit()
        return existing, False

    result = ExtractionResult(
        organization_id=org_id,
        document_id=document.id,
        extraction_version=version,
        status=ProcessingStatus.PROCESSING.value,
        started_at=datetime.now(timezone.utc),
    )
    db.add(result)
    db.commit()
    return result, True


def _fields_from_ocr(
    db: Session, *, org_id: object, result: ExtractionResult, ocr: OcrDocument
) -> int:
    """Persist per-field rows with evidence spans + confidence.

    The stub provider yields no pages, so this writes zero rows — honest.
    A real provider's field normalization joins here without touching the
    fraud gate: confidence travels as-is (None = below gate).
    """
    count = 0
    for page in ocr.pages:
        for block in page.blocks:
            field = ExtractionField(
                organization_id=org_id,
                extraction_result_id=result.id,
                field_name=f"block:{page.page_number}:{count}",
                field_value=block.text,
                confidence=block.confidence,
                evidence_spans=[
                    {
                        "page": page.page_number,
                        "bbox": list(block.bbox) if block.bbox else None,
                        "text": block.text,
                        "confidence": block.confidence,
                    }
                ],
            )
            db.add(field)
            count += 1
    return count


def run_extraction(db: Session, *, org_id: object, document_id: object) -> ExtractionResult:
    """The job function for job_type=ocr_extraction."""
    from app.modules.documents.service import get_document, set_processing_status

    document = get_document(db, org_id=org_id, document_id=document_id)
    result, _created = get_or_create_result(db, org_id=org_id, document=document)

    # The document row walks the same guarded machine: pending → processing.
    if document.processing_status == ProcessingStatus.PENDING.value:
        set_processing_status(db, document, ProcessingStatus.PROCESSING.value)

    settings = get_settings()
    try:
        provider = build_ocr_provider(settings.ocr_provider)
    except ValueError as exc:
        result.status = ProcessingStatus.FAILED.value
        result.error = str(exc)
        result.completed_at = datetime.now(timezone.utc)
        db.commit()
        set_processing_status(
            db, document, ProcessingStatus.FAILED.value, error=str(exc)
        )
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, str(exc)) from exc

    from app.modules.documents.service import open_document_bytes

    data = open_document_bytes(db, document)
    ocr = provider.extract(data.read(), document.mime_type)

    result.ocr_provider = ocr.provider
    _fields_from_ocr(db, org_id=org_id, result=result, ocr=ocr)
    result.status = ProcessingStatus.COMPLETED.value
    result.completed_at = datetime.now(timezone.utc)
    db.commit()
    set_processing_status(db, document, ProcessingStatus.COMPLETED.value)
    return result


def get_result(
    db: Session, *, org_id: object, document_id: object
) -> ExtractionResult | None:
    return db.scalar(
        select(ExtractionResult)
        .where(
            ExtractionResult.organization_id == org_id,
            ExtractionResult.document_id == document_id,
        )
        .order_by(ExtractionResult.created_at.desc())
    )


def list_fields(db: Session, *, result_id: object) -> list[ExtractionField]:
    return list(
        db.scalars(
            select(ExtractionField)
            .where(ExtractionField.extraction_result_id == result_id)
            .order_by(ExtractionField.created_at)
        )
    )
