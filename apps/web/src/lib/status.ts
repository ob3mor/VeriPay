/**
 * Honest status vocabulary — single source of truth for user-facing status
 * labels in the web app.
 *
 * Business invariants (docs/ARCHITECTURE.md §8, normative):
 * - R1: VeriPay never authorizes payments → there is no "Payment Approved"
 *   state anywhere in this mapping, and there never will be.
 * - R2: VeriPay never claims an invoice is genuine → the words
 *   "genuine"/"legitimate"/"safe"/"verified invoice" are banned. The most
 *   positive label allowed is "No material discrepancies" — a statement about
 *   what the assessment found, not a verdict on the invoice.
 * - R4: missing records are not fraud → absence never maps to a
 *   high-severity label.
 *
 * The four assessment-outcome labels below are the owner-mandated vocabulary
 * (Prompt 05); every other state uses neutral, factual labels.
 */

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

export interface StatusPresentation {
  label: string;
  tone: BadgeTone;
}

/**
 * The four honest assessment outcomes (owner vocabulary, Prompt 05):
 *
 * | Assessment                  | Label                    | Tone    |
 * |-----------------------------|--------------------------|---------|
 * | risk none / low             | No material discrepancies| success |
 * | risk medium                 | Manual review required   | warning |
 * | risk high                   | High-risk discrepancy    | danger  |
 * | risk critical               | High-risk discrepancy    | danger  |
 * | processing / assessment failed | Processing failed     | danger  |
 */
export const HONEST_OUTCOME_LABELS = {
  noMaterialDiscrepancies: "No material discrepancies",
  manualReviewRequired: "Manual review required",
  highRiskDiscrepancy: "High-risk discrepancy",
  processingFailed: "Processing failed",
} as const;

/**
 * The per-row FETCH failed (e.g. a network hiccup on the small per-invoice
 * assessment GET) — deliberately distinct from "Processing failed", which
 * means the assessment itself ran and reported a failed state. A load
 * failure says nothing about the invoice or the pipeline; a retry is
 * offered instead of leaving the row in a permanent loading state.
 */
export const LOAD_FAILED_PRESENTATION: StatusPresentation = {
  label: "Load failed",
  tone: "warning",
};

/**
 * Map a fraud-assessment `risk_level` (core.enums.RiskLevel) to its honest
 * presentation. `critical` and `high` deliberately share the label — both
 * mean "a material discrepancy exists and a human must look at it"; the
 * severity badge carries the gradation. "No material discrepancies" is a
 * finding statement, never a genuineness claim (R2).
 */
export function assessmentRiskPresentation(riskLevel: string): StatusPresentation {
  switch (riskLevel) {
    case "none":
    case "low":
      return { label: HONEST_OUTCOME_LABELS.noMaterialDiscrepancies, tone: "success" };
    case "medium":
      return { label: HONEST_OUTCOME_LABELS.manualReviewRequired, tone: "warning" };
    case "high":
    case "critical":
      return { label: HONEST_OUTCOME_LABELS.highRiskDiscrepancy, tone: "danger" };
    default:
      // Unknown value: render it as-is, neutral — never invent a verdict.
      return { label: riskLevel, tone: "neutral" };
  }
}

/**
 * Map a document/processing `processing_status` (core.enums.ProcessingStatus)
 * to its honest presentation. Failed processing is stated as failed — never
 * papered over as "done" or "clear".
 */
