# VeriPay — Local Deployment & Runbook

Status: current as of 2026-10-17 (prompts 00–07 run) · written and verified on the development machine (Windows 11, cmd.exe).
Related: [ARCHITECTURE.md §6](ARCHITECTURE.md) (execution profiles) · [TESTING.md](TESTING.md) · [LIMITATIONS.md](LIMITATIONS.md) · [DEPLOYMENT_AZURE.md](DEPLOYMENT_AZURE.md) (PROFILE B) · [scripts/](../scripts/) · [DEMO_GUIDE.md](DEMO_GUIDE.md)

> **Honesty header:** Docker is **not installed** and WSL is **unavailable** on this machine (re-verified 2026-10-17: `docker --version` → `'docker' is not recognized…`; `wsl --status` → "The Windows Subsystem for Linux is not installed"). **No compose command has ever run anywhere** — §1 is a faithful walkthrough of files, not of observed behavior. §2 (no-Docker fallback) lists only commands actually executed on this machine on 2026-10-17, each marked with what it produced.

Two ways to run VeriPay locally — same code and adapters, only settings differ (ARCHITECTURE §6 matrix):

- **PROFILE A — `LOCAL_FULL`** (§1): Docker Compose with PostgreSQL + MinIO + API + web. **UNVERIFIED — never executed, by anyone, anywhere.**
- **PROFILE LOCAL — no-Docker fallback** (§2): SQLite + local-filesystem storage + text-layer/stub OCR, API and web on the host. **Verified on this machine, 2026-10-17.**

---

## 1. PROFILE A — Docker Compose (`LOCAL_FULL`) — **UNVERIFIED, never executed**

> The compose file carries its own honesty note; CI runs a YAML **syntax** check only (`compose-yaml-validate` job), explicitly not a `docker compose config` substitute.

### 1.1 What the stack defines

File: `infrastructure/local/docker-compose.yml` (project `veripay-local`). YAML parse verified 2026-10-17 (PyYAML `safe_load`) — services: **`api`, `minio`, `minio-init`, `postgres`, `redis`, `web`, `worker`**.

| Service | Image / build | Port (host) | Notes |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | Canonical DB; dev creds `veripay`/`veripay_dev`, DB `veripay`; healthcheck `pg_isready`; named volume. |
| `minio` | MinIO | 9000 (S3) · 9001 (console) | Document storage; named volume; healthcheck. |
| `minio-init` | `mc` one-shot | — | Waits for `minio`, creates the documents bucket if missing. |
| `api` | built from `apps/api/Dockerfile` | 8000 | **Entrypoint runs `alembic upgrade head` before uvicorn** (`apps/api/docker-entrypoint.sh` — closes the old "compose runs no migrations" gap); healthcheck on `/api/v1/health`; wired to postgres + minio. |
| `web` | built from `apps/web/Dockerfile` | 3000 | Next.js dev server in compose (repo-root build context so the npm workspace resolves). |
| `redis` | `redis:7` | 6379 | **Opt-in only** — lives under the `worker` profile; not started by default. |
| `worker` | worker profile | — | Optional Celery worker over Redis for the `celery` ProcessingBackend. The default `VERIPAY_PROCESSING_BACKEND=inline` needs no worker — that is what keeps the Azure demo scale-to-zero (ADR 0006). |

### 1.2 Start / stop (never observed)

```bat
docker compose -f infrastructure\local\docker-compose.yml up -d --build
docker compose -f infrastructure\local\docker-compose.yml --profile worker up -d   :: optional worker
docker compose -f infrastructure\local\docker-compose.yml down -v                  :: also wipes data volumes
```

(`scripts/dev-up.ps1` / `dev-down.ps1`, and the `.sh` twins, wrap the same commands.)

**Expected result (per file contents, never observed):** API on :8000 (docs at `/docs`), web on :3000, MinIO console on :9001, PostgreSQL on :5432 — schema created automatically by the api container's entrypoint.

### 1.3 What has actually been checked about these files

- YAML parses (§1.1) — syntax only.
- `apps/api/Dockerfile` + `docker-entrypoint.sh` and `apps/web/Dockerfile` exist and were **code-read** (entrypoint migrates-then-serves; HEALTHCHECK on `/api/v1/health`) — **never built, never run**. Image builds are planned for CI (Docker-absent machine; PREFLIGHT_AZURE.md §2).
- Everything else — service startup, healthchecks, bucket init, PG/MinIO connectivity, the migrations running inside the api container — has **never been executed**. Before the first real run on a Docker-equipped machine: `docker compose -f infrastructure/local/docker-compose.yml config`.

---

## 2. PROFILE LOCAL — no-Docker fallback — **verified on this machine, 2026-10-17**

| What | How | URL / path |
|---|---|---|
| FastAPI API | uvicorn on the host (§2.4) | http://localhost:8000 — Swagger UI `/docs`, OpenAPI JSON at `/openapi.json` (app root, not `/api/v1/openapi.json` — known API.md §1 deviation) |
| Web | Next.js on the host (§2.5) | http://localhost:3000 |
| Database | SQLite file `apps\api\veripay.db` | created by §2.2; gitignored |
| Documents | filesystem `apps\api\data\documents` | created lazily; gitignored |
| OCR | `text_layer` default (reads embedded PDF text); `stub` fallback | `app/core/config.py` |

All commands are cmd.exe forms; `cd /d` switches drive+directory.

### 2.1 Prerequisites

- Python 3.12 — `python` on PATH. The backend runs on the **project venv** `apps\api\.venv` (the global Python lacks pytest/alembic).
- Node 25 + npm 11.
- **No Docker, no WSL needed.**

