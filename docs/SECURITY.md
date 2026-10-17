# VeriPay — Security (as implemented, Phase 1)

Status: 2026-10-17 · describes the code actually in the repo (apps/api, apps/web) ·
Related: [API.md §5](API.md) (org-scoping rules) · [ARCHITECTURE.md §8](ARCHITECTURE.md) (what is never automated) · [ADR 0004](adr/0004-static-export-frontend.md)

**Read this as an honest status report, not a security certification.** §7 lists the gaps
that remain open. The pipeline gates (pytest, `next build`, contracts `tsc`) ran green in
the infrastructure workstream; the behaviors below are additionally verified by the
pytest modules named in §8.

---

## 1. Auth model as implemented

VeriPay secures a **decision-support API** — it holds invoice and vendor data, never
payment credentials. Phase 1 ships identity only:

- **`POST /api/v1/auth/register`** (public, throttled) creates a **new organization** and
  its first user, who gets role `owner` (`apps/api/app/modules/auth/service.py:59`).
  Email is normalized to lowercase and globally unique — the login key
  (`service.py:69`, `app/models/identity.py:43`). Duplicate email → `409 conflict`.
  Joining an existing organization (invites) does not exist yet.
- **`POST /api/v1/auth/login`** (public, throttled) takes the OAuth2 **password form**
  (`application/x-www-form-urlencoded`, `username=<email>`; `routes/auth.py:98`).
  Unknown email, wrong password, and a **disabled account** return the *identical*
  `401 unauthorized` / "Invalid email or password." — no account enumeration
  (`service.py:34`, `:148-180`; verified by `tests/test_auth_disabled.py`).
- **`GET /api/v1/auth/me`** (bearer) returns the user + organization.
- **`POST /api/v1/auth/logout`** (bearer) **revokes the presented token server-side**
  until its own expiry (`routes/auth.py:131`, `app/core/token_store.py`) — signing out
  kills the token, not just the client's copy of it.

Every state-changing auth event (register, login success, **login failure**, logout) is
written to the append-only `audit_logs` table with ip / user-agent / request-id provenance
(`app/modules/audit/service.py:49`). A failed login against a *known* email carries the
organization context; an unknown email has none — both are recorded
(`service.py:150-164`).

## 2. JWT details

Implemented in `apps/api/app/core/security.py`:

- **Algorithm:** HS256 with a server-side symmetric secret (`VERIPAY_JWT_SECRET`,
  `app/core/config.py:31-32`). Switching to asymmetric keys later does not change the
  bearer-header contract (API.md §1).
- **TTL:** 480 minutes = 8 hours by default (`config.py:33` `access_token_expire_minutes`).
  There are no refresh tokens yet — `POST /api/v1/auth/refresh` is **reserved** for the
  httpOnly-cookie upgrade (API.md §4, ADR 0004).
- **Claims** (`security.py:58-68`): `sub` (user id), `org_id` (tenant — the *only* tenant
  source), `role`, `type: "access"`, `jti` (unique id — the logout-revocation key),
  `iat`, `exp`.
- **Verification** (`security.py:72-80`, `app/tenancy/deps.py:28`): PyJWT verifies
  signature and expiry; the token type must be `access`; the `jti` is checked against the
  revocation registry; the user row must exist and be `active`; and the `org_id` claim is
  **cross-checked against the user's current organization** — a token minted for another
  org (or minted before an org change) is invalid (`deps.py:61-62`).
- **Known residual** (documented at `deps.py:41-45`): tokens minted before the `jti`
  claim existed carry no `jti` and cannot be revoked; they remain valid until natural
  expiry. Irrelevant on a fresh deployment.

**Revocation registry limitation** (`app/core/token_store.py:9-13`): revocations are held
**in-process** and are lost on restart. Correct for the single-instance free-tier
deployment target; a multi-instance deployment must swap this for a shared store (Redis /
DB) — the module is the seam. Same applies to throttling state (§6).

## 3. Password hashing

`app/core/security.py:31-41`:

