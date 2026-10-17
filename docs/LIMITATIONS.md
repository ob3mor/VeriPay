# VeriPay — Limitations (what is true today, stated plainly)

Status: current as of 2026-10-17 (prompts 00–07 run) · every claim below was verified by reading code or running a command on this machine on that date; the verifying command or file is named inline.
Related: [MASTER_PLAN.md](MASTER_PLAN.md) · [TESTING.md](TESTING.md) (what the checks cover) · [SECURITY.md](SECURITY.md) · [ARCHITECTURE.md §8](ARCHITECTURE.md) (what is never automated)

This is the companion to TESTING.md: that file records what was **verified**; this file records what remains **unverified, unavailable, or synthetic**. Nothing here is a defect report against the invariants (ARCHITECTURE §2 holds in the code and tests); it is the honest boundary of what one Windows machine without Docker, WSL, or cloud access can prove.

---

## 1. No Docker locally — the compose stack has never executed

- **Verified:** `docker --version` → `'docker' is not recognized as an internal or external command`; `wsl --status` → "The Windows Subsystem for Linux is not installed" (both re-run 2026-10-17).
- Consequence: `docker compose config` / `up` / `down` have **never** run, no VeriPay image has ever been built, and no container of the stack (postgres, minio, api, web, redis/worker) has ever started anywhere. `infrastructure/local/docker-compose.yml` (7 services) and both Dockerfiles are code-inspected and YAML-parsed only — a syntax check, never the compose check ([TESTING.md §6](TESTING.md)).
- Every claim about container behavior (entrypoint migrates-then-serves, healthchecks, bucket init) is **code reading, not observation**. First real validation belongs to CI or a Docker-equipped machine ([DEPLOYMENT_LOCAL.md §1](DEPLOYMENT_LOCAL.md)).

## 2. Tesseract absent — skip-marked, with the absence path itself tested

- **Verified:** the full pytest run reports `SKIPPED [1] tests/test_ocr_providers.py:92: tesseract binary not installed`.
- The pixel-OCR adapter (`app/adapters/ocr/tesseract.py`) is fully coded but has never executed against a real scan on this machine. The inverse test (`test_ocr_providers.py:104`) **does** run here and proves the provider fails cleanly (`TesseractUnavailableError`) and the pipeline falls back with an explicit persisted reason — never silently.
- Practical effect for demos: PDFs with an embedded text layer extract normally (`text_layer` default); photographed/scanned images have no local pixel-OCR path — they surface honestly as unverified input, not as fabricated fields.

## 3. Azure Document Intelligence adapter: coded, never live

- `app/adapters/ocr/azure_di.py` implements the F0 free-tier contract (2-page cap never raised by code, HTTP 429 → explicit `AzureDiQuotaExceededError` with no silent retry, transient-failure backoff, lazily imported SDK) but has **never talked to the service** — no cloud access from engineering work, and the whole Azure profile (Prompt 06) is [PLAN ONLY awaiting explicit owner approval](PREFLIGHT_AZURE.md).
- Azure costs in [COST_ESTIMATE.md](COST_ESTIMATE.md) are analyst estimates against published pricing, **not** readings of any subscription's billing.

## 4. SQLite is the only dialect that has ever executed — PostgreSQL is canonical but uncontacted

- **Verified:** the pytest suite, the scratch-DB migration cycle (upgrade→downgrade→upgrade, 20 domain tables), and `alembic check` all run on SQLite ([TESTING.md §2, §5](TESTING.md)). Five retrieval tests are skip-marked "requires a live PostgreSQL engine — runs on the CI PostgreSQL leg" (`tests/test_retrieval_pg.py:19-28`); the MinIO/S3 storage adapter has never executed (no boto3, no MinIO — needs Docker).
- What has improved: `psycopg 3.3.6` is now in the venv, so `alembic upgrade head --sql` **emits PostgreSQL-dialect SQL** (verified this run — 485 lines, `Context impl PostgresqlImpl`). That is a rendering check only; **no PostgreSQL server has ever executed the schema or served a query.**
- The portability conventions (portable types, dual-dialect partial indexes, JSON-as-whole, Decimal money) are designed for this gap and partially executable-tested on SQLite, but PG-specific behavior (native UUID, JSONB, partial-index predicates on PG, timezone handling) remains unproven until the CI leg runs. Until then: **PostgreSQL is canonical by design and by declaration, not yet by observation** (ADR 0002).

