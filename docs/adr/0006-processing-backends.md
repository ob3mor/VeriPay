# ADR 0006: Durable processing jobs + selectable ProcessingBackend

Date: 2026-10-17 · Status: accepted (Phase 2)

## Context

OCR extraction and future fraud scans must be **durable** (state survives
restarts, retryable, inspectable), retries must be **idempotent**, and the
cloud demo **must not depend on an always-on paid queue or fire-and-forget
in-process tasks**. Local PROFILE A may use Redis/Celery.

## Decision

- Every unit of asynchronous work is a `processing_jobs` row with a guarded
  state machine (`pending → processing → completed | failed |
  requires_manual_input`; `failed → pending` retry; terminal `completed`).
  The ONLY writer of the status column is `processing.service.transition`.
- **Idempotency**: `uq (organization_id, job_type, idempotency_key)` —
  re-enqueueing returns the existing job; a failed job with retry budget
  resets to pending; an exhausted job is refused (422).
- **ProcessingBackend seam** (`adapters/processing/base.py`): `InlineBackend`
  (default — executes in-request after commit; zero infrastructure, the
  scale-to-zero cloud path), `CeleryBackend` (optional PROFILE A worker over
  Redis; honest status: implemented, not executed without a broker). Future
  cloud mechanisms implement the same protocol without module changes.

## Consequences

- Upload → process → status is fully observable through the API.
- The Azure demo needs no worker and no queue spend.
- Inline execution blocks the request during OCR — acceptable at demo scale
  with the stub provider; real engines switch the backend via settings only.