- **bcrypt** (`bcrypt.hashpw` with generated salt; verification via constant-time
  `checkpw`). Hashes live in `users.password_hash` and are **never serialized** — the
  only response path is explicit Pydantic models, and `UserOut` has no such field
  (`app/modules/auth/schemas.py:16`). Verified by `tests/test_password_storage.py`.
- **Length contract:** bcrypt truncates at 72 bytes, so requests are validated up front —
  min 8 / max 72 chars at the schema (`schemas.py:11`) and a byte-level re-check at the
  service (`security.py:24-28`) — hashing can never silently truncate or fail mid-request.

## 4. Tenant isolation (org scoping)

Design contract: [API.md §5](API.md) — every future endpoint PR is reviewed against it
line by line. As implemented for identity:

1. **The tenant comes from the token, only.** `organization_id` is never read from a
   header, query parameter, path segment, or request body (`deps.py:6-7`).
2. **Server-stamped writes.** Registration creates the organization server-side; clients
   cannot influence ids or org assignment.
3. **Token↔DB cross-check.** The `org_id` claim must match the user row's current
   organization on every request (`deps.py:61-62`).
4. **Cross-org is 404, not 403** (no existence leak) — the rule is specified in API.md §5;
   no tenant-scoped resource endpoints exist yet to exercise it, only the pattern tests
   (`tests/test_org_scoping.py` covers org scoping for the identity surface).
5. **Storage follows the same rule** (design): object keys are tenant-prefixed
   `{org_id}/{document_id}/{sha256}{ext}` (`app/adapters/storage/base.py:50-58`), and the
   local provider rejects keys that would escape its root (`app/adapters/storage/local.py:24-27`).
   Upload endpoints themselves arrive in Phase 2.

The full tenant-isolation matrix across **all** resources is a Phase 8 deliverable
([IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)) — for the resources that exist, the
org-scoping tests run green in the pipeline.

## 5. CORS

`app/main.py:49-55` + `app/core/config.py:50-52`:

- Explicit **allowlist** from `VERIPAY_CORS_ORIGINS` (comma-separated), default
  `["http://localhost:3000"]` — exactly the local dev frontend origin.
- **Wildcards are rejected in review** (API.md §1). `allow_credentials=True` is paired
  with explicit origins only.
- The SWA production origin must be **added to the allowlist** when PROFILE B deploys —
  it is not pre-wired.

## 6. Throttling and lockout

`app/core/ratelimit.py`, configured at `config.py:37-40`:

- `/auth/login`: sliding-window **20 requests / minute / client IP**;
  `/auth/register`: **10 / minute / IP**.
- **Failed-login lockout:** 5 failures per **(client IP, normalized email)** within
  900 s locks the pair; a successful login clears it (`routes/auth.py:53-71`, `:105-119`).
  The per-(IP,email) key means one source cannot brute-force an account, and sprayed
  failures from many IPs cannot mass-lock victims.
- **The client IP is the socket peer** — deliberately *not* `X-Forwarded-For`, which is
  client-controlled unless every proxy in front is trusted (`ratelimit.py:16-19`).
  Consequence to plan for: behind a reverse proxy all clients share one throttling key;
  trusted-proxy wiring must be done together with the shared-store migration below.
- **Limitation, deliberate:** state is in-process and lost on restart (single-instance
  assumption; `ratelimit.py:3-13`). Multi-instance deployments need Redis/DB-backed state.

## 7. "Not secure yet" — honest gaps

Open items, ordered roughly by severity. Nothing here is concealed:

1. **Token in `localStorage` (XSS exposure).** The web app stores the JWT under
   `localStorage["veripay:access_token"]` (`apps/web/src/lib/auth.ts:27`); any script
   running on the origin can read it. Mitigations shipped **now** are below; the real fix
   is the reserved **httpOnly-cookie refresh flow** (`POST /api/v1/auth/refresh`, API.md
   §4) — XSS-safety is the deciding criterion per ADR 0004, at which point
   `src/lib/auth.ts` shrinks to a wrapper around the session cookie.
   *Shipped mitigations:*
   - **Server-side sign-out** — `POST /auth/logout` revokes the token's `jti`, so a
     stolen token dies at logout instead of living out its 8-hour expiry
     (`apps/web/src/hooks/use-session.ts:35`; verified by `tests/test_auth_logout.py`).
   - **CSP + hardening headers on Azure Static Web Apps** —
     `apps/web/public/staticwebapp.config.json` serves `default-src 'self'` (blocks
     third-party script origins), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
     `Permissions-Policy`, HSTS, COOP. **Caveats:** these headers apply **only when
     hosted on Azure Static Web Apps — `next dev` locally serves none of them**; the CSP
     needs `script-src 'unsafe-inline'` (a static export cannot inject per-response
     nonces); and `connect-src` allows any `https:` because the API origin is a
     build-time variable — it must be tightened to the real API origin when known.
