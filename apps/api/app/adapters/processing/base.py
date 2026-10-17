"""ProcessingBackend seam — WHERE jobs execute (docs/ARCHITECTURE.md §7.3).

The durable state lives in ``processing_jobs`` regardless of backend; the
backend only decides the execution context:

- ``InlineBackend`` (default): executes synchronously in the request after
  commit. Used by the no-Docker dev profile and the scale-to-zero Azure demo
  — no always-on worker, no fire-and-forget (the job row records everything).
- ``CeleryBackend`` (optional PROFILE A): enqueues onto Redis/Celery; a
  worker process claims jobs by id. Implemented in adapters/processing/celery_backend.py
  and exercised only when a Redis instance exists.
- Future cloud mechanism (e.g. Azure Functions on queue trigger) implements
  the same protocol without touching modules.
"""

from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

# The unit of work: run(session, job_row) -> None. Implementations raise on
# failure; the caller records the error and transitions the job to failed.
JobFunction = Callable[[Session, object], None]


class ProcessingBackend(Protocol):
    name: str

    def submit(self, db: Session, job: object, fn: JobFunction) -> None:
        """Schedule ``fn`` for the persisted ``job``. Called AFTER commit.
        Must not lose the job: on backend failure the caller falls back to
        inline execution or leaves the job pending for retry."""
        ...


class InlineBackend:
    """Executes the job synchronously in-request (after commit).

    Deliberate choice for the free-tier profiles: processing state is durable
    (the job row), execution is simple, and nothing depends on an always-on
    worker. Long OCR work would block the request — acceptable at demo scale;
    swap via settings.processing_backend without module changes.
    """

    name = "inline"

    def submit(self, db: Session, job: object, fn: JobFunction) -> None:
        from app.modules.processing.service import run_job

        # A NEW session: the request session committed the job row already;
        # the run must see it and must survive request-scope rollbacks.
        run_job(db, job, fn)


def build_backend(name: str) -> ProcessingBackend:
    if name == "inline":
        return InlineBackend()
    if name == "celery":
        from app.adapters.processing.celery_backend import CeleryBackend

        return CeleryBackend()
    raise ValueError(f"Unknown processing backend: {name!r}")
