/**
 * Typed fetch wrapper for the VeriPay REST API (docs/API.md).
 *
 * Design rules for the static export:
 * - The base URL comes from NEXT_PUBLIC_API_BASE_URL and is NOT required at
 *   build time: when unset it falls back to http://localhost:8000, so a pure
 *   static preview always builds and renders.
 * - docs/API.md §1: every v1 endpoint lives under /api/v1. Both common base
 *   forms — with or without the /api/v1 suffix (the repo-root .env.example
 *   uses the suffixed form) — are normalized here, never double-appended.
 *   Callers pass endpoint paths only, e.g. "/auth/me".
 * - Session (ADR 0005, kept unchanged): the durable session is the httpOnly
 *   `veripay_session` cookie (credentials: "include" on every call); the
 *   readable `veripay_csrf` cookie is echoed in `X-CSRF-Token` on mutating
 *   requests; the short-lived Bearer token lives in memory only and 401s are
 *   transparently refreshed via POST /auth/refresh.
 * - Errors: every non-2xx response uses the versioned envelope (docs/API.md
 *   §2) and is parsed into ApiError; `message` is safe to render. Fetch
 *   rejections (API unreachable / offline) become ApiNetworkError. UI code
 *   must branch on these instead of crashing — the static pages render even
 *   with no backend running.
 * - List endpoints: the docs/API.md §3 envelope — `{"items": [...],
 *   "pagination": {limit, offset, total}}` — on every list surface. The list
 *   helpers below return the `Paginated<T>` envelope; consumers read
 *   `.items` (and `.pagination.total` where the total matters).
 */
import type {
  ApiErrorBody,
  ApiErrorResponse,
  AuditEventOut,
  AuditEventsListParams,
  BankAccountIn,
  BankAccountListItem,
  BankAccountDetail,
  CaseAssignIn,
  CaseCloseIn,
  CaseIn,
  CaseOut,
  ChangeRequestDecisionIn,
  ChangeRequestIn,
  ChangeRequestOut,
  ContactIn,
  ContactOut,
  DashboardStatsOut,
  DocumentOut,
  EvidenceMatchOut,
  ExtractionFieldOut,
  ExtractionFieldReviewIn,
  ExtractionResultOut,
  FindingDispositionIn,
  FraudAssessmentOut,
  FraudFindingOut,
  HealthOut,
  InvoiceEvidenceOut,
  InvoiceIn,
  InvoiceOut,
  LineItemIn,
  LineItemOut,
  ListParams,
  LogoutResponse,
  MatchReviewIn,
  MeResponse,
  Paginated,
  ProcessingJobOut,
  ProcessedDocumentOut,
  PurchaseOrderIn,
  PurchaseOrderOut,
  RefreshResponse,
  RegisterRequest,
  RegisterResponse,
  RejectAccountIn,
  ResolveVendorIn,
  ReviewActionIn,
  ReviewActionOut,
  TokenResponse,
  UploadDocumentBody,
  VendorIn,
  VendorOut,
  VerifyAccountIn,
} from "@veripay/api-contracts";
import { clearAccessToken, getAccessToken, getCsrfToken, setAccessToken as setAccessTokenInternal } from "./auth";

/** Used when NEXT_PUBLIC_API_BASE_URL is not set at build time. */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Normalized API root (origin + /api/v1), for display in offline hints. */
export function getApiRoot(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  const base = raw.replace(/\/+$/, "");
  return /\/api\/v1$/i.test(base) ? base : `${base}/api/v1`;
}

/** Non-2xx parsed from the docs/API.md §2 envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorBody["code"];
  readonly details?: ApiErrorBody["details"];
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }

  /** field → first message, from `validation_error` details (docs/API.md §2). */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const detail of this.details ?? []) {
      if (detail.field) out[detail.field] ??= detail.message;
    }
    return out;
  }
}

