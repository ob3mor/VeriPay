/**
 * @veripay/api-contracts — TypeScript mirrors of the VeriPay REST contract.
 *
 * SCAFFOLDING PLACEHOLDER. docs/API.md §1 requires frontend types to be GENERATED
 * from the FastAPI OpenAPI schema (a committed `openapi.json` snapshot, Phase 1) and
 * states hand-written client types fail review. These hand-mirrored types exist so
 * Phase 1 scaffolding (npm workspaces, static-export build) type-checks before the
 * backend ships its snapshot; they MUST be replaced by generated types.
 *
 * Sources: docs/API.md (endpoint shapes, error envelope, pagination),
 * docs/DATABASE.md (entity placeholder names/fields), docs/ARCHITECTURE.md §8
 * (business invariants reflected in the status/field choices below).
 */

// ---------------------------------------------------------------------------
// Versioned error envelope — docs/API.md §2 (stable for all of v1)
// ---------------------------------------------------------------------------

/** The only error codes v1 emits (API.md §2 code registry). */
export type ApiErrorCode =
  | "validation_error" // 422
  | "unauthorized" // 401
  | "forbidden" // 403 (rare — cross-org access is 404, API.md §5.4)
  | "not_found" // 404 (unknown OR out-of-tenant)
  | "conflict" // 409 (duplicate invoice numbers are NOT this — they are a fraud signal)
  | "business_rule_violation" // 422
  | "rate_limited" // 429
  | "method_not_allowed" // 405
  | "internal"; // 500 (never carries stack traces)

export interface ApiErrorDetail {
  field?: string;
  message: string;
}

/** Body of the `error` object; additive `details` only. */
export interface ApiErrorBody {
  code: ApiErrorCode;
  /** Safe to display to end users (API.md §2). */
  message: string;
  details?: ApiErrorDetail[];
  /** Correlates with server logs (and `audit_logs` from Phase 6). */
  request_id: string;
}

/** Every non-2xx response uses this envelope. */
export interface ApiErrorResponse {
  error: ApiErrorBody;
}

// ---------------------------------------------------------------------------
// Pagination envelope — docs/API.md §3
// ---------------------------------------------------------------------------

export interface Pagination {
  limit: number; // default 25, max 100 (clamped, not rejected)
  offset: number; // default 0
  total: number; // COUNT over the same org-scoped filter
}

/** All list endpoints (Phase 2+) return this envelope. */
export interface Paginated<T> {
  items: T[];
  pagination: Pagination;
}

// ---------------------------------------------------------------------------
// Health — docs/API.md §4 (GET /api/v1/health, public)
// ---------------------------------------------------------------------------

export interface HealthOut {
  status: "ok";
  service: "veripay-api";
  version: string;
}

// ---------------------------------------------------------------------------
// Auth — docs/API.md §4
// ---------------------------------------------------------------------------

/** Roles stored in `users.role` — docs/DATABASE.md §5.
 *  Note: the API.md §5 role×action matrix also names a `viewer` role; reconcile
 *  against the generated types once the OpenAPI snapshot exists. */
export type UserRole = "owner" | "admin" | "analyst" | "reviewer";

/** POST /api/v1/auth/register (public) — creates a new org + its first user. */
export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  organization_name: string;
}

export interface OrgOut {
  id: string;
  name: string;
  slug: string; // URL-safe, immutable (DATABASE.md §4)
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  /** Present in the register response; `GET /auth/me` omits it and returns the
   *  organization as a sibling — docs/API.md §4. */
  organization_id?: string;
}

/** POST /api/v1/auth/login — OAuth2 password form (`application/x-www-form-urlencoded`);
 *  `username` carries the email so FastAPI's "Authorize" button works (API.md §4). */
export interface LoginRequest {
  username: string;
  password: string;
}

/** 200 of POST /auth/login (also the token part of register's 201). */
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

/** 201 of POST /auth/register. */
export interface RegisterResponse {
  user: UserOut;
  organization: OrgOut;
  access_token: string;
  token_type: "bearer";
}

/** 200 of POST /auth/logout — the presented access token is revoked
 *  server-side (requires auth; the Bearer token is attached automatically). */
export interface LogoutResponse {
  status: "ok";
}

/** 200 of GET /auth/me (requires auth). */
export interface MeResponse {
  user: UserOut;
  organization: OrgOut;
}

// ---------------------------------------------------------------------------
// Entity placeholders — docs/DATABASE.md (replace with generated types)
// ---------------------------------------------------------------------------
// Deliberately minimal but named/typed per the DATABASE.md tables so UI
// scaffolding can compile. Timestamps are ISO 8601 strings; money is a string
// (Numeric(14,2) on the server — never float, DATABASE.md §1).

