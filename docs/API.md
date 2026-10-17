# VeriPay — API Design

Status: design v1 · 2026-10-17. Implementation contract for `backend/app/api/v1`.

## 1. General

- **Prefix & versioning:** all endpoints live under `/api/v1`. v1 is frozen except for *additive* response fields; breaking changes go to `/api/v2` with v1 kept during a deprecation window. There is no v0.
- **OpenAPI comes from FastAPI** — never hand-maintained. Served at `GET /api/v1/openapi.json` (with docs UI at `/docs`, configured with the v1 prefix). Frontend types are generated from this schema at build time (e.g. `openapi-typescript`); hand-written client types fail review. A generated **`openapi.json` snapshot is committed to the repo (Phase 1) with a drift test** against the live schema, so type generation and static builds never require a running backend.
- **Auth:** `Authorization: Bearer <JWT>` on everything except the endpoints explicitly marked public below. Tokens issued by `POST /api/v1/auth/login` and `POST /api/v1/auth/register`. HS256 with a server-side secret in Phase 1; switching to asymmetric keys later does not change the header contract.
- **Errors:** every non-2xx uses the versioned envelope (§2). Success responses are plain resources/envelopes — no wrapper.
- **Content types:** JSON everywhere; `multipart/form-data` only on the future document-upload endpoints.
- **CORS:** allowlist of known frontend origins only (local dev origin; the SWA origin for PROFILE B). Wildcards are rejected in review.

## 2. Versioned error shape

