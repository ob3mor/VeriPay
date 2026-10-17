import { FileText } from "lucide-react";

import { PlaceholderPage } from "@/components/placeholder-page";

export default function InvoicesPage() {
  return (
    <PlaceholderPage
      title="Invoices"
      description="Invoice intake, vendor resolution and consistency assessments — evidence for humans, never verdicts."
      phase="Phase 3–4"
      icon={FileText}
      points={[
        "POST /invoices · GET /invoices — intake with duplicate detection: a duplicate vendor + invoice number is recorded as a fraud signal (needs_review), never rejected as an error (docs/API.md §2).",
        "POST /invoices/{id}/resolve-vendor — vendor resolution is an explicit workflow step.",
        "POST /invoices/{id}/assess · GET /invoices/{id}/assessment — checks against POs, trusted accounts and OCR evidence (Phase 4).",
        "A missing purchase order is a missing_evidence signal, not proof of fraud (invariant R4); uncertain OCR never becomes confident fraud evidence (R3).",
        "The status vocabulary has no approved/genuine state — payment authorization stays a human decision outside VeriPay (R1/R2).",
      ]}
    />
  );
}