/** fetch() itself rejected — the API is unreachable (offline / wrong port). */
export class ApiNetworkError extends Error {
  constructor(options?: { cause?: unknown }) {
    super("Could not reach the VeriPay API.", options ? { cause: options.cause } : undefined);
    this.name = "ApiNetworkError";
  }
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function performFetch<T>(path: string, init?: RequestInit): Promise<Response> {
  const url = `${getApiRoot()}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = new Headers(init?.headers);
  const token = getAccessToken();
  // Never clobber an explicitly provided Authorization header.
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  // CSRF double-submit: mutating requests authenticated by the session cookie
  // must echo the readable csrf cookie (Bearer requests are exempt — the
  // backend enforces the rule, the client just always complies).
  const method = (init?.method ?? "GET").toUpperCase();
  if (MUTATING_METHODS.has(method) && !headers.has("X-CSRF-Token")) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  try {
    // credentials: the httpOnly session cookie IS the durable session — it
    // must travel on every call, same-origin locally and via the SWA proxy.
    return await fetch(url, { ...init, headers, credentials: "include" });
  } catch (cause) {
    // fetch only rejects on network-level failures — the API is unreachable.
    throw new ApiNetworkError({ cause });
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let parsed: unknown;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined; // HTML error page / proxy noise — handled below
    }
  }

  if (!response.ok) {
    const envelope = parsed as ApiErrorResponse | undefined;
    const body =
      envelope && typeof envelope === "object" && envelope.error && typeof envelope.error === "object"
        ? envelope.error
        : undefined;
    if (body && typeof body.code === "string" && typeof body.message === "string") {
      throw new ApiError(response.status, body);
    }
    // Non-enveloped failure (gateway page, empty body…). Keep the envelope
    // contract: message stays user-safe; body snippets land in details.
    throw new ApiError(response.status, {
      code: "internal",
      message: `The API returned an unexpected response (HTTP ${response.status}).`,
      request_id: "",
      details: text ? [{ message: `Response body: ${text.slice(0, 200)}` }] : undefined,
    });
  }

  // A 2xx with an empty/non-JSON body would otherwise resolve `undefined`
  // typed as T — every caller expects a JSON contract body, so fail loudly.
  if (parsed === undefined) {
    throw new ApiError(response.status, {
      code: "internal",
      message: "The API returned a 2xx response with an empty or non-JSON body.",
      request_id: "",
    });
  }
  return parsed as T;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await performFetch<T>(path, init);
  if (response.status === 401 && getAccessToken() && !path.startsWith("/auth/")) {
    // The in-memory Bearer token expired. One transparent refresh attempt;
    // on success the original request is retried with the fresh token.
    try {
      const refreshed = await parseResponse<RefreshResponse>(
        await performFetch("/auth/refresh", { method: "POST" })
      );
      setAccessTokenInternal(refreshed.access_token);
      const retry = await performFetch<T>(path, init);
      return await parseResponse<T>(retry);
    } catch {
      clearAccessToken();
      throw await parseResponse<T>(response);
    }
  }
  return await parseResponse<T>(response);
}

// ---------------------------------------------------------------------------
// Small helpers shared by the endpoint functions below
// ---------------------------------------------------------------------------

/** Build `?limit=&offset=&…` from an optional params object — undefined and
 *  empty values are omitted entirely (the backend defaults apply). Generic so
 *  the contracts' ListParams interfaces (no index signature) are accepted. */
export function buildQuery<T extends object>(params?: T): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value === undefined || value === null || value === "") continue;
    if (typeof value !== "string" && typeof value !== "number") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

function jsonRequest(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  };
}

// ---------------------------------------------------------------------------
// Health — GET /health (public)
// ---------------------------------------------------------------------------

export async function fetchHealth(): Promise<HealthOut> {
  return apiFetch<HealthOut>("/health");
}

// ---------------------------------------------------------------------------
// Auth — docs/API.md §4 (Phase 1 surface, unchanged)
// ---------------------------------------------------------------------------

/**
 * POST /auth/login — OAuth2 password form: `username` carries the email so
 * FastAPI's "Authorize" button works out of the box (docs/API.md §4).
 */
export async function loginRequest(email: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams({ username: email, password });
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
}

/** POST /auth/register — creates a new organization and its first user (owner). */
export async function registerRequest(input: RegisterRequest): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

/** GET /auth/me — requires auth; the session cookie authenticates it
 *  (credentials: "include"), the Bearer token is attached automatically when
 *  one is held in memory. */
export async function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me");
}

/**
 * POST /auth/logout — requires auth; revokes the presented credential
 * (session row or Bearer jti) server-side so a signed-out session is rejected
 * even though the cookie might still be present. Fire-and-forget on the
 * client: the local session must be cleared even when the API is unreachable.
 */
export async function logoutRequest(): Promise<LogoutResponse> {
  return apiFetch<LogoutResponse>("/auth/logout", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Vendors — /vendors (API.md §6)
// ---------------------------------------------------------------------------

export async function createVendor(input: VendorIn): Promise<VendorOut> {
  return apiFetch<VendorOut>("/vendors", jsonRequest(input));
}

export async function listVendors(params?: ListParams): Promise<Paginated<VendorOut>> {
  return apiFetch<Paginated<VendorOut>>(`/vendors${buildQuery(params)}`);
}

export async function getVendor(vendorId: string): Promise<VendorOut> {
  return apiFetch<VendorOut>(`/vendors/${encodeURIComponent(vendorId)}`);
}

// ---------------------------------------------------------------------------
// Vendor contacts — /vendors/{id}/contacts
// ---------------------------------------------------------------------------

export async function listContacts(vendorId: string): Promise<Paginated<ContactOut>> {
  return apiFetch<Paginated<ContactOut>>(`/vendors/${encodeURIComponent(vendorId)}/contacts`);
}

export async function createContact(vendorId: string, input: ContactIn): Promise<ContactOut> {
  return apiFetch<ContactOut>(
    `/vendors/${encodeURIComponent(vendorId)}/contacts`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Bank accounts (R5) — /vendors/{id}/bank-accounts
// ---------------------------------------------------------------------------

/** List a vendor's bank accounts. Items are the masked view; for
 *  reviewer/org_admin the backend widens them to BankAccountDetail (the R5
 *  verification provenance — API.md §5.8). */
export async function listBankAccounts(vendorId: string): Promise<Paginated<BankAccountListItem>> {
  return apiFetch<Paginated<BankAccountListItem>>(
    `/vendors/${encodeURIComponent(vendorId)}/bank-accounts`
  );
}

/** Create a PENDING account (R5: nothing can create an approved account). */
export async function createBankAccount(
  vendorId: string,
  input: BankAccountIn
): Promise<BankAccountListItem> {
  return apiFetch<BankAccountListItem>(
    `/vendors/${encodeURIComponent(vendorId)}/bank-accounts`,
    jsonRequest(input)
  );
}

/**
 * POST …/bank-accounts/{id}/verify — the ONLY way an account becomes
 * `approved` (R5): a human, with an independent verification method and a
 * reference or supporting document. Missing method → 422
 * business_rule_violation; there is no automatic path anywhere.
 */
export async function verifyBankAccount(
  vendorId: string,
  accountId: string,
  input: VerifyAccountIn
): Promise<BankAccountDetail> {
  return apiFetch<BankAccountDetail>(
    `/vendors/${encodeURIComponent(vendorId)}/bank-accounts/${encodeURIComponent(accountId)}/verify`,
    jsonRequest(input)
  );
}

export async function rejectBankAccount(
  vendorId: string,
  accountId: string,
  input: RejectAccountIn = {}
): Promise<BankAccountDetail> {
  return apiFetch<BankAccountDetail>(
    `/vendors/${encodeURIComponent(vendorId)}/bank-accounts/${encodeURIComponent(accountId)}/reject`,
    jsonRequest(input)
  );
}

export async function revokeBankAccount(
  vendorId: string,
  accountId: string,
  input: RejectAccountIn = {}
): Promise<BankAccountDetail> {
  return apiFetch<BankAccountDetail>(
    `/vendors/${encodeURIComponent(vendorId)}/bank-accounts/${encodeURIComponent(accountId)}/revoke`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Bank-account change requests (R5 change control)
// ---------------------------------------------------------------------------

export async function listChangeRequests(vendorId: string): Promise<Paginated<ChangeRequestOut>> {
  return apiFetch<Paginated<ChangeRequestOut>>(
    `/vendors/${encodeURIComponent(vendorId)}/change-requests`
  );
}

export async function createChangeRequest(
  vendorId: string,
  input: ChangeRequestIn
): Promise<ChangeRequestOut> {
  return apiFetch<ChangeRequestOut>(
    `/vendors/${encodeURIComponent(vendorId)}/change-requests`,
    jsonRequest(input)
  );
}

/** Human approval (reviewer/org_admin only) — on approval the service creates
 *  the approved account stamped with the deciding human. */
export async function approveChangeRequest(
  vendorId: string,
  requestId: string,
  input: ChangeRequestDecisionIn = {}
): Promise<ChangeRequestOut> {
  return apiFetch<ChangeRequestOut>(
    `/vendors/${encodeURIComponent(vendorId)}/change-requests/${encodeURIComponent(requestId)}/approve`,
    jsonRequest(input)
  );
}

export async function rejectChangeRequest(
  vendorId: string,
  requestId: string,
  input: ChangeRequestDecisionIn = {}
): Promise<ChangeRequestOut> {
  return apiFetch<ChangeRequestOut>(
    `/vendors/${encodeURIComponent(vendorId)}/change-requests/${encodeURIComponent(requestId)}/reject`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Purchase orders — /purchase-orders
// ---------------------------------------------------------------------------

export async function createPurchaseOrder(input: PurchaseOrderIn): Promise<PurchaseOrderOut> {
  return apiFetch<PurchaseOrderOut>("/purchase-orders", jsonRequest(input));
}

export async function listPurchaseOrders(params?: ListParams): Promise<Paginated<PurchaseOrderOut>> {
  return apiFetch<Paginated<PurchaseOrderOut>>(`/purchase-orders${buildQuery(params)}`);
}

export async function getPurchaseOrder(poId: string): Promise<PurchaseOrderOut> {
  return apiFetch<PurchaseOrderOut>(`/purchase-orders/${encodeURIComponent(poId)}`);
}

// ---------------------------------------------------------------------------
// Invoices — /invoices
// ---------------------------------------------------------------------------

export async function createInvoice(input: InvoiceIn): Promise<InvoiceOut> {
  return apiFetch<InvoiceOut>("/invoices", jsonRequest(input));
}

export async function listInvoices(params?: ListParams): Promise<Paginated<InvoiceOut>> {
  return apiFetch<Paginated<InvoiceOut>>(`/invoices${buildQuery(params)}`);
}

export async function getInvoice(invoiceId: string): Promise<InvoiceOut> {
  return apiFetch<InvoiceOut>(`/invoices/${encodeURIComponent(invoiceId)}`);
}

/** POST /invoices/{id}/resolve-vendor — attach an existing vendor or create a
 *  pending vendor from a name; duplicates from resolution become
 *  needs_review signals, never 409 (API.md §2). */
export async function resolveInvoiceVendor(
  invoiceId: string,
  input: ResolveVendorIn
): Promise<InvoiceOut> {
  return apiFetch<InvoiceOut>(
    `/invoices/${encodeURIComponent(invoiceId)}/resolve-vendor`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Fraud assessments — /invoices/{id}/assess (+ latest read)
// ---------------------------------------------------------------------------

/** POST /invoices/{id}/assess — deterministic explainable assessment
 *  (rules-v0.1). Signals carry severities per ARCHITECTURE §8; a `critical`
 *  result auto-opens a case (R6) server-side. */
export async function assessInvoice(invoiceId: string): Promise<FraudAssessmentOut> {
  return apiFetch<FraudAssessmentOut>(
    `/invoices/${encodeURIComponent(invoiceId)}/assess`,
    { method: "POST" }
  );
}

/** GET /invoices/{id}/assessment — the latest assessment, or null when the
 *  invoice has not been assessed yet. */
export async function getLatestAssessment(invoiceId: string): Promise<FraudAssessmentOut | null> {
  return apiFetch<FraudAssessmentOut | null>(
    `/invoices/${encodeURIComponent(invoiceId)}/assessment`
  );
}

// ---------------------------------------------------------------------------
// Evidence retrieval — GET /invoices/{id}/evidence (read-only)
// ---------------------------------------------------------------------------

/**
 * GET /invoices/{id}/evidence — the org-scoped citable evidence for one
 * invoice: graph relationships + fuzzy retrieval hits (vendor, approved bank
 * accounts, PO, historical invoices, review actions) plus the missing
 * relationships (gaps) and data disagreements (contradictions).
 *
 * Read-only aggregation with provenance (ARCHITECTURE §4 step 4) — nothing
 * here approves anything or claims genuineness; gaps are absence statements
 * (R4), never fraud claims.
 */
export async function getInvoiceEvidence(invoiceId: string): Promise<InvoiceEvidenceOut> {
  return apiFetch<InvoiceEvidenceOut>(
    `/invoices/${encodeURIComponent(invoiceId)}/evidence`
  );
}

// ---------------------------------------------------------------------------
// Findings & matches — human dispositions of machine detections
// ---------------------------------------------------------------------------

/**
 * POST /findings/{finding_id}/disposition — human disposition of one signal
 * (reviewer/org_admin only; other roles get 403). A NON-EMPTY reason is
 * MANDATORY — the backend's model validator returns 422 without one
 * (_domain_schemas.py FindingDispositionIn). A disposition is an annotation:
 * it never rewrites severity or un-flags the invoice (the ARCHITECTURE §8
 * forcing rules are not dispositioned away).
 */
export async function dispositionFinding(
  findingId: string,
  input: FindingDispositionIn
): Promise<FraudFindingOut> {
  return apiFetch<FraudFindingOut>(
    `/findings/${encodeURIComponent(findingId)}/disposition`,
    jsonRequest(input)
  );
}

/** GET /matches/{match_id} — one evidence-match row (org-scoped 404). */
export async function getMatch(matchId: string): Promise<EvidenceMatchOut> {
  return apiFetch<EvidenceMatchOut>(`/matches/${encodeURIComponent(matchId)}`);
}

/**
 * POST /matches/{match_id}/review — human review decision on one evidence
 * match (reviewer/org_admin). `status` must be "dismissed" | "confirmed"
 * ("open" is not a decision — 422); a NON-EMPTY reason is mandatory (422).
 * NOTE: no current response exposes evidence-match ids (the duplicate_candidate
 * finding's evidence_refs carry the OTHER INVOICE's id), so no screen can
 * address this endpoint yet — it is wrapped for completeness, and the
 * matches panel states that honestly instead of faking a flow.
 */
export async function reviewMatch(
  matchId: string,
  input: MatchReviewIn
): Promise<EvidenceMatchOut> {
  return apiFetch<EvidenceMatchOut>(
    `/matches/${encodeURIComponent(matchId)}/review`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Invoice line items — /invoices/{id}/line-items
// ---------------------------------------------------------------------------

/** GET /invoices/{id}/line-items — parse/display order line items. */
export async function listLineItems(invoiceId: string): Promise<Paginated<LineItemOut>> {
  return apiFetch<Paginated<LineItemOut>>(
    `/invoices/${encodeURIComponent(invoiceId)}/line-items`
  );
}

/** POST /invoices/{id}/line-items — money as decimal STRINGS (never float). */
export async function createLineItem(
  invoiceId: string,
  input: LineItemIn
): Promise<LineItemOut> {
  return apiFetch<LineItemOut>(
    `/invoices/${encodeURIComponent(invoiceId)}/line-items`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Processing jobs — GET /processing-jobs/{id} (ADR 0006)
// ---------------------------------------------------------------------------

/** GET /processing-jobs/{id} — one durable processing job row. */
export async function getProcessingJob(jobId: string): Promise<ProcessingJobOut> {
  return apiFetch<ProcessingJobOut>(
    `/processing-jobs/${encodeURIComponent(jobId)}`
  );
}

// ---------------------------------------------------------------------------
// Documents — /documents (multipart upload + reads + processing)
// ---------------------------------------------------------------------------

/**
 * POST /documents — multipart/form-data upload. `kind`/`vendor_id` ride as
 * form fields alongside the file. NOTE: the browser sets the multipart
 * Content-Type (with the boundary) when the body is a FormData — never set
 * the header manually here.
 */
export async function uploadDocument(
  body: UploadDocumentBody & { fileName?: string }
): Promise<ProcessedDocumentOut> {
  const form = new FormData();
  form.append("file", body.file, body.fileName);
  if (body.kind) form.append("kind", body.kind);
  if (body.vendor_id) form.append("vendor_id", body.vendor_id);
  return apiFetch<ProcessedDocumentOut>("/documents", { method: "POST", body: form });
}

export async function listDocuments(params?: ListParams): Promise<Paginated<DocumentOut>> {
  return apiFetch<Paginated<DocumentOut>>(`/documents${buildQuery(params)}`);
}

export async function getDocument(documentId: string): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`/documents/${encodeURIComponent(documentId)}`);
}

/**
 * GET /documents/{id}/file — protected download (DB-resolved storage key,
 * never a client path). Returns the raw bytes as a Blob plus the server
 * filename (from the record when the Content-Disposition header is absent).
 */
export async function downloadDocumentFile(
  documentId: string,
  fallbackFileName: string
): Promise<{ blob: Blob; fileName: string }> {
  const response = await performFetch(`/documents/${encodeURIComponent(documentId)}/file`);
  if (!response.ok) {
    // Reuse the envelope parser so errors surface exactly like other calls
    // (it always throws on a non-2xx response).
    await parseResponse<never>(response);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
  let fileName = fallbackFileName;
  if (utf8Match?.[1]) {
    try {
      fileName = decodeURIComponent(utf8Match[1]);
    } catch {
      fileName = fallbackFileName;
    }
  } else if (plainMatch?.[1]) {
    fileName = plainMatch[1];
  }
  return { blob: await response.blob(), fileName };
}

/** GET /documents/{id}/extraction — the extraction umbrella row, or null
 *  when the document has not been processed yet. */
export async function getExtraction(documentId: string): Promise<ExtractionResultOut | null> {
  return apiFetch<ExtractionResultOut | null>(
    `/documents/${encodeURIComponent(documentId)}/extraction`
  );
}

/** GET /documents/{id}/fields — per-field rows with evidence spans +
 *  confidence (R3). Empty items when nothing was extracted yet. */
export async function listExtractionFields(documentId: string): Promise<Paginated<ExtractionFieldOut>> {
  return apiFetch<Paginated<ExtractionFieldOut>>(
    `/documents/${encodeURIComponent(documentId)}/fields`
  );
}

/**
 * PATCH /documents/{id}/fields/{field_id} — the human R3 field review:
 * confirm the extracted value, or correct it with verified_value.
 * Reviewer/org_admin only (403 otherwise); "correct" requires a NON-EMPTY
 * verified_value (422 otherwise). The original extraction is never
 * overwritten — the human's value lands in verified_value.
 */
export async function reviewExtractionField(
  documentId: string,
  fieldId: string,
  input: ExtractionFieldReviewIn
): Promise<ExtractionFieldOut> {
  return apiFetch<ExtractionFieldOut>(
    `/documents/${encodeURIComponent(documentId)}/fields/${encodeURIComponent(fieldId)}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) }
  );
}

