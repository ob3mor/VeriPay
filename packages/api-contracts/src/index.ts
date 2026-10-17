/**
 * @veripay/api-contracts — TypeScript mirrors of the VeriPay REST contract.
 *
 * Hand-mirrored 1:1 from the committed OpenAPI snapshot
 * (apps/api/openapi.json, schema dump verified 2026-10-17 against every path
 * and component). docs/API.md §1 ultimately requires GENERATED types from
 * FastAPI's schema; until codegen lands, every interface below is checked
 * against the snapshot — property names, requiredness, and nullability follow
 * it exactly, with vocabulary unions from apps/api/app/core/enums.py (the
 * server's StrEnum source of truth, mirrored by docs/DATABASE.md).
 *
 * Wire-shape notes (verified against the snapshot, deviating from API.md §3):
 * - List endpoints (GET /vendors, /invoices, /documents, /purchase-orders,
 *   /cases, /audit-events, and the per-vendor sub-lists) currently return a
 *   BARE JSON ARRAY, not the `{ items, pagination }` envelope of API.md §3.
 *   They take `limit`/`offset` query params but do not return `pagination`.
 *   The client therefore types them as `T[]`; `Paginated<T>` below is kept
 *   for the moment the envelope lands (additive change, API.md §1).
 * - `GET /documents/{id}/extraction` and `GET /invoices/{id}/assessment`
 *   return the resource OR `null` (no assessment/extraction yet).
 * - `GET /vendors/{id}/bank-accounts` items are `BankAccountOut | BankAccountDetail`
 *   (the detail shape carries the R5 verification provenance, visible to
 *   reviewer/org_admin per API.md §5.8).
 * - `GET /stats/dashboard` IS in the committed snapshot (56 paths total,
 *   verified 2026-10-17): `DashboardStatsOut` below mirrors it exactly.
 * - Evidence retrieval (`GET /invoices/{id}/evidence` → `InvoiceEvidenceOut`),
 *   evidence matches (`GET/POST /matches/{id}[/review]` → `EvidenceMatchOut`),
 *   findings disposition (`POST /findings/{id}/disposition`), extraction-field
 *   review (`PATCH /documents/{id}/fields/{field_id}`), line items
 *   (`GET/POST /invoices/{id}/line-items`) and `GET /processing-jobs/{id}`
 *   are all in the snapshot and mirrored below.
 * - `POST /findings/{finding_id}/disposition` and
 *   `POST /matches/{match_id}/review` REJECT an empty reason with 422
 *   (server-side model validator in _domain_schemas.py) — callers must send a
 *   non-empty `reason` (or legacy `note`).
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
  /** Correlates with server logs (and `audit_events` from Phase 6). */
  request_id: string;
}

/** Every non-2xx response uses this envelope. */
export interface ApiErrorResponse {
  error: ApiErrorBody;
}

// ---------------------------------------------------------------------------
// Pagination — docs/API.md §3
// ---------------------------------------------------------------------------

/** Request-side pagination params accepted by every list endpoint
 *  (limit clamped server-side, never rejected). */
export interface ListParams {
  limit?: number; // default 25, max 100 (clamped, not rejected)
  offset?: number; // default 0
}

export interface Pagination {
  limit: number;
  offset: number;
  total: number;
}

/**
 * The API.md §3 list envelope. Produced by every list endpoint (Phase 2+):
 * `{"items": [...], "pagination": {"limit": …, "offset": …, "total": …}}`
 * (docs/API.md §5 rule 5). The backend also accepts `limit`/`offset` on the
 * sub-resource lists (line items, contacts, bank accounts, change requests,
 * case actions, extraction fields, audit events).
 */
export interface Paginated<T> {
  items: T[];
  pagination: Pagination;
}

// ---------------------------------------------------------------------------
// Health — GET /api/v1/health (public). Snapshot: object of string values.
// ---------------------------------------------------------------------------

export interface HealthOut {
  status: string;
  service: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Auth — /auth/* (docs/API.md §4, ADR 0005 cookie sessions)
// ---------------------------------------------------------------------------

/** Roles stored in `users.role` — the four canonical roles (Phase 2,
 *  apps/api/app/core/enums.py UserRole). Org creator = org_admin.
 *  Display labels live in apps/web/src/lib/auth.ts. */
export type UserRole = "org_admin" | "finance_officer" | "reviewer" | "auditor";

/** POST /auth/register (public) — creates a new org + its first user.
 *  Password: 8–72 chars (snapshot constraints). */
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
  /** Required in the snapshot (present on register AND /auth/me payloads). */
  organization_id: string;
}