Stable for all of v1; additive `details` only:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request body failed validation.",
    "details": [
      { "field": "email", "message": "value is not a valid email address" }
    ],
    "request_id": "b7c9d1e0-4f2a-4c8e-9a51-3f0d2c7b9e10"
  }
}
```

Code registry (the only codes; handlers implemented once in `core` as FastAPI exception handlers — no route returns a naked `HTTPException`):

| code | HTTP | meaning |
|---|---|---|
| `validation_error` | 422 | body/query/path validation failed; FastAPI's `RequestValidationError` is mapped into this envelope (overrides the default `{"detail": ...}` shape) |
| `unauthorized` | 401 | missing/invalid/expired token, or bad credentials |
| `forbidden` | 403 | authenticated but not permitted (rare — cross-org access is 404, see §5) |
| `not_found` | 404 | unknown **or out-of-tenant** resource |
| `conflict` | 409 | uniqueness or state conflict (e.g. duplicate email at registration). **Duplicate invoice numbers are deliberately NOT 409** — they are recorded as `duplicate_matches` + `needs_review`, because they are a fraud signal, not an error (DATABASE.md §9); re-uploading a document with identical bytes returns 200 with the existing document |
| `business_rule_violation` | 422 | well-formed but violates business state (e.g. verifying a bank account without `verification_method`) |
| `rate_limited` | 429 | throttled |
| `method_not_allowed` | 405 | the path exists but not for this HTTP method (e.g. GET on a POST-only endpoint) |
| `internal` | 500 | unexpected; **never** includes stack traces or driver errors |

Rules: `message` is safe to display to end users; `request_id` correlates with server logs (and, from Phase 6, `audit_logs`); `details` is optional and structured — never a raw exception string.

## 3. Pagination convention

- List endpoints (Phase 2+) take `limit` (int, default **25**, max **100** — higher values are clamped, not rejected) and `offset` (int, default 0).
- Response envelope:

```json
{
  "items": [],
  "pagination": { "limit": 25, "offset": 0, "total": 137 }
}
```

- Default order is stable: `created_at DESC, id DESC`. Explicit `sort` parameters may be added additively; clients must not rely on ordering they did not request.
- `total` is a COUNT over the same org-scoped filter. If cursor pagination is ever needed for very hot streams, it is added as a new optional `cursor` request param + `next_cursor` response field — both additive; `limit/offset` stay valid.

## 4. Phase 1 endpoint list

Phase 1 ships exactly these; no other resources exist yet (reserved names are in §6).

### GET /api/v1/health — public

Liveness. No auth.

```json
{ "status": "ok", "service": "veripay-api", "version": "0.1.0" }
```

A readiness variant `GET /api/v1/health/ready` (DB ping) may be added later — additive.

### POST /api/v1/auth/register — public

Creates a **new organization** and its first user (role `owner`). Joining an existing org (invites) is a later, additive flow.

Request:
```json
{ "email": "dana@acme.example", "password": "…", "full_name": "Dana Reyes", "organization_name": "Acme GmbH" }
```

201:
```json
{
  "user": { "id": "…", "email": "dana@acme.example", "full_name": "Dana Reyes", "role": "owner", "organization_id": "…" },
  "organization": { "id": "…", "name": "Acme GmbH", "slug": "acme-gmbh" },
  "access_token": "…",
  "token_type": "bearer"
}
```

Errors: 409 `conflict` (email already registered); 422 `validation_error`.

### POST /api/v1/auth/login — public

OAuth2 password form (`application/x-www-form-urlencoded`: `username=<email>`, `password=…`) so FastAPI's "Authorize" button works out of the box.

200: `{ "access_token": "…", "token_type": "bearer" }`

401 `unauthorized` / `invalid_credentials` for **both** unknown email and wrong password (same message — no account enumeration). Updates `users.last_login_at`; success/failure are audit events through the audit facade (app logs until Phase 6).

**Reserved with Phase 1: `POST /api/v1/auth/refresh`** — the httpOnly-cookie refresh endpoint ADR 0004 needs. It is reserved **now**, in Phase 1's own scope, so the "v1 frozen except additive" rule cannot block the token-refresh decision; it is specified and implemented alongside the Phase 1 auth work.

### GET /api/v1/auth/me — requires auth

```json
{
  "user": { "id": "…", "email": "…", "full_name": "…", "role": "owner" },
  "organization": { "id": "…", "name": "Acme GmbH", "slug": "acme-gmbh" }
}
```

401 `unauthorized` otherwise.

## 5. Org-scoping rules — mandatory for every future resource endpoint

Any new endpoint PR must satisfy all of these; reviewers check them line by line:

1. **Tenant source is the token, only.** `organization_id` is read from the authenticated principal (JWT claim set at login). It is never taken from a header, query parameter, path segment, or request body.
2. **Server-stamped writes.** Create endpoints ignore any client-supplied `organization_id`; the service stamps it from the principal.
3. **Every query is org-filtered.** All reads and writes go through the tenancy helpers / base repository that inject `WHERE organization_id = :org`. A raw unscoped query on a tenant table fails review (ARCHITECTURE §5, rule D2/D4 discipline).
4. **Cross-org is 404, not 403.** A valid ID belonging to another org is indistinguishable from a nonexistent one (no existence leak).
5. **List endpoints are scoped and paginated.** Every list route filters by the principal's org and uses the §3 envelope. There are no global lists.
6. **Mandatory isolation test.** Each resource's test module includes a tenant-isolation case: fixtures for org A and org B; A's principal gets 404 reading/updating/deleting B's objects, and B's objects never appear in A's lists.
7. **Storage follows the same rule.** Object keys are tenant-prefixed `{org_id}/…` (ARCHITECTURE §7.1); download endpoints resolve keys from the database record, never from client-supplied paths.
8. **Response hygiene.** `password_hash` and internal flags never appear anywhere; Pydantic response models are the only serialization path. `vendor_trusted_accounts.verification_method` / `verification_reference` / `verification_document_id` are the R5 provenance record: they are **omitted from list payloads and any cross-role surface**, and **visible to `reviewer`/`admin`/`owner` roles in the case/vendor investigation detail**, where proving independent verification is the point (R5).

### Role × action matrix (beyond tenancy)

Phase 2 canonical roles (ADR 0007): `org_admin`, `finance_officer`, `reviewer`,
`auditor`. Tenancy is necessary but not sufficient; new endpoints are checked
against this matrix too. Enforcement lives in `tenancy/permissions.py`:

| Action | finance_officer | reviewer | auditor | org_admin |
|---|---|---|---|---|
| Upload documents / create vendors, POs, invoices / run assessments | ✓ | ✓ | – | ✓ |
| Work cases: assign, review actions, disposition | ✓ | ✓ | – | ✓ |
| Verify / reject / revoke bank accounts (R5) | – | ✓ | – | ✓ |
| Approve / reject bank-account change requests (R5) | – | ✓ | – | ✓ |
| Close a case (R6 outcome) | – | ✓ | – | ✓ |
| View audit events (`/audit-events`) | – | – | ✓ | ✓ |
| Org/user administration | – | – | – | ✓ |

Resource conventions: plural kebab-case nouns (`/api/v1/documents`, `/api/v1/vendors/{vendor_id}/trusted-accounts`); UUID path parameters; POST returns 201 with the created resource; non-CRUD state changes are verb subresources (`POST /api/v1/cases/{id}/close`); GETs must never mutate.

## 6. Phase 2 endpoint map (implemented)

Auth (see §4 for shapes): `POST /auth/register`, `POST /auth/login`,
`POST /auth/refresh` (session cookie + CSRF), `GET /auth/me`,
`POST /auth/logout` (Bearer jti and/or session row revoked, cookies cleared).
Browser clients authenticate with the httpOnly `veripay_session` cookie and
echo `veripay_csrf` in `X-CSRF-Token` on mutating requests (ADR 0005);
programmatic clients use Bearer tokens (exempt from the CSRF header).

| Surface | Endpoints |
|---|---|
| Vendors | `POST/GET /vendors`, `GET /vendors/{id}`; `POST/GET /vendors/{id}/contacts` |
| Bank accounts (R5) | `POST/GET /vendors/{id}/bank-accounts`, `POST /bank-accounts/{id}/verify` (human-only; method + reference/document mandatory), `POST …/reject`, `POST …/revoke` |
| Change control (R5) | `POST/GET /vendors/{id}/change-requests`, `POST …/change-requests/{id}/approve`, `POST …/reject` — on approval the service creates the approved account stamped with the deciding human |
| Purchase orders | `POST/GET /purchase-orders`, `GET /purchase-orders/{id}` |
| Invoices | `POST/GET /invoices`, `GET /invoices/{id}` (duplicate vendor+number intake is allowed — evidence match + needs_review, never 409), `POST /invoices/{id}/resolve-vendor` |
| Documents | `POST /documents` (multipart; PDF/PNG/JPEG magic-byte + size validation; per-org sha256 dedup → dedup returns the existing doc; inline processing job runs), `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/file` (protected, DB-resolved key), `GET /documents/{id}/extraction`, `GET /documents/{id}/fields`, `POST /documents/{id}/process` (idempotent retry) |
| Fraud (rules-v0.1) | `POST /invoices/{id}/assess`, `GET /invoices/{id}/assessment` — deterministic explainable signals per ARCHITECTURE §8; `evc` stays NULL (Phase 4) |
| Cases (R6) | `POST/GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/assign`, `POST /cases/{id}/close` (outcome + resolution summary mandatory), `POST/GET /cases/{id}/actions` (review actions) |
| Audit | `GET /audit-events` (org_admin/auditor only, append-only) |

Each of these follows §5 verbatim and inherits the §2 envelope and §3 pagination
(`limit`/`offset` clamped 1..100/0). Storage keys are never serialized.