/** POST /documents/{id}/process — idempotent retry of the processing job. */
export async function reprocessDocument(documentId: string): Promise<ProcessedDocumentOut> {
  return apiFetch<ProcessedDocumentOut>(
    `/documents/${encodeURIComponent(documentId)}/process`,
    { method: "POST" }
  );
}

// ---------------------------------------------------------------------------
// Cases & review actions (R6) — /cases
// ---------------------------------------------------------------------------

export async function listCases(params?: ListParams): Promise<Paginated<CaseOut>> {
  return apiFetch<Paginated<CaseOut>>(`/cases${buildQuery(params)}`);
}

export async function openCase(input: CaseIn): Promise<CaseOut> {
  return apiFetch<CaseOut>("/cases", jsonRequest(input));
}

export async function getCase(caseId: string): Promise<CaseOut> {
  return apiFetch<CaseOut>(`/cases/${encodeURIComponent(caseId)}`);
}

export async function assignCase(caseId: string, input: CaseAssignIn): Promise<CaseOut> {
  return apiFetch<CaseOut>(`/cases/${encodeURIComponent(caseId)}/assign`, jsonRequest(input));
}

/** POST /cases/{id}/close — outcome + resolution summary mandatory (R6);
 *  missing either → 422 business_rule_violation. */