### 2.2 One-time setup — **not re-run this session** (artifacts pre-existed; listed for a fresh clone)

```bat
cd /d C:\Users\Xander\Desktop\VeriPay
npm install                                   :: npm workspaces root (apps/web + packages/api-contracts)

cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 2.3 Create the schema — required before first API start (**verified**)

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.venv\Scripts\python.exe -m alembic -c alembic.ini current          :: 0003 (head)
```

Verified this run from the repo root with an explicit scratch URL (equivalent cycle: upgrade → `0003 (head)` → downgrade base → upgrade, exit 0, 20 domain tables — TESTING.md §5.2). Skip this and every DB-backed call fails while `/health` still returns 200 — the app never creates tables itself.

**Two verified gotchas (still true):**

- **The default DB URL is CWD-relative** (`sqlite:///./veripay.db`, `app/core/config.py`). Run Alembic and uvicorn **from the same directory** (`apps\api`), or pass an absolute `VERIPAY_DATABASE_URL` to both — otherwise you create two different databases.
- **List-typed settings need JSON when set through the environment.** `VERIPAY_CORS_ORIGINS=["http://localhost:3000"]` boots; the bare-URL form shown at `.env.example:96` fails (`SettingsError`) when loaded via `uvicorn --env-file` (verified in an earlier session this date; config unchanged — `config.py:125` is still `list[str]`, no `env_file` in Settings). The no-Docker defaults need no env file at all.

### 2.4 Optional: seed the demo dataset (**verified this run**)

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe ..\..\scripts\seed_demo.py
```

Runs the REAL service paths (human account approval, deterministic fraud engine, case service) and writes the fully synthetic dataset: 5 vendors, 5 bank accounts (3 approved / 2 pending), 8 POs, **12 invoices** with EVC assessments, **3 investigation cases** (2 auto-opened `critical` + 1 human-opened), 15 audit events. Logins: `admin@demo.example` / `finance@demo.example` / `reviewer@demo.example` / `auditor@demo.example` — password `VeriPay-Demo-2026!`. Idempotent: re-running prints a note and exits 0. **Important:** it seeds whatever DB the CWD-relative default (or `VERIPAY_DATABASE_URL`) points at — run it from the same directory context as the server (§2.3 gotcha), or delete `veripay.db` first for a clean slate. Full scenario table: [DEMO_GUIDE.md](DEMO_GUIDE.md).

### 2.5 Start the API

```bat
cd /d C:\Users\Xander\Desktop\VeriPay\apps\api
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

(Verified in earlier sessions this date; not re-run in this docs run — the suite's TestClient exercises the same app, and the prompt07 E2E test proves the full flow, TESTING.md §8.) Stop with Ctrl+C.

### 2.6 Start the web dev server

```bat
cd /d C:\Users\Xander\Desktop\VeriPay
npm run dev -w @veripay/web
```

Verified in earlier sessions this date (HTTP 200 on `/`, `/login`, `/dashboard`). Auth is the httpOnly `veripay_session` cookie + `X-CSRF-Token` header — **no tokens in web storage**. With the API down, pages render error/empty states instead of crashing (by design, `apps/web/src/components/error-state.tsx`).

### 2.7 Production build (static export) — **verified this run**

```bat
node apps\web\node_modules\next\dist\bin\next build apps\web
```

Exit 0 — 14 routes, all static, output in `apps\web\out\` **including `staticwebapp.config.json`** (the CSP/security-headers file that only Azure Static Web Apps serves; local static hosting serves no such headers — LIMITATIONS.md §7). There is no verified local command to serve `out/`; locally, browse via the dev server (§2.6).

### 2.8 Data locations and reset

| Data | Path | Reset |
|---|---|---|
| Database | `apps\api\veripay.db` (+ `-wal`/`-shm`) | stop server, delete files, re-run §2.3 (re-seed with §2.4) |
| Documents | `apps\api\data\documents\` | delete the directory |
| Web build | `apps\web\out\` | regenerated by §2.7 |

All three are gitignored; nothing installs system-wide; Ctrl+C on the two consoles is the whole teardown.

---

## 3. Profile differences at a glance

| | PROFILE A (compose) | PROFILE LOCAL (fallback) |
|---|---|---|
| Database | PostgreSQL 16 (canonical) | SQLite file (accepted dev/test fallback, ADR 0002) |
| Document storage | MinIO (S3 API) | Local filesystem |
| OCR | `text_layer`/`stub` | `text_layer`/`stub` |
| Migrations | api container entrypoint runs `alembic upgrade head` | §2.3 (manual, verified) |
| Worker | optional `worker` profile (Celery+Redis) | none needed (`inline` default) |
| Verification status | **never executed anywhere** | **verified 2026-10-17** (§2.2/§2.5/§2.6 marked where not re-run) |

## 4. Honesty list — what this document does NOT claim

- **No compose command (`config`, `up`, `down`) has ever run** — Docker absent (verified this run), WSL unavailable. §1 describes files, not behavior. No VeriPay Docker image has ever been built.
- **PostgreSQL and MinIO have never been started** by anyone; `psycopg` is installed now (so PG-dialect offline SQL emits), but no PG server has executed the migrations — the CI leg is the first live-PG contact (TESTING.md §9).
- §2.2 one-time setup and §2.5/§2.6 server starts were verified in earlier sessions on this date and **not re-run in this docs run** — each is marked; §2.3, §2.4, §2.7 and all YAML/parse checks were (re-)executed this run.
- A live browser walkthrough of the UI was done earlier on this date during the run's QA (per PREFLIGHT_AZURE.md §2); it was **not** re-driven in this docs run — the automated equivalent is `test_prompt07_e2e_happy_path.py` (green this run).
