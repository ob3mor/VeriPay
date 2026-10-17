/**
 * Row-level derivations shared by the invoices table and its filters.
 *
 * Why the processing state comes from the assessment: the invoice list
 * payload (InvoiceOut) does not serialize the source document link (verified
 * in apps/api/app/api/v1/routes/_domain_schemas.py — InvoiceOut has no
 * source_document_id), so the honest machine-pipeline signal available per
 * invoice is its latest fraud assessment (GET /invoices/{id}/assessment):
 * none → "Not assessed", complete → "Assessed", partial → "Partially
 * assessed", failed → "Processing failed". The human review state is the
 * invoice's own `status` (invoiceStatusPresentation in src/lib/status.ts).
 * Every label is factual; nothing implies approval or genuineness (R1/R2).
 */
import type { FraudAssessmentOut } from "@veripay/api-contracts";

/** Risk category — the owner-mandated honest outcome vocabulary (Prompt 05). */
export type RiskCategory =
  | "not_assessed"
  | "no_material_discrepancies"
  | "manual_review_required"
  | "high_risk_discrepancy"
  | "processing_failed";

export function riskCategoryOf(assessment: FraudAssessmentOut | null | undefined): RiskCategory {
  if (!assessment) return "not_assessed";
  if (assessment.status === "failed") return "processing_failed";
  switch (assessment.risk_level) {
    case "none":
    case "low":
      return "no_material_discrepancies";
    case "medium":
      return "manual_review_required";
    case "high":
    case "critical":
      return "high_risk_discrepancy";
    default:
      // Unknown risk level: keep it visible rather than pretending a category.
      return "manual_review_required";
  }
}

/** Machine pipeline state, derived from the latest assessment. */
export type ProcessingState = "not_assessed" | "assessed" | "partial" | "failed";

export function processingStateOf(
  assessment: FraudAssessmentOut | null | undefined
): ProcessingState {
  if (!assessment) return "not_assessed";
  switch (assessment.status) {
    case "failed":
      return "failed";
    case "partial":
      return "partial";
    default:
      return "assessed";
  }
}
