"""Processing-job reads — durable state-machine rows, org-scoped.

Jobs were previously only embedded in document responses; the standalone read
lets an operator inspect a job's retry budget, status history and last error
directly (docs/DATABASE.md — processing_jobs). Writes stay behind the document
endpoints (upload/process); jobs are never created or mutated here.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routes import _domain_schemas as ds
from app.core.db import get_db
from app.models import User
from app.modules.processing import service as processing_service
from app.tenancy.deps import get_current_user

router = APIRouter(prefix="/processing-jobs", tags=["processing"])

_Db = Annotated[Session, Depends(get_db)]


def _job_out(job) -> ds.ProcessingJobOut:
    return ds.ProcessingJobOut(
        id=job.id,
        job_type=job.job_type,
        document_id=job.document_id,
        invoice_id=job.invoice_id,
        idempotency_key=job.idempotency_key,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=job.last_error,
        backend=job.backend,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.get("/{job_id}", response_model=ds.ProcessingJobOut)
def get_processing_job(
    job_id: uuid.UUID,
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> ds.ProcessingJobOut:
    """One job of the caller's organization; cross-org ids are 404."""
    return _job_out(
        processing_service.get_job(db, org_id=actor.organization_id, job_id=job_id)
    )