/** POST /auth/login — OAuth2 password form (`application/x-www-form-urlencoded`);
 *  `username` carries the email so FastAPI's "Authorize" button works (API.md §4). */
export interface LoginRequest {
  username: string;
  password: string;
}

/** 200 of POST /auth/login and POST /auth/refresh. The durable session is the
 *  httpOnly cookie set alongside; this token is short-lived (30 min) and is
 *  kept in memory only — never web storage (ADR 0005). */
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

/** 200 of POST /auth/refresh — a fresh short-lived token minted from the
 *  httpOnly session cookie (+ CSRF header). Same shape as TokenResponse. */
export interface RefreshResponse extends TokenResponse {}

/** 201 of POST /auth/register. */
export interface RegisterResponse {
  user: UserOut;
  organization: OrgOut;
  access_token: string;
  token_type: "bearer";
}

/** 200 of POST /auth/logout — the presented credential (Bearer jti or session
 *  row) is revoked server-side and the cookies are cleared. */
export interface LogoutResponse {
  status: "ok";
}

/** 200 of GET /auth/me (requires auth; authenticates via the session cookie
 *  alone on a fresh page load — ADR 0005). */
export interface MeResponse {
  user: UserOut;
  organization: OrgOut;
}

// ---------------------------------------------------------------------------
// Vocabulary unions — mirrored from apps/api/app/core/enums.py
// (StrEnum validated at the API boundary; the wire values are exactly these)
// ---------------------------------------------------------------------------

export type VendorStatus = "active" | "inactive" | "blocked";

/** R5 (docs/ARCHITECTURE.md §8.5): starts `pending`; ONLY a human moves it to
 *  `approved`, and only with an independent verification record. No code path
 *  auto-approves. */
export type BankAccountStatus = "pending" | "approved" | "rejected" | "revoked";

/** Human-only verification methods (DATABASE.md §7). Required when an account
 *  becomes `approved`. */
export type BankAccountVerificationMethod =
  | "callback_to_known_contact"
  | "written_confirmation"
  | "registry_check";

export type ChangeRequestStatus = "pending" | "approved" | "rejected";

export type PurchaseOrderStatus = "draft" | "active" | "closed" | "cancelled";

/** R1/R2: NO "approved"/"genuine" state exists — the terminal outcome is a
 *  human decision made outside VeriPay (docs/ARCHITECTURE.md §8.1/8.2). */
export type InvoiceStatus = "received" | "processing" | "needs_review" | "closed";

/** Durable processing state machine (documents, extraction results, jobs;
 *  ADR 0006). */
export type ProcessingStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "requires_manual_input";

export type DocumentKind =
  | "invoice"
  | "purchase_order"
  | "bank_letter"
  | "statement"
  | "other";

export type ExtractionFieldVerificationStatus = "unverified" | "confirmed" | "corrected";

/** evidence_matches kinds (DATABASE.md v2). */
export type MatchKind =
  | "bank_account"
  | "vendor"
  | "purchase_order"
  | "invoice_number"
  | "near_duplicate"
  | "field_overlap";

export type MatchStatus = "open" | "dismissed" | "confirmed";

/** The fraud signal vocabulary — single source of truth docs/ARCHITECTURE.md
 *  §8 (missing_evidence capped ≤ medium per R4; bank_account_unverified
 *  floored at high per R5), extended additively by EVC v1 in
 *  apps/api/app/core/enums.py: `unknown_vendor` and `ocr_uncertain` are
 *  uncertainty/absence-flavored signals, severity-capped at medium, whose only
 *  forcing is mandatory human review — they never claim fraud by themselves. */
export type SignalType =
  | "missing_evidence"
  | "unverified_input"
  | "field_provenance_conflict"
  | "duplicate_candidate"
  | "amount_mismatch"
  | "bank_account_unverified"
  | "unknown_vendor"
  | "ocr_uncertain";

export type FindingDisposition = "open" | "acknowledged" | "dismissed";

export type Severity = "low" | "medium" | "high" | "critical";

export type RiskLevel = "none" | "low" | "medium" | "high" | "critical";

export type AssessmentStatus = "complete" | "partial" | "failed";

