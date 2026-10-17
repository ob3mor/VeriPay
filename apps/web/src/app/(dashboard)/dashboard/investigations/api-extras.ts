/**
 * Investigation-workspace UI helpers.
 *
 * History: the backend surfaces below existed in the working tree before they
 * were part of the committed OpenAPI snapshot, so their typed wrappers lived
 * here. They are now first-class in src/lib/api.ts (snapshot-verified
 * 2026-10-17) and re-exported for the panels:
 *
 * - PATCH  /documents/{id}/fields/{field_id}   → reviewExtractionField (R3
 *     human review; reviewer/org_admin only)
 * - POST   /findings/{finding_id}/disposition  → dispositionFinding
 *     (reviewer/org_admin; a NON-EMPTY reason is mandatory — 422 otherwise)
 * - GET    /invoices/{id}/line-items           → listLineItems
 * - GET    /invoices/{id}/evidence             → getInvoiceEvidence
 *
 * Still intentionally NOT wired: POST /matches/{match_id}/review — the API
 * has no list endpoint that exposes evidence-match IDs, and the
 * duplicate_candidate finding's evidence_refs carry the OTHER INVOICE's id
 * (fraud/evc.py), not a match id. There is no honest way to wire a
 * match-review action yet; duplicate candidates are surfaced and dispositioned
 * through the finding disposition instead (stated in the matches panel).
 */
import { ApiError } from "@/lib/api";

export {
  dispositionFinding,
  getInvoiceEvidence,
  listLineItems,
  reviewExtractionField,
} from "@/lib/api";

export type {
  ExtractionFieldReviewIn,
  FindingDispositionIn,
  LineItemOut,
} from "@veripay/api-contracts";

/** User-safe message from a failed mutation: the envelope `message` when the
 *  API answered (docs/API.md §2 — safe to display), the caller's fallback
 *  otherwise. Never a raw error. */
export function mutationMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  return fallback;
}

/** True when a failed request was an offline/network failure — panels use it
 *  to phrase the retry hint honestly. */
export function isNetworkError(error: unknown): boolean {
  return error instanceof Error && error.name === "ApiNetworkError";
}