export async function closeCase(caseId: string, input: CaseCloseIn): Promise<CaseOut> {
  return apiFetch<CaseOut>(`/cases/${encodeURIComponent(caseId)}/close`, jsonRequest(input));
}

export async function listReviewActions(caseId: string): Promise<Paginated<ReviewActionOut>> {
  return apiFetch<Paginated<ReviewActionOut>>(`/cases/${encodeURIComponent(caseId)}/actions`);
}

export async function addReviewAction(
  caseId: string,
  input: ReviewActionIn
): Promise<ReviewActionOut> {
  return apiFetch<ReviewActionOut>(
    `/cases/${encodeURIComponent(caseId)}/actions`,
    jsonRequest(input)
  );
}

// ---------------------------------------------------------------------------
// Audit — GET /audit-events (org_admin/auditor only, append-only)
// ---------------------------------------------------------------------------

export async function listAuditEvents(params?: AuditEventsListParams): Promise<Paginated<AuditEventOut>> {
  return apiFetch<Paginated<AuditEventOut>>(`/audit-events${buildQuery(params)}`);
}

// ---------------------------------------------------------------------------
// Dashboard stats — GET /stats/dashboard (org-scoped aggregates)
// ---------------------------------------------------------------------------
// Backend route in flight at the time of writing (untracked stats route +
// module, registered in api/v1/router.py); shape mirrors its Pydantic
// DashboardStatsOut. See the contract note in packages/api-contracts.

export async function fetchDashboardStats(): Promise<DashboardStatsOut> {
  return apiFetch<DashboardStatsOut>("/stats/dashboard");
}

// ---------------------------------------------------------------------------
// Vocabulary re-exports for screen code (single import site)
// ---------------------------------------------------------------------------

export type {
  AssessmentStatus,
  BankAccountVerificationMethod,
  CaseOutcome,
  DocumentKind,
  FindingDisposition,
  InvoiceStatus,
  ProcessingStatus,
  RiskLevel,
  Severity,
  SignalType,
} from "@veripay/api-contracts";
