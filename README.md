# VeriPay

**AI-powered invoice & payment fraud prevention for finance and procurement teams.**

> **Made by Xander + Joka** 🛡️

VeriPay ingests invoices and supporting documents, extracts structured fields with OCR,
resolves vendors, retrieves corroborating evidence, computes **explainable** fraud signals,
and routes critical inconsistencies to human investigators with a full audit trail.

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

## Status — what exists today

This repository is the **Phase 1 foundation** ("walking skeleton"), plus the full database
schema. Verified on this machine (2026-10-17):

- **Backend API** (`apps/api`, FastAPI): `GET /api/v1/health` (public) and the auth surface
  — `POST /api/v1/auth/register` (creates organization + owner), `POST /api/v1/auth/login`
  (OAuth2 password form), `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` (server-side
  token revocation). Router composition: [apps/api/app/api/v1/router.py](apps/api/app/api/v1/router.py).
- **Database**: complete schema for all product tables (organizations, users, documents,
  extracted_fields, vendors, vendor_trusted_accounts, purchase_orders, invoices,
  invoice_line_items, fraud_assessments, duplicate_matches, cases, case_notes,
  audit_logs) via Alembic migrations 0001–0006. PostgreSQL is canonical; SQLite is the
  no-Docker dev/test fallback (ADR [0002](docs/adr/0002-postgres-canonical-sqlite-dev-fallback.md)).
  Only the identity tables are exercised by endpoints today.
- **Audit trail**: registrations, logins (success **and** failure), and logouts are written
  to the append-only `audit_logs` table with ip / user-agent / request-id provenance
  ([apps/api/app/modules/audit/service.py](apps/api/app/modules/audit/service.py)).
- **Storage seam**: `StorageProvider` protocol with local-filesystem (default) and
  MinIO/S3 implementations behind a settings-driven factory
  ([apps/api/app/adapters/storage/](apps/api/app/adapters/storage/__init__.py)) — upload
  endpoints arrive in Phase 2.
- **Frontend** (`apps/web`, Next.js App Router **static export** for Azure Static Web Apps
  Free): landing, register, and login pages wired to the real API, and a dashboard shell
  (overview, vendors, invoices, investigations, settings placeholders) behind a client-side
  guard. All authorization is enforced by the API (ADR [0004](docs/adr/0004-static-export-frontend.md)).
- **Shared contracts**: `packages/api-contracts` (TypeScript mirrors of the REST contract;
  to be replaced by OpenAPI-generated types — see
  [packages/api-contracts/src/index.ts](packages/api-contracts/src/index.ts)).

**Not yet implemented** (endpoint-wise): document upload/OCR, vendor & invoice management,
fraud assessment (incl. the EVC placeholder), case workflow, and the audit-log reader API.
The plan: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

Pipeline gates (run by the infrastructure workstream; results reported, not re-run in this
documentation pass): `pytest` exit 0 · `next build` exit 0 · contracts `tsc --noEmit` pass.

## Architecture at a glance

```
  Next.js App Router, static export (apps/web)          ← Azure Static Web Apps Free / next dev
        │  REST /api/v1  (Bearer JWT)
  FastAPI modular monolith (apps/api)                   ← api/v1 ──► modules ──► adapter seams
        │                              │
  SQLAlchemy 2 (portable types)   StorageProvider / OcrProvider protocols
        │                              │
  PostgreSQL (canonical)          local filesystem (default) · MinIO/S3 (compose)
  SQLite (dev/test fallback)      Azure Blob (later)
```

One FastAPI service with enforced internal module boundaries (ADR
[0001](docs/adr/0001-modular-monolith.md)); provider-agnostic storage/OCR adapter seams
(ADR [0003](docs/adr/0003-provider-agnostic-adapters.md)). Full design, module dependency
rules, the 8-step workflow, and execution profiles:
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### Repository layout (as built)

```
VeriPay/
├── apps/
│   ├── api/                 # FastAPI backend (app/, alembic/, tests/, pyproject.toml)
│   └── web/                 # Next.js static-export frontend (src/, out/ after build)
├── packages/
│   └── api-contracts/       # TypeScript mirrors of the REST contract (npm workspace)
├── infrastructure/
│   └── local/               # docker-compose.yml (PROFILE A) — requires Docker
├── scripts/                 # dev-up/dev-down helpers (compose wrappers; need Docker)
├── docs/                    # architecture, database, API, plan, ADRs, cost, security, demo
├── .env.example             # environment template (VERIPAY_* / NEXT_PUBLIC_*)
└── package.json             # npm workspaces root (web + api-contracts)
```

(The design docs in `docs/ARCHITECTURE.md §3.1` sketch `backend/`, `frontend/`, `deploy/`;
the implemented layout uses `apps/`, `packages/`, and `infrastructure/` as above. Same
content, different directory names.)

## Quickstart — no Docker (works on this machine)

