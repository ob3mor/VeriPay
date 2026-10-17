# VeriPay — Testing & Verification

Status: reflects the repo as of 2026-10-17 · every result below was produced by running the named command on this machine on that date, unless explicitly marked otherwise.
Related: [ARCHITECTURE.md](ARCHITECTURE.md) (§2 invariants, §9 testing) · [API.md](API.md) · [DEPLOYMENT_LOCAL.md](DEPLOYMENT_LOCAL.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

Environment the checks ran in: Windows 11, cmd.exe, Python 3.12 (project venv at `apps/api/.venv`), Node 25 + npm 11. **Docker is not installed and WSL is unavailable** — everything that requires Docker/PostgreSQL/MinIO is marked as not run, not as passed.

The backend interpreter is the **venv**, not the global Python: the global Python 3.12 on this machine has no `pytest` and no `alembic` installed (`python -m pytest` → `No module named pytest`; `python -m alembic` → `No module named alembic`). All commands below use `apps\api\.venv\Scripts\python.exe`.

---

## 1. Gate results (summary)

| Gate | Command | Pipeline result (reported) | Re-run here 2026-10-17 | Result |
|---|---|---|---|---|
| Backend pytest | see §2 | exit 0 | **yes** | **42 passed**, 1 third-party warning, exit 0 |
| Frontend production build | see §3 | exit 0 | **yes** | **11 routes, all static**, exit 0 |
| Contracts tsc | see §4 | passed | **yes** | exit 0, no output |

All three pipeline gates were independently reproduced locally in this session; the outputs recorded in §2–§4 are from those runs.

---

## 2. Backend test suite (pytest)

**Command** (from repo root, cmd.exe):

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m pytest -q
```

**Result (2026-10-17):**

```
..........................................                               [100%]
42 passed, 1 warning in 13.49s
exit code 0
```

The one warning is a third-party deprecation inside `fastapi`'s own `testclient` import (`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`), not VeriPay code.

**Test environment:** `tests/conftest.py` pins `VERIPAY_ENV=test` and an in-memory SQLite (`sqlite://` with `StaticPool`) **before** any `app` import (settings and the engine are built at import time — `app/core/db.py:93`), creates and drops the schema around every test, and resets the in-process throttle/lockout/revoked-token registries between tests (`conftest.py:34-45`). Throttle limits are lowered for tests (login 10/min, register 4/min) so the rate-limit tests can exhaust real windows.

**Inventory** — 42 tests across 13 test modules (plus `conftest.py` fixtures and `helpers.py` utilities; `pytest --collect-only -q` → `42 tests collected`):

| File | Tests | Behaviors covered |
|---|---|---|
| `tests/test_health.py` | 1 | `GET /api/v1/health` public, 200 with `status`/`service`/`version` (API.md §4 shape). |
| `tests/test_auth_flow.py` | 6 | register→login→me happy path; duplicate email → 409 `conflict`; missing fields → 422 versioned `validation_error` envelope; unknown email and wrong password produce **identical** 401s (no account enumeration); `/auth/me` requires a token; `users.last_login_at` updated on login. |
| `tests/test_token_security.py` | 4 | missing, garbage, tampered, and expired bearer tokens all → 401 `unauthorized` envelope. |
| `tests/test_auth_logout.py` | 4 | `POST /auth/logout` revokes the presented token's jti server-side (later `/me` → 401); revocation is scoped to that token only (other tokens keep working); logout requires auth; logout writes a `user.logout` audit row. |
| `tests/test_auth_throttle.py` | 7 | per-IP sliding windows on register (409 duplicate-email attempts still consume budget) and login (distinct emails, so the per-account lockout is not what trips); failed-login lockout per (IP, email) rejects even the **correct** password while active; a successful login resets the failure streak; lockout is per email (other accounts unaffected); sliding-window burst→refuse→recover; lockout records, recovers after the window, and clears. |
| `tests/test_auth_disabled.py` | 3 | a `disabled` user cannot log in (401, generic message), the failure is audited (`user.login_failed`, never a success row), and the disabled user's previously issued valid token is rejected on every request. |
| `tests/test_audit.py` | 3 | `audit_logs` rows written for register, successful login, **and** failed login with org/actor/entity/detail; failed login for an unknown email carries no tenant; `password_hash` never appears in audit detail. |
| `tests/test_audit_context.py` | 3 | audit events carry `ip`/`user_agent`/`request_id`; the failed-login audit `request_id` matches the error envelope's; the error envelope carries the `X-Request-ID` header value. |
| `tests/test_org_scoping.py` | 1 | two organizations register; each principal's `/auth/me` reports only its own org (slug asserted); JWT `org_id`/`sub` claims are distinct per org — the tenant comes from the token only (API.md §5 rules 1–2). |
| `tests/test_password_storage.py` | 1 | `users.password_hash` is a bcrypt hash (`$2b$…`), never plaintext; `verify_password` accepts the true password and rejects a wrong one. |
| `tests/test_config.py` | 5 | dev defaults accepted; production refuses the built-in dev secret and short secrets (`ValidationError`); a strong secret is accepted; spelling variants (`PRODUCTION`, `Production`, `PROD`, `prod`, whitespace) cannot bypass the production guard; non-production variants normalize without becoming production. |
| `tests/test_storage_local.py` | 3 | `LocalFilesystemProvider` contract: roundtrip save/open/delete with `exists`, `StorageObjectNotFound` on missing keys, delete idempotence; tenant-prefixed key builder; `../` path traversal rejected with `ValueError` and nothing written outside the root; the settings factory defaults to the local provider. |
| `tests/test_openapi_snapshot.py` | 1 | the committed `apps/api/openapi.json` snapshot equals the live FastAPI schema (drift guard, so type generation and static builds never need a running backend — API.md §1). |
| `tests/helpers.py` | — | shared fixtures/helpers (`register`, `login`, `bearer`, `db_query`); not tests. |

**What the suite proves about the six business invariants (ARCHITECTURE §2):** Phase 1 implements identity, tenancy, audit, and the storage seam only — the implemented API surface is exactly `/health` + `/auth/{register,login,me,logout}` (`app/api/v1/routes/` contains only `auth.py` and `health.py`). Accordingly:

- **R1 (never auto-authorize payments) / R2 (never claim an invoice is genuine):** trivially satisfied today — no payment or genuineness concept exists anywhere in the code; there is nothing to test yet, and the suite does not test it.
- **R3 (uncertain OCR), R4 (absence ≠ fraud), R5 (bank-account verification), R6 (mandatory human review):** the corresponding modules (`documents`, `extraction`, `fraud`, `cases`, `vendors`) do not exist yet (`app/modules/` contains only `audit` and `auth`), so none of these invariants has direct test coverage yet. Their test obligations arrive with Phases 2–5 per IMPLEMENTATION_PLAN.md §3.
- What **is** covered today that later phases build on: org-scoped identity from the token (test_org_scoping), append-only audit trail with request correlation (test_audit*, the Phase-6 R5/R6 evidence base), no-plaintext-password storage, token revocation, and abuse throttling.

---

## 3. Frontend production build (static export)

**Command** (from repo root — this is the quality gate documented in `apps/web/README.md:16-19`; it avoids npm-workspaces hoisting issues):

```bat
node apps\web\node_modules\next\dist\bin\next build apps\web
```

**Result (2026-10-17):** exit 0.

```
▲ Next.js 16.4.2 (Turbopack)
✓ Compiled successfully in 433ms
  Running TypeScript ...
  Finished TypeScript in 1816ms ...
✓ Generating static pages using 12 workers (11/11) in 945ms

Route (app)                     — all 11 marked ○ (Static) prerendered as static content
  / , /_not-found , /dashboard , /dashboard/investigations , /dashboard/invoices ,
  /dashboard/settings , /dashboard/vendors , /icon.svg , /login , /register
```

What it covers: full TypeScript compilation of `apps/web`, and a successful static export (`output: "export"`) — the exact artifact Azure Static Web Apps serves (PROFILE B, ADR 0004). Output lands in `apps/web/out/` (including `staticwebapp.config.json` copied from `public/`).

Equivalent workspace form: `npm run build -w @veripay/web` (apps/web/package.json:8). Not separately re-run; the gate command above is the one the README designates.

**Typecheck-only form** (also verified, exit 0):

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\web
npm run typecheck
```

**Dev-server smoke (manual, this session):** `npm run dev -w @veripay/web` from the repo root, then `curl` → HTTP 200 on `/`, `/login`, `/dashboard`. This is a manual probe, not an automated test.

---

## 4. API contracts (TypeScript)

**Command** (from repo root — exact form used by the pipeline, `package.json:9`):

```bat
node node_modules\typescript\bin\tsc --noEmit -p packages\api-contracts
```

**Result (2026-10-17):** exit 0, no output (clean).

npm-script form `npm run typecheck:contracts` — also run, exit 0.

What it covers: `packages/api-contracts` (hand-mirrored TS types for the REST API, per its package.json a scaffolding placeholder to be replaced by OpenAPI-generated types). It checks types compile; it does **not** check runtime agreement with the backend (that is the OpenAPI snapshot drift test, §2, plus future typegen per API.md §1).

---

## 5. Alembic migration checks

### 5.1 Offline SQL emission (`--sql`) — verified, SQLite dialect

**Command** (from repo root):

```bat
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head --sql
```

**Result (2026-10-17):** exit 0 — 408 lines of static SQL covering all six migrations (`0001_core_identity` → `0006_audit`), ending in the `alembic_version` bump to `'0006'`.

**Dialect caveat (verified failure, documented honestly):** the SQL emitted is **SQLite-dialect** SQL, because `alembic/env.py:26-27` takes the URL from app settings, whose default is `sqlite:///./veripay.db` (config.py:29). Attempting to emit PostgreSQL-dialect SQL by setting `VERIPAY_DATABASE_URL=postgresql+psycopg://…` **fails on this machine**:

```
sqlalchemy.exc.ModuleNotFoundError: No module named 'psycopg'
```

Root cause: `alembic/env.py:17-19` imports `app.models` → `app.core.db`, and `app/core/db.py:93` creates the engine **at import time**, so the DBAPI driver is required even in offline mode (which never connects). `psycopg` is not installed in the venv (`pip list` confirms). Consequence: **this check validates migration structure on SQLite only; PostgreSQL-dialect SQL and any live PG migration have never been produced or run** — the first real PostgreSQL validation must happen on a Docker/CI machine (PROFILE A).

### 5.2 Migration executability smoke (live upgrade, scratch SQLite) — verified

**Command** (from repo root; scratch file outside the repo):

```bat
set VERIPAY_DATABASE_URL=sqlite:///C:/Users/Xander/AppData/Local/Temp/veripay_scratch_mig.db
apps\api\.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head
```

**Result (2026-10-17):** exit 0. All six migrations ran (`Running upgrade -> 0001 … 0005 -> 0006`), `alembic_version` = `0006`, and the resulting schema contains exactly the expected tables: `organizations`, `users`, `documents`, `extracted_fields`, `vendors`, `vendor_trusted_accounts`, `purchase_orders`, `invoices`, `invoice_line_items`, `fraud_assessments`, `duplicate_matches`, `cases`, `case_notes`, `audit_logs` (+ `alembic_version`). This is an **executability check on SQLite, not a PostgreSQL substitute** (IMPLEMENTATION_PLAN.md §2 marks it the same way).

The same command from inside `apps\api` (`cd apps\api && .venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head`, default URL) was also run — exit 0, `alembic current` → `0006 (head)`. This is the command DEPLOYMENT_LOCAL.md §3.2 uses, because the default URL is CWD-relative (`sqlite:///./veripay.db`): run Alembic and uvicorn **from the same directory** or you create two different databases.

---

## 6. Compose file — syntax check only

`docker compose config` has **never been executed** — Docker is not installed (`docker --version` → `'docker' is not recognized as an internal or external command`) and WSL is unavailable. The only check ever run against `infrastructure/local/docker-compose.yml` is a YAML parse (the fallback IMPLEMENTATION_PLAN.md §2 explicitly labels "a syntax check, **not** the compose check"):

```bat
apps\api\.venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(open('infrastructure/local/docker-compose.yml', encoding='utf-8')); print(sorted(d['services']))"
```

**Result (2026-10-17):** parses cleanly; services found: `api, minio, minio-init, postgres, redis`.

Additional structural fact (from reading the file, not from execution): the `api` service builds from `apps/api/Dockerfile`, **which does not exist** (`infrastructure/local/docker-compose.yml:74-79` documents this as deliberate — the file is owned by the backend workstream). `docker compose up --build` would fail at the api build even on a Docker-equipped machine until that Dockerfile lands.

---

## 7. Manual API smoke (live server) — verified, with a required first step

**Ordering matters: run migrations before first API start.** Verified experimentally in this session:

1. Booted uvicorn against a brand-new empty SQLite file → `GET /api/v1/health` returned 200 (health touches no tables), but `POST /api/v1/auth/register` returned **500** with the versioned `internal` envelope. Server log: `sqlite3.OperationalError: no such table: users` (raised at `app/modules/auth/service.py:70`, via `app/api/v1/routes/auth.py:83`). There is no `create_all` in application code (only `tests/conftest.py:28` uses it) — schema comes from Alembic only.
2. Ran `alembic -c alembic.ini upgrade head` against the same file (exit 0, all six migrations), restarted the server, and retried: `register` → **201**, `login` → **200**.

**Verified smoke sequence** (see DEPLOYMENT_LOCAL.md §3 for the full walkthrough): `uvicorn app.main:app` serving `GET /api/v1/health` → `{"status":"ok","service":"veripay-api","version":"0.1.0"}`; `POST /api/v1/auth/register` → 201 with user/org/access_token; `POST /api/v1/auth/login` (form-encoded) → 200; `GET /api/v1/auth/me` with the bearer token → 200 with the registered user + org; `/docs` → 200.

**One deviation from docs/API.md §1 found during the smoke:** the OpenAPI schema is served at `/openapi.json` (FastAPI default; verified 200), **not** at `/api/v1/openapi.json` (verified 404). The committed snapshot drift test is unaffected (it calls `app.openapi()` directly, `test_openapi_snapshot.py:12`). API.md should be corrected or the path overridden in a future change — recorded here so nobody debugs a nonexistent endpoint.

**`.env` handling finding (verified):** the backend does **not** read a `.env` file on its own — `SettingsConfigDict(env_prefix="VERIPAY_", extra="ignore")` (`app/core/config.py:20`) declares no `env_file`. `uvicorn --env-file <path>` works as a loading mechanism (verified: a distinctive `VERIPAY_CORS_ORIGINS` in the file was reflected in CORS preflight responses), **but** complex fields must be JSON: `VERIPAY_CORS_ORIGINS=http://localhost:3000` (the bare-URL form shown in the root `.env.example:44`) crashes startup with `pydantic_settings.exceptions.SettingsError: error parsing value for field "cors_origins"`, while the JSON form `VERIPAY_CORS_ORIGINS=["http://localhost:3000"]` boots fine (both verified). For the no-Docker fallback no env file is needed at all — the defaults already match it (SQLite, local storage, stub OCR, CORS `localhost:3000`).

---

## 8. Coverage gaps (honest list)

1. **No end-to-end tests.** There is no browser/e2e runner in the repo (no Playwright/Cypress/nightwatch anywhere, no test script in `apps/web/package.json`). The frontend is verified only by `tsc` + the production build (§3) and a manual dev-server HTTP probe. Nothing tests web ↔ API integration; the auth pages were never driven against a live backend by an automated test.
2. **No frontend unit tests.** `apps/web` has no test runner, no test files, and no test script.
3. **No Docker-validated compose.** `docker compose config` and any `docker compose up` have never run (Docker absent — verified). Compose is only YAML-parsed (§6), and the api service cannot build anywhere until `apps/api/Dockerfile` exists (§6). PostgreSQL, MinIO, the mc bucket init, and the worker/redis profile have never been started by anyone.
4. **The S3/MinIO storage adapter is untested.** `app/adapters/storage/s3.py` (MinIOS3Provider) has zero test coverage: it lazily imports `boto3`, which is not installed in the venv (`pip list`), and exercising it needs a live MinIO — which needs Docker. The shared storage contract suite (roundtrip/not-found/idempotent-delete, ARCHITECTURE §7.1) currently covers only `LocalFilesystemProvider` (test_storage_local.py). The MinIO provider was written to the same protocol but has never been executed against anything.
5. **PostgreSQL is unexercised everywhere.** pytest runs on in-memory SQLite; the migration smoke is SQLite; PostgreSQL-dialect offline SQL cannot even be emitted here (§5.1). PG-specific behavior — native UUID, JSONB, partial indexes (`postgresql_where`), `Numeric` rounding, timezone handling — is written portably (app/core/db.py:1-10 conventions) but has never run against PostgreSQL.
6. **In-process rate-limiting/lockout/revocation state is untested across processes.** The registries (`app/core/ratelimit.py`, `app/core/token_store.py`) live in process memory (conftest.py:34-45 resets them per test). Multi-worker deployments, restarts, or any horizontally scaled deployment change their semantics; nothing tests that. Single-process uvicorn is the assumed local shape.
7. **No CI executes these gates.** The pipeline gate results quoted in §1 were reported by the pipeline and re-run manually on this machine on 2026-10-17; there is no committed CI workflow in the repo running them automatically.
8. **Tenant-isolation coverage is currently one endpoint deep.** test_org_scoping.py proves token-based org separation at the identity layer; the per-resource isolation matrix (API.md §5 rule 6) has no resources yet and arrives with Phases 2–6.
9. **`.env.example` CORS line is unusable as-is** if ever loaded into the environment (§7 finding) — either fix the example to JSON-array form or add `env_file` support to Settings; recorded here because documentation-only workstreams cannot edit application code.
