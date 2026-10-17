# VeriPay — Demo Guide (full product flow)

Status: current as of 2026-10-17 (prompts 00–07 run) · the seeded dataset below was produced by actually running `scripts/seed_demo.py` on this machine on that date; the screen flow matches the components as built (file references inline) ·
Related: [README.md](../README.md) · [MASTER_PLAN.md](MASTER_PLAN.md) · [LIMITATIONS.md](LIMITATIONS.md) · [SECURITY.md](SECURITY.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

**What you are demoing:** the whole loop — upload → extraction → assess → evidence → case close — over a tenant-isolated, fully audited decision-support API. VeriPay **never authorizes payments and never claims an invoice is genuine**; the demo's honesty is part of the pitch.

**Two ways to run it:**
- **Seeded demo (recommended):** one command fills the org with 12 synthetic invoices covering every fraud scenario, then you walk the screens.
- **Blank-tenant demo:** register a fresh org and drive everything by hand — slower, but shows org creation.

---

## 0. Before the audience arrives (~10 min, first time; ~2 min after)

**Terminal 1 — backend** (from the repo root):

```bat
cd apps\api
python -m venv .venv                       :: skip if .venv exists
.venv\Scripts\python.exe -m pip install -e ".[dev]"   :: skip if installed

:: schema — REQUIRED once; the app does not create tables on startup.
.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head

:: optional but recommended: the synthetic demo dataset (DEPLOYMENT_LOCAL.md §2.4).
:: IMPORTANT: run it from apps\api (we are already there) so it seeds the SAME
:: file uvicorn will use — the default DB URL is CWD-relative (sqlite:///./veripay.db).
.venv\Scripts\python.exe ..\..\scripts\seed_demo.py

.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Seed output to expect (verified 2026-10-17): a per-invoice assessment table ending with the logins
`admin@demo.example / finance@demo.example / reviewer@demo.example / auditor@demo.example` —
password **`VeriPay-Demo-2026!`** — and `Investigation case: CASE-2026-0003`. Idempotent: a
re-run prints a note and exits 0. For a clean slate: stop the server, delete `apps\api\veripay.db`
(+ `-wal`/`-shm`), re-run `alembic upgrade head`, then seed again.

**Terminal 2 — frontend** (from the repo root):

```bat
npm install                    :: skip if node_modules exists
npm run dev -w @veripay/web
```

Wait for `✓ Ready` → http://localhost:3000. CORS is allowlisted for `http://localhost:3000`.

**Optional — synthetic documents to upload** (already committed under `apps/api/tests/fixtures/`;
regenerate with `apps\api\.venv\Scripts\python.exe scripts\generate_fixtures.py`):
`normal_invoice.pdf` (clean), `modified_account.pdf` (altered IBAN digit), `duplicate_invoice.pdf`,
`missing_po_invoice.pdf`, `arabic_invoice.pdf` / `mixed_language.pdf` (Arabic-Indic digits),
`blurry_scan.png` (no text layer — shows the honest "no confident OCR" path). All content is fictional.

---

## 1. (0:00–1:00) Seeded dataset at a glance

Log in at http://localhost:3000 as **`admin@demo.example`** (Organization Admin) /
`VeriPay-Demo-2026!`. The session is an **httpOnly cookie** — open DevTools → Application and show
that nothing sensitive sits in localStorage.

The **Overview** page (`dashboard/page.tsx` — "the live dashboard (Prompt 05)") shows real numbers
from `GET /stats/dashboard`: every count comes verbatim from the org-scoped aggregate; when the API
is down the page shows a retryable error state, never placeholder numbers.

| Seed scenario (INV-…) | What the audience will see |
|---|---|
| INV-NW-1001/1002 | clean invoices — `low` risk, no forcing |
| INV-BT-2001 (first) | same vendor/number as the duplicate below — assessed `medium` (score 10.5) because its duplicate twin exists in the seeded org; the pair is the demo story |
| INV-NW-1003 | no printed pay-to details → `missing_evidence` (medium, R4) — a gap, **not fraud** |
| INV-BT-2001 (duplicate) | same number as the first BT-2001, altered total → `duplicate_candidate` + `amount_mismatch`, intake recorded the match and forced `needs_review` (never a 409) |
| INV-BT-2002 | missing purchase order → `missing_evidence` (medium) |
| INV-BT-2003 | pay-to account ≠ approved account → `bank_account_unverified` (**high floor**) → `needs_review` |
| INV-HD-3001 | remits to a **pending** account → same high signal |
| INV-HD-3002 | tampered amount + unverified account → `critical` → **case auto-opened (R6)** |
| INV-KF-4001 | vendor has no accounts on file → high pay-to risk (R5) |
| INV-SL-5001 | extraction below the confidence gate → `unverified_input` (low, R3) — never a mismatch |
| INV-SL-5002 | provenance disagrees with the column → `field_provenance_conflict` (medium; column wins) |

Observed seed result (2026-10-17): 12 invoices, EVC populated on all 12, **3 cases** —
`CASE-2026-0001` and `CASE-2026-0002` auto-opened (`critical`, system actor) and `CASE-2026-0003`
human-opened (`high`). Talking point: the engine aggregates honestly (a lone `high` signal can
aggregate to `medium` risk while the invoice is *still* forced to `needs_review` by the signal
itself) — the forcing rules live in ARCHITECTURE §8 and are what the audience should hear about.

## 2. (1:00–2:30) Vendors & the R5 workflow — bank accounts are human-approved

**Vendors** (`vendors/page.tsx`): 5 fictional vendors. Open one:

- **Bank accounts panel** (`accounts-panel.tsx`): 3 accounts `approved` (each with its
  verification method + reference — the R5 provenance record), 2 `pending`.
- Show that approval is **role-gated and human-only**: accounts start `pending`; only a
  `reviewer`/`org_admin` can approve, and the form **requires** a verification method +
  reference (or a supporting document). An invoice can never approve an account — there is no
  code path that flips status automatically (enforced in `apps/api/app/modules/vendors/service.py`,
  proven by `tests/test_bank_account_workflow.py`).
- To demo the approval itself: sign out, sign in as **`reviewer@demo.example`**, approve a pending
  account with a fictional reference ("callback to known contact, ticket DEMO-001").
- **Change requests panel**: requests to change pay-to details are approved/rejected by a
  reviewer — the approval mints the new account stamped with the deciding human. This is the
  control that catches invoice-borne "we changed banks" fraud (the INV-HD-3001 story).

## 3. (2:30–4:00) Upload → extraction

**Invoices → Upload** (`invoices/upload/page.tsx`):

1. Drag `apps\api\tests\fixtures\normal_invoice.pdf` onto the drop zone. Point out the
   client-side validation mirrors the API: MIME allowlist (PDF/PNG/JPEG), magic-byte checks, 10 MiB
   cap — try renaming `blurry_scan.png` to `.pdf` and show the rejection.
2. Upload runs with progress; the processing card polls the document endpoints and offers the
   **idempotent retry** (`POST /documents/{id}/process`).
3. When processing completes, the **extraction panel** shows the named fields with **evidence
   spans and confidence badges**. Honesty beat: every field shows its confidence; low/unknown
   confidence is displayed as exactly that — and the fraud engine will treat it as
   `unverified_input` rather than evidence (R3). Nothing on screen ever says "this document is
   genuine".
4. Scope note (the page says it too): this uploads + processes the **document**; invoice intake
   (number, amounts, vendor) is the separate API step so humans control what enters the registry.
   For the seeded demo, invoices already exist — this step shows the extraction machinery.
5. Optional: upload `arabic_invoice.pdf` and show Arabic-Indic digits normalized
   (`١٠٥٠٫٠٠` → `1050.00`), or `modified_account.pdf` to set up §4.

## 4. (4:00–5:30) Assess → evidence

**Invoices** (`invoices/page.tsx`): the enriched table joins each invoice with its latest
assessment and any linked case — status badges use the honest outcome vocabulary
(`invoices/_components/derive.ts`: "the owner-mandated honest outcome vocabulary (Prompt 05)":
`needs_review`, case outcomes as dispositions — never "genuine/safe").

Open the **Investigations** workspace (`investigations/workspace.tsx`) for an invoice with no
assessment yet (or re-assess an existing one via the **Assess** action):

1. **Assess** runs `POST /invoices/{id}/assess` — the EVC panel shows the explainable structure:
   six features with uncertainty states (`verified_agreement` / `confirmed_discrepancy` /
   `insufficient_evidence`), contributions, and the resulting state. Talking point: the score is a
   **consistency measure, never a fraud probability** (R2), and result states force
   `needs_review` — nothing auto-approves.
2. **Evidence** panel (`evidence-panel.tsx` + `GET /invoices/{id}/evidence`): the citable
   evidence for the invoice — matched PO, the vendor's trusted accounts **with their verification
   status**, vendor/PO/invoice/document history — every item with provenance. Contrast two seed
   invoices: INV-BT-2003 (pay-to mismatches the approved account → high signal) vs a clean one
   (agreement across the board).
3. Findings and duplicate matches are individually **dispositionable** by a human
   (`findings-panel.tsx`, `matches-panel.tsx` → `/findings/{id}/disposition`, `/matches/{id}/review`).

## 5. (5:30–7:00) Case close (R6)

**Cases** (`cases/page.tsx`) — or straight from the workspace:

- `CASE-2026-0001` / `CASE-2026-0002` were **auto-opened** by critical assessments (system actor —
  show `opened_by` on the case). `CASE-2026-0003` was opened by a human; both paths are the R6
  workflow.
- **Case detail** (`cases/detail/page.tsx`, reached as `…cases/detail?id=<uuid>`): the evidence
  view, the investigation record (**review actions** — every human decision lands in
  `review_actions`, not free-floating notes), and role-aware actions.
- Assign the case, add a note, then **Close** as `reviewer` or `org_admin`: the form **requires**
  an outcome + resolution summary — try submitting empty and show the rejection (422
  `business_rule_violation`, enforced server-side AND client-side). Closing writes the outcome;
  even `no_critical_findings` is a **disposition, not a genuineness claim** (R2).
- Talking point: critical cases cannot be closed or downgraded by any threshold, scheduler, or
  background job — only by the human recording an outcome (ARCHITECTURE §8.6).

## 6. (7:00–7:30) Audit trail

**Audit** page (`dashboard/audit/page.tsx`) — sign in as `admin@demo.example` or
**`auditor@demo.example`** (the only roles allowed; the API returns 403 for others — demonstrate
that with `finance@demo.example`). Every step just performed — logins, account approval, upload,
assessment, case actions — is an append-only `audit_events` row with ip / user-agent /
request-id. Direct DB view if you want it:

```bat
cd apps\api
.venv\Scripts\python.exe -c "import sqlite3; con=sqlite3.connect('veripay.db'); [print(r[0],'|',r[1],'|',r[2]) for r in con.execute('select occurred_at, action, actor_type from audit_events order by occurred_at')]"
```

(The seeded scratch run produced 15 events before anyone touched the UI.)

## 7. Closing talking points

- **Decision-support, never payments.** No payment rails exist anywhere in the codebase; the
  terminal workflow state is a human decision made *outside* VeriPay.
- **Explainable by construction.** EVC v1 shows its six features, weights, uncertainty states and
  contributions on screen; assessments carry ordered explanations and a feature snapshot.
- **Confidence is never laundered.** Uncertain OCR becomes `unverified_input`, not evidence (R3);
  provenance conflicts surface as signals with the human-entered column winning.
- **Absence is not fraud.** Missing POs/accounts are capped at `medium` with an explicit
  "may simply not exist in VeriPay" framing (R4) — while a *pay-to* risk on an unverified
  account is `high` and forces review (R5). The distinction is deliberate.
- **Tenant isolation everywhere.** The org comes only from the session; cross-org IDs are 404
  with no existence leak (proven across the surface by `test_tenant_isolation.py`).
- **What is NOT proven yet** — say it before the audience asks: no Docker run anywhere, no live
  PostgreSQL yet, OCR is text-layer/stub (no Tesseract binary here, Azure DI not live), metrics
  are synthetic. Full list: [LIMITATIONS.md](LIMITATIONS.md).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Register/login returns `500 internal` | Schema missing — run `alembic -c alembic.ini upgrade head` in `apps\api`, restart backend (§0) |
| Seed says "already present" | The `demo-co` org exists — either keep the data or delete `apps\api\veripay.db` (+`-wal`/`-shm`) and re-run §0 |
| Login page says the API is unreachable | Backend not running / different port. Start Terminal 1; pages degrade gracefully, nothing crashes |
| Upload rejected | MIME allowlist (PDF/PNG/JPEG), magic-byte checks, 10 MiB cap — renamed binaries are refused by design |
| Two databases with different data | The default DB URL is CWD-relative — always run uvicorn, alembic, and seed from `apps\api` (§0), or set an absolute `VERIPAY_DATABASE_URL` for all three |
| Login suddenly always "try again later" | Throttle tripped (per-IP login window or per-(IP,email) lockout). Restart the backend to clear the in-memory counters (dev only) |
| Port 8000/3000 in use | Stop the other process or move the port (set `NEXT_PUBLIC_API_BASE_URL` before building the web app; dev proxy reads it at startup) |
