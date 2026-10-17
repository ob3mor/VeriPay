# VeriPay — 5-Minute Demo Guide (Phase 1 foundation)

Status: 2026-10-17 · every command below was executed and passed on this machine (Windows,
cmd.exe, no Docker) on that date ·
Related: [README.md](../README.md) · [SECURITY.md](SECURITY.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

**What you are demoing:** the foundation — a tenant-aware identity layer (register →
login → dashboard) over a modular-monolith FastAPI backend with an append-only audit
trail, and a statically-exported Next.js frontend. Document upload, OCR, fraud signals,
and cases come later; the demo's honesty ("here is the ground the product stands on, and
here is the audit spine it grows around") is part of the pitch.

---

## 0. Before the audience arrives (one-time setup, ~5 min)

**Terminal 1 — backend** (from `apps\api`):

```bat
cd apps\api
python -m venv .venv                     :: skip if .venv already exists
.venv\Scripts\pip install -e .[dev]      :: skip if already installed
.venv\Scripts\python.exe -m alembic upgrade head    :: creates the schema (REQUIRED once)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

> The `alembic upgrade head` step matters: the app does **not** create tables on startup.
> Without it, registration fails with `500 internal` ("no such table: users"). If a
> previous demo left data behind and you want a clean slate, stop the server, delete
> `apps\api\veripay.db`, re-run `alembic upgrade head`, and restart.

Check: `curl http://localhost:8000/api/v1/health` →
`{"status":"ok","service":"veripay-api","version":"0.1.0"}`.

**Terminal 2 — frontend** (from the repo root):

```bat
npm install          :: skip if node_modules already exists
cd apps\web
npm run dev
```

Wait for `✓ Ready` — Next.js serves http://localhost:3000. CORS is already allowlisted
for `http://localhost:3000`.

Pick demo credentials now (used in step 2): any email like `dana@acme.example`, password
`Demo-2026-Safe` (min 8 chars), full name, and organization name — e.g. "Acme GmbH".

---

## 1. (0:00–1:00) Show the API surface — optional but quick

Open **http://localhost:8000/docs** (FastAPI's interactive docs, verified serving).
Point out the five Phase 1 endpoints (`/health`, `/auth/register`, `/auth/login`,
`/auth/me`, `/auth/logout`) and the API description banner: *"this API never authorizes
payments and never claims an invoice is genuine"* — the product's constitution lives in
the code, not a slide.

## 2. (1:00–2:30) Register an organization

Open **http://localhost:3000** → **Create an account** (`/register`). Fill in full name,
organization name, email, password (+ confirm). Submit.

- What happened: `POST /api/v1/auth/register` created **a new organization** (with a
  URL-safe slug like `acme-gmbh`) and its **owner** user, then returned a signed JWT.
  The client stored the token and redirected to `/dashboard`.
- Talking point: registration is org-creation, not sign-up-to-a-shared-pool; every
  future row in the system will be stamped with this organization's id.

## 3. (2:30–3:00) The dashboard

On `/dashboard` (Overview):

- The **Signed-in user** card is **live data** — email, full name, role `owner`,
  organization name/slug, user id — fetched from `GET /auth/me` over a Bearer JWT.
- The four stat cards ("Invoices needing review", "Open investigations", …) are
  **deliberate placeholders** showing the phase in which each goes live, and the page
  says so. Honest scaffolding — nothing pretends to be real data.
- Sidebar: Vendors, Invoices, Investigations, Settings — shells listing the API surface
  they will consume (docs/API.md §6).

## 4. (3:00–3:45) Sign out, wrong password, sign back in

1. Click **Sign out** (top bar). Two things happen: the local token is cleared **and**
   `POST /auth/logout` revokes that token **server-side** — a copied token is now dead
   even though its 8-hour expiry hasn't passed.
2. At `/login`, first enter a **wrong password** → an inline error. Mention: the same
   message appears for unknown email, wrong password, and disabled account — no account
   enumeration. (It also just wrote a `user.login_failed` audit row — shown next.)
3. Sign in correctly → back on the dashboard.

## 5. (3:45–4:45) The audit trail in the database

**Terminal 3** (from `apps\api`; the dev DB is the SQLite file `veripay.db`):

```bat
cd apps\api
.venv\Scripts\python.exe -c "import sqlite3; con = sqlite3.connect('veripay.db'); [print(r[0], '|', r[1], '|', r[2]) for r in con.execute('select occurred_at, action, actor_type from audit_logs order by occurred_at')]"
```

You will see, in order: `user.registered`, `user.logout`, `user.login_failed`,
`user.login_succeeded` — every step you just performed, appended by the audit service.

To show the forensics inside one row (ip, user agent, request id):

```bat
.venv\Scripts\python.exe -c "import sqlite3; con = sqlite3.connect('veripay.db'); r = con.execute(\"select detail from audit_logs where action='user.login_failed' order by occurred_at desc limit 1\").fetchone(); print(r[0])"
```

Talking points while this is on screen:

- **Append-only by design** — no update/delete paths exist for audit rows.
- **Correlated**: the row's `request_id` matches the `X-Request-ID` response header and
  the `request_id` in any error envelope — a failed login can be attributed and traced.
- This trail is the backbone of the fraud product: in later phases every upload,
  assessment, and human decision lands here with the same discipline.

(If you prefer a GUI, any SQLite browser works against `apps\api\veripay.db` — commands
above are the zero-dependency path.)

## 6. (4:45–5:00) Talking points to close

- **Decision-support, never payments.** No payment rails exist anywhere in the codebase,
  and none may: the terminal workflow state is a human decision made *outside* VeriPay.
- **Explainable by construction.** Future assessments carry ordered human-readable
  explanations, feature snapshots, and confidence-gated inputs — no black-box verdicts,
  and never a "this invoice is genuine" claim.
- **Tenant isolation from day one.** The organization comes only from the JWT, is
  cross-checked against the user row on every request, and every future table is
  org-scoped with mandatory isolation tests; cross-org access is designed to 404 (no
  existence leak).
- **The API is the security perimeter.** The frontend is a pure static export (Azure
  Static Web Apps Free); route "protection" there is UX only — all authorization is
  enforced server-side.
- **Honest limitations are documented** — [docs/SECURITY.md §7](SECURITY.md) lists what
  is not secure yet (token in localStorage with mitigations, per-process throttling, …).

## What comes next (the roadmap this demo sets up)

| Phase | Delivers |
|---|---|
| 2 | Document upload (sha256 dedup, storage adapters), OCR protocol + stub, `extracted_fields` with **confidence gating** |
| 3 | Vendors, purchase orders, invoices; **human-only trusted-account verification** (new bank account = independent verification or `high` severity review) |
| 4 | Fraud features + explainable risk assessments (`bank_account_unverified`, `amount_mismatch`, `duplicate_candidate`…), EVC placeholder |
| 5 | Investigation **cases** — critical assessments auto-open a case; close requires a human outcome + summary |
| 6 | Audit-log reader (owner/admin), dashboards |
| 7 | Azure deployment runbooks (Static Web Apps + containerized API) |
| 8 | Hardening: full tenant-isolation matrix, security pass |

Full plan: [docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Register returns `500 internal` | Schema missing — run `alembic upgrade head` in `apps\api`, restart backend (see §0) |
| Login page shows "Can't reach the API at http://localhost:8000/api/v1" | Backend not running (or on another port). Start Terminal 1. The frontend degrades gracefully — nothing crashes |
| `email already exists` (409) | A previous demo run registered that address — use a fresh email or reset the DB (§0) |
| Login suddenly always says "try again later" | You tripped the throttle (20 login/min/IP or 5 failed attempts → 15-min lockout per IP+email). Restart the backend to clear the in-memory counters (dev only) |
| Port 8000/3000 already in use | Another process owns it — stop it or run uvicorn with `--port 8001` (and set `NEXT_PUBLIC_API_BASE_URL` accordingly before `npm run dev`) |
