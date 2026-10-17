# VeriPay — Architecture

Status: design v1 · 2026-10-17
Related: [DATABASE.md](DATABASE.md) · [API.md](API.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · [ADRs](adr/0001-modular-monolith.md)

## 1. What VeriPay is

VeriPay is an AI-assisted invoice and payment-fraud **prevention** platform for finance and procurement teams. It ingests invoices and supporting documents (purchase orders, bank letters), extracts structured fields with OCR, resolves vendors, retrieves corroborating evidence, computes **explainable** fraud signals, and routes critical inconsistencies to human investigators with a full audit trail.

VeriPay is a **decision-support system, not a payment system**. Its output is evidence, explanations, and review workflow — never money movement, and never a claim that an invoice is genuine. The six business invariants (§2) are normative for every design and implementation decision; the "what is never automated" list (§8) is the checklist every change is reviewed against.

## 2. Business invariants (normative)

| # | Invariant | Where it is enforced in this design |
|---|-----------|-------------------------------------|
| R1 | Never authorize payments automatically | No payment-rail integration exists anywhere in the module map (§5); the terminal workflow state is a human decision made **outside** VeriPay (§8.1). |
| R2 | Never claim an invoice is genuine | No `is_genuine`/`is_fraud` field in the schema (DATABASE.md §fraud_assessments); assessments carry signals + explanations + residual uncertainty only (§8.2). |
| R3 | Uncertain OCR must not become confident fraud evidence | `extracted_fields.confidence` + human `verification_status` are first-class (DATABASE.md §extracted_fields); fraud features gate on confidence (§8.3). |
| R4 | Missing records are not proof of fraud | Absence findings are typed `missing_evidence` with severity capped at `medium` (§8.4). |
| R5 | A new bank account requires independent verification | `vendor_trusted_accounts.verification_status` defaults to `pending`; only a human can set `verified`, and only with `verification_method` + `verification_reference` (DATABASE.md §vendor_trusted_accounts, §8.5). |
| R6 | Human review is mandatory for critical inconsistencies | A `critical` assessment always auto-opens a case; cases cannot close without a human outcome + resolution summary (§8.6, `cases` module). |

## 3. System overview

The backend is a **modular monolith** (ADR [0001](adr/0001-modular-monolith.md)): one FastAPI application, internal module boundaries, one database schema, and provider-agnostic adapter seams (ADR [0003](adr/0003-provider-agnostic-adapters.md)). PostgreSQL is the canonical database; SQLite is the dev/test fallback on machines without Docker (ADR [0002](adr/0002-postgres-canonical-sqlite-dev-fallback.md)). The frontend is a **statically exported Next.js app** (ADR [0004](adr/0004-static-export-frontend.md)) talking to the API over REST.

```
                ┌──────────────────────────────────┐
                │  Next.js App Router, static      │
                │  export (SWA Free / next dev)    │
                └───────────────┬──────────────────┘
                                │  REST /api/v1  (Bearer JWT)
                ┌───────────────▼──────────────────┐
                │   FastAPI modular monolith       │
                │   api/v1 ──► modules ──► seams   │
                └──────┬──────────────────┬────────┘
        SQLAlchemy 2   │                  │  StorageProvider / OcrProvider
   (portable types)    │                  │  (protocol seams, ADR 0003)
        ┌──────────────▼───────┐  ┌───────▼────────────────────┐
        │ PostgreSQL (canonical)│  │ local filesystem (default) │
        │ SQLite (dev/test fb)  │  │ MinIO/S3 (PROFILE A)       │
        └───────────────────────┘  │ Azure Blob (PROFILE B, tbd)│
                                   └────────────────────────────┘
```

### 3.1 Repository layout (as built)

```
VeriPay/
├── apps/
│   ├── api/                        # FastAPI backend (Python 3.12, uvicorn)
│   │   ├── app/
│   │   │   ├── main.py             # FastAPI factory: CORS, request-id, CSRF middleware
│   │   │   ├── core/               # settings, errors, security, ratelimit, csrf, db
│   │   │   ├── models/             # SQLAlchemy 2 models, canonical v2 vocabulary
│   │   │   ├── tenancy/            # deps.py (bearer+cookie identity), permissions.py (RBAC)
│   │   │   ├── adapters/
│   │   │   │   ├── storage/        # StorageProvider: local (default) + MinIO/S3
│   │   │   │   ├── ocr/            # OcrProvider protocol + stub (real engines later)
│   │   │   │   └── processing/     # ProcessingBackend: inline (default) + Celery (optional)
│   │   │   ├── modules/            # auth(+sessions), vendors, documents, processing,
│   │   │   │                       # extraction, procurement, fraud(+evidence), cases, audit
│   │   │   └── api/v1/             # routers only (composition — D4)
│   │   ├── alembic/                # 0001_full_schema (single squashed migration)
│   │   ├── tests/                  # 72 pytest tests on SQLite (WAL file)
│   │   └── Dockerfile              # migrates then serves (PROFILE A)
│   └── web/                        # Next.js App Router, output:'export' (ADR 0004)
├── packages/api-contracts/         # TS mirrors of the REST contract
├── infrastructure/local/           # docker-compose (PROFILE A)
├── scripts/                        # dev-up / dev-down
└── docs/                           # this documentation set + ADRs
```

Phase 2 additions to the module map: `processing` (durable jobs + ProcessingBackend
seam, ADR 0006), auth sessions (durable cookie sessions + CSRF, ADR 0005), and the
canonical v2 model vocabulary (ADR 0007). The business invariants (§2) and the
no-go list (§8) are unchanged and normative.

## 4. The 8-step functional workflow

The pipeline is: **upload → ingestion → OCR/extraction → vendor resolution → evidence retrieval → fraud features → explainable risk → human investigation → audit**, documented here as 8 steps, with upload and ingestion as the two halves of step 1 (intake).

| Step | Name | What happens | Modules | Writes (tables) |
|---|---|---|---|---|
| 1 | Upload & ingestion | Analyst uploads a document (invoice, PO, bank letter). API validates type/size, computes sha256, stores bytes via `StorageProvider`, records the `documents` row. | `documents`, `adapters.storage` | documents |
| 2 | OCR / extraction | `OcrProvider` produces text, blocks, bounding boxes, per-block confidence. Extraction normalizes this into named fields with **evidence spans and confidence**; humans may later confirm/correct fields. | `adapters.ocr`, `extraction` | documents (ocr_status), extracted_fields |
| 3 | Vendor resolution | Extracted vendor identity (name, tax id) is matched against the registry: exact normalized match → fuzzy match → human confirmation. Unresolved vendors stay unresolved — never guessed. At resolution the service re-runs the duplicate-number check against prior invoices and records `duplicate_matches` rows for any hit — catching duplicates that arrived before the vendor was resolved (behavior identical to intake, DATABASE.md §9). | `vendors` | vendors (new pending vendor), invoices.vendor_id, duplicate_matches |
| 4 | Evidence retrieval | For the resolved invoice: matching POs, the vendor's **trusted accounts and their verification status** (with their supporting `verification_document_id`), the vendor's invoice history, and the vendor's document history via `documents.vendor_id` (added in migration 0003). Read-only aggregation, every item carrying provenance. | `evidence` | (reads only) |
| 5 | Fraud features | Feature computation from evidence: amount vs PO, duplicate detection (→ `duplicate_matches`), remittance account vs trusted accounts, vendor history gaps. Every feature records its inputs. | `fraud` (+ `evidence`, `vendors`, `procurement`) | duplicate_matches |
| 6 | Explainable risk | Assessment persisted: risk_level, risk_score, ordered human-readable explanations, feature snapshot, `evc` placeholder (Phase 4). A `critical` assessment auto-opens a case (step 7). | `fraud` | fraud_assessments |
| 7 | Human investigation | Investigator reviews evidence, verifies uncertain OCR fields, **independently verifies any new bank account**, records notes and an outcome. Nothing in this step is automatable by design. | `cases` (+ UI) | case_notes, cases, vendor_trusted_accounts.verification_status |
| 8 | Audit | Every significant action across steps 1–7 appends to `audit_logs` (actor, action, entity, request context). Cross-cutting. | `audit` | audit_logs |

Steps 1–6 are machine steps, step 7 is human by design, step 8 wraps all others. The API surface per step is listed in API.md §6.

## 5. Module dependency map

Dependency rules (enforced by review now, import-linter later):

- **D1** `core` and `db` depend on nothing internal; every module may use them.
- **D2** Feature modules (`auth` … `audit`) may depend on `core`, `db`, `tenancy`, and on other feature modules **only in the direction listed in the table** — no cycles.
- **D3** Adapters depend on nothing but `core`; modules depend on adapter **protocols**, never concrete implementations (inversion, ADR 0003).
- **D4** No module imports `api`; `api/v1` imports modules to compose HTTP surfaces only — no business logic lives in `api`.
- **D5** `audit` is a leaf: any module may write audit events through it; it imports nothing above `db`.

| Module | May depend on | Why |
|---|---|---|
| `core` | — | settings, structured logging, versioned error envelope, security primitives (password hashing, JWT) shared by all |
| `db` | core | engine/session/declarative Base + portable-type conventions (`sa.Uuid`, `sa.JSON`, `DateTime(timezone=True)`) so models run on PostgreSQL and SQLite alike |
| `tenancy` | core, db | resolves principal + `organization_id` from the JWT; provides the org-scoped query helpers every module must use (API.md §5) |
| `adapters.storage` | core | `StorageProvider` protocol + `LocalFilesystemProvider` (default) + `MinIOS3Provider`; keeps vendor SDKs out of modules |
| `adapters.ocr` (Phase 2) | core | `OcrProvider` protocol + `StubOcrProvider`; real engines (Tesseract, Azure Document Intelligence) plug in later without touching modules |
| `auth` | core, db, tenancy, audit | register/login/me; issues JWTs carrying `org_id`; audits registrations and logins |
| `documents` | core, db, tenancy, adapters.storage, audit | upload/download/delete of document records; bytes are only ever touched through the storage seam |
| `extraction` | core, db, tenancy, documents, adapters.ocr, audit | turns OCR output into `extracted_fields` rows with evidence spans + confidence |
| `vendors` | core, db, tenancy, audit | vendor registry, trusted bank accounts (human-only verification workflow), vendor resolution |
| `procurement` | core, db, tenancy, vendors, documents, audit | purchase_orders, invoices, invoice_line_items; links invoices to vendor and to the remittance account |
| `evidence` | core, db, tenancy, vendors, procurement, documents | read-only aggregation of corroboration for an invoice (POs, trusted accounts, history) |
| `fraud` | core, db, tenancy, evidence, extraction, vendors, procurement, cases, audit | computes features, writes `duplicate_matches` + `fraud_assessments`; opens cases for critical findings via the `cases` service (one-way edge: fraud → cases) |
| `cases` | core, db, tenancy, audit | investigation workflow, notes, human outcomes. Does **not** import `fraud` — the API composes case + assessment views (keeps D2 acyclic) |
| `audit` | core, db | append-only `audit_logs` writer; leaf module (D5) |
| `api.v1` | all modules | routers, versioned error envelope, pagination, auth dependencies; composition only (D4) |
| `frontend` | backend REST contract | Next.js static export; depends only on the OpenAPI-derived types, never on backend internals |

The `fraud → cases` edge is the only module-to-module trigger edge in the system. It exists so that a critical assessment implies a mandatory human-review case (R6). Sequencing note: the `cases` table arrives in Phase 5; between Phases 4 and 5 the obligation is **derived on read, not stored** — a `critical` assessment without an associated case is by definition an unmet obligation (no transient marker that a restart could lose), and Phase 5 backfills cases for exactly that set (IMPLEMENTATION_PLAN.md §Phase 4/5).

## 6. Execution profiles

Both profiles run the same code, models, and adapters; only settings differ.

### PROFILE A — LOCAL_FULL (Docker Compose)

`deploy/docker-compose.yml` (written in a later phase; owned by the deployment workstream) defines:

- `postgres:16` — canonical database.
- `minio` + one-shot `mc` bucket init — document storage.
- `backend` — uvicorn serving the FastAPI app.
- `frontend` — Next.js dev server or the statically exported build served statically.

Settings: `DATABASE_URL=postgresql+psycopg://...@postgres:5432/veripay`, `STORAGE_BACKEND=minio`, `OCR_PROVIDER=stub`.

**Honesty note:** Docker is not installed and WSL is unavailable on the development machine, so compose can **never be executed locally**. The file is written for CI and other machines. Local development without Docker uses the fallback column below — same models, SQLite + LocalFilesystemProvider + stub OCR.

### PROFILE B — AZURE_STUDENT_DEMO

- **Frontend:** Azure Static Web Apps (Free) serves `frontend/out/` produced by `next build` with `output: 'export'` (ADR 0004). API base URL is a build-time env (`NEXT_PUBLIC_API_BASE_URL`).
- **Backend:** the FastAPI app containerized on student-eligible compute (e.g. Azure App Service B1 or Azure Container Apps). Cost note (design-reviewer estimate, not verified in this session): App Service B1 (~$13/mo) + Azure Database for PostgreSQL Flexible Server B1ms (~$13/mo plus storage) ≈ $26–30/mo, which can exceed a $20 student budget — the Phase 7 runbook must prefer scale-to-zero compute (Azure Container Apps consumption free grant) or demo-only start/stop, and record the actual monthly cost against the cap.
- **Database:** Azure Database for PostgreSQL Flexible Server (burstable tier) — PostgreSQL stays canonical in the cloud.
- **Storage:** Azure Blob Storage via a future `AzureBlobStorageProvider` implementing the same `StorageProvider` contract (MinIO is a local-only convenience). Until that adapter exists, PROFILE B demos run the local-filesystem provider inside the backend container — ephemeral storage, acceptable for a demo, documented limitation.
- Nothing was provisioned for this profile in this session (no cloud access); the profile is a documented target with a runbook to be written in Phase 7.

### Configuration matrix

| Setting | Local no-Docker (this machine) | PROFILE A (compose) | PROFILE B (Azure demo) |
|---|---|---|---|
| `DATABASE_URL` | `sqlite:///./veripay.db` | `postgresql+psycopg://...postgres:5432/...` | Azure PG Flexible Server |
| `STORAGE_BACKEND` | `local` | `minio` | `azure_blob` (later) / `local` (demo) |
| `OCR_PROVIDER` | `stub` | `stub` | `stub` or cloud adapter |
| Frontend hosting | `next dev` | compose service | Azure Static Web Apps |
| Alembic | offline `upgrade head --sql` only | live `upgrade head` | live `upgrade head` |

## 7. Provider-agnostic adapter seams

### 7.1 StorageProvider — designed now, implemented in Phase 1

Protocol (Python `typing.Protocol`, structural — no inheritance coupling):

```python
class StorageProvider(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...                 # raises StorageObjectNotFound
    def delete(self, key: str) -> None: ...                   # idempotent
    def exists(self, key: str) -> bool: ...
    def temporary_url(self, key: str, ttl_s: int) -> str | None:  # None where unsupported
```

- Implementations: `LocalFilesystemProvider` (default; root from settings), `MinIOS3Provider` (PROFILE A), `AzureBlobStorageProvider` (PROFILE B, later).
- Object keys are **tenant-prefixed**: `{org_id}/{document_id}/{sha256}{ext}` — a misconfigured shared bucket still cannot silently merge tenants' objects.
- Every implementation must pass the **same contract test suite** (roundtrip, not-found, delete idempotency, content-type preservation).
- `documents` rows store `storage_provider` + `storage_key`; no module other than `documents` reads bytes, and only through the seam.

### 7.2 OcrProvider — Phase 2 interface stub

```python
class OcrProvider(Protocol):
    def extract(self, data: bytes, mime_type: str) -> OcrDocument: ...

# OcrDocument = pages[page_no, blocks[text, bbox, confidence]] + provider_meta[provider, model, request_id]
```

- Phase 2 ships **only the protocol + `StubOcrProvider`** (deterministic placeholder output that marks itself synthetic). The pipeline, persistence, and confidence gating (R3) are built against the protocol so real engines drop in without module changes.
- Stub output always carries `confidence = None`, and `None`/below-threshold is treated as below the confidence gate — stub output must never be scored as evidence (§8.3).

## 8. What is never automated

Normative "no-go list". A change that violates any line here is rejected regardless of other merit.

1. **No payment authorization.** There is no payment-rail integration, no payment-execution code path, and no endpoint that moves money or sends payment instructions to a finance system. The terminal workflow state is a human decision made **outside** VeriPay; invoice/case statuses top out at "cleared for manual review" — a recommendation, nothing more.
2. **No genuineness verdicts.** The data model has no `is_genuine` / `is_fraud` boolean; assessments expose signals, severities, and explanations only. Product/UI copy may say "no critical findings detected in assessment N" — never "invoice is genuine / legitimate / safe".
3. **No confidence laundering.** The gate applies to **machine-extracted values**: a value enters fraud features only if its `confidence >= OCR_CONFIDENCE_THRESHOLD` (default 0.85) **or** a human supplied/verified it. Below the gate, a feature emits an `unverified_input` observation instead of a mismatch claim. Stub/mock OCR output (`confidence = None`) is always below the gate. **Input contract for manual entry:** values typed by a human through the API are gate-passed by definition; the **invoice columns are the source of truth** for computation and `extracted_fields` are provenance. `invoices.field_sources` records each column's origin (`manual` | `extracted` + provenance field id); if a column and its extracted provenance disagree, the column wins and the disagreement itself surfaces as a `field_provenance_conflict` signal (severity `medium`) for human attention. Low confidence can lower trust in a value; it can never be presented as confident evidence of anything.
4. **No fraud-from-absence.** A missing PO, missing vendor history, or missing accounts on file produces a `missing_evidence` signal with severity capped at `medium`, and its explanation must state that the record may simply not exist in VeriPay. Absence alone must never produce a `high`/`critical` risk level. This cap governs **evidence absence** only; it does not cap the pay-to-destination finding of §8.5, which is an action risk (where money would go), not absent evidence.
5. **No automatic bank-account verification.** `vendor_trusted_accounts.verification_status` starts at `pending`. Only a human moves it to `verified` through the cases/vendor UI, and `verification_method` + `verification_reference`/`verification_document_id` are mandatory at that moment. There is no time-, score-, or volume-based auto-verification. **Signal & forcing (R5):** any invoice whose remittance fingerprint does not match a **verified** trusted account yields `bank_account_unverified` with severity **`high`** (fixed floor — scoring may not downgrade it), whether the account is missing, `pending`, `failed`, or `revoked`. Forcing mechanism: severity `high` sets `invoices.status = needs_review` (machine-set, audited), and the invoice cannot transition to `closed` while the signal is undispositioned; severity `critical` additionally auto-opens a case (§8.6). A vendor with no accounts on file yields **both** `missing_evidence` (≤ `medium`, about evidence — §8.4) **and** `bank_account_unverified` (`high`, about the pay-to destination): a first payment to an unverified payee is exactly the R5 case that must be human-reviewed.
6. **No auto-resolution of critical findings.** Any assessment with severity `critical` automatically opens a case. Cases can only be closed by a human recording an outcome and resolution summary. No threshold, scheduler, or background job may close, downgrade, or suppress a critical case.

**Signal vocabulary, default severities, and forcing rules** — single source of truth (DATABASE.md §13 mirrors it):

| Signal | Default severity | Forcing rule |
|---|---|---|
| `missing_evidence` | `low`–`medium` (capped, §8.4) | none — informational; humans decide whether to look |
| `unverified_input` | `low` | none — marks a gated-out input (R3) |
| `field_provenance_conflict` | `medium` | none — invoice column wins; humans informed |
| `duplicate_candidate` | `medium` | sets `invoices.status = needs_review`; dispositioned via `duplicate_matches` |
| `amount_mismatch` | `high` | sets `needs_review` |
| `bank_account_unverified` | `high` (floor — may not be downgraded) | sets `needs_review`; invoice cannot close while undispositioned (§8.5) |
| aggregated `risk_level = critical` | `critical` | auto-opens a case (R6) |

Forcing rule summary: severity `high` ⇒ `invoices.status = needs_review` (machine-set, audited); `critical` ⇒ auto-case. No rule auto-approves, auto-closes, or downgrades anything.

## 9. Cross-cutting decisions (pointers)

- **Tenancy:** the tenant comes only from the JWT; every query goes through org-scoped helpers; cross-org access is 404. Details: API.md §5.
- **API conventions:** `/api/v1`, versioned error envelope, limit/offset pagination, OpenAPI generated by FastAPI. Details: API.md.
- **Data conventions:** UUID PKs, org column + index on every tenant table, created/updated timestamps, portable types. Details: DATABASE.md §1.
- **Testing:** pytest on SQLite (schema from `Base.metadata.create_all`), adapter contract tests, mandatory tenant-isolation tests per resource, `next build` static-export check. Alembic targets PostgreSQL and is validated offline with `alembic upgrade head --sql` on this machine.
- **Sequencing:** the `audit` module exists from Phase 1 as a **facade** — `record(action, entity_type, entity_id, detail, actor)` writing structured application logs with the `audit_logs.action` dotted-name vocabulary (DATABASE.md §15). Phase 6 swaps persistence to the `audit_logs` table behind the same interface; no module ever logs around it.

## 10. Open questions

- **EVC** (`fraud_assessments.evc` placeholder) — exact expansion and mechanics are deferred to the Phase 4 design; the column is reserved and stays `NULL` until then.
- **Email uniqueness** — globally unique in Phase 1 (login key); revisit if the product later needs the same person in multiple orgs.
- **Azure Blob storage adapter** timing (Phase 2+; needed for durable PROFILE B storage).
