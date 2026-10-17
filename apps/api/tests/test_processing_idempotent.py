"""Processing state machine: idempotency and guarded transitions."""

import io

import pytest

from app.core.enums import JobType, ProcessingStatus
from app.modules.processing import service as processing
from helpers import db_query, register

PDF_BYTES = b"%PDF-1.4\nprocessing test\n"


def _upload(client):
    return client.post(
        "/api/v1/documents",
        files={"file": ("doc.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )


def test_reprocess_is_idempotent_same_job_row(client):
    assert register(client).status_code == 201
    document_id = _upload(client).json()["id"]

    first = client.post(f"/api/v1/documents/{document_id}/process")
    second = client.post(f"/api/v1/documents/{document_id}/process")
    assert first.status_code == 200 and second.status_code == 200
    # Same idempotency key â†’ the SAME durable job row, not a duplicate.
    assert first.json()["job_id"] == second.json()["job_id"]


def _make_job(org_slug: str, key: str) -> object:
    def create(session):
        from app.models import Organization, ProcessingJob

        org = Organization(name=org_slug, slug=org_slug)
        session.add(org)
        session.flush()
        job = ProcessingJob(
            organization_id=org.id,
            job_type=JobType.OCR_EXTRACTION.value,
            idempotency_key=key,
        )
        session.add(job)
        session.commit()
        return job.id

    return db_query(create)


def test_transitions_are_guarded(client):
    from app.models import ProcessingJob

    assert register(client).status_code == 201
    job_id = _make_job("transitions", "k1")

    # pending â†’ completed is INVALID (must pass through processing).
    def illegal_jump(session):
        processing.transition(
            session, session.get(ProcessingJob, job_id), ProcessingStatus.COMPLETED.value
        )

    with pytest.raises(Exception):
        db_query(illegal_jump)

    # The legal path works and records attempts.
    def legal(session):
        job = session.get(ProcessingJob, job_id)
        processing.transition(session, job, ProcessingStatus.PROCESSING.value)
        processing.transition(session, job, ProcessingStatus.COMPLETED.value)
        return job.status, job.attempts

    status, attempts = db_query(legal)
    assert status == ProcessingStatus.COMPLETED.value
    assert attempts == 1

    # completed is terminal.
    def after_terminal(session):
        processing.transition(
            session, session.get(ProcessingJob, job_id), ProcessingStatus.PENDING.value
        )

    with pytest.raises(Exception):
        db_query(after_terminal)
