# VeriPay

**AI-powered invoice & payment fraud prevention for finance and procurement teams.**

> **Made by Xander + Joka** 🛡️

VeriPay ingests invoices and supporting documents, validates and stores them securely,
resolves vendors, compares pay-to bank details against **independently verified** accounts
on file, computes **explainable** fraud signals, and routes critical inconsistencies to
human investigators with a full audit trail.

VeriPay is a **decision-support system, not a payment system**. Its output is evidence,
explanations, and review workflow — never money movement, and never a claim that an
invoice is genuine. Six business invariants are normative for every design and
implementation decision ([docs/ARCHITECTURE.md §2](docs/ARCHITECTURE.md)):

1. Never authorize payments automatically.
2. Never claim an invoice is genuine.
3. Uncertain OCR must not become confident fraud evidence.
4. Missing records are not proof of fraud.
5. A new bank account requires independent verification.
6. Human review is mandatory for critical inconsistencies.

## Status — what works today (Phase 2)

- **Secure backend & data layer** (`apps/api`, FastAPI + SQLAlchemy 2 + Alembic):
  - **Auth**: httpOnly **cookie sessions** (durable `sessions` table, SHA-256-hashed
    opaque tokens, server-side revocation) + CSRF double-submit middleware +
    short-lived Bearer tokens + `POST /auth/refresh` + rate limiting with per-(IP,
    email) lockout. **No tokens in browser localStorage** — ever.
  - **Roles**: `org_admin · finance_officer · reviewer · auditor`, enforced per
    endpoint (`tenancy/permissions.py`); organization-scoped tenancy on every
    query (cross-org is 404).
  - **Vendors & bank-account change control (R5)**: accounts start `pending`; ONLY a
    human approves — with `verification_method` + reference/document; an uploaded
    invoice can never approve an account. Change requests are approved/rejected by
    reviewers and mint the approved account with the deciding human stamped.
  - **Documents**: PDF/PNG/JPEG with **magic-byte signature checks**, size limits,
    per-org SHA-256 dedup, tenant-prefixed private storage, protected downloads.
  - **Processing**: durable, idempotent job state machine
    (pending → processing → completed/failed/requires_manual_input) with a
    ProcessingBackend seam — **inline by default** (no always-on worker; the Azure
    demo stays scale-to-zero), optional Celery/Redis worker locally.
  - **Fraud (rules-v0.1)**: deterministic, explainable signals — missing evidence
    (≤ medium), unverified OCR input, provenance conflicts, duplicate candidates,
    amount mismatch, **bank_account_unverified (severity floor: high, forces
    human review)**. The EVC construct stays a NULL placeholder until its phase.
  - **Investigations & audit**: investigation cases with mandatory human outcome +
    resolution summary to close, review-action trail, and an append-only
    `audit_events` reader (org_admin/auditor only).
  - 20 tables · single squashed migration (`0001_full_schema`) · 35 REST routes ·
    committed OpenAPI snapshot with a drift test.
- **Frontend** (`apps/web`, Next.js App Router **static export** for Azure Static Web
  Apps Free): landing, register, login wired to the real API, dashboard shell with
  cookie-based session resolution and role labels.
- **Docker** (`infrastructure/local/docker-compose.yml`): postgres + MinIO + API
  (container **migrates before serving**) + web dev server; optional Redis/Celery
  worker profile. Health checks and persistent volumes throughout. *Authored on a
  machine without Docker — first real run happens on a Docker-equipped machine or CI.*
- **CI** (`.github/workflows/ci.yml`): backend migrations + pytest, contracts
  typecheck, frontend build, compose YAML check.

Verified on this machine (2026-10-17): **72/72 backend tests**, frontend static build,
migration upgrade/downgrade/check cycle, and a live end-to-end acceptance flow
(register → login → vendor → approved bank account → PO → invoice upload → assess).
Plan: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Architecture at a glance

```
  Next.js App Router, static export (apps/web)          ← Azure Static Web Apps Free / next dev
        │  REST /api/v1   cookie session (browser) · Bearer JWT (programs) · CSRF on mutations
  FastAPI modular monolith (apps/api)                   ← api/v1 ──► modules ──► adapter seams
        │                              │
  SQLAlchemy 2 (portable types)   StorageProvider / OcrProvider / ProcessingBackend seams
        │                              │
  PostgreSQL (canonical)          local filesystem (default) · MinIO/S3 (compose)
  SQLite (dev/test fallback)      Azure Blob (later) · inline (default) / Celery (optional)
```

One FastAPI service with enforced internal module boundaries (ADR
[0001](docs/adr/0001-modular-monolith.md)); provider-agnostic adapter seams (ADR
[0003](docs/adr/0003-provider-agnostic-adapters.md)); cookie+CSRF auth strategy (ADR
[0005](docs/adr/0005-cookie-session-csrf.md)); durable processing (ADR
[0006](docs/adr/0006-processing-backends.md)); canonical model vocabulary (ADR
[0007](docs/adr/0007-canonical-model-vocabulary-v2.md)). Full design, module dependency
rules, the 8-step workflow, and execution profiles:
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### Repository layout

