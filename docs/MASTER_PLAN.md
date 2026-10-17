# VeriPay — Master Plan (owner prompts 00–07)

Status: approved plan · implementation status recorded 2026-10-17 · every "verified" claim below was produced by running the named command on this machine on that date (see [TESTING.md](TESTING.md) for full outputs)
Related: [ARCHITECTURE.md](ARCHITECTURE.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · [TESTING.md](TESTING.md) · [LIMITATIONS.md](LIMITATIONS.md) · [DEPLOYMENT_AZURE.md](DEPLOYMENT_AZURE.md) · [PREFLIGHT_AZURE.md](PREFLIGHT_AZURE.md) · [COST_ESTIMATE.md](COST_ESTIMATE.md)

This document is the delivery contract between the owner's prompt series (00–07) and the code. Each prompt maps to: what it asked for, what status it has, the acceptance checks that prove it, and what remains. The business invariants (ARCHITECTURE §2, no-go list §8) are normative for every prompt; no prompt, past or future, can override them.

**Honesty frame:** this is a Windows 11 machine with **no Docker and no WSL** (re-verified 2026-10-17: `docker --version` → `'docker' is not recognized`, `wsl --status` → "The Windows Subsystem for Linux is not installed") and **no cloud access from engineering work** (`az` is never run during implementation; the one Azure pre-flight was a separate, owner-supervised read-only pass — see Prompt 06). Anything that needs Docker/PostgreSQL/cloud is marked **not run**, never "passed".

---

## 1. Status board

| Prompt | Theme | Status | Where the proof lives |
|---|---|---|---|
| 00 | Design docs + repo scaffold | **DONE** | commits `2f40681` (docs) + `fe3702f` (workspace scaffold); docs set in `docs/` |
| 01 | Secure backend core (auth, schema, ingestion, procurement, cases, audit) | **DONE this run** | commit `a9e9231`; 43-path OpenAPI (`apps/api/openapi.json`); suite green |
| 02 | Document extraction pipeline (OCR seam, fields, confidence gate) | **DELIVERED this run** | `apps/api/app/modules/extraction/` (files carry `Prompt-02` headers); R3 tests |
| 03 | Evidence retrieval & search | **DELIVERED this run** | `apps/api/app/modules/retrieval/` (files carry `Prompt-03` headers); migration `0002`; 9 retrieval test modules |
| 04 | EVC v1 — explainable value/consistency scoring | **DELIVERED this run** | `apps/api/app/modules/fraud/evc.py`, `policy_v1.json`; migration `0003`; `tests/test_evc_scenarios.py` |
| 05 | Frontend application (static-export dashboard) | **DELIVERED this run** | commit `8836fe1`; components carry `Prompt 05` headers; 14-route build green |
| 06 | Azure deployment (`AZURE_STUDENT_DEMO`) | **PLAN ONLY — awaiting explicit owner approval** | [DEPLOYMENT_AZURE.md](DEPLOYMENT_AZURE.md), [COST_ESTIMATE.md](COST_ESTIMATE.md), read-only pre-flight [PREFLIGHT_AZURE.md](PREFLIGHT_AZURE.md) |
| 07 | QA & hardening (E2E, functional cases, injection, security) + Docker/cloud items | **PARTIAL — local QA done; Docker/cloud items pending** | `apps/api/tests/test_prompt07_*.py` (4 modules, all green); pending items in §4.7 |

Aggregate verification state (all re-run 2026-10-17, this machine):

- **Backend:** `295 passed, 6 skipped` (301 collected) — 6 skips are honest environment skips, itemized in [TESTING.md §3](TESTING.md).
- **Frontend:** `next build` exit 0 — 14 routes, all statically prerendered.
- **Contracts:** `tsc --noEmit` on `packages/api-contracts` exit 0.
- **Migrations:** offline SQL (SQLite + PostgreSQL dialects), live upgrade→downgrade→upgrade on scratch SQLite, `alembic check` clean.
- **Demo data:** `scripts/seed_demo.py` ran end-to-end against a fresh SQLite DB (12 invoices, 3 cases; details in [DEMO_GUIDE.md](DEMO_GUIDE.md)).

---

## 2. Ground rules carried over from IMPLEMENTATION_PLAN §0 (unchanged, normative)

1. The docs set is the contract; implementation deviations require updating the docs in the same change and recording them in [IMPLEMENTATION_PLAN.md §5](IMPLEMENTATION_PLAN.md).
2. The six business invariants override convenience. A change that violates ARCHITECTURE §8's no-go list is rejected regardless of other merit.
3. Acceptance checks must be runnable on this dev machine; anything needing Docker/PostgreSQL/cloud is marked **[not runnable locally]** and belongs to CI / PROFILE A.
4. Engineering agents never run `git commit` / `git push` — the owner reviews and commits.
5. No cloud provisioning without the owner's explicit word (hard owner rule; gates G1–G7 in DEPLOYMENT_AZURE.md §3).

## 3. The fixed per-phase review gate

Every prompt/phase passes through the same gate before it may be called "done". The gate is fixed — it does not shrink under time pressure:

1. **Acceptance checks ran for real.** Every check the phase names was executed on this machine and its output recorded (command + exit code + tail) in [TESTING.md](TESTING.md). A check that could not run is listed as not run, with the reason — never marked passed. Substitutions are labeled as substitutions (e.g. YAML parse ≠ `docker compose config`).
2. **Invariant review, line by line.** The delivered surface is reviewed against ARCHITECTURE §2 (R1–R6) and §8 (the no-go list): no payment authorization path, no genuineness vocabulary, confidence gate intact, absence capped at medium, bank accounts human-approved only, critical ⇒ human case. The prompt07 test modules make the review executable; they supplement it, not replace it.
3. **Docs updated in the same change.** Whatever drifted (ARCHITECTURE, DATABASE, API) is corrected with the code, and the deviation is recorded in [IMPLEMENTATION_PLAN.md §5](IMPLEMENTATION_PLAN.md).
4. **Honest artifacts.** Compose/deploy files carry the "never executed here" header; synthetic data and synthetic metrics are labeled as such; skip-marked tests state their reason.
5. **Owner review and commit.** The gate closes when the owner reviews the working tree and commits. Uncommitted state is explicitly part of the deal on this run (owner pushes via the main session).

A phase is **done** only when 1–5 all hold. It is **partial** when the code exists but a check could not run (e.g. Docker-only items) — the phase then stays open with the pending items named, as Prompt 07 does below.

---

## 4. Prompt-by-prompt status

### 4.0 Prompt 00 — design docs + repo scaffold — **DONE**

- **Delivered:** the design contract (ARCHITECTURE.md, DATABASE.md, API.md, IMPLEMENTATION_PLAN.md, COST_ESTIMATE.md, ADRs 0001–0007) and the repository scaffold (npm workspaces root, `packages/api-contracts`, `infrastructure/local/docker-compose.yml`, seed/fixture scripts, CI workflow).
- **Evidence:** commits `2f40681` ("docs: architecture, database schema, API design, phase plan and Azure cost analysis") and `fe3702f` ("chore: npm workspace, api-contracts package, docker compose, seed/fixture scripts and CI workflows").
- **Acceptance:** docs set exists and cross-references; CI workflow parses (re-verified this run: `.github/workflows/ci.yml` → jobs `backend-tests`, `frontend-build`, `contracts-typecheck`, `compose-yaml-validate`).

### 4.1 Prompt 01 — secure backend core — **DONE (this run)**

- **Delivered** (commit `a9e9231`, "feat(api): FastAPI backend — cookie/RBAC auth, 20-table schema, EVC fraud engine, evidence retrieval, document ingestion and processing"): cookie-session + CSRF auth with Bearer for programmatic clients; four-role RBAC (`org_admin`, `finance_officer`, `reviewer`, `auditor`); the 20-table canonical v2 schema (squashed `0001_full_schema`); vendors/contacts/bank accounts/change requests with **human-only approval (R5)**; document ingestion (magic bytes, size cap, per-org SHA-256 dedup, tenant-prefixed storage, protected downloads); durable idempotent processing jobs + ProcessingBackend seam (inline default, Celery optional); procurement with duplicate-as-signal intake (never 409); deterministic explainable fraud assessments; investigation cases with mandatory human outcome + resolution summary (R6); append-only audit events; stats dashboard.
- **Acceptance (run this session):** full pytest suite green; OpenAPI snapshot drift test green; API surface = **43 paths / 54 operations** (counted from `apps/api/openapi.json` this run), each org-scoped per API.md §5.
- **Status note:** the extraction, retrieval, and EVC layers named in the commit message were built by Prompts 02–04 on top of this core.

### 4.2 Prompt 02 — document extraction pipeline — **DELIVERED (this run)**

- **Delivered:** `OcrProvider` seam with four adapters — `text_layer` (**new default**: reads a PDF's embedded digital text so real text-layer documents never need pixel OCR — `app/core/config.py` settings block, this run's change from the documented `stub` default), `tesseract` (optional binary; cleanly absent here), `azure` (Azure Document Intelligence adapter, coded against the F0 contract, **not live** — see Prompt 06/LIMITATIONS), `stub` (always available, marks itself synthetic). Structured field extraction with evidence spans + per-field confidence (`app/modules/extraction/fields.py:1` — "Structured field extraction from OCR blocks (Prompt-02)"), the pipeline (`service.py:7`), extraction-quality validation that is explicitly **NOT fraud signals** (`validation.py:1`), manual field review (`PATCH /documents/{id}/fields/{field_id}`, `tests/test_field_review.py:1`), and the **R3 confidence gate** — below-threshold/NULL confidence emits `unverified_input`, never a mismatch.
- **Acceptance (run this session):** `tests/test_extraction_pipeline.py`, `test_extraction_fields.py`, `test_extraction_binding.py`, `test_extraction_validation.py`, `test_extraction_evaluation.py`, `test_field_review.py`, `test_ocr_providers.py` all green in the 295-test run (1 tesseract test skip-marked — binary absent, `test_ocr_providers.py:92`).

### 4.3 Prompt 03 — evidence retrieval & search — **DELIVERED (this run)**

- **Delivered:** the `retrieval` module (`app/modules/retrieval/__init__.py:1` — "Information retrieval & evidence search (Prompt-03)"): normalization (incl. Arabic-Indic digits), two dialect-selected backends behind one interface (portable SQLite trigram + **optional** pgvector on PostgreSQL — migration `0002` is titled "retrieval: OPTIONAL pgvector enablement (Prompt-03 §2)" and is off by default, never required), five relationship families (evidence graph), trust-tier ranking, hybrid RRF fusion, and the citable-evidence API `GET /invoices/{id}/evidence` (`app/api/v1/routes/retrieval.py:1` — "citable evidence for an invoice (Prompt-03 §7)"). IR metrics (Precision@K, Recall@K, MRR, nDCG@K) over an honestly-labeled **synthetic** fixture set (`app/modules/retrieval/metrics.py:1`, `tests/test_retrieval_evaluation.py:1`).
- **Acceptance (run this session):** 7 retrieval test modules green on SQLite within the 295-test run (`test_retrieval_{normalize,search,hybrid,graph,resolution,evidence_api,evaluation}.py`); the PostgreSQL-conditional module (`tests/test_retrieval_pg.py`, 5 tests) skips with reason "requires a live PostgreSQL engine — runs on the CI PostgreSQL leg" — this is a named pending item, not a pass.

### 4.4 Prompt 04 — EVC v1 — **DELIVERED (this run)**

- **Delivered:** EVC v1 as the assessment payload (`app/modules/fraud/evc.py:8` — "Design contract (docs/ARCHITECTURE.md §8, normative; Prompt-04)"): `policy_version`, six weighted features with per-feature uncertainty states (`verified_agreement` / `confirmed_discrepancy` / `insufficient_evidence`), contributions, overrides, result state; scoring contract `app/modules/fraud/policy_v1.json` with invariant floors cross-checked at load; migration `0003` (makes `review_actions.case_id` nullable for case-less override records); critical result states force `needs_review` and auto-open a case (R6). The score is a consistency measure, **never a fraud probability** (R2).
- **Acceptance (run this session):** `tests/test_evc_scenarios.py:1` ("the 9 brief scenarios as executable tests") green; `seed_demo.py` run produced EVC-populated assessments on all 12 invoices (checked: `evc non-null: 12 / 12` in the seeded scratch DB).

### 4.5 Prompt 05 — frontend application — **DELIVERED (this run)**

- **Delivered** (commit `8836fe1`): the statically-exported Next.js App Router app (ADR 0004) with: landing + auth screens (`(auth)` layout carries the Prompt-05 palette — `(auth)/layout.tsx:12`), live dashboard overview fed by `GET /stats/dashboard` ("Overview — the live dashboard (Prompt 05)" — `dashboard/page.tsx:22`), vendor management workspace with contacts/authorized contacts/bank accounts/change requests (`vendors/page.tsx:10`, `vendor-detail.tsx:24`), invoice list with honest outcome vocabulary (`invoices/_components/derive.ts:16` — "the owner-mandated honest outcome vocabulary (Prompt 05)"), document upload with client-side validation + processing-status polling + idempotent retry (`invoices/upload/page.tsx`), split-screen investigation workspace (evidence/fields/PO/vendor/findings/matches panels + actions feed — `investigations/workspace.tsx:41`), case list/detail with role-aware close (R6), audit page (org_admin/auditor), settings. Cookie+CSRF session, zero web storage.
- **Acceptance (run this session):** `next build` exit 0 — **14 routes, all static** (`/`, `/dashboard`, `/dashboard/{audit,cases,cases/detail,investigations,invoices,invoices/upload,settings,vendors}`, `/login`, `/register`, `/_not-found`, `/icon.svg`); contracts `tsc` exit 0.

### 4.6 Prompt 06 — Azure deployment — **PLAN ONLY, awaiting explicit owner approval**

- **What exists:** the full plan (DEPLOYMENT_AZURE.md — "STATUS: PLAN ONLY. Nothing in this document has been executed"), the cost analysis (COST_ESTIMATE.md — prices verified against the Azure Retail Prices API 2026-10-17; verdict GO on ~$20 with four hard conditions), and a **read-only pre-flight** (PREFLIGHT_AZURE.md — Gate G0: subscription facts confirmed via `az` in an owner-supervised pass; **NOTHING provisioned**).
- **The gate that blocks everything:** the owner's explicit approval checklist (PREFLIGHT_AZURE.md §4 — spending-limit confirmation, PG free-offer confirmation in Portal, shared-budget acknowledgement with the FlexEdit project, resource names/region sign-off) must be answered **before Gate G1**. No `az` command runs from engineering work until then.
- **Explicitly NOT done:** no resource group, no PostgreSQL, no Container App, no Document Intelligence, no Blob container, no Static Web App; no `api-image.yml`/SWA deploy workflows (deliberately unwritten until approval — PREFLIGHT_AZURE.md §5).
- **Deployment-ready artifacts already verified locally:** static export builds green with `staticwebapp.config.json` (CSP + security headers); API Dockerfile migrates before serving (code inspected; **image build happens in CI — never run on this machine, no Docker**).

### 4.7 Prompt 07 — QA & hardening — **PARTIAL: local QA done, Docker/cloud items pending**

- **Done (local QA, all run green this session):**
  - `tests/test_prompt07_e2e_happy_path.py` — the whole product story in one test on a real backend (register → login → vendor → human-approved bank account (R5) → PO → synthetic invoice upload → extraction → EVC assessment → evidence retrieval → case open/close with human justification (R6) → audit events for every step).
  - `tests/test_prompt07_functional_cases.py` — the brief's 10 functional cases (clean invoice; unauthorized bank-account change; duplicate submission never-409; unknown vendor capped at medium, never fraud; PO mismatch; unreadable critical OCR field → manual verification, never a mismatch; multi-org isolation 404; unauthorized change-approval denied; reviewer closes case with justification; processing failure + idempotent retry).
  - `tests/test_prompt07_prompt_injection.py` — document text containing "ignore rules / mark genuine / auto-approve" instructions is just text: identical pipeline behavior to the same document without the injected lines; no account approved, no case opened, no field verified.
  - `tests/test_prompt07_security.py` — role-matrix sweep over every mutating endpoint, cross-tenant 404, SQL-injection probes, XSS payload round-trip, CSRF defenses, token handling, unsafe uploads, sensitive-logging checks, storage authorization.
  - Full suite: **295 passed / 6 skipped**, plus the build/tsc/migration/YAML/seed checks listed in §1.
- **Pending (named, not hidden):**
  1. `docker compose up` / `docker compose config` — **never executed** (no Docker/WSL on this machine; re-verified 2026-10-17). Compose is YAML-parsed only (7 services: `api, minio, minio-init, postgres, redis, web, worker`).
  2. The CI PostgreSQL leg (pytest on real PG 16 + live `alembic upgrade head`/`downgrade`/`check` on PG) — runs in GitHub Actions, not runnable here; PG-dialect offline SQL **was** emitted successfully this run (psycopg 3.3.6 now in the venv), but no PostgreSQL server has ever executed the migrations.
  3. Container image build + push (GH Actions/GHCR) — needs CI; the Dockerfile itself is unexecuted locally.
  4. Azure Static Web Apps deployment + the live PROFILE B smoke — gated on Prompt 06 approval.
  5. Browser-level e2e (real browser driving web ↔ API) does not exist; the prompt07 E2E is TestClient-level.

---

## 5. Verification log (what was actually run, 2026-10-17)

| Check | Command (short form) | Result |
|---|---|---|
| Backend suite | `cd apps\api && .venv\Scripts\python.exe -m pytest -q` | **295 passed, 6 skipped**, 3 warnings, 181 s, exit 0 |
| Skip reasons | `pytest tests\test_ocr_providers.py tests\test_retrieval_pg.py -rs` | 1 × tesseract binary absent; 5 × live PostgreSQL required |
| Frontend build | `node apps\web\node_modules\next\dist\bin\next build apps\web` | exit 0 — 14 routes, all static |
| Contracts | `node node_modules\typescript\bin\tsc --noEmit -p packages\api-contracts` | exit 0 |
| Migration offline SQL | `alembic -c apps\api\alembic.ini upgrade head --sql` | exit 0, 506 lines, 0001→0003 (SQLite dialect) |
| Migration offline SQL (PG dialect) | same + `VERIPAY_DATABASE_URL=postgresql+psycopg://…` | exit 0, 485 lines, `PostgresqlImpl` — works now (psycopg 3.3.6 installed); the old "cannot emit PG SQL" caveat is **resolved** |
| Migration cycle (scratch SQLite) | `VERIPAY_DATABASE_URL=sqlite:///…scratch.db` → `upgrade head` → `downgrade base` → `upgrade head` | exit 0; `current` = `0003 (head)`; 20 domain tables + `alembic_version` |
| Model/migration drift | `alembic check` against the migrated scratch DB | "No new upgrade operations detected." |
| YAML checks | PyYAML `safe_load` on compose + CI workflows | 7 compose services; 4 CI jobs |
| Demo seed | `VERIPAY_DATABASE_URL=…scratch` `python scripts\seed_demo.py` | 12 invoices assessed, EVC 12/12, 3 cases (2 auto-opened critical + 1 human), 5 vendors / 5 accounts (3 approved, 2 pending), 15 audit events |
| Docker absence | `docker --version`; `wsl --status` | not installed / not installed |

Full outputs: [TESTING.md](TESTING.md). What these checks do **not** cover: [LIMITATIONS.md](LIMITATIONS.md).

## 6. What remains open

1. **Prompt 06 execution** — blocked solely on the owner's approval checklist (PREFLIGHT_AZURE.md §4). Until then nothing cloud exists.
2. **Prompt 07 Docker/cloud items** — compose validation, CI PG leg, image build, SWA deploy (§4.7 pending list).
3. **Documentation debt that outlives this run** — [LIMITATIONS.md](LIMITATIONS.md) is the canonical list; the highest-impact items are: no live PostgreSQL run anywhere yet, no Docker execution anywhere yet, synthetic retrieval metrics are not real-world performance, and the static export's security headers exist only via the SWA config (the dev server serves none).
4. **Known doc/code drift recorded, code untouched** — `scripts/seed_demo.py`'s docstring still describes the pre-EVC engine ("evc stays NULL", "1 case"); the actual engine now populates EVC on every assessment and R6 auto-opens cases for critical results (observed: 3 cases). Recorded in IMPLEMENTATION_PLAN.md §5; the script itself is application code and was deliberately not modified in this docs-only change.
