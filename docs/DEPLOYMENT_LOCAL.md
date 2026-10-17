# VeriPay — Local Deployment & Runbook

Status: 2026-10-17 · Written and verified on the development machine (Windows 11, cmd.exe).
Related: [ARCHITECTURE.md §6](ARCHITECTURE.md) (execution profiles) · [TESTING.md](TESTING.md) · [DEPLOYMENT_AZURE.md](DEPLOYMENT_AZURE.md) (PROFILE B) · [infrastructure/local/docker-compose.yml](../infrastructure/local/docker-compose.yml) · [scripts/](../scripts/)

There are two ways to run VeriPay locally:

- **PROFILE A — `LOCAL_FULL`**: Docker Compose (PostgreSQL + MinIO + API in containers). **Every command in §1 is UNVERIFIED** — Docker is not installed and WSL is unavailable on this machine, so this stack has never been started anywhere. Do not trust it until it has run once on a Docker-equipped machine.
- **PROFILE LOCAL — no-Docker fallback**: SQLite + local-filesystem storage + stub OCR, API and web on the host. **Every command in §2 was executed and verified on this machine on 2026-10-17** unless a step is explicitly marked otherwise.

Both profiles run the same code and adapters; only settings differ (ARCHITECTURE.md §6 configuration matrix).

---

## 1. PROFILE A — Docker Compose (`LOCAL_FULL`) — **UNVERIFIED, never executed**

