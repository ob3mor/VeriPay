"""Optional Celery processing backend (PROFILE A 'worker' profile).

HONEST STATUS: implemented and import-checked on the development machine, but
NOT executed end-to-end — no Redis/Celery broker exists there (no Docker).
It activates only when VERIPAY_PROCESSING_BACKEND=celery with a live broker
(compose 'worker' profile). The inline backend remains the default and the
only path the cloud demo uses (scale-to-zero, no always-on worker).

Design: the durable state stays in processing_jobs regardless of backend —
Celery carries only the job id as the wake-up signal; the worker claims the
row through the same guarded state machine, so a lost or duplicated broker
message cannot corrupt state (idempotency comes from the DB, not the broker).
"""

from __future__ import annotations

import os

from app.adapters.processing.base import JobFunction

try:  # celery is an optional dependency (pyproject: celery extra)
    from celery import Celery
except ImportError:  # pragma: no cover - exercised only with the extra
    Celery = None  # type: ignore[assignment]

BROKER_URL = os.environ.get("VERIPAY_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("veripay", broker=BROKER_URL, backend=BROKER_URL) if Celery else None

if celery_app is not None:  # pragma: no branch
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        # A message may arrive twice (broker redelivery): the worker's claim
        # is guarded by the state machine, so duplicates are no-ops.
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )


def _run_job_in_new_session(job_id: str) -> None:
    """Claim and run the job row in a fresh session (worker context)."""
    import uuid as _uuid

    from app.core.db import SessionLocal
    from app.modules.extraction import service as extraction_service
    from app.modules.processing.service import claim_job_by_id, run_job

    with SessionLocal() as session:
        job = claim_job_by_id(session, _uuid.UUID(job_id))
        if job.job_type == "ocr_extraction" and job.document_id is not None:
            fn = lambda s, j: extraction_service.run_extraction(  # noqa: E731
                s, org_id=j.organization_id, document_id=j.document_id
            )
        else:
            raise ValueError(f"No worker implementation for job_type={job.job_type!r}")
        run_job(session, job, fn)


if celery_app is not None:  # pragma: no cover - requires a broker

    @celery_app.task(name="veripay.process_job", bind=True, max_retries=3)
    def process_job(self, job_id: str) -> str:  # type: ignore[misc]
        try:
            _run_job_in_new_session(job_id)
        except Exception as exc:  # noqa: BLE001 — broker-level retry
            raise self.retry(exc=exc, countdown=5)
        return job_id


class CeleryBackend:
    """Enqueues the persisted job's id onto the broker (state stays in DB)."""

    name = "celery"

    def submit(self, db, job, fn: JobFunction) -> None:  # noqa: ANN001
        if celery_app is None:
            raise RuntimeError(
                "celery is not installed — use the inline backend or install "
                "the 'celery' extra."
            )
        process_job.delay(str(job.id))