2. **JWT secret defaults.** The code ships a dev-only default secret
   (`config.py:16`). A model validator refuses to start with `VERIPAY_ENV=production`
   unless the secret is set, is not the built-in default, and is ≥ 32 chars
   (`config.py:63-75`; `prod`/case/whitespace variants are normalized first,
   `config.py:42-48`; verified by `tests/test_config.py`). **Hole:** the *placeholder in
   `.env.example`* (`dev-only-insecure-secret-change-me`) is a different string and long
   enough — copy-pasting it with `VERIPAY_ENV=production` would pass the validator.
   Treat every known placeholder as insecure; production must use a generated secret
   (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
3. **Per-process auth state.** Token revocations (§2) and throttling/lockout state (§6)
   are in-memory and lost on restart; both assume a single API instance. Swapping to a
   shared store is required before any multi-instance deployment.
4. **No refresh tokens / session management.** 8-hour access tokens, no silent renewal,
   no "sign out everywhere", no device list.
5. **No account-lifecycle security yet:** no email verification, no password reset, no
   MFA, no invite flow (which also means no role administration — every current user is
   an `owner`).
6. **Role claims can go stale.** The JWT carries `role`; it is checked as *present* but
   not re-validated against the DB per request (`deps.py` verifies user, status, and org
   — not role). No role-change endpoint exists today, so this is latent, but any future
   role demotion takes effect only at next login.
7. **Throttling key behind a proxy.** Socket-peer IP keying (§6) collapses all clients
   behind one proxy into one bucket until trusted-proxy handling is added.
8. **Transport / headers.** Local dev is plain HTTP without security headers; HSTS and
   CSP only apply on Azure SWA hosting (§7.1). TLS termination is a deployment concern
   (PROFILE B runbook, Phase 7).
9. **Audit visibility.** The append-only `audit_logs` table exists and captures
   identity events with provenance — but there is **no audit reader endpoint or UI yet**
   (Phase 6), so review today is direct DB access (owner/admin only by convention until
   the role-gated endpoint exists).
10. **Dev data at rest.** The SQLite dev database (`apps/api/veripay.db`) and local
    document storage (`./data/documents`) are unencrypted local files; the compose
    profile uses static dev credentials (`postgres/veripay_dev`, MinIO
    `veripay/veripay-dev-change-me`). Acceptable for dev only.
11. **Compose path unproven.** Docker has never run on the authoring machine — the
    compose security posture (secrets, networking) is unreviewed by execution.

## 8. What is verified by tests

Pipeline gates (run by the infrastructure workstream, reported green): full `pytest`
suite exit 0, `next build` exit 0, contracts `tsc --noEmit` pass. Security-relevant
pytest modules in `apps/api/tests/` (each named by its own docstring):

| Module | Verifies |
|---|---|
| `test_token_security.py` | Tampered, expired, and garbage tokens are all rejected |
| `test_password_storage.py` | Passwords are bcrypt-hashed in the DB — never plaintext |
| `test_org_scoping.py` | Each organization's principal sees only its own org (token-only tenancy) |
| `test_auth_throttle.py` | Per-IP sliding windows on login/register + (IP, email) lockout |
| `test_auth_logout.py` | `POST /auth/logout` revokes the presented token server-side |
| `test_auth_disabled.py` | Disabled users cannot sign in; identical 401, audited as `login_failed` |
| `test_auth_flow.py` | Register→login→me happy path + registration conflicts |
| `test_audit.py` | Register, successful **and** failed logins are written to `audit_logs` |
| `test_audit_context.py` | Audit events carry ip / user_agent / request_id matching the error envelope |
| `test_config.py` | Dev defaults accepted; production refuses the dev secret |
| `test_storage_local.py` | Storage contract incl. path-traversal guard |
| `test_openapi_snapshot.py` | Committed OpenAPI snapshot matches the live schema (drift test) |

The full suite was **not re-run** during this documentation pass.

## 9. Product-level safety rules (normative)

These are the six business invariants ([ARCHITECTURE.md §2](ARCHITECTURE.md)); every
change is reviewed against the no-go list in §8 of the same doc. Security work must
never weaken them:

1. **Never authorize payments automatically.** No payment-rail integration exists or may
   exist; the terminal workflow outcome is a human decision made *outside* VeriPay.
2. **Never claim an invoice is genuine.** No `is_genuine`/`is_fraud` field exists in the
   schema; assessments expose signals + explanations + residual uncertainty only.
3. **Uncertain OCR must not become confident fraud evidence.** Machine-extracted values
   enter fraud features only above the confidence threshold (default 0.85) or when a
   human verified them; below the gate emits `unverified_input`, never a mismatch claim.
4. **Missing records are not proof of fraud.** Absence findings are capped at `medium`
   severity and must state that the record may simply not exist in VeriPay.
5. **A new bank account requires independent verification.** `verification_status`
   starts `pending`; only a human can set `verified`, and only with a verification
   method + reference. An invoice paying to an unverified destination is severity `high`
   and forces human review.
6. **Human review is mandatory for critical inconsistencies.** `critical` assessments
   auto-open an investigation case; cases cannot close without a human outcome +
   resolution summary.

Today these are design constraints (no fraud pipeline exists yet to enforce them in
code); the API's own description already commits to the first two
(`app/main.py:42-46`). Phases 2–5 implement the enforcement points named in
[ARCHITECTURE.md §8](ARCHITECTURE.md).


---

## Phase 2 update (2026-10-17) — cookie sessions, CSRF, RBAC, masking

The auth model changed in Phase 2 (ADR [0005](adr/0005-cookie-session-csrf.md)):

- **No tokens in browser storage.** The frontend keeps the short-lived (30 min)
  Bearer token in a module-scoped variable that dies with the page. The durable
  session is the httpOnly `veripay_session` cookie: an opaque 256-bit random
  token whose **SHA-256 hash only** is stored server-side (`sessions` table,
  7-day TTL). XSS cannot read the session cookie or persist a stolen short token.
- **CSRF** is enforced once in `core/csrf.py`: cookie-authenticated mutating
  requests must echo the readable `veripay_csrf` cookie in `X-CSRF-Token` AND
  pass the Origin/Referer allowlist; Bearer requests are exempt (not ambient
  authority). Login/register/refresh get the Origin check.
- **Revocation is durable**: `POST /auth/logout` revokes the session row (or the
  Bearer token's jti) — enforced in `tenancy/deps.py` on every request.
- **Roles**: `org_admin | finance_officer | reviewer | auditor` enforced by
  `tenancy/permissions.py` require_roles guards; role is read fresh from the user
  row per request. Tested: finance_officer cannot verify accounts or read audit
  events; auditor cannot upload; cross-org is 404.
- **Masking**: bank-account responses expose last4/holder/bank/country/status
  only — never the fingerprint, never a full number (not stored), and the R5
  verification provenance (method/reference/document) only in the
  reviewer/org_admin detail view. `tax_id` is masked in vendor lists.
- **Uploads**: PDF/PNG/JPEG with magic-byte signature checks (a renamed file
  fails), size ceiling (10 MiB default), per-org SHA-256 dedup, tenant-prefixed
  storage keys resolved from the DB row only (path traversal cannot cross
  tenants).
- **Known limits (honest)**: throttling and Bearer-jti revocation are in-process
  (single-instance assumption, documented seams); the sessions table is the
  durable/multi-instance path. No CSP nonces under static export (documented in
  staticwebapp.config.json).
