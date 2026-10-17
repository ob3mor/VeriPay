"""Durable processing state machine + idempotent job orchestration.

State machine (docs/DATABASE.md — processing_jobs):

    pending → processing → completed | failed | requires_manual_input
    failed  → pending           (retry, guarded by max_attempts)
    requires_manual_input → pending  (after a human supplies input)

Every transition goes through :func:`transition` — nothing else writes the
status column, so an invalid jump is impossible. Retries are idempotent:
:func:`enqueue` dedupes on (organization_id, job_type, idempotency_key) and
returns the existing job instead of duplicating work.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import JobType, ProcessingStatus
from app.core.errors import AppError, ErrorCode
from app.models import ProcessingJob

_ALLOWED: dict[str, set[str]] = {
    ProcessingStatus.PENDING.value: {ProcessingStatus.PROCESSING.value},
    ProcessingStatus.PROCESSING.value: {
        ProcessingStatus.COMPLETED.value,
        ProcessingStatus.FAILED.value,
        ProcessingStatus.REQUIRES_MANUAL_INPUT.value,
    },
    ProcessingStatus.FAILED.value: {ProcessingStatus.PENDING.value},
    ProcessingStatus.REQUIRES_MANUAL_INPUT.value: {ProcessingStatus.PENDING.value},
    ProcessingStatus.COMPLETED.value: set(),
}


def transition(db: Session, job: ProcessingJob, new_status: str, *, error: str | None = None) -> ProcessingJob:
    """Guarded state transition — the ONLY writer of ProcessingJob.status."""
    allowed = _ALLOWED.get(job.status, set())
    if new_status not in allowed:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            f"Cannot transition job from {job.status} to {new_status}.",
        )
    job.status = new_status
    if new_status == ProcessingStatus.PROCESSING.value:
        job.started_at = datetime.now(timezone.utc)
        job.attempts += 1
    elif new_status in (
        ProcessingStatus.COMPLETED.value,
        ProcessingStatus.FAILED.value,
        ProcessingStatus.REQUIRES_MANUAL_INPUT.value,
    ):
        job.completed_at = datetime.now(timezone.utc)
        job.last_error = error
    db.commit()
    return job


def get_job(db: Session, *, org_id: object, job_id: object) -> ProcessingJob:
    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.organization_id == org_id
        )
    )
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "Processing job not found.")
    return job


def find_job_by_key(
    db: Session, *, org_id: object, job_type: str, idempotency_key: str
) -> ProcessingJob | None:
    return db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.organization_id == org_id,
            ProcessingJob.job_type == job_type,
            ProcessingJob.idempotency_key == idempotency_key,
        )
    )


def enqueue(
    db: Session,
    *,
    org_id: object,
    job_type: JobType,
    idempotency_key: str,
    document_id: object | None = None,
    invoice_id: object | None = None,
    max_attempts: int = 3,
) -> tuple[ProcessingJob, bool]:
    """Create (or idempotently return) a job row.

    Returns (job, created). A FAILED job with attempts left is reset to
    pending (retry); an exhausted FAILED job raises 422; a COMPLETED job is
    returned as-is. The caller decides whether to ``submit`` after commit.
    """
    existing = find_job_by_key(
        db, org_id=org_id, job_type=job_type.value, idempotency_key=idempotency_key
    )
    if existing is not None:
        if existing.status == ProcessingStatus.FAILED.value:
            if existing.attempts >= existing.max_attempts:
                raise AppError(
                    ErrorCode.BUSINESS_RULE_VIOLATION,
                    "This job failed and exhausted its retry budget.",
                )
            transition(db, existing, ProcessingStatus.PENDING.value)
        return existing, False

    job = ProcessingJob(
        organization_id=org_id,
        job_type=job_type.value,
        idempotency_key=idempotency_key,
        document_id=document_id,
        invoice_id=invoice_id,
        max_attempts=max_attempts,
        backend=get_settings().processing_backend,
        status=ProcessingStatus.PENDING.value,
    )
    db.add(job)
    db.commit()
    return job, True


def claim_job_by_id(db: Session, job_id: object) -> ProcessingJob:
    """System-context lookup for worker processes (no org filter — the worker
    is trusted infrastructure; the API surface never uses this path)."""
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "Processing job not found.")
    return job


def run_job(db: Session, job: ProcessingJob, fn: Callable[[Session, ProcessingJob], None]) -> ProcessingJob:
    """Claim and execute one job, recording the outcome durably.

    Any exception transitions the job to FAILED with the error message (trun-
    cated; never includes secrets — callers pass plain engineering messages).
    """
    transition(db, job, ProcessingStatus.PROCESSING.value)
    try:
        fn(db, job)
    except Exception as exc:  # noqa: BLE001 — the failure IS the durable record
        message = f"{type(exc).__name__}: {exc}"[:500]
        transition(db, job, ProcessingStatus.FAILED.value, error=message)
        raise
    transition(db, job, ProcessingStatus.COMPLETED.value)
    return job