export type CaseStatus = "open" | "in_review" | "waiting_vendor" | "closed";

export type CaseSeverity = Severity;

/** Case outcomes set ONLY by a human at close (R6). Even
 *  `no_critical_findings` is a disposition, not a genuineness claim (R2). */
export type CaseOutcome =
  | "fraud_confirmed"
  | "policy_violation"
  | "false_positive"
  | "no_critical_findings"
  | "inconclusive";

export type ReviewActionType =
  | "comment"
  | "decision"
  | "assignment"
  | "status_change"
  | "field_verified"
  | "account_verified"
  | "account_change_approved"
  | "account_change_rejected";

export type ActorType = "user" | "system";

// ---------------------------------------------------------------------------
// Documents — /documents (DATABASE.md §11, snapshot DocumentOut)
// ---------------------------------------------------------------------------

/** Ordinary document view. NOTE: the v2 model calls the processing state
 *  `processing_status` (not the Phase-1 `ocr_status`), and storage keys are
 *  never serialized (API.md §5.8). */
export interface DocumentOut {
  id: string;
  organization_id: string;
  kind: DocumentKind;
  /** Vendor context for non-invoice documents (bank letters, statements). */
  vendor_id: string | null;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  processing_status: ProcessingStatus;
  uploaded_by: string;
}

/** 201 of POST /documents (multipart upload) and 200 of
 *  POST /documents/{id}/process — adds the inline processing outcome.
 *  `deduplicated: true` means the per-org sha256 dedup returned the existing
 *  document (API.md §6; never an error). */
export interface ProcessedDocumentOut extends DocumentOut {
  deduplicated: boolean;
  job_id: string | null;
  job_status: string | null;
}

/** multipart/form-data body of POST /documents. `file` is the only required
 *  part; PDF/PNG/JPEG magic-byte + size validation happens server-side. */
export interface UploadDocumentBody {
  file: Blob;
  kind?: DocumentKind;
  vendor_id?: string;
}

// ---------------------------------------------------------------------------
// Vendors — /vendors (DATABASE.md §6, snapshot VendorOut)
// ---------------------------------------------------------------------------

export interface VendorIn {
  display_name: string;
  legal_name?: string | null;
  /** Masked server-side; matching-only access (DATABASE.md §6). */
  tax_id?: string | null;
  notes?: string | null;
}

