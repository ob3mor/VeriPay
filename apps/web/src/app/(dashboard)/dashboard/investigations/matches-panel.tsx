"use client";

import { useQueries } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/error-state";
import { SeverityBadge } from "@/components/severity-badge";
import { StatusBadge } from "@/components/status-badge";
import { getInvoice } from "@/lib/api";
import { invoiceStatusPresentation } from "@/lib/status";
import type { FraudAssessmentOut } from "@veripay/api-contracts";

/**
 * Evidence matches (right pane).
 *
 * In rules-v0.1 the duplicate_candidate finding's `evidence_refs` carry the
 * OTHER INVOICE's id (apps/api fraud service), and the API has no
 * list-matches endpoint that would expose evidence-match row ids — so the
 * honest presentation of "evidence matches" here is: for every
 * duplicate_candidate finding, fetch and show the referenced invoice. The
 * human disposition path is the finding disposition in the risk-findings
 * panel; the POST /matches/{id}/review endpoint exists but is not reachable
 * because no response ever carries a match id (stated here rather than faked).
 */
export function MatchesPanel({ assessment }: { assessment: FraudAssessmentOut | null }) {
  const duplicateFindings = (assessment?.findings ?? []).filter(
    (finding) => finding.signal_type === "duplicate_candidate"
  );

  const referencedIds = [
    ...new Set(duplicateFindings.flatMap((finding) => finding.evidence_refs ?? [])),
  ].filter((id) => typeof id === "string" && id.length > 0);

  const invoiceQueries = useQueries({
    queries: referencedIds.map((id) => ({
      queryKey: ["invoice", id],
      queryFn: () => getInvoice(id),
      staleTime: 30_000,
    })),
  });
  const anyPending = invoiceQueries.some((query) => query.isPending);
  const anyError = invoiceQueries.find((query) => query.isError);

  if (duplicateFindings.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Evidence matches</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No duplicate or overlapping-evidence candidates were recorded for
            this invoice. Duplicates are a recorded signal for human review —
            a duplicate invoice number is never rejected at intake (it is a
            finding, not an error).
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Evidence matches</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {duplicateFindings.map((finding) => (
          <div key={finding.id} className="rounded-md border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={finding.severity} />
              <span className="text-sm font-medium">Duplicate candidate</span>
            </div>
            <p className="mt-1 text-sm text-foreground/90">{finding.message}</p>
          </div>
        ))}

        {referencedIds.length > 0 ? (
          anyPending ? (
            <div className="h-16 animate-pulse rounded bg-muted" role="status" aria-label="Loading matched invoices" />
          ) : anyError ? (
            <ErrorState
              error={anyError.error}
              title="Could not load a referenced invoice"
              onRetry={() => void invoiceQueries.forEach((query) => void query.refetch())}
            />
          ) : (
            <ul className="space-y-2">
              {invoiceQueries.map((query, index) => {
                const invoice = query.data;
                const id = referencedIds[index];
                return (
                  <li key={id} className="rounded-md border bg-muted/30 p-3 text-sm">
                    {invoice ? (
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">Invoice {invoice.invoice_number}</span>
                        <span className="flex items-center gap-2">
                          <span>
                            {invoice.total_amount ?? "—"} {invoice.currency ?? ""}
                          </span>
                          <StatusBadge
                            presentation={invoiceStatusPresentation(invoice.status)}
                            hideDot
                          />
                        </span>
                      </div>
                    ) : (
                      <span className="font-mono text-xs">Referenced invoice {id}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        ) : null}

        <p className="text-xs text-muted-foreground">
          Disposition a duplicate through the finding actions in the risk
          findings panel — that decision is audited. (The underlying
          evidence-match rows are server-side; the current API does not expose
          their ids for direct review.)
        </p>
      </CardContent>
    </Card>
  );
}