// ---------- documents (DATABASE.md §11) ----------

export type DocumentKind =
  | "invoice"
  | "purchase_order"
  | "bank_letter"
  | "statement"
  | "other";

export type StorageProviderName = "local" | "minio" | "azure_blob";

export type OcrStatus = "pending" | "processing" | "done" | "failed";

export interface Document {
  id: string;
  organization_id: string;
  kind: DocumentKind;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  storage_provider: StorageProviderName;
  storage_key: string; // tenant-prefixed: {org_id}/{document_id}/{sha256}{ext}
  ocr_status: OcrStatus;
  uploaded_by: string;
  created_at: string;
  updated_at: string;
}

// ---------- vendors (DATABASE.md §6) ----------

export type VendorStatus = "active" | "inactive" | "blocked";

export interface Vendor {
  id: string;
  organization_id: string;
  display_name: string;
  legal_name?: string | null;
  normalized_name: string;
  /** Masked in API responses; matching-only access (DATABASE.md §6). */
  tax_id?: string | null;
  status: VendorStatus;
  created_at: string;
  updated_at: string;
}

// ---------- vendor_trusted_accounts (DATABASE.md §7) ----------
// Invariant R5: verification_status starts `pending`; only a human can set
// `verified`, and only with a verification method + reference. There is no
// automatic verification path (docs/ARCHITECTURE.md §8.5).

export type BankAccountVerificationStatus =
  | "pending"
  | "verified"
  | "failed"
  | "revoked";

export interface BankAccount {
  id: string;
  organization_id: string;
  vendor_id: string;
  account_holder_name: string;
  bank_name?: string | null;
  /** ISO 3166-1 alpha-2 (DATABASE.md §7). */
  bank_country?: string | null;
  account_number_last4?: string | null;
  /** Full account numbers/IBANs are never stored — only the SHA-256 fingerprint
   *  server-side (data minimization, DATABASE.md §7), so it is not in the API type. */
  verification_status: BankAccountVerificationStatus;
  /** Marks the vendor's current on-file account (one per vendor per org). */
  is_current: boolean;
  created_at: string;
  updated_at: string;
}
// NOTE (API.md §5 rule 8): `verification_method`, `verification_reference` and
// `verification_document_id` are deliberately absent — they are omitted from list
// payloads and cross-role surfaces, visible only to reviewer/admin/owner in the
// case/vendor investigation detail (R5 provenance record).

// ---------- purchase_orders (DATABASE.md §8) ----------

export type PurchaseOrderStatus = "draft" | "active" | "closed" | "cancelled";

export interface PurchaseOrder {
  id: string;
  organization_id: string;
  po_number: string;
  /** POs may be ingested before vendor resolution. */
  vendor_id?: string | null;
  /** Numeric(14,2) — string to avoid float drift (DATABASE.md §1). */
  amount?: string | null;
  /** ISO 4217. */
  currency?: string | null;
  issued_at?: string | null;
  status: PurchaseOrderStatus;
  created_at: string;
  updated_at: string;
}

// ---------- invoices (DATABASE.md §9) ----------
// Invariants R1/R2: the status vocabulary has NO "approved"/"genuine" state —
// the terminal outcome is a human decision made outside VeriPay.

export type InvoiceStatus = "received" | "processing" | "needs_review" | "closed";

export interface Invoice {
  id: string;
  organization_id: string;
  /** NULL until vendor resolution (workflow step 3) — a state, not an error. */
  vendor_id?: string | null;
  /** NULL → `missing_evidence` signal (R4), never fraud by itself. */
  purchase_order_id?: string | null;
  /** Deliberately NOT unique per org+vendor — duplicates are a fraud signal
   *  recorded as `duplicate_matches` + needs_review, never a 409 (API.md §2). */
  invoice_number: string;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal_amount?: string | null;
  tax_amount?: string | null;
  total_amount?: string | null;
  /** Pay-to details as printed on the invoice (DATABASE.md §9). */
  remittance_bank_name_raw?: string | null;
  remittance_account_raw?: string | null;
  /** Trusted account matched to the remittance fingerprint; NULL (or a
   *  pending/failed/revoked match) → `bank_account_unverified`, severity high,
   *  forces needs_review (ARCHITECTURE §8.5). */
  payment_account_id?: string | null;
  status: InvoiceStatus;
  created_at: string;
  updated_at: string;
}