export function processingStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "pending":
      return { label: "Queued", tone: "neutral" };
    case "processing":
      return { label: "Processing", tone: "info" };
    case "completed":
      return { label: "Processed", tone: "success" };
    case "failed":
      return { label: HONEST_OUTCOME_LABELS.processingFailed, tone: "danger" };
    case "requires_manual_input":
      return { label: "Manual input required", tone: "warning" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/**
 * Map an invoice `status` (core.enums.InvoiceStatus) to its honest
 * presentation. R1/R2: "closed" is a human workflow disposition — it does NOT
 * mean approved or genuine, and is labeled accordingly.
 */
export function invoiceStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "received":
      return { label: "Received", tone: "neutral" };
    case "processing":
      return { label: "Processing", tone: "info" };
    case "needs_review":
      return { label: HONEST_OUTCOME_LABELS.manualReviewRequired, tone: "warning" };
    case "closed":
      return { label: "Closed by reviewer", tone: "muted" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/**
 * Map a bank-account `status` (core.enums.BankAccountStatus, R5) to its
 * presentation. "Verified" is the human's independent verification decision —
 * the only meaning "approval" has in this product, and it never refers to a
 * payment or an invoice.
 */
export function bankAccountStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "pending":
      return { label: "Pending verification", tone: "warning" };
    case "approved":
      return { label: "Verified", tone: "success" };
    case "rejected":
      return { label: "Rejected", tone: "danger" };
    case "revoked":
      return { label: "Revoked", tone: "danger" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/** Case status (core.enums.CaseStatus, R6 workflow). */
export function caseStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "open":
      return { label: "Open", tone: "info" };
    case "in_review":
      return { label: "In review", tone: "warning" };
    case "waiting_vendor":
      return { label: "Waiting on vendor", tone: "neutral" };
    case "closed":
      return { label: "Closed", tone: "muted" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/**
 * Case outcome (core.enums.CaseOutcome) — set only by a human at close (R6).
 * Even `no_critical_findings` is a case disposition, NOT a claim that the
 * invoice is genuine (R2), so it is labeled plainly with no genuineness
 * language.
 */
export function caseOutcomePresentation(outcome: string): StatusPresentation {
  switch (outcome) {
    case "fraud_confirmed":
      return { label: "Fraud confirmed", tone: "danger" };
    case "policy_violation":
      return { label: "Policy violation", tone: "danger" };
    case "false_positive":
      return { label: "False positive", tone: "success" };
    case "no_critical_findings":
      return { label: "No critical findings", tone: "success" };
    case "inconclusive":
      return { label: "Inconclusive", tone: "muted" };
    default:
      return { label: outcome, tone: "neutral" };
  }
}

/** Vendor status (core.enums.VendorStatus). */
export function vendorStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "active":
      return { label: "Active", tone: "success" };
    case "inactive":
      return { label: "Inactive", tone: "neutral" };
    case "blocked":
      return { label: "Blocked", tone: "danger" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/** Purchase-order status (core.enums.PurchaseOrderStatus). */
export function purchaseOrderStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "draft":
      return { label: "Draft", tone: "neutral" };
    case "active":
      return { label: "Active", tone: "info" };
    case "closed":
      return { label: "Closed", tone: "muted" };
    case "cancelled":
      return { label: "Cancelled", tone: "danger" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/** Change-request status (core.enums.ChangeRequestStatus, R5 change control). */
export function changeRequestStatusPresentation(status: string): StatusPresentation {
  switch (status) {
    case "pending":
      return { label: "Pending decision", tone: "warning" };
    case "approved":
      return { label: "Approved", tone: "success" };
    case "rejected":
      return { label: "Rejected", tone: "danger" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/** Extraction-field verification (core.enums.ExtractionFieldVerificationStatus). */
export function fieldVerificationPresentation(status: string): StatusPresentation {
  switch (status) {
    case "unverified":
      return { label: "Unverified", tone: "neutral" };
    case "confirmed":
      return { label: "Confirmed", tone: "success" };
    case "corrected":
      return { label: "Corrected by human", tone: "info" };
    default:
      return { label: status, tone: "neutral" };
  }
}

/** Confidence presentation for extracted fields (R3): NULL/below-gate
 *  confidence is stated as uncertain — never laundered into confident
 *  evidence (docs/ARCHITECTURE.md §8.3). Threshold mirrors the backend's
 *  OCR_CONFIDENCE_THRESHOLD default (0.85). */
export const OCR_CONFIDENCE_THRESHOLD = 0.85;

export function confidencePresentation(confidence: number | null): StatusPresentation & {
  /** True when the value may be used as machine evidence (R3 gate). */
  passesGate: boolean;
} {
  if (confidence === null || confidence < OCR_CONFIDENCE_THRESHOLD) {
    return { label: "Uncertain", tone: "warning", passesGate: false };
  }
  return { label: "Confident", tone: "success", passesGate: true };
}
