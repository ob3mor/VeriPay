# VeriPay — Testing & Verification

Status: **current as of 2026-10-17 (prompts 00–07 run)** · every result below was produced by running the named command on this machine on that date, unless explicitly marked otherwise.
Related: [MASTER_PLAN.md](MASTER_PLAN.md) (per-phase gates) · [ARCHITECTURE.md](ARCHITECTURE.md) (§2 invariants, §9 testing) · [LIMITATIONS.md](LIMITATIONS.md) (what these checks do NOT cover) · [DEPLOYMENT_LOCAL.md](DEPLOYMENT_LOCAL.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

Environment the checks ran in: Windows 11, cmd.exe, Python 3.12 (project venv at `apps/api/.venv`), Node 25 + npm 11. **Docker is not installed and WSL is unavailable** (re-verified this run: `docker --version` → `'docker' is not recognized…`; `wsl --status` → "The Windows Subsystem for Linux is not installed") — everything that requires Docker/PostgreSQL/MinIO is marked **not run**, never passed.

The backend interpreter is the **venv**, not the global Python: the global Python 3.12 on this machine has no `pytest`/`alembic` installed. All commands below use `apps\api\.venv\Scripts\python.exe`.

---

## 1. Gate results (summary)

| Gate | Command (short form) | Result (this run, 2026-10-17) |
|---|---|---|
| Backend pytest | `.venv\Scripts\python.exe -m pytest -q` in `apps\api` | **295 passed, 6 skipped** (301 collected), 3 warnings, 181.4 s, exit 0 |
| Frontend production build | `node apps\web\node_modules\next\dist\bin\next build apps\web` | exit 0 — **14 routes, all static** |
| Contracts TypeScript | `node node_modules\typescript\bin\tsc --noEmit -p packages\api-contracts` | exit 0 |
| Alembic offline SQL | `…alembic -c apps\api\alembic.ini upgrade head --sql` | exit 0 (SQLite dialect, 506 lines) **and** PG dialect (485 lines, `PostgresqlImpl`) |
| Alembic scratch cycle | `VERIPAY_DATABASE_URL=…scratch.db` upgrade→downgrade→upgrade | exit 0, `current` = `0003 (head)`, 20 domain tables |
| Alembic drift check | `alembic check` (against a migrated scratch DB) | "No new upgrade operations detected." |
| Compose YAML syntax | PyYAML `safe_load` | parses; 7 services — **syntax check only, NOT a compose check** (§6) |
| CI workflow YAML | PyYAML `safe_load` | parses; jobs `backend-tests`, `frontend-build`, `contracts-typecheck`, `compose-yaml-validate` |
| Demo seed | `python scripts\seed_demo.py` (scratch DB) | 12 invoices, EVC 12/12, 3 cases, 15 audit events (§7) |
| `docker compose config` / `up` | — | **NEVER RUN — Docker absent** (honesty header; §6) |

History: the gate counts evolved 42 (Phase 1) → 72 (Phase 2 backend brief) → 301 collected / 295 passing (2026-10-17 run) → **296 passed, 6 skipped** (2026-10-18, latest full run); prior full inventories are in git history and §10.

---

## 2. Backend test suite (pytest)

**Command** (from `apps\api`):

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m pytest -q
```

**Result (2026-10-17, this run):**

```
295 passed, 6 skipped, 3 warnings in 181.36s (0:03:01)
exit code 0
```

Warnings are third-party only: a Starlette deprecation inside FastAPI's `testclient` import, and an Alembic `path_separator` deprecation raised by `tests/test_migrations.py`.

**Test environment:** `tests/conftest.py` pins `VERIPAY_ENV=test` and a file-backed SQLite (WAL) before any `app` import, creates/drops the schema per test, resets in-process throttle/lockout/revocation state, and honors a preset `VERIPAY_DATABASE_URL` (which is how the CI PostgreSQL leg runs the same suite — not executed locally; §5/§9).

### 2.1 The 6 skips — all honest environment skips (verified with `-rs`)

```
SKIPPED [1] tests\test_ocr_providers.py:92: tesseract binary not installed
SKIPPED [1] tests\test_retrieval_pg.py:42: requires a live PostgreSQL engine — runs on the CI
           PostgreSQL leg; the no-Docker dev machine runs SQLite so this skips
SKIPPED [1] tests\test_retrieval_pg.py:55  (same reason)
SKIPPED [1] tests\test_retrieval_pg.py:71  (same reason)
SKIPPED [1] tests\test_retrieval_pg.py:93  (same reason)
SKIPPED [1] tests\test_retrieval_pg.py:109 (same reason)
```

- **Tesseract (1):** the pixel-OCR adapter is fully coded (`app/adapters/ocr/tesseract.py`) and its absence path is itself tested (the inverse test at `test_ocr_providers.py:104` RUNS here and asserts a clean `TesseractUnavailableError`).
- **PostgreSQL-conditional retrieval (5):** `tests/test_retrieval_pg.py` proves the pg/trigram backend selection and pgvector path on a real server; skipped on SQLite by design (`pytestmark`, `test_retrieval_pg.py:19-28`). First contact with a live PostgreSQL happens in the CI backend job.

### 2.2 What the suite covers (module map)

| Area | Modules (all green this run) | Invariant coverage |
|---|---|---|
| Identity & sessions | `test_auth_flow`, `test_auth_logout`, `test_auth_throttle`, `test_auth_disabled`, `test_token_security`, `test_csrf_cookies`, `test_password_storage`, `test_config` | no account enumeration; server-side revocation; per-(IP,email) lockout; CSRF double-submit + Bearer exemption; production refuses dev secret |
| Tenancy & roles | `test_org_scoping`, `test_roles_and_isolation`, `test_tenant_isolation` | tenant from token only; cross-org 404; 4-role matrix per API.md §5 |
| Documents & processing | `test_document_ingestion`, `test_document_edges`, `test_processing_idempotent`, `test_processing_jobs_api` | magic bytes, mime mismatch, size cap, per-org SHA-256 dedup, protected cross-tenant download, idempotent job transitions/retry |
| Extraction (Prompt-02) | `test_extraction_pipeline`, `test_extraction_fields`, `test_extraction_binding`, `test_extraction_validation`, `test_extraction_evaluation`, `test_field_review`, `test_ocr_providers` | **R3**: below-threshold/NULL confidence → `unverified_input`, never a mismatch; manual field review; honest OCR fallbacks |
| Fraud & EVC (Prompt-04) | `test_fraud_rules`, `test_evc_scenarios` | **R2/R4/R5**: no genuineness vocabulary; absence capped medium; `bank_account_unverified` high floor; EVC 9 brief scenarios; result states force `needs_review` |
| Retrieval (Prompt-03) | `test_retrieval_normalize`, `test_retrieval_search`, `test_retrieval_hybrid`, `test_retrieval_graph`, `test_retrieval_resolution`, `test_retrieval_evidence_api`, `test_retrieval_evaluation` (7 green on SQLite) + `test_retrieval_pg` (5 skips, §2.1) | org-scoped evidence; trust tiers; citable provenance; synthetic-labeled metrics |
| Procurement | `test_line_items`, `test_disposition_and_matches` | duplicates are signals, never 409; human disposition of matches/findings |
| Cases (R6) | prompt07 functional cases + `test_field_review` flows | critical ⇒ auto-case; close needs human outcome + summary (422 otherwise) |
| QA (Prompt-07) | `test_prompt07_e2e_happy_path` (one full story incl. audit-per-step), `test_prompt07_functional_cases` (the brief's 10 cases), `test_prompt07_prompt_injection` (injected instructions in document text change nothing), `test_prompt07_security` (role sweep, SQLi probes, XSS round-trip, unsafe uploads, sensitive-logging) | executable line-by-line review of ARCHITECTURE §8 |
| Audit & infra | `test_audit`, `test_audit_context`, `test_audit_listing`, `test_stats_dashboard`, `test_storage_local`, `test_openapi_snapshot`, `test_migrations`, `test_health` | append-only audit with ip/UA/request-id; OpenAPI drift guard; migration cycle |

---

## 3. Frontend production build (static export)

**Command** (from repo root; the designated quality gate):

```bat
node apps\web\node_modules\next\dist\bin\next build apps\web
```

**Result (2026-10-17, this run):** exit 0.

```
▲ Next.js 16.4.2 (Turbopack)
✓ Compiled successfully in 827ms
  Running TypeScript ...
  Finished TypeScript in 1901ms ...
✓ Generating static pages using 16 workers (15/15) in 1102ms

Route (app)                — all ○ (Static) prerendered
  / , /_not-found , /dashboard , /dashboard/audit , /dashboard/cases ,
  /dashboard/cases/detail , /dashboard/investigations , /dashboard/invoices ,
  /dashboard/invoices/upload , /dashboard/settings , /dashboard/vendors ,
  /icon.svg , /login , /register
```

Output lands in `apps/web/out/` (including `public/staticwebapp.config.json` — the CSP/security-headers file Azure Static Web Apps serves; **the dev server serves no such headers**, LIMITATIONS.md §7). Equivalent workspace form: `npm run build -w @veripay/web` (not separately re-run this session; the command above is the designated gate).

---

## 4. API contracts (TypeScript)

**Command** (from repo root, exact pipeline form):

```bat
node node_modules\typescript\bin\tsc --noEmit -p packages\api-contracts
```

**Result (2026-10-17, this run):** exit 0.

Covers `packages/api-contracts` (TS mirrors of the REST contract). It checks types compile; runtime agreement with the backend is guarded by the OpenAPI snapshot drift test (`tests/test_openapi_snapshot.py`, green in §2).

**API surface size (counted from `apps/api/openapi.json` this run):** **43 paths / 54 operations**, plus `GET /openapi.json` + `/docs` served at the app root (FastAPI defaults — NOT under `/api/v1/…`; known deviation, API.md §1, recorded since the Phase-1 smoke and still true).

---

## 5. Alembic migration checks

Three migrations ship: `0001_full_schema` (canonical v2, 20 tables) → `0002_retrieval_optional_pgvector` (off by default; no-op without PG) → `0003_evc_review_action_case_nullable`.

### 5.1 Offline SQL — both dialects now verified

```bat
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head --sql
```

- Default (SQLite dialect): exit 0 — **506 lines**, `Running upgrade -> 0001 … 0002 -> 0003`, ends `UPDATE alembic_version SET version_num='0003'`.
- **PostgreSQL dialect** (`set VERIPAY_DATABASE_URL=postgresql+psycopg://u:p@localhost:5432/veripay` before the same command): exit 0 — **485 lines**, log shows `Context impl PostgresqlImpl` + `BEGIN;`. This is NEW: `psycopg 3.3.6` is now installed in the venv, resolving the old "cannot emit PG-dialect SQL" caveat. It validates dialect rendering **only** — no PostgreSQL server was contacted.

### 5.2 Scratch-SQLite executability cycle — verified

```bat
set VERIPAY_DATABASE_URL=sqlite:///C:/Users/Xander/AppData/Local/Temp/veripay_docs_scratch.db
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini current        :: 0003 (head)
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini downgrade base
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head
```

Result (this run): exit 0 throughout; all three migrations up, down, and up again. Final schema: **20 domain tables** + `alembic_version` — `organizations, users, sessions, vendors, vendor_bank_accounts, vendor_authorized_contacts, bank_account_change_requests, documents, extraction_results, extraction_fields, purchase_orders, invoices, invoice_line_items, fraud_assessments, fraud_findings, evidence_matches, investigation_cases, review_actions, processing_jobs, audit_events`. This is an **executability check on SQLite, not a PostgreSQL substitute**; the first live-PG run is the CI gate (`test_migrations.py` repeats this cycle in-suite and was green in §2).

### 5.3 Model/migration drift — verified

```bat
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini check
```

(against the migrated scratch DB) → **"No new upgrade operations detected."** Note: `alembic check` needs a database already at head — against an unmigrated URL it fails with "Target database is not up to date" (observed before pointing it at the scratch DB).

---

## 6. Compose file — YAML syntax check ONLY (honesty header)

> **Honesty header:** Docker has **never** run on this machine and no VeriPay container stack has **ever** been started anywhere. `docker compose config` / `up` / `down` have never been executed. The ONLY check ever applied to `infrastructure/local/docker-compose.yml` is the YAML parse below — a syntax check, **not** the compose check, exactly as IMPLEMENTATION_PLAN.md §2 labels it.

```bat
apps\api\.venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(open('infrastructure/local/docker-compose.yml', encoding='utf-8')); print(sorted(d['services']))"
```

**Result (2026-10-17, this run):** parses cleanly; services: `api, minio, minio-init, postgres, redis, web, worker` (7 — the compose file grew `web` and the opt-in `worker` since the Phase-1 parse).

CI runs the identical YAML-only check (`compose-yaml-validate` job). See [DEPLOYMENT_LOCAL.md §1](DEPLOYMENT_LOCAL.md) for what the stack defines and what has never been validated about it.

---

## 7. Demo seed script (`scripts/seed_demo.py`) — verified end-to-end

**Command** (fresh scratch DB so no pre-existing dev database is touched; from repo root):

```bat
set VERIPAY_DATABASE_URL=sqlite:///C:/Users/Xander/AppData/Local/Temp/veripay_seed_demo.db
apps\api\.venv\Scripts\python.exe scripts\seed_demo.py
```

**Result (2026-10-17, this run):** exit 0. Output tail:

```
  INV-HD-3002 tampered amount              -> risk=critical score=55
  INV-BT-2001 DUPLICATE (altered total)    -> risk=critical score=60.2
Seeded demo data into: sqlite:///…veripay_seed_demo.db
Login (all demo users, fictional people):
  admin@demo.example / finance@demo.example / reviewer@demo.example /
  auditor@demo.example — password: VeriPay-Demo-2026!
Investigation case: CASE-2026-0003 (Duplicate invoice number INV-BT-2001 with altered total)
```

**Verified contents of the seeded DB (queried directly after the run):** 5 vendors · 5 bank accounts (3 `approved`, 2 `pending`) · 8 POs · 12 invoices · 12 assessments with **EVC populated on all 12** · **3 investigation cases** — `CASE-2026-0001` and `CASE-2026-0002` auto-opened (`opened_by` NULL, severity `critical`, R6) and `CASE-2026-0003` human-opened (severity `high`) · 4 review actions · 15 audit events · 0 documents/extractions (the seed enters invoices manually; the upload→extraction flow is exercised in the UI or by the prompt07 E2E test).

**Known docstring drift (code untouched — docs-only change):** the script's header still says "evc stays NULL" and "1 case" from the pre-EVC engine. The observed behavior above is what [DEMO_GUIDE.md](DEMO_GUIDE.md) documents.

---

## 8. Live-server smoke

The ordering rule is unchanged and re-confirmed by the migration checks: **run `alembic upgrade head` from `apps\api` before first API start** — the app never creates tables itself; against a brand-new empty DB, `GET /api/v1/health` returns 200 but any DB-backed call fails (the Phase-1 experiment recorded in git history: `500` + `no such table: users`).

The full-flow live smoke for this run is executable, automated, and green: `tests/test_prompt07_e2e_happy_path.py` drives register → cookie login → vendor → human-approved bank account (R5) → PO → synthetic invoice upload → extraction → EVC assessment → evidence retrieval → case open/close (R6) → audit-per-step against the real app (TestClient, no mocks). A manual browser walkthrough with the seeded data is in [DEMO_GUIDE.md](DEMO_GUIDE.md); it was **not** re-driven through a real browser in this docs run.

---

## 9. Coverage gaps (honest list)

1. **PostgreSQL has never executed anything.** The suite, migrations, and retrieval PG tests all await the CI PostgreSQL leg (or any live PG). PG-dialect SQL *emits* cleanly now (§5.1), which is a rendering check, not an execution.
2. **Docker/compose has never run.** No container of any kind has been built or started. The api/web Dockerfiles and docker-entrypoint.sh are code-inspected only.
3. **MinIO/S3 storage adapter is untested.** `app/adapters/storage/s3.py` lazily imports `boto3` (not installed) and needs a live MinIO (needs Docker) — zero executions.
4. **Azure Document Intelligence adapter is coded, never live.** `app/adapters/ocr/azure_di.py` (F0 page-cap contract, quota mapping, retries) is unit-testable via client injection but has never talked to the service; gated on Prompt 06.
5. **No browser-level e2e.** No Playwright/Cypress in the repo; web↔API integration is covered at TestClient level (prompt07 E2E) and by the build; a real browser was not driven by an automated test.
6. **In-process rate-limit/lockout/revocation state** is per-process (`conftest.py` resets it); multi-worker/horizontal semantics untested.
7. **Synthetic metrics are not real-world performance.** Retrieval metrics and the extraction evaluation run over generated fixtures (`tests/fixtures`, `scripts/generate_fixtures.py`) — labeled synthetic by design; they measure correctness of the metric code, not production accuracy.
8. **Security headers exist only in the SWA config.** `apps/web/out` is served with CSP/HSTS/etc. **only** when hosted via Azure Static Web Apps (`public/staticwebapp.config.json`); `next dev`/static hosting elsewhere serves none (LIMITATIONS.md §7).
9. **CI gates are pipeline-reported.** `.github/workflows/ci.yml` defines the PG leg, builds, and YAML checks; this document records what ran **here**. CI execution is owner-triggered on push.

---

## 10. Historical gate results (for provenance)

| Date | Suite | Result | Notes |
|---|---|---|---|
| 2026-10-17 (Phase 1) | 42 tests | 42 passed | identity/tenancy/audit/storage only; localStorage-token era |
| 2026-10-17 (Phase 2 brief) | 72 tests | 72 passed | cookie+CSRF, RBAC, documents, processing, rules-v0.1; single migration |
| 2026-10-17 (pre-flight, prompts 02–05) | 299 tests | 293 passed / 6 skipped | reported by the read-only Azure pre-flight |
| **2026-10-17 (this run)** | **301 tests** | **295 passed / 6 skipped** | + prompt07 QA growth; all gates in §1 re-executed here |
