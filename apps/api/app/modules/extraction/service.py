"""Extraction: OCR output → durable extraction results with evidence (R3).

Runs inside a processing job. The same ``extraction_version`` on the same
document upserts (result row reused, field rows replaced in place); different
versions coexist.

Pipeline (Prompt-02): configured OCR provider (settings.ocr_provider, default
``text_layer``; an unavailable engine falls back to the stub with a recorded
reason) → OcrDocument → structured fields (fields.py) → validation summary
(validation.py) → persisted field rows with evidence spans + confidence.

Stub output carries zero pages and confidence ``None`` everywhere — the stub
can never produce fraud evidence (R3). Field confidence travels as-is from
the provider; ``None``/below-threshold stays below the R3 gate downstream.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ocr.base import OcrDocument, build_ocr_provider_with_fallback
from app.core.config import get_settings
from app.core.enums import ExtractionFieldVerificationStatus, ProcessingStatus
from app.core.errors import AppError, ErrorCode
from app.models import Document, ExtractionField, ExtractionResult, User

# Extractor + label-set version. Bumping it starts a NEW version's rows
# (previous versions are preserved side by side — DATABASE.md §12 rule).
EXTRACTION_VERSION = "fields-v1"


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


def _persist_fields(
    db: Session,
    *,
    org_id: object,
    result: ExtractionResult,
    extracted_fields: list,
) -> int:
    """Persist per-field rows with evidence spans + confidence (R3).

    The human-correction flag is always False here — ``verification_status``
    starts at ``unverified``; only the review endpoint (reviewer/org_admin)
    flips it. Original extraction values are never overwritten: corrections
    live in ``verified_value``.
    """
    count = 0
    for item in extracted_fields:
        field = ExtractionField(
            organization_id=org_id,
            extraction_result_id=result.id,
            field_name=item.field_name,
            field_value=item.raw_value,
            normalized_value=item.normalized_value,
            confidence=item.confidence,
            evidence_spans=[
                {
                    "page": item.page,
                    "bbox": list(item.bbox) if item.bbox else None,
                    "text": item.supporting_text,
                    "confidence": item.confidence,
                    "source": item.source,
                    "human_verified": item.human_verified,
                }
            ],
            verification_status=ExtractionFieldVerificationStatus.UNVERIFIED.value,
        )
        db.add(field)
        count += 1
    return count


def run_extraction(db: Session, *, org_id: object, document_id: object) -> ExtractionResult:
    """The job function for job_type=ocr_extraction."""
    from app.modules.documents.service import get_document, set_processing_status
    from app.modules.extraction.fields import extract_fields
    from app.modules.extraction.validation import validate_fields

    document = get_document(db, org_id=org_id, document_id=document_id)
    result, _created = get_or_create_result(db, org_id=org_id, document=document)

    # The document row walks the same guarded machine as the job. A retry
    # first walks the machine's own recovery edge (failed → pending —
    # documents service: FAILED allows exactly PENDING), or the retry endpoint
    # could never heal a failed document (the final completed transition
    # would be an illegal failed → completed jump).
    if document.processing_status in (
        ProcessingStatus.FAILED.value,
    ):
        set_processing_status(db, document, ProcessingStatus.PENDING.value)
    if document.processing_status == ProcessingStatus.PENDING.value:
        set_processing_status(db, document, ProcessingStatus.PROCESSING.value)

    settings = get_settings()
    try:
        provider, fallback_reason = build_ocr_provider_with_fallback(
            settings.ocr_provider
        )
    except ValueError as exc:
        # Unknown provider name = misconfiguration: fail loudly, never stub.
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
    ocr: OcrDocument = provider.extract(data.read(), document.mime_type)

    provider_meta = dict(ocr.provider_meta)
    if fallback_reason:
        provider_meta["fallback"] = fallback_reason

    extracted_fields = extract_fields(ocr)
    validation = validate_fields(
        extracted_fields, confidence_threshold=settings.ocr_confidence_threshold
    )

    result.ocr_provider = ocr.provider
    result.provider_meta = provider_meta
    result.validation_summary = validation
    document.page_count = ocr.page_count or document.page_count
    _persist_fields(db, org_id=org_id, result=result, extracted_fields=extracted_fields)
    result.status = ProcessingStatus.COMPLETED.value
    result.completed_at = datetime.now(timezone.utc)
    db.commit()
    set_processing_status(db, document, ProcessingStatus.COMPLETED.value)
    return result


def review_field(
    db: Session,
    *,
    org_id: object,
    document_id: object,
    field_id: object,
    actor: User,
    action: str,
    verified_value: str | None = None,
) -> ExtractionField:
    """Human field review (R3): confirm or correct one extracted field.

    - ``confirm``: the human asserts the extracted value is correct.
    - ``correct``: the human supplies the true value in ``verified_value``;
      the original extraction is preserved untouched.
    Only reviewer/org_admin may call this (route guard); the extracted
    ``field_value`` is never overwritten either way.
    """
    from app.modules.documents.service import get_document

    document = get_document(db, org_id=org_id, document_id=document_id)

    # The field must exist in this org AND belong to THIS document (its
    # extraction result's document) — anything else is a 404, no existence
    # leak (docs/API.md §5.4).
    field = db.scalar(
        select(ExtractionField).where(
            ExtractionField.id == field_id,
            ExtractionField.organization_id == org_id,
        )
    )
    if field is None:
        raise AppError(ErrorCode.NOT_FOUND, "Extraction field not found.")
    result = db.get(ExtractionResult, field.extraction_result_id)
    if result is None or str(result.document_id) != str(document.id):
        raise AppError(ErrorCode.NOT_FOUND, "Extraction field not found.")

    now = datetime.now(timezone.utc)
    if action == "confirm":
        field.verification_status = ExtractionFieldVerificationStatus.CONFIRMED.value
    elif action == "correct":
        if not verified_value or not verified_value.strip():
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "correcting a field requires a non-empty verified_value.",
            )
        field.verification_status = ExtractionFieldVerificationStatus.CORRECTED.value
        field.verified_value = verified_value.strip()
    else:  # pragma: no cover — schema-level Literal guards this
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "action must be 'confirm' or 'correct'."
        )
    field.verified_by = actor.id
    field.verified_at = now
    db.commit()
    return field


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