## 5. Synthetic metrics are not real-world performance

- The retrieval IR metrics (Precision@K, Recall@K, MRR, nDCG@K — `app/modules/retrieval/metrics.py`) and the extraction evaluation run over **generated fixtures** (`scripts/generate_fixtures.py`, `apps/api/tests/fixtures/`) that the tests themselves label synthetic (`tests/test_retrieval_evaluation.py:1` — "a small, honestly labeled synthetic…").
- They prove the metric/ranking code is correct and that invariant behaviors hold on crafted scenarios (Arabic/English vendor variants, tampered amounts, pending accounts). They say **nothing** about accuracy on real-world invoices, real scan quality, or production load. No performance benchmark has been run: no latency/throughput numbers exist for any component.
- Likewise `scripts/seed_demo.py` data is fully fictional (synthetic vendors, `XX00DEMO…` non-IBANs) by design.

## 6. Static-export security headers exist only via the Azure SWA config

- **Verified:** `apps/web/public/staticwebapp.config.json` defines CSP, HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP — these headers are applied **only when the app is served by Azure Static Web Apps** (PROFILE B). `next dev` and any plain static file server serve `out/` **without** them; nothing in the Next.js build injects them.
- Known CSP compromise, documented in the file itself: `script-src`/`style-src` carry `'unsafe-inline'` because a pure static export cannot inject per-response nonces into Next's hydration payloads. `connect-src` is deliberately permissive (`https:` + localhost) until the demo API origin is known.
- The API itself sets **no** security-header middleware locally; headers are a deployment concern by design (ADR 0004).

## 7. Smaller boundaries worth naming (each verified)

1. **Single-process assumptions.** Rate limiting, failed-login lockout, and token/session revocation state live in process memory (`app/core/ratelimit.py`, `app/core/token_store.py`; `tests/conftest.py` resets them per test). Multi-worker uvicorn or any horizontal scaling changes their semantics — untested.
2. **No browser-level e2e.** No Playwright/Cypress exists; the prompt07 E2E drives the real app at TestClient level, and the UI was walked manually once during this run's QA (per [PREFLIGHT_AZURE.md §2](PREFLIGHT_AZURE.md)) — web↔API integration has no automated browser test.
3. **Seed-script docstring drift.** `scripts/seed_demo.py`'s header still describes the pre-EVC engine ("evc stays NULL", "1 case"); observed reality this run: EVC populated 12/12 and 3 cases (2 auto-opened critical via R6). Recorded in [IMPLEMENTATION_PLAN.md §5](IMPLEMENTATION_PLAN.md); the script is application code and was deliberately not edited in this docs-only change.
4. **CI gates are defined, not observed.** `.github/workflows/ci.yml` (pytest on SQLite **and** PostgreSQL, builds, YAML checks) parses cleanly, but its runs are owner-triggered on push; this doc set records only what executed locally.
5. **API.md §1 deviation still open.** OpenAPI is served at `/openapi.json` (FastAPI default), not `/api/v1/openapi.json`; `/docs` likewise. Verified unchanged this run (no `openapi_url` override in `app/main.py`). The committed snapshot + drift test are unaffected.
6. **In-memory OCR fallback ordering.** An unavailable configured OCR engine falls back to the stub with the reason persisted in `provider_meta` — honest, but it means a misconfigured `OCR_PROVIDER` degrades to stub output (which the confidence gate then refuses to score) rather than failing fast at startup.
7. **The `$20` Azure budget is shared.** The student subscription's credits are shared with the FlexEdit project (PREFLIGHT_AZURE.md §1) — any future Azure month must be checked against *combined* usage before Gate G1.
