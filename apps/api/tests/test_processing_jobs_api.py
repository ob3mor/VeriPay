"""Processing-job reads + retry-budget enforcement — the auditor's untested
branches (standalone job reads, exhausted-retry 422, failed→retry→completed)."""

import io
import uuid

import pytest

from app.core.enums import JobType, ProcessingStatus
from app.models import ProcessingJob
from app.modules.extraction import service as extraction_service
from app.modules.processing import service as processing
from helpers import db_query, register
from role_helpers import register_second_org

PDF_BYTES = b"%PDF-1.4\njob api test\n"


def _upload(client):
    return client.post(
        "/api/v1/documents",
        files={"file": ("job.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )


def test_job_read_is_org_scoped(client):
    assert register(client).status_code == 201
    upload = _upload(client)
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    assert job_id

    job = client.get(f"/api/v1/processing-jobs/{job_id}")
    assert job.status_code == 200
    body = job.json()
    assert body["job_type"] == JobType.OCR_EXTRACTION.value
    assert body["status"] == ProcessingStatus.COMPLETED.value
    assert body["attempts"] == 1
    assert body["backend"] == "inline"

    # Another org's read is a 404 (no existence leak).
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    assert client.get(f"/api/v1/processing-jobs/{job_id}").status_code == 404


def _seed_exhausted_job(client, document_id: str) -> str:
    """Force the document's inline job into the exhausted-failed state (raw
    seed: simulates a failed run history; the guarded machine itself is
    tested in test_processing_idempotent.py)."""

    def _seed(session):
        from app.models import Document

        doc = session.get(Document, uuid.UUID(document_id))
        job = (
            session.query(ProcessingJob)
            .filter_by(
                organization_id=doc.organization_id,
                job_type=JobType.OCR_EXTRACTION.value,
                idempotency_key=f"ocr:{doc.id}:{extraction_service.EXTRACTION_VERSION}",
            )
            .first()
        )
        assert job is not None, "the inline upload job must exist"
        job.status = ProcessingStatus.FAILED.value
        job.attempts = 3
        job.max_attempts = 3
        job.last_error = "RuntimeError: synthetic exhaustion"
        session.commit()
        return str(job.id)

    return db_query(_seed)


def test_retry_budget_exhaustion_is_422(client):
    """A FAILED job with no attempts left must refuse re-enqueueing with the
    documented business_rule_violation (processing/service.py enqueue)."""
    assert register(client).status_code == 201
    document = _upload(client).json()
    _seed_exhausted_job(client, document["id"])

    response = client.post(f"/api/v1/documents/{document['id']}/process")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "business_rule_violation"
    assert "retry budget" in error["message"].lower()


def test_failed_job_retries_then_completes(client):
    """failed → (re-enqueue resets to pending) → completed, on the durable
    state machine — attempts recorded per run."""
    assert register(client).status_code == 201

    def _seed(session):
        from app.models import Organization

        org = Organization(name="retry-org", slug="retry-org")
        session.add(org)
        session.flush()
        job = ProcessingJob(
            organization_id=org.id,
            job_type=JobType.OCR_EXTRACTION.value,
            idempotency_key="retry-key-1",
            max_attempts=3,
        )
        session.add(job)
        session.commit()
        return str(job.id), str(org.id)

    job_id, org_id = db_query(_seed)

    def _fail(session):
        job = session.get(ProcessingJob, uuid.UUID(job_id))
        processing.run_job(session, job, _raise_boom)

    with pytest.raises(RuntimeError):
        db_query(_fail)

    def _state(session):
        job = session.get(ProcessingJob, uuid.UUID(job_id))
        return job.status, job.attempts

    assert db_query(_state) == (ProcessingStatus.FAILED.value, 1)

    # Re-enqueue with the same key: attempts remain → reset to pending.
    def _reenqueue(session):
        job, created = processing.enqueue(
            session,
            org_id=uuid.UUID(org_id),
            job_type=JobType.OCR_EXTRACTION,
            idempotency_key="retry-key-1",
        )
        return job.status, created

    status, created = db_query(_reenqueue)
    assert created is False
    assert status == ProcessingStatus.PENDING.value

    # A clean run completes it (attempt #2).
    def _complete(session):
        job = session.get(ProcessingJob, uuid.UUID(job_id))
        processing.run_job(session, job, lambda _s, _j: None)
        return job.status, job.attempts

    status, attempts = db_query(_complete)
    assert status == ProcessingStatus.COMPLETED.value
    assert attempts == 2


def _raise_boom(_session, _job):
    raise RuntimeError("boom")
