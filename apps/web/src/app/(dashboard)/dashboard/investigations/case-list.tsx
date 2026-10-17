"use client";

import { Scale } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { SeverityBadge } from "@/components/severity-badge";
import { SkeletonList } from "@/components/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { caseOutcomePresentation, caseStatusPresentation } from "@/lib/status";
import type { CaseOut } from "@veripay/api-contracts";

export interface CaseListProps {
  /** undefined while loading; the list endpoints return bare arrays. */
  cases?: CaseOut[];
  pending: boolean;
  error: unknown;
  onRetry: () => void;
  onOpen: (caseId: string) => void;
}

/**
 * The investigations list. A row is a plain button (keyboard reachable,
 * aria-pressed marks the workspace's only interactive element per row).
 * Status/outcome labels come from the honest vocabulary in lib/status.ts —
 * a closed case shows its human outcome, never an approval claim.
 */
export function CaseList({ cases, pending, error, onRetry, onOpen }: CaseListProps) {
  if (pending) {
    return <SkeletonList rows={6} />;
  }
  if (error) {
    return <ErrorState error={error} onRetry={onRetry} />;
  }
  if (!cases || cases.length === 0) {
    return (
      <EmptyState
        icon={Scale}
        title="No investigations yet"
        description="Cases appear here when a critical assessment auto-opens one (R6), or when a reviewer opens one manually from an invoice's Investigate view. Running an assessment on an invoice from the Invoices screen creates the evidence a case would review."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-left text-sm">
        <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">Case</th>
            <th scope="col" className="px-4 py-3 font-medium">Title</th>
            <th scope="col" className="px-4 py-3 font-medium">Severity</th>
            <th scope="col" className="px-4 py-3 font-medium">Status</th>
            <th scope="col" className="px-4 py-3 font-medium">Outcome</th>
            <th scope="col" className="px-4 py-3" aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {cases.map((row) => {
            const status = caseStatusPresentation(row.status);
            const outcome = row.outcome ? caseOutcomePresentation(String(row.outcome)) : null;
            return (
              <tr key={row.id} className="border-b last:border-b-0 hover:bg-muted/30">
                <td className="px-4 py-3 font-mono text-xs">{row.case_number}</td>
                <td className="max-w-[22rem] truncate px-4 py-3 font-medium" title={row.title}>
                  {row.title}
                </td>
                <td className="px-4 py-3">
                  <SeverityBadge severity={row.severity} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge presentation={status} />
                </td>
                <td className="px-4 py-3">
                  {outcome ? <StatusBadge presentation={outcome} hideDot /> : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => onOpen(row.id)}
                    className="rounded-md px-2 py-1 text-sm font-medium text-primary hover:bg-muted hover:underline"
                  >
                    Open workspace
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
