import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { StatusBadge } from "@/components/status-badge";
import {
  HONEST_OUTCOME_LABELS,
  assessmentRiskPresentation,
  invoiceStatusPresentation,
} from "@/lib/status";
import { formatAmount, formatDate } from "@/app/(dashboard)/dashboard/invoices/_components/format";
import {
  processingStateOf,
  type ProcessingState,
} from "@/app/(dashboard)/dashboard/invoices/_components/derive";
import type { FraudAssessmentOut, InvoiceOut } from "@veripay/api-contracts";

/** One enriched list row: the invoice plus everything the screen joins in. */
export interface InvoiceRow {
  invoice: InvoiceOut;
  /** Resolved vendor display name; null when the vendor is unresolved. */
  vendorName: string | null;
  /** Latest assessment; undefined while its query is still loading. */
  assessment: FraudAssessmentOut | null | undefined;
  /** Open/closed case linked to this invoice, when one exists. */
  linkedCase: { id: string; caseNumber: string } | null;
}

export interface InvoicesTableProps {
  rows: InvoiceRow[];
}

const RISK_NOT_ASSESSED = { label: "Not assessed", tone: "muted" } as const;

/**
 * Risk-category cell: undefined assessment = still loading ("…"); null =
 * loaded, no assessment ("Not assessed"); failed = "Processing failed";
 * otherwise the owner-mandated honest outcome label (src/lib/status.ts).
 */
function RiskCell({ assessment }: { assessment: FraudAssessmentOut | null | undefined }) {
  if (assessment === undefined) {
    return <span className="text-xs text-muted-foreground">…</span>;
  }
  if (assessment === null) {
    return <StatusBadge presentation={RISK_NOT_ASSESSED} hideDot />;
  }
  if (assessment.status === "failed") {
    return <StatusBadge presentation={{ label: HONEST_OUTCOME_LABELS.processingFailed, tone: "danger" }} hideDot />;
  }
  return <StatusBadge presentation={assessmentRiskPresentation(assessment.risk_level)} hideDot />;
}

const PROCESSING_BADGES: Record<ProcessingState, { label: string; tone: "muted" | "info" | "warning" | "danger" }> = {
  not_assessed: { label: "Not assessed", tone: "muted" },
  assessed: { label: "Assessed", tone: "info" },
  partial: { label: "Partially assessed", tone: "warning" },
  failed: { label: HONEST_OUTCOME_LABELS.processingFailed, tone: "danger" },
};

function InvestigationLink({ row }: { row: InvoiceRow }) {
  if (row.linkedCase) {
    return (
      <Link
        href={`/dashboard/investigations?case=${row.linkedCase.id}`}
        className="inline-flex items-center gap-1 whitespace-nowrap text-sm font-medium text-primary hover:underline"
      >
        Case {row.linkedCase.caseNumber}
        <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
      </Link>
    );
  }
  return (
    <Link
      href={`/dashboard/investigations?invoice=${row.invoice.id}`}
      className="inline-flex items-center gap-1 whitespace-nowrap text-sm text-muted-foreground hover:text-foreground"
    >
      Investigate
      <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
    </Link>
  );
}

/**
 * The invoices table. Columns per the task: vendor, number, amount, date,
 * risk category, processing state, review status — plus the row-level
 * investigation link. The vendor column says "Unresolved" as a neutral state
 * (a missing vendor is a workflow step, not an error — docs/API.md §6).
 */
export function InvoicesTable({ rows }: InvoicesTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="px-4 py-3">Vendor</th>
            <th scope="col" className="px-4 py-3">Number</th>
            <th scope="col" className="px-4 py-3 text-right">Amount</th>
            <th scope="col" className="px-4 py-3">Date</th>
            <th scope="col" className="px-4 py-3">Risk category</th>
            <th scope="col" className="px-4 py-3">Processing</th>
            <th scope="col" className="px-4 py-3">Review status</th>
            <th scope="col" className="px-4 py-3">Investigation</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const { invoice } = row;
            const assessment = row.assessment;
            return (
              <tr key={invoice.id} className="border-b last:border-b-0 hover:bg-muted/30">
                <td className="max-w-[220px] truncate px-4 py-3">
                  {invoice.vendor_id === null ? (
                    <span className="text-muted-foreground">Unresolved</span>
                  ) : (
                    (row.vendorName ?? <span className="text-muted-foreground">Unknown vendor</span>)
                  )}
                </td>
                <td className="px-4 py-3 font-medium text-foreground">{invoice.invoice_number}</td>
                <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                  {formatAmount(invoice.total_amount, invoice.currency)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                  {formatDate(invoice.invoice_date)}
                </td>
                <td className="px-4 py-3">
                  <RiskCell assessment={assessment} />
                </td>
                <td className="px-4 py-3">
                  {assessment === undefined ? (
                    <span className="text-xs text-muted-foreground">…</span>
                  ) : (
                    <StatusBadge presentation={PROCESSING_BADGES[processingStateOf(assessment)]} hideDot />
                  )}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge presentation={invoiceStatusPresentation(invoice.status)} />
                </td>
                <td className="px-4 py-3">
                  <InvestigationLink row={row} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