Prerequisites: Python 3.12 (`python`), Node 25 + npm 11. Windows cmd.exe is fine.

### 1. Backend (FastAPI) — http://localhost:8000

From `apps/api`:

```bat
cd apps\api

python -m venv .venv
.venv\Scripts\pip install -e .[dev]

:: Create the database schema (SQLite file apps\api\veripay.db by default).
:: REQUIRED before first use — the app does not create tables on startup;
:: without this step POST /auth/register fails with "no such table: users".
.venv\Scripts\python.exe -m alembic upgrade head

.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

(In PowerShell/bash, quote the extras: `pip install -e ".[dev]"`.)

Check: `curl http://localhost:8000/api/v1/health` →
`{"status":"ok","service":"veripay-api","version":"0.1.0"}`.
Interactive API docs: `http://localhost:8000/docs`. The OpenAPI schema is served at
`/openapi.json` (note: docs/API.md §1 says `/api/v1/openapi.json`; the committed snapshot
lives at `apps/api/openapi.json` and is drift-tested by `tests/test_openapi_snapshot.py`).

Defaults are dev-safe: SQLite at `apps/api/veripay.db` (gitignored), local-filesystem
document storage, HS256 JWT with a dev-only secret. See [.env.example](.env.example) for
every `VERIPAY_*` setting (copy to `.env` to override; `.env` is gitignored).

### 2. Frontend (Next.js) — http://localhost:3000

```bat
npm install            :: from the repo root — installs all npm workspaces
cd apps\web
npm run dev
```

Open http://localhost:3000 → **Create an account** (registers an organization and its
owner) → you land on `/dashboard`. The API base URL defaults to `http://localhost:8000`
(build-time `NEXT_PUBLIC_API_BASE_URL`, see [apps/web/.env.example](apps/web/.env.example);
both forms with/without the `/api/v1` suffix are normalized).

A 5-minute walkthrough of this flow: **[docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)**.

### Tests (optional)

```bat
cd apps\api
.venv\Scripts\python.exe -m pytest -q
```

(Reported green by the pipeline gate; not re-run during this documentation pass.)

## Docker path — requires Docker Desktop (not yet verified on this machine)

[infrastructure/local/docker-compose.yml](infrastructure/local/docker-compose.yml) defines
PROFILE A: PostgreSQL 16 (canonical DB), MinIO + bucket init, and the FastAPI API. The web
app intentionally stays on the host (`npm run dev`) — it is a static export targeting
Azure Static Web Apps.

> **Honesty note:** Docker is not installed and WSL is unavailable on the machine that
> authored this stack, so **the compose stack has never been executed**. Additionally,
> the `api` service builds from `apps/api/Dockerfile`, which does **not exist yet** (see
> the header comment in the compose file) — `--build` will fail until the backend
> workstream adds it. Validate with
> `docker compose -f infrastructure/local/docker-compose.yml config` on a Docker-equipped
> machine before the first real run.

On a Docker-equipped machine the wrappers are:

```bat
powershell -File scripts\dev-up.ps1     :: or scripts\dev-up.sh
powershell -File scripts\dev-down.ps1   :: or scripts\dev-down.sh
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System overview, business invariants, 8-step workflow, module map, execution profiles, "what is never automated" |
| [docs/DATABASE.md](docs/DATABASE.md) | Every table, constraint, migration plan, SQLite fallback notes |
| [docs/API.md](docs/API.md) | REST contract: error envelope, pagination, org-scoping rules, endpoint phases |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Phase plan 1–8 with acceptance checks and recorded deviations |
| [docs/SECURITY.md](docs/SECURITY.md) | Auth model as implemented, JWT details, tenancy, honest security gaps, product safety rules |
| [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) | 5-minute demo script for this foundation |
| [docs/DEPLOYMENT_AZURE.md](docs/DEPLOYMENT_AZURE.md) | Azure Static Web Apps / PROFILE B target |
| [docs/COST_ESTIMATE.md](docs/COST_ESTIMATE.md) | Cloud cost estimate vs. student budget |
| ADRs | [0001 modular monolith](docs/adr/0001-modular-monolith.md) · [0002 PostgreSQL canonical / SQLite fallback](docs/adr/0002-postgres-canonical-sqlite-dev-fallback.md) · [0003 provider-agnostic adapters](docs/adr/0003-provider-agnostic-adapters.md) · [0004 static-export frontend](docs/adr/0004-static-export-frontend.md) |

## Contributing notes

- Do not `git commit` / `git push` — the owner reviews and commits.
- New endpoints must satisfy every org-scoping rule in [docs/API.md §5](docs/API.md) and
  get a mandatory tenant-isolation test; reviewers check rule by rule.
- The no-go list in [docs/ARCHITECTURE.md §8](docs/ARCHITECTURE.md) is normative: no
  payment authorization, no genuineness verdicts, no confidence laundering, no
  fraud-from-absence, no automatic bank-account verification, no auto-closing critical cases.