```
VeriPay/
├── apps/
│   ├── api/                 # FastAPI backend (app/, alembic/, tests/, Dockerfile, pyproject.toml)
│   └── web/                 # Next.js static-export frontend (src/, out/ after build, Dockerfile)
├── packages/
│   └── api-contracts/       # TypeScript mirrors of the REST contract (npm workspace)
├── infrastructure/
│   └── local/               # docker-compose.yml (PROFILE A) — postgres/minio/api/web (+worker)
├── scripts/                 # dev-up/dev-down helpers (compose wrappers; need Docker)
├── docs/                    # architecture, database, API, plan, ADRs, cost, security, demo
├── .github/workflows/ci.yml # CI: migrations + tests + builds
├── .env.example             # environment template (VERIPAY_* / NEXT_PUBLIC_*)
└── package.json             # npm workspaces root (web + api-contracts)
```

## Quickstart — no Docker (verified on this machine)

Prerequisites: Python 3.12 (`python`), Node 22+ and npm 11. Windows cmd.exe is fine.

### 1. Backend (FastAPI) — http://localhost:8000

From `apps/api`:

```bat
cd apps\api

python -m venv .venv
.venv\Scripts\pip install -e .[dev]

:: Create the database schema (SQLite file apps\api\veripay.db by default).
:: REQUIRED before first use — the app does not create tables on startup.
.venv\Scripts\python.exe -m alembic upgrade head

.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

(In PowerShell/bash, quote the extras: `pip install -e ".[dev]"`.)

Check: `curl http://localhost:8000/api/v1/health` →
`{"status":"ok","service":"veripay-api","version":"0.1.0"}`.
Interactive API docs: `http://localhost:8000/docs`. The committed OpenAPI snapshot
lives at `apps/api/openapi.json` and is drift-tested by `tests/test_openapi_snapshot.py`.

Defaults are dev-safe: SQLite at `apps/api/veripay.db` (gitignored), local-filesystem
document storage, HS256 JWT with a dev-only secret (production refuses to start
without a real one). See [.env.example](.env.example) for every `VERIPAY_*` setting
(copy to `.env` to override; `.env` is gitignored).

### 2. Frontend (Next.js) — http://localhost:3000

```bat
npm install            :: from the repo root — installs all npm workspaces
cd apps\web
npm run dev
```

Open http://localhost:3000 → **Create an account** (registers an organization; you
become its Organization Admin) → you land on `/dashboard`. Sign-in sets the httpOnly
session cookie; no token is ever stored in web storage. The API base URL defaults to
`http://localhost:8000` (build-time `NEXT_PUBLIC_API_BASE_URL`, see
[apps/web/.env.example](apps/web/.env.example)).

A 5-minute walkthrough of this flow: **[docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)**.

### Tests

```bat
cd apps\api
.venv\Scripts\python.exe -m pytest -q      :: 72 tests
```

## Docker path — requires Docker Desktop (compose files authored on a machine without Docker; first real run on CI/Docker-equipped machines)

```bat
docker compose -f infrastructure\local\docker-compose.yml up --build
```

Brings up postgres (migrated by the api container), MinIO (+ bucket), the API on
:8000, and the web app on :3000. Optional Celery worker:
`docker compose -f infrastructure\local\docker-compose.yml --profile worker up -d`.
Details: [docs/DEPLOYMENT_LOCAL.md](docs/DEPLOYMENT_LOCAL.md).

## Azure demo (PROFILE B) — planned, gated on owner approval

**Nothing is provisioned.** The cost analysis and step-by-step runbook (Static Web
Apps Free + Container Apps scale-to-zero + free-eligible PostgreSQL + Document
Intelligence F0 + private Blob storage, with a full teardown plan) live in
[docs/COST_ESTIMATE.md](docs/COST_ESTIMATE.md) and
[docs/DEPLOYMENT_AZURE.md](docs/DEPLOYMENT_AZURE.md). Verdict from the analysis: GO
on a ~$20 student budget with four hard conditions (confirm the PostgreSQL free
offer before creating it, keep min replicas at 0, no ACR/Standard/Marketplace
resources, one resource group torn down after the demo).

## Security

The model as implemented — cookie sessions, CSRF, RBAC, masking, upload validation,
audit provenance — with honest "not secure yet" gaps:
**[docs/SECURITY.md](docs/SECURITY.md)**.

## Documentation

[ARCHITECTURE](docs/ARCHITECTURE.md) · [DATABASE](docs/DATABASE.md) ·
[API](docs/API.md) · [IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md) ·
[SECURITY](docs/SECURITY.md) · [TESTING](docs/TESTING.md) ·
[DEPLOYMENT_LOCAL](docs/DEPLOYMENT_LOCAL.md) ·
[DEPLOYMENT_AZURE](docs/DEPLOYMENT_AZURE.md) · [COST_ESTIMATE](docs/COST_ESTIMATE.md) ·
[DEMO_GUIDE](docs/DEMO_GUIDE.md) · [ADRs](docs/adr/0001-modular-monolith.md)
