# ADR 0001 — Modular monolith

Status: Accepted · 2026-10-17

## Context

VeriPay is an early-stage product with a small team. The fraud pipeline (ingestion → extraction → resolution → evidence → assessment → cases → audit) needs strong transactional consistency across steps, and the deployment targets (single backend container; Azure student budget; no local Docker) favor few moving parts. Microservices would add network, deployment, and observability cost before there is any scale or organizational pressure to justify it.

## Decision

Build one FastAPI service — a **modular monolith**:

- Internal modules (`auth`, `documents`, `extraction`, `vendors`, `procurement`, `evidence`, `fraud`, `cases`, `audit`) live in `backend/app/modules/` with enforced dependency rules (ARCHITECTURE §5, D1–D5): `core`/`db` are leaves everyone may use; adapters are leaves only modules may use via protocols; no module imports `api`; `api/v1` composes only; `audit` is a universal leaf.
- Cross-module triggers are explicit, one-way edges — the only one today is `fraud → cases`.
- One database schema owned by the monolith; no external writers.

## Consequences

**Positive:** single deploy artifact; local transactions across the whole workflow; cheap cross-boundary refactors while the product's shape is still moving; the module boundaries are the seam along which a service could later be extracted.

**Negative:** boundary discipline depends on review now and an import linter later; scaling is whole-service; extracting a module (e.g. an OCR worker) will require an out-of-process seam — the provider-agnostic adapter pattern (ADR 0003) already models it.
