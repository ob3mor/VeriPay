# VeriPay — Implementation Plan

Status: plan v1 · 2026-10-17
Related: [ARCHITECTURE.md](ARCHITECTURE.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

## 0. Ground rules for every phase

- The docs in this set are the contract; implementation deviations require updating the docs in the same change.
- The business invariants (ARCHITECTURE §2 and the no-go list §8) override convenience; each phase below names the guardrails it must not break.
- Acceptance checks are commands **actually runnable on this dev machine** (Windows, cmd.exe, no Docker, no WSL, no cloud). Anything needing Docker/PostgreSQL/cloud is marked **[not runnable locally]** and belongs to CI / PROFILE A.
- Do not run `git commit` / `git push` — the owner reviews and commits.
- **Repo state (verified 2026-10-17 via `git status`/`git log`):** branch `main`, zero commits, `docs/` untracked — the owner should commit `docs/` **before** parallel implementation starts, so the contract itself is in version control.
- Other engineers own disjoint paths; follow the layout in ARCHITECTURE §3.1 and create files only in your area.

## 1. Phase overview

| Phase | Theme | Headline deliverables |
|---|---|---|
| 1 | Foundation & identity | Backend scaffold, `/api/v1/health`, auth (register/login/me), `organizations`+`users` migration, tenancy infra, **audit facade (logging; DB persistence in Phase 6)**, storage seam (protocol + local provider), frontend scaffold (static export) |
| 2 | Ingestion & OCR | `documents`, `extracted_fields`; upload endpoint; MinIO storage provider; `OcrProvider` protocol + stub; confidence gate |
| 3 | Vendors & procurement | `vendors`, `vendor_trusted_accounts`, `purchase_orders`, `invoices`, `invoice_line_items`; vendor resolution; trusted-account verification workflow |
| 4 | Fraud & explainable risk | evidence retrieval; duplicate detection; features with provenance; `fraud_assessments` (EVC stays NULL); explanations |
| 5 | Cases & investigation | `cases`, `case_notes`; auto-open of critical assessments; close validation; investigation UI |
| 6 | Audit & reporting | `audit_logs` with event coverage for all prior actions; admin audit endpoint; dashboards |
| 7 | Deployment profiles | `deploy/docker-compose.yml` (PROFILE A, written — never executed locally); Azure SWA config (PROFILE B); runbooks |
| 8 | Hardening | full tenant-isolation matrix; security pass; performance smoke; docs finalization |

## 2. Phase 1 — Foundation & identity (expanded: today's concrete task list)

**Goal:** a walking skeleton — repo layout per ARCHITECTURE §3.1, health endpoint, working auth over `organizations`/`users`, tenancy plumbing, the storage seam, and a static-export frontend shell talking to the API.

**Tasks (order = dependency order; see the concurrency-hotspots paragraph after the checklist):**

1. **Backend scaffold** — `backend/` package + pinned dependencies; app factory `app/main.py`; `core/settings.py` (pydantic-settings: `DATABASE_URL`, `STORAGE_BACKEND`, `OCR_PROVIDER`, `JWT_SECRET`, token TTLs, `OCR_CONFIDENCE_THRESHOLD=0.85`); structured logging; CORS allowlist.
2. **Health endpoint** — `GET /api/v1/health` exactly per API.md §4.
3. **DB layer** — `db/base.py` declarative Base with naming conventions; portable-type conventions (DATABASE.md §1); engine/session (sync engine in Phase 1); an `OrgScopedMixin` providing `organization_id` + index + timestamps.
4. **Models + migration** — `organizations`, `users` models (DATABASE.md §4–5); Alembic init; migration `0001_core_identity` authored against PostgreSQL; validate **offline** with `alembic upgrade head --sql` [runnable]; a live `alembic upgrade head` against PostgreSQL is **[not runnable locally — no Docker]**.
5. **Auth module** — register (creates org + owner), login (OAuth2 form), me; argon2/bcrypt hashing; JWT claim contract `sub`, `org_id`, `role`, `exp` **frozen here** (task 6 and the frontend client consume it verbatim); login success/failure recorded **through the audit facade (task 8)** — the `audit_logs` table arrives in Phase 6 (§4 Sequencing).
6. **Tenancy infra** — `get_current_user` dependency; org-scoped query helper / base repository; the 404-on-cross-org helper (API.md §5).
7. **Error envelope + pagination helpers** — `core` exception handlers mapping validation/HTTP errors into the versioned envelope (API.md §2); `limit/offset` dependency + response envelope helper (API.md §3; exercised from Phase 2 on).
8. **Audit facade** — `modules/audit/` exposing `record(action, entity_type, entity_id, detail, actor)` that writes structured application logs using the `audit_logs.action` dotted-name vocabulary (DATABASE.md §15). Auth calls it from day 1; **no module logs around it**. Phase 6 swaps persistence to the `audit_logs` table behind the same interface — no call-site changes.
9. **Storage seam** — `StorageProvider` protocol + `LocalFilesystemProvider` + settings-based factory + the shared contract-test suite skeleton (MinIO implementation lands in Phase 2).
10. **Frontend scaffold** — Next.js App Router with `output: 'export'` (ADR 0004); Tailwind + shadcn/ui init; TanStack Query provider; API client types generated from FastAPI's OpenAPI; `/login` page wired to the auth endpoints; placeholder dashboard behind a client-side guard. A generated **`openapi.json` snapshot is committed** with a drift test against the live schema, so typegen and static builds never need a running backend.
11. **Tests** — pytest on SQLite (`Base.metadata.create_all`): health, register→login→me happy paths, error-shape assertions (401/409/422 envelopes), JWT org-claim presence, audit-facade emissions on register/login.
12. **Deploy artifacts** — `deploy/docker-compose.yml` + `.env.example` **written with a header note that they are never executed on this machine** (owned by the deployment workstream; docs only reference them).
13. **Docs sync (solo, runs last)** — verify ARCHITECTURE/DATABASE/API/ADRs match what Phase 1 actually built; record deviations at the bottom of this file.

**Concurrency hotspots (file ownership):** tasks 1/2/7 all touch `app/main.py` + `app/core/*` (factory, router mounting, error envelope) — give them one owner or run them strictly sequentially; tasks 3/4 both own `app/db/*` and the Alembic env — one owner; task 5 freezes the JWT claim contract that task 10's client consumes — freeze first; task 8 (audit facade) must land before or with task 5 (auth calls it); tasks 11 (tests) and 13 (docs sync, solo) run **last**; tasks 9 (storage seam), 10 (frontend), and 12 (deploy) are safely parallel. The checklist invites parallel work — these are the hotspots to respect.

**Phase 1 acceptance checks (definition of done):**

| Check | Command | Runnable locally? |
|---|---|---|
| Backend tests green (SQLite) | `python -m pytest backend/tests -q` | **yes** |
| Migration SQL emits cleanly (offline) | `alembic -c backend/alembic.ini upgrade head --sql` | **yes** (offline only) |
| Migration executability smoke (model/migration drift) | `alembic -c backend/alembic.ini upgrade head` against a scratch SQLite file | **yes** (executability only — not a PG substitute) |
| OpenAPI snapshot drift | diff live `/api/v1/openapi.json` against the committed snapshot | **yes** |
| Live migration against PostgreSQL | `alembic upgrade head` with `DATABASE_URL` pointing at PG | **no — needs Docker/PG** |
| Frontend static export builds | `npm run build` in `frontend/` → `out/` produced | **yes** |
| Manual smoke | run `uvicorn app.main:app`, register→login→me via the login page | **yes** |
| Compose file valid | `docker compose -f deploy/docker-compose.yml config` | **no — Docker absent**; fallback: parse YAML with `python -c "import yaml,sys;yaml.safe_load(open('deploy/docker-compose.yml'))"` (this is a syntax check, **not** the compose check) |

**Guardrails Phase 1 must not break:** R1/R2 trivially (no payment/genuineness concepts exist yet — keep it that way); R5 groundwork only (the `verification_status` design in DATABASE.md §7).

### Today's checklist (Phase 1)

- [ ] backend scaffold + settings + logging + CORS
- [ ] `GET /api/v1/health`
- [ ] db Base + conventions + `organizations`/`users` models (portable types)
- [ ] Alembic init + `0001_core_identity` (+ offline `--sql` check)
- [ ] **audit facade (`modules/audit/`) — auth emits through it**
- [ ] auth register/login/me + versioned error envelope (+ JWT claim contract frozen; `POST /auth/refresh` reserved)
- [ ] tenancy dependency + org-scoped query helper
- [ ] pagination helper (dormant until Phase 2)
- [ ] `StorageProvider` protocol + `LocalFilesystemProvider` + contract-test skeleton
- [ ] frontend: static-export scaffold, shadcn/ui, TanStack Query, generated client, login page
- [ ] **openapi.json snapshot + drift test committed**
- [ ] pytest suite (health/auth/error shapes/facade emissions) green on SQLite
- [ ] `deploy/docker-compose.yml` written (header: never executed locally)
- [ ] docs cross-check + deviations recorded here (runs last)

## 3. Phases 2–8 (brief, mapped to deliverables + acceptance checks)

### Phase 2 — Ingestion & OCR
- **Deliverables:** migration `0002_documents` (`documents`, `extracted_fields`); `POST /documents` (multipart, mime/size allowlist, per-org sha256 dedup → 200-with-existing on re-upload); `MinIOS3Provider` passing the shared contract suite; `OcrProvider` protocol + `StubOcrProvider` (ARCHITECTURE §7.2); extraction service persisting fields with spans + confidence; document/field read endpoints; orchestration via FastAPI background tasks (queue later if needed) with **SQLite write serialization**: `PRAGMA busy_timeout` ≥ 5000 ms + WAL and a single-writer queue (or per-org lock) for OCR background writes, or the sync engine on Windows will hit `database is locked` (DATABASE.md §17); **re-extraction = upsert per `extraction_version`** (same version replaces in place, different versions coexist — DATABASE.md §12).
- **Acceptance:** upload→stub-OCR→fields round-trip test on SQLite + local storage; both storage providers pass the contract suite; **confidence-gate unit tests** (below-threshold / NULL confidence → `unverified_input`, never a mismatch — R3); re-extraction upsert test (same version → rows replaced, no 409); `python -m pytest backend/tests -q` green; `npm run build` static export green. Note for Phase 4: per-org document dedup means two distinct documents with identical bytes cannot exist, so duplicate detection uses `invoice_number_match`/`near_duplicate`/`field_overlap`, never content hash (DATABASE.md §14).
- **Guardrails:** R3 is the deliverable of this phase.

### Phase 3 — Vendors & procurement
- **Deliverables:** migration `0003_vendor_procurement` (**also adds `documents.vendor_id` and `vendor_trusted_accounts.verification_document_id`** — the `vendors` table does not exist yet in `0002`); vendors + trusted-account endpoints (create → `pending`); **human-only** `POST …/trusted-accounts/{id}/verify` requiring `verification_method` + `verification_reference`/`verification_document_id` (API.md §6); `POST …/{id}/revoke`; PO + invoice endpoints (**duplicate vendor+number intake is allowed**: 201 + `duplicate_matches` + `needs_review` — never 409, API.md §2); vendor resolution service (exact normalized → fuzzy → human confirm queue; no-match stays unresolved; resolution re-runs the duplicate-number check and records hits); invoice↔document binding (incl. vendor context for bank letters via `documents.vendor_id`).
- **Acceptance:** resolution tests (exact / fuzzy / unresolved); **partial-index contract test: one current + one historical trusted account coexist on SQLite** — this guards the `postgresql_where` + `sqlite_where` pair, and with only `postgresql_where` it fails with `IntegrityError` (reviewer-verified); duplicate-number intake test (second invoice, same vendor+number → 201 + `duplicate_matches` row + `needs_review`, **not** 409); verify-endpoint test proves machine/auto verification is impossible (missing method → 422 `business_rule_violation` — R5); missing-PO represented as a neutral gap, not fraud (R4 groundwork).
- **Guardrails:** R5 is the deliverable of this phase.

### Phase 4 — Fraud & explainable risk
- **Deliverables:** migration `0004_fraud` (`fraud_assessments`, `duplicate_matches`); evidence retrieval service (PO match, trusted accounts + verification status incl. `verification_document_id`, vendor history, `documents.vendor_id` history); duplicate detection (`invoice_number_match` + `near_duplicate` + `field_overlap` — no content hash, DATABASE.md §14); feature computation with full input provenance (**invoice columns are source of truth; `invoices.field_sources` decides gate applicability** — ARCHITECTURE §8.3); assessment writer (`risk_level`, `risk_score`, `signals` with the ARCHITECTURE-§8 severities, ordered `explanation`, `feature_snapshot`; **`evc` stays NULL** — Phase 4 later refines the EVC concept itself); `POST /invoices/{id}/assess` + latest-assessment read; the mandatory-case obligation for `critical` assessments is **derived on read** (critical without a case = unmet obligation — no transient marker to lose on restart); the `fraud → cases` edge and backfill are wired in Phase 5.
- **Acceptance:** E2E test: invoice total tampered vs PO → `high`/`critical` assessment with ordered explanations; **R5 signal tests:** remittance matching a `pending`/`failed`/`revoked` account → `bank_account_unverified` (`high`) + `needs_review`; remittance with **no accounts on file** → `missing_evidence` (≤ `medium`) **and** `bank_account_unverified` (`high`) — reconciling ARCHITECTURE §8.4/§8.5; remittance matching a `verified` account → no `bank_account_unverified`; **R3 input-contract tests:** manual invoice (`origin: "manual"`) is computable, stub-extracted invoice is `unverified_input` (stub output can never pass the gate), invoice-column-vs-provenance disagreement → `field_provenance_conflict` with the column winning; missing-PO invoice → `missing_evidence`, severity ≤ `medium` (**R4 test**); duplicate detection tests with the §14 vocabulary; critical-assessment-without-case is detectable on read; snapshot test asserting features → signals → explanation chain is recorded; no `is_fraud`/`is_genuine` anywhere (**R2 check**).
- **Guardrails:** R2 and R4.

### Phase 5 — Cases & investigation
- **Deliverables:** migration `0005_cases` (incl. `cases.triggering_assessment_id`); case endpoints (list/get/assign/notes/close) per API.md §6; **auto-open wiring** from critical assessments + backfill of the **derived-on-read set** (critical assessments without a case), each case recording `triggering_assessment_id`; close validation (outcome + `resolution_summary` mandatory — DB CHECK + service); investigation UI: case list/detail, evidence panel (document preview, extracted fields with spans + confidence badges, trusted accounts with verification status + supporting document), verify-OCR-field action, verify-bank-account flow.
- **Acceptance:** integration test: critical assessment ⇒ case exists (R6); close-without-outcome → 422; case+assessment composed view anchored on `triggering_assessment_id` (fallback: latest) served by `api` without a `cases → fraud` import (dependency-rule test); frontend build green.
- **Guardrails:** R6 is the deliverable of this phase.

### Phase 6 — Audit & reporting
- **Deliverables:** migration `0006_audit` (`audit_logs`); the `audit` facade (Phase 1) **swaps persistence to the table behind the same `record(...)` interface** — no call-site changes anywhere; event coverage for **all** state-changing actions from Phase 6 on (pre-Phase-6 history lives in app logs — best-effort backfill only, documented); audit list endpoint (owner/admin only per the API.md role matrix, paginated, tenant-isolated); dashboards (assessments by risk, open cases, SLA).
- **Acceptance:** parametrized test: every state-changing endpoint writes an audit row; audit endpoint isolation test; dashboard static-export build green.
- **Guardrails:** the full trail underpinning R5/R6 review; closes the Phase-1 audit gap for *future* events (historical backfill is best-effort from app logs — documented, not guaranteed).

### Phase 7 — Deployment profiles
- **Deliverables:** finalize `deploy/docker-compose.yml` (PROFILE A: postgres, minio + mc init, backend, frontend) — **written, never run locally**; PROFILE B: Azure SWA config for `frontend/out`, backend compute + Azure PG Flexible Server checklist, secrets handling, CORS origins, runbook docs — **the runbook must record the actual monthly cost against the student cap** (reviewer estimate: App Service B1 + PG B1ms ≈ $26–30/mo, which can exceed $20; prefer scale-to-zero compute — Azure Container Apps consumption free grant — or demo-only start/stop).
- **Acceptance:** compose YAML parses (`python -c "import yaml; yaml.safe_load(...)"` — syntax only); SWA config reviewed against ADR 0004; **explicitly no cloud provisioning performed** (no `az`, no paid services).

### Phase 8 — Hardening
- **Deliverables:** tenant-isolation matrix test across **all** resources (rule 6 of API.md §5, complete); security review (JWT handling, upload sniffing beyond mime allowlist, PII minimization in logs, ORM-only SQL surface); performance smoke on a synthetic 1k-invoice dataset; final docs pass; release checklist.
- **Acceptance:** full pytest suite green; threat-model review recorded against ARCHITECTURE §8 line by line; all phase acceptance commands re-run and their outputs recorded.

## 4. Sequencing & dependency notes

- **audit_logs (Phase 6) after the audit facade (Phase 1):** the facade exists from day 1 so every module emits events with the final vocabulary; until Phase 6 they land in structured application logs — Phase 6 swaps persistence behind the same interface (no retrofit, no call-site churn).
- **fraud (Phase 4) before cases (Phase 5):** the only cross-module trigger edge (`fraud → cases`) is wired in Phase 5; the Phase 4–5 obligation is **derived on read** (critical assessment without a case = unmet obligation), and Phase 5 opens cases and backfills exactly that set.
- **Storage seam in Phase 1** so that `documents` (Phase 2) never touches the filesystem directly (dependency rule D3).
- **Alembic targets PostgreSQL throughout**; every migration is validated offline on this machine; the first live `upgrade head` happens under PROFILE A/CI — **[not runnable locally]**.

## 5. Recorded deviations

- **Phase 1 — audit persistence arrived early (healthy deviation):** `audit_logs` was planned for Phase 6, but the Phase 1 build persisted the facade straight to the `audit_logs` table behind the unchanged `record_audit(...)` interface (migration `0006_audit` included; openapi/tests cover it). The Phase 6 swap therefore reduces to event-coverage work, not a persistence change.
- **Phase 1 — auth shipped beyond plan (healthy deviation):** logout with server-side `jti` revocation, per-IP throttling and per-(IP, email) failed-login lockout landed in Phase 1 (`core/ratelimit.py`, `core/token_store.py`), ahead of the API.md §4 reservation.
- **Phase 1 — role vocabulary unresolved at review time:** the API.md §5 matrix named a `viewer` role that neither code nor DATABASE.md defined. Superseded in Phase 2 by the owner's canonical role set (Organization Admin, Finance Officer, Reviewer, Auditor).


### Phase 2 — Secure backend & data layer (owner's brief; DONE 2026-10-17)

- Deliverables: canonical v2 models + squashed `0001_full_schema`; cookie
  sessions + CSRF + refresh + RBAC (4 roles); rate-limited auth with lockout;
  vendors/contacts/bank-accounts/change-requests (R5 human-only approval);
  document ingestion (magic bytes, size, SHA-256 dedup, tenant storage,
  protected downloads); processing state machine + ProcessingBackend seam
  (inline default, Celery optional); procurement + duplicate-as-signal intake;
  deterministic explainable fraud assessments (rules-v0.1, EVC stays NULL);
  investigation cases + review actions (R6); audit-events endpoint;
  OpenAPI snapshot regenerated; Docker image migrates before serving; CI
  workflow; frontend moved to cookie+CSRF sessions with zero web storage.
- Acceptance run: live end-to-end flow (register → login → vendor → approved
  bank account → change request → PO → invoice upload → assess) executed via
  HTTP on this machine; 72/72 pytest; frontend build green.
- Guardrails: R1-R6 honored (no auto-approval code path exists; invoices never
  approve accounts; EVC NULL; no genuineness vocabulary anywhere).