> **Honesty note (repeated from the compose file's own header, `infrastructure/local/docker-compose.yml:4-7`):** Docker is not installed on the authoring machine (`docker --version` → `'docker' is not recognized as an internal or external command`, verified 2026-10-17) and WSL is unavailable, so compose can never be executed here. §1 is a walkthrough of what the file *should* do, for CI and Docker-equipped machines. Before the first real run, validate with `docker compose -f infrastructure/local/docker-compose.yml config`.

### 1.1 What the stack defines

File: `infrastructure/local/docker-compose.yml` (project name `veripay-local`). The web app is deliberately **not** containerized — it runs on the host (§1.4).

| Service | Image | Port (host) | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | **5432** | Canonical database. Dev credentials `veripay` / `veripay_dev`, DB `veripay`. Named volume `postgres-data`. Healthcheck `pg_isready -U veripay -d veripay` every 5 s. |
| `minio` | `minio/minio:latest` | **9000** (S3 API) · **9001** (web console) | Document storage. Dev credentials `veripay` / `veripay-dev-change-me`. Named volume `minio-data`. Healthcheck on `/minio/health/live`. |
| `minio-init` | `minio/mc:latest` | — | One-shot (`restart: "no"`): waits for `minio` to be healthy, then creates the `veripay-documents` bucket if missing. |
| `api` | built from `../../apps/api` + `Dockerfile` | **8000** | FastAPI + uvicorn. Depends on `postgres` and `minio` being healthy and `minio-init` having completed. Wired to PostgreSQL (`VERIPAY_DATABASE_URL=postgresql+psycopg://veripay:veripay_dev@postgres:5432/veripay`), MinIO storage (`VERIPAY_STORAGE_BACKEND=minio`), stub OCR. |
| `redis` | `redis:7-alpine` | 6379 | **Opt-in only** — lives under the `worker` compose profile; not started by default. |

**Known blocker (from reading the file, never executed):** the `api` service builds `apps/api/Dockerfile`, which **does not exist** (`infrastructure/local/docker-compose.yml:74-79` states this is deliberate — the file is owned by the backend workstream). `docker compose up --build` fails at the api build on any machine until that Dockerfile is committed.

**Second gap:** no service in the compose file runs Alembic. After the stack is up, the database schema must be created manually once (§1.4 step 4) — otherwise every auth request fails the same way the no-Docker fallback does without migrations (TESTING.md §7).

### 1.2 Start

PowerShell (Windows) or bash (CI/Unix):

```powershell
powershell -File scripts\dev-up.ps1
```
```bash
./scripts/dev-up.sh
```

Both wrap the same thing (`scripts/dev-up.ps1:7`):

```bat
docker compose -f infrastructure/local/docker-compose.yml up -d --build
```

Expected result (per the script's own output, never observed): API at http://localhost:8000 (docs at `/docs`), MinIO console at http://localhost:9001, PostgreSQL at localhost:5432.

### 1.3 Optional worker profile

```bat
docker compose -f infrastructure/local/docker-compose.yml --profile worker up -d
```

Adds `redis` on 6379. Nothing in the current code consumes it (background-worker work is future).

### 1.4 After the stack is up (unverified walkthrough)

1. `copy .env.example .env` — the compose services read their settings from the environment block inside `docker-compose.yml`; a root `.env` is not read by containers.
2. Web (host, not compose): `cd apps\web` then `npm run dev` → http://localhost:3000, or build the static export and serve `out/` on Azure Static Web Apps (PROFILE B).
3. Point the web app at the API: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` is baked at **build** time — rebuild the web app after changing it (apps/web/.env.example).
4. Create the schema once (compose runs no migrations): with PostgreSQL reachable on localhost:5432,
   `set VERIPAY_DATABASE_URL=postgresql+psycopg://veripay:veripay_dev@localhost:5432/veripay` then `alembic -c apps\api\alembic.ini upgrade head`. **Never run — `psycopg` is not installed in this machine's venv (verified: `pip list`), so this exact command cannot even start here.**

### 1.5 Stop / wipe

```powershell
powershell -File scripts\dev-down.ps1    # docker compose ... down — volumes kept
```
```bat
docker compose -f infrastructure\local\docker-compose.yml down -v    # also wipe postgres + minio data
```

### 1.6 What has actually been checked about the compose file

- YAML parses (PyYAML `safe_load`, 2026-10-17): services `api, minio, minio-init, postgres, redis` — **a syntax check only, not the compose check** (IMPLEMENTATION_PLAN.md §2 marks it the same way).
- Everything else — service startup, healthchecks, bucket creation, the api build, PostgreSQL/MinIO connectivity — has never been executed anywhere. **Status: unverified.**

---

## 2. PROFILE LOCAL — no-Docker fallback — **verified on this machine, 2026-10-17**

Same application, different settings: SQLite (dev/test fallback, ADR 0002), `LocalFilesystemProvider` for documents, stub OCR. What runs where when everything is up:

| What | How | URL |
|---|---|---|
| FastAPI API | uvicorn on the host (step 3) | http://localhost:8000 — Swagger UI at `/docs`, OpenAPI JSON at `/openapi.json` |
| Web dev server | Next.js on the host (step 5) | http://localhost:3000 |
| Database | SQLite file `apps\api\veripay.db` | created by step 2; gitignored |
| Document storage | filesystem `apps\api\data\documents` | created lazily; gitignored |

All commands below are **cmd.exe** forms. `cd /d` switches drive+directory.

### 2.0 Prerequisites (verified installed)

- Python 3.12 — `python` on PATH. (The project venv is what actually runs the backend: `apps\api\.venv`. The global Python lacks `pytest`/`alembic`.)
- Node 25 + npm 11 — `node`/`npm` on PATH.
- **No Docker, no WSL needed for this profile.**

### 2.1 One-time setup — **not re-run in this session** (artifacts already present; listed for a fresh clone)

```bat
:: 1. Node workspaces (root node_modules with apps/web + packages/api-contracts)
cd /d C:\Users\Xander\Desktop\VeriPay
npm install

:: 2. Backend venv with the API installed editable + dev tools
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Not verified here: `apps\api\.venv` and the root `node_modules` already existed on this machine, so these commands were **not executed in this session**. Everything downstream was executed against those existing artifacts (venv contents confirmed via `pip list`: fastapi, uvicorn, sqlalchemy, alembic, pytest, httpx, `veripay-api 0.1.0 editable`).

### 2.2 Create the database schema — required before first API start (verified)

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.venv\Scripts\python.exe -m alembic -c alembic.ini current
```

Verified 2026-10-17: exit 0; all six migrations (`0001_core_identity` … `0006_audit`); `current` prints `0006 (head)`. This creates `apps\api\veripay.db`.

**Two verified gotchas:**

- **Skip this step and auth breaks:** booted against a brand-new empty SQLite file, `GET /api/v1/health` still returns 200, but `POST /api/v1/auth/register` returns 500 (`no such table: users`) — the app has no auto-migration (TESTING.md §7 has the full experiment). Run step 2.2 first.
- **Stay in `apps\api` for both Alembic and uvicorn:** the default database URL is CWD-relative (`sqlite:///./veripay.db`, `app/core/config.py:29`). Running Alembic from the repo root and uvicorn from `apps\api` would create and use **two different databases**. (Alternatively pass an absolute `VERIPAY_DATABASE_URL` to both.)

### 2.3 Start the API — verified

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Verified serving on this machine (bound successfully and answered on dedicated test ports): `Uvicorn running on http://127.0.0.1:<port>` in the log, `GET /api/v1/health` → 200.

- http://localhost:8000/api/v1/health — liveness (public)
- http://localhost:8000/docs — Swagger UI (verified HTTP 200)
- http://localhost:8000/openapi.json — OpenAPI schema (verified HTTP 200; note it is at the root, **not** `/api/v1/openapi.json` as docs/API.md §1 currently says — deviation recorded in TESTING.md §7)

Stop with Ctrl+C.

**Environment variables (optional):** the defaults already match this profile — SQLite, `VERIPAY_STORAGE_BACKEND=local`, stub OCR, CORS `http://localhost:3000` (`app/core/config.py:25-61`). The backend does **not** read a `.env` file by itself (no `env_file` in `SettingsConfigDict`, `app/core/config.py:20`). Two verified mechanisms exist:

- Set real environment variables, e.g. `set VERIPAY_JWT_SECRET=...` before starting uvicorn.
- Or let uvicorn load one: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --env-file ..\..\.env` — verified working. **But list-valued settings must be JSON**: `VERIPAY_CORS_ORIGINS=["http://localhost:3000"]` boots, while the bare-URL form `VERIPAY_CORS_ORIGINS=http://localhost:3000` shown in the root `.env.example` **crashes startup** (`pydantic_settings.exceptions.SettingsError: error parsing value for field "cors_origins"` — both forms verified). Until `.env.example` is fixed, treat its `VERIPAY_CORS_ORIGINS` line as documentation of intent, not a loadable value.

### 2.4 Smoke-test the API — verified end to end

```bat
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"<password>\",\"full_name\":\"You\",\"organization_name\":\"Your Org\"}"
curl -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/x-www-form-urlencoded" -d "username=you@example.com&password=<password>"
curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
```

Verified responses on this machine: health → `{"status":"ok","service":"veripay-api","version":"0.1.0"}`; register → **201** with user (role `owner`), organization (slug derived from the name), and `access_token`; login → **200** with `access_token`; `/auth/me` → **200** with the user + organization. `/auth/logout` exists as well (revokes the presented token server-side; covered by tests, not curl-verified in this session).

Registering creates a **new organization**; there is no invite/join flow yet.

### 2.5 Start the web dev server — verified

From the repo root:

```bat
npm run dev -w @veripay/web
```

Verified on this machine: Next dev server up, HTTP 200 on `/`, `/login`, and `/dashboard`. Open http://localhost:3000, register through the UI, and you land on the dashboard. The client stores the JWT in `localStorage` under `veripay:access_token` and calls the API at `http://localhost:8000/api/v1` (default when no build-time env is set). With the API stopped, pages still render with offline hints rather than crashing (by design, apps/web/README.md §"Static-export rules" — behavior taken from the README, not re-verified by killing the API mid-session).

### 2.6 Production build of the web app — verified

From the repo root (the documented quality gate, apps/web/README.md:16-19):

```bat
node apps\web\node_modules\next\dist\bin\next build apps\web
```

Verified 2026-10-17: exit 0, 11 routes, all prerendered static; output in `apps\web\out\` (including `staticwebapp.config.json`). Locally there is **no verified command to serve `out/`** — it is the artifact Azure Static Web Apps deploys (PROFILE B). The verified way to browse locally is the dev server (§2.5).

### 2.7 Data locations and reset

| Data | Path | Reset |
|---|---|---|
| Database | `apps\api\veripay.db` (+ `-wal`/`-shm`) | delete the files, re-run step 2.2 |
| Documents | `apps\api\data\documents\` | delete the directory |
| Web build | `apps\web\out\` | regenerated by step 2.6 |

All three are gitignored (root `.gitignore`, `apps/api/.gitignore`). Everything above runs from the repo — no services are installed system-wide; Ctrl+C on the two consoles is the whole teardown.

---

## 3. Profile differences at a glance

| | PROFILE A (compose) | PROFILE LOCAL (fallback) |
|---|---|---|
| Database | PostgreSQL 16 (canonical) | SQLite file (accepted dev/test fallback, ADR 0002) |
| Document storage | MinIO (S3 API, port 9000) | Local filesystem `apps\api\data\documents` |
| OCR | stub | stub |
| Web | host (`npm run dev`) or static `out/` | host (`npm run dev`) or static `out/` |
| Migrations | manual `alembic upgrade head` against PG (§1.4) | `alembic upgrade head` on SQLite (§2.2, verified) |
| Verification status | **never executed anywhere** | **every step executed 2026-10-17** (except §2.1 one-time setup, marked) |

## 4. Honesty list — what this document does NOT claim

- No compose command (`config`, `up`, `down`) has ever run — Docker is absent (verified) and WSL unavailable. §1 is a faithful walkthrough of files, not of observed behavior.
- `apps/api/Dockerfile` does not exist; the compose api service cannot build anywhere yet.
- PostgreSQL and MinIO have never been started; `psycopg` is not installed in the venv, so even the §1.4 migration step cannot run on this machine.
- The `MinIOS3Provider` storage adapter has never been executed against anything (no boto3, no MinIO) — TESTING.md §8.
- §2.1 one-time setup commands were not re-run in this session (environment pre-existed); every other command in §2 was executed here on 2026-10-17 with the responses quoted.
- One leftover uvicorn process (started outside this session, global Python) was found listening on port 8000 during verification and was stopped; all §2 verifications were therefore performed on dedicated ports with freshly created databases, then the documented commands were run as written.