export interface VendorOut {
  id: string;
  organization_id: string;
  display_name: string;
  legal_name: string | null;
  /** Masked form of the tax id — the raw value never round-trips. */
  tax_id_masked: string | null;
  status: VendorStatus;
  created_at: string | null;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Vendor contacts — /vendors/{id}/contacts (vendor_authorized_contacts)
// ---------------------------------------------------------------------------

export interface ContactIn {
  full_name: string;
  email: string;
  phone?: string | null;
  role_title?: string | null;
  is_primary?: boolean;
  notes?: string | null;
}

export interface ContactOut {
  id: string;
  vendor_id: string;
  full_name: string;
  role_title: string | null;
  email: string;
  phone: string | null;
  is_primary: boolean;
}

// ---------------------------------------------------------------------------
// Bank accounts — /vendors/{id}/bank-accounts (R5, vendor_bank_accounts)
// ---------------------------------------------------------------------------

/** Body of POST /vendors/{id}/bank-accounts. `account_number` (or IBAN) is
 *  the ONLY place the full value may appear — the service fingerprints it and
 *  stores the SHA-256 hash; the raw value never touches the database or logs. */
export interface BankAccountIn {
  account_holder_name: string;
  account_number: string;
  bank_name?: string | null;
  /** ISO 3166-1 alpha-2. */
  bank_country?: string | null;
  make_current?: boolean; // default true
}

/** Ordinary (masked) view — list payloads and cross-role surfaces. */
export interface BankAccountOut {
  id: string;
  vendor_id: string;
  account_holder_name: string;
  bank_name: string | null;
  bank_country: string | null;
  account_number_last4: string | null;
  status: BankAccountStatus;
  /** Marks the vendor's current on-file account (one per vendor per org). */
  is_current: boolean;
}

/**
 * Reviewer/org_admin investigation view — adds the R5 verification
 * provenance (still never the fingerprint or any full number). Returned by
 * the verify/reject/revoke actions and included in list items for
 * privileged roles (snapshot: `BankAccountOut | BankAccountDetail`).
 */
export interface BankAccountDetail extends BankAccountOut {
  /** Method + reference/document are the R5 provenance record: mandatory
   *  when a human set status = approved (docs/ARCHITECTURE.md §8.5). */
  verification_method: string | null;
  verification_reference: string | null;
  verification_document_id: string | null;
  verified_at: string | null;
  verified_by: string | null;
}

/** A list item is either shape (the backend widens it for privileged roles). */
export type BankAccountListItem = BankAccountOut | BankAccountDetail;

export function isBankAccountDetail(
  account: BankAccountListItem
): account is BankAccountDetail {
  return "verification_method" in account;
}

/** Human approval (R5): exactly one of reference/document proof must be
 *  supplied together with the method; there is no approval without one.
 *  Missing method → 422 business_rule_violation (machine approval impossible). */
export interface VerifyAccountIn {
  verification_method: BankAccountVerificationMethod;
  verification_reference?: string | null;
  verification_document_id?: string | null;
}

/** Body of POST …/bank-accounts/{id}/reject (and the reject half of change
 *  request decisions). */
export interface RejectAccountIn {
  resolution_note?: string | null;
}

// ---------------------------------------------------------------------------
// Bank-account change requests — R5 change control
// (an invoice can never approve an account or a change request)
// ---------------------------------------------------------------------------

export interface ChangeRequestIn {
  account_holder_name: string;
  account_number: string;
  bank_name?: string | null;
  bank_country?: string | null;
  reason: string;
}

export interface ChangeRequestOut {
  id: string;
  vendor_id: string;
  current_account_id: string | null;
  proposed_holder_name: string;
  proposed_account_last4: string | null;
  proposed_bank_name: string | null;
  proposed_bank_country: string | null;
  reason: string;
  status: ChangeRequestStatus;
  requested_by: string;
  reviewed_by: string | null;
  resolution_note: string | null;
}

/** Body of POST …/change-requests/{id}/approve | /reject. */
export interface ChangeRequestDecisionIn {
  resolution_note?: string | null;
}

// ---------------------------------------------------------------------------
// Purchase orders — /purchase-orders (DATABASE.md §8)
// ---------------------------------------------------------------------------

export interface PurchaseOrderIn {
  po_number: string;
  vendor_id?: string | null;
  /** Decimal string, e.g. "1250.00" (Numeric(14,2) — never float, §1). */
  amount?: string | null;
  currency?: string | null;
  issued_at?: string | null;
  description?: string | null;
}

export interface PurchaseOrderOut {
  id: string;
  po_number: string;
  vendor_id: string | null;
  amount: string | null;
  currency: string | null;
  issued_at: string | null;
  status: PurchaseOrderStatus;
}

// ---------------------------------------------------------------------------
// Invoices — /invoices (DATABASE.md §9)
// ---------------------------------------------------------------------------

export interface InvoiceIn {
  invoice_number: string;
  vendor_id?: string | null;
  purchase_order_id?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal_amount?: string | null;
  tax_amount?: string | null;
  total_amount?: string | null;
  /** Pay-to details as printed on the invoice (DATABASE.md §9). */
  remittance_bank_name_raw?: string | null;
  remittance_account_raw?: string | null;
  source_document_id?: string | null;
}

export interface InvoiceOut {
  id: string;
  invoice_number: string;
  /** NULL until vendor resolution (workflow step 3) — a state, not an error. */
  vendor_id: string | null;
  /** NULL → `missing_evidence` signal (R4), never fraud by itself. */
  purchase_order_id: string | null;
  invoice_date: string | null;
  currency: string | null;
  total_amount: string | null;
  status: InvoiceStatus;
  remittance_bank_name_raw: string | null;
  /** Last 4 of the printed pay-to account (masked on the wire). */
  remittance_account_last4: string | null;
  /** Trusted account matched to the remittance fingerprint; NULL (or a
   *  pending/rejected/revoked match) → `bank_account_unverified`, severity
   *  high, forces needs_review (docs/ARCHITECTURE.md §8.5). */
  payment_account_id: string | null;
}

// ---------------------------------------------------------------------------
// Vendor resolution — POST /invoices/{id}/resolve-vendor
// ---------------------------------------------------------------------------

/** Provide an existing `vendor_id`, or a `vendor_name` to create a pending
 *  vendor. Unresolved vendors stay unresolved — never guessed (ARCHITECTURE
 *  §4 step 3). */
export interface ResolveVendorIn {
  vendor_id?: string | null;
  vendor_name?: string | null;
}

// ---------------------------------------------------------------------------
// Extraction — /documents/{id}/extraction and /fields (R3)
// ---------------------------------------------------------------------------

export interface ExtractionResultOut {
  id: string;
  document_id: string;
  extraction_version: string;
  ocr_provider: string | null;
  status: ProcessingStatus;
  error: string | null;
  /** Provider metadata (e.g. OCR request id, model) — additive, snapshot. */
  provider_meta?: Record<string, unknown> | null;
  /** Cross-field validation summary recorded by extraction — additive. */
  validation_summary?: Record<string, unknown> | null;
}

/** One evidence span as stored in `evidence_spans` (DATABASE.md §12): the
 *  provenance humans inspect in step 7. The snapshot leaves the array items
 *  untyped; this shape mirrors DATABASE.md §12 (bbox = [x0, y0, x1, y1]). */
export interface EvidenceSpan {
  page?: number;
  block?: number;
  text?: string;
  bbox?: number[];
  confidence?: number | null;
}

/** One extracted field with evidence + confidence (R3). `confidence` is NULL
 *  when the provider gives none (e.g. the stub) — NULL behaves like "below
 *  gate": it can never be presented as confident evidence of anything
 *  (docs/ARCHITECTURE.md §8.3). */
export interface ExtractionFieldOut {
  id: string;
  field_name: string;
  field_value: string | null;
  /** 0..1 or null (stub output is always null). */
  confidence: number | null;
  evidence_spans: EvidenceSpan[];
  verification_status: ExtractionFieldVerificationStatus;
  /** The human's value when corrected. */
  verified_value: string | null;
  /** Typed normal form, e.g. {value: "1250.00", currency: "EUR"} — additive. */
  normalized_value?: Record<string, unknown> | null;
  /** The human who confirmed/corrected, when reviewed — additive. */
  verified_by?: string | null;
  verified_at?: string | null;
}

/** Body of PATCH /documents/{id}/fields/{field_id} — the human R3 review
 *  action (reviewer/org_admin only; other roles get 403). `confirm` marks the
 *  extracted value human-verified; `correct` requires a NON-EMPTY
 *  `verified_value` (422 otherwise) and never overwrites the extraction. */
export interface ExtractionFieldReviewIn {
  action: "confirm" | "correct";
  /** Mandatory (non-empty) when action = "correct"; ignored on "confirm". */
  verified_value?: string | null;
}

// ---------------------------------------------------------------------------
// Fraud — /invoices/{id}/assess (+ latest-assessment read)
// ---------------------------------------------------------------------------

/** A signal as recorded in `fraud_assessments.signals` (DATABASE.md §13).
 *  The snapshot leaves the array items untyped; this mirrors the documented
 *  `{type, severity, field_refs, evidence_refs, message}` shape. */
export interface FraudSignal {
  type: SignalType | string;
  severity: Severity;
  field_refs: string[];
  evidence_refs: string[];
  message: string;
}

/** Per-signal child row of an assessment, individually dispositionable
 *  (fraud_findings, snapshot FraudFindingOut). A disposition (set via
 *  POST /findings/{id}/disposition) is an annotation: it never rewrites
 *  severity or the invoice status — the ARCHITECTURE §8 forcing rules are not
 *  dispositioned away. */
export interface FraudFindingOut {
  id: string;
  signal_type: SignalType | string;
  severity: Severity;
  message: string;
  field_refs: string[];
  evidence_refs: string[];
  disposition: FindingDisposition;
  /** Who/when dispositioned (null while open) — additive, snapshot. */
  dispositioned_by?: string | null;
  dispositioned_at?: string | null;
}

/** Body of POST /findings/{finding_id}/disposition (reviewer/org_admin; other
 *  roles get 403). A NON-EMPTY reason (or legacy `note`) is MANDATORY — the
 *  backend's model validator returns 422 without one. `case_id` anchors the
 *  generated review-actions row; without it the invoice's latest case is used,
 *  or a case-less review action is written. */
export interface FindingDispositionIn {
  disposition: FindingDisposition;
  /** Mandatory in practice: non-empty after trim, ≤ 2000 chars. */
  reason?: string | null;
  /** Legacy alias for `reason` accepted by the backend. */
  note?: string | null;
  case_id?: string | null;
}

/**
 * Explainable assessment (EVC v1). Invariants carried in the shape (R2): there
 * is no `is_fraud`/`is_genuine` field — only signals + explanations +
 * findings + residual uncertainty. `evc` carries the full explainable
 * structure (policy_version, weighted features with per-feature uncertainty
 * states, contributions, overrides, result state); NULL only for legacy rows.
 * The score measures consistency, never a fraud probability.
 */
export interface FraudAssessmentOut {
  id: string;
  invoice_id: string;
  risk_level: RiskLevel;
  /** 0..100, meaningful only within `model_version`; null when not computable. */
  risk_score: number | null;
  model_version: string;
  signals: FraudSignal[];
  /** Ordered human-readable reasons — the "explainable" deliverable. */
  explanation: string[];
  status: AssessmentStatus;
  /** EVC v1 structure — additive; null only on legacy assessments. */
  evc?: Record<string, unknown> | null;
  findings: FraudFindingOut[];
}

// ---------------------------------------------------------------------------
// Evidence retrieval — GET /invoices/{id}/evidence (read-only, any role)
// ---------------------------------------------------------------------------

/** Where on a source document an evidence item was found (bbox = normalized
 *  [x0, y0, x1, y1] as recorded by the retrieval index). */
export interface DocumentLocationOut {
  document_id?: string | null;
  page?: number | null;
  bbox?: number[] | null;
}

/** One citable evidence item for an invoice: what was retrieved, why it
 *  matched, with what techniques/scores, and its trust tier. Everything is
 *  provenance for the human — nothing here is a verdict (R2). */
export interface EvidenceItemOut {
  entity_type: string;
  entity_id: string;
  title: string;
  matched_field: string | null;
  /** Why this item was retrieved (graph relationship or query explanation). */
  match_explanation: string;
  /** Trust tier value (e.g. "verified" | "unverified" | "system"). */
  trust_status: string;
  retrieval_score: number;
  fused_score: number;
  /** Retrieval technique names that produced the hit (graph, exact, trigram…). */
  techniques: string[];
  document_location?: DocumentLocationOut | null;
  provenance: Record<string, unknown>;
  record_version?: string | null;
}

/** A missing relationship (R4: absence is stated as a gap — a record may
 *  simply not exist in VeriPay; severity is capped ≤ medium) or a
 *  contradiction between records. */
export interface GraphGapOut {
  kind: string;
  message: string;
  relationship: string;
  severity: Severity | string;
  detail?: Record<string, unknown>;
}

/** Query metadata of an evidence run: backend name, RRF weights, seeds. */
export interface EvidenceMetaOut {
  backend: string;
  latency_ms: number;
  seeds: string[];
  weights: Record<string, number | unknown>;
}

/** 200 of GET /invoices/{id}/evidence — the graph + fuzzy retrieval
 *  aggregation for one invoice. Read-only; org-scoped 404 for foreign ids. */
export interface InvoiceEvidenceOut {
  evidence: EvidenceItemOut[];
  gaps: GraphGapOut[];
  contradictions: GraphGapOut[];
  meta: EvidenceMetaOut;
}

// ---------------------------------------------------------------------------
// Evidence matches — GET /matches/{id}, POST /matches/{id}/review
// ---------------------------------------------------------------------------

/** One machine-detected correspondence between two entities
 *  (evidence_matches, DATABASE.md v2). `status` is the human disposition:
 *  open | dismissed | confirmed (MatchStatus). */
export interface EvidenceMatchOut {
  id: string;
  source_entity_type: string;
  source_entity_id: string;
  target_entity_type: string;
  target_entity_id: string;
  match_kind: MatchKind | string;
  similarity_score: number;
  matched_fields: Record<string, unknown>;
  status: MatchStatus | string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

/** Body of POST /matches/{match_id}/review (reviewer/org_admin only; 403
 *  otherwise). `status` is a DECISION — the backend accepts only
 *  "dismissed" | "confirmed" ("open" is not a decision and returns 422), and
 *  a NON-EMPTY reason is mandatory (422 without one). */
export interface MatchReviewIn {
  status: Exclude<MatchStatus, "open"> | string;
  /** Mandatory in practice: non-empty after trim, ≤ 2000 chars. */
  reason?: string | null;
  /** Legacy alias for `reason` accepted by the backend. */
  note?: string | null;
  case_id?: string | null;
}

// ---------------------------------------------------------------------------
// Invoice line items — GET/POST /invoices/{id}/line-items
// ---------------------------------------------------------------------------

/** Body of POST /invoices/{id}/line-items. Money as decimal STRINGS
 *  (Numeric(14,4)/(14,2) — never float, DATABASE.md §1). */
export interface LineItemIn {
  description?: string | null;
  quantity?: string | null;
  unit_price?: string | null;
  line_total?: string | null;
}

/** One invoice line item (parse/display `position` order). */
export interface LineItemOut {
  id: string;
  invoice_id: string;
  position: number;
  description: string | null;
  quantity: string | null;
  unit_price: string | null;
  line_total: string | null;
}

// ---------------------------------------------------------------------------
// Processing jobs — GET /processing-jobs/{id} (ADR 0006 state machine)
// ---------------------------------------------------------------------------

/** One durable processing job (processing_jobs). Documents/assessments are
 *  the higher-level views; this is the job row itself. */
export interface ProcessingJobOut {
  id: string;
  job_type: string; // JobType: ocr_extraction | duplicate_scan | assessment
  status: ProcessingStatus | string;
  attempts: number;
  max_attempts: number;
  backend: string;
  idempotency_key: string;
  document_id: string | null;
  invoice_id: string | null;
  last_error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

// ---------------------------------------------------------------------------
// Cases & review actions — /cases (R6; investigation_cases / review_actions)
// ---------------------------------------------------------------------------

export interface CaseIn {
  title: string;
  severity: CaseSeverity;
  description?: string | null;
  /** At least one of invoice_id / vendor_id (DB CHECK). */
  invoice_id?: string | null;
  vendor_id?: string | null;
}

export interface CaseOut {
  id: string;
  case_number: string;
  invoice_id: string | null;
  vendor_id: string | null;
  title: string;
  severity: CaseSeverity;
  status: CaseStatus;
  /** Set ONLY by a human at close (R6). */
  outcome: CaseOutcome | string | null;
  assigned_to: string | null;
  /** R6 provenance: the assessment that opened the case (auto-opened ones);
   *  the latest assessment can differ from the triggering one. Additive. */
  triggering_assessment_id?: string | null;
}

/** Body of POST /cases/{id}/assign. */
export interface CaseAssignIn {
  user_id: string;
}

/** Body of POST /cases/{id}/close — outcome + resolution summary are
 *  mandatory (422 without them; R6). */
export interface CaseCloseIn {
  outcome: CaseOutcome;
  resolution_summary: string;
}

export interface ReviewActionIn {
  action_type: ReviewActionType | string;
  body: string;
  payload?: Record<string, unknown> | null;
}

export interface ReviewActionOut {
  id: string;
  action_type: ReviewActionType | string;
  body: string;
  payload: Record<string, unknown> | null;
  actor_user_id: string | null;
}

// ---------------------------------------------------------------------------
// Audit — GET /audit-events (append-only; org_admin/auditor only)
// ---------------------------------------------------------------------------

export interface AuditEventOut {
  id: string;
  /** Nullable: pre-auth events (failed login for an unknown email) have no
   *  tenant — the one intentional exception to org scoping (DATABASE.md §15). */
  organization_id: string | null;
  actor_user_id: string | null;
  actor_type: ActorType;
  /** Dotted names: `document.uploaded`, `case.opened`, `vendor.account.verified`, … */
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  detail: Record<string, unknown> | null;
  occurred_at: string | null;
}

export interface AuditEventsListParams extends ListParams {
  /** Exact-action filter (snapshot: `action: query`). */
  action?: string;
}

// ---------------------------------------------------------------------------
// Dashboard stats — GET /stats/dashboard (org-scoped aggregates)
// ---------------------------------------------------------------------------
// In the committed openapi.json snapshot (verified 2026-10-17; the drift test
// against the live schema is the CI gate). Shape mirrors the Pydantic
// DashboardStatsOut (_domain_schemas.py) exactly.
//
// R2 note carried from the backend docstrings: these counts are work-queue
// sizes for decision support — needs_review/high_risk are NOT verdicts and
// never imply that any invoice is genuine.

export interface DashboardStatsOut {
  organization_id: string;
  total_invoices: number;
  needs_review_invoices: number;
  open_cases: number;
  high_risk_invoices: number;
  processing_failures: number;
}
