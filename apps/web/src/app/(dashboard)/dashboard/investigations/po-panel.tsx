"use client";

import { useQuery } from "@tanstack/react-query";
import { FileSearch } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { getPurchaseOrder } from "@/lib/api";
import { purchaseOrderStatusPresentation } from "@/lib/status";
import type { InvoiceOut } from "@veripay/api-contracts";

import { listLineItems } from "./api-extras";

/**
 * PO comparison (right pane): the linked purchase order next to the invoice's
 * own numbers, plus the invoice's line items for the human to eyeball.
 *
 * The client deliberately does NOT recompute the mismatch verdict — the
 * assessment's `amount_mismatch` finding (findings panel) is the recorded
 * machine observation. When the two displayed amounts differ, this panel says
 * exactly that and points at the findings panel.
 */
export function PoPanel({ invoice }: { invoice: InvoiceOut | null }) {
  const poId = invoice?.purchase_order_id ?? null;
  const poQuery = useQuery({
    queryKey: ["po", poId],
    queryFn: () => getPurchaseOrder(poId as string),
    enabled: poId !== null,
  });
  const lineItemsQuery = useQuery({
    queryKey: ["line-items", invoice?.id ?? null],
    queryFn: async () => (await listLineItems((invoice as InvoiceOut).id)).items,
    enabled: invoice !== null,
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Purchase-order comparison</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!poId ? (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            No purchase order is linked to this invoice. A missing PO is recorded
            as a <span className="font-medium">missing_evidence</span> signal with
            severity capped at medium — the record may simply not exist in
            VeriPay; absence alone is never treated as proof of fraud (R4).
          </p>
        ) : poQuery.isError ? (
          <ErrorState
            error={poQuery.error}
            title="Could not load the purchase order"
            onRetry={() => void poQuery.refetch()}
          />
        ) : poQuery.isPending ? (
          <div className="h-16 animate-pulse rounded bg-muted" role="status" aria-label="Loading purchase order" />
        ) : poQuery.data ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">PO {poQuery.data.po_number}</p>
              <StatusBadge
                presentation={purchaseOrderStatusPresentation(poQuery.data.status)}
                hideDot
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Invoice total
                </p>
                <p className="mt-1 text-sm font-medium">
                  {invoice?.total_amount ?? "—"} {invoice?.currency ?? ""}
                </p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  PO amount
                </p>
                <p className="mt-1 text-sm font-medium">
                  {poQuery.data.amount ?? "—"} {poQuery.data.currency ?? invoice?.currency ?? ""}
                </p>
              </div>
            </div>
            <AmountObservation
              invoiceAmount={invoice?.total_amount ?? null}
              poAmount={poQuery.data.amount}
              sameCurrency={
                poQuery.data.currency == null ||
                invoice?.currency == null ||
                poQuery.data.currency === invoice.currency
              }
            />
            {poQuery.data.issued_at ? (
              <p className="text-xs text-muted-foreground">PO issued: {poQuery.data.issued_at}</p>
            ) : null}
          </div>
        ) : null}

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <FileSearch className="h-3.5 w-3.5" />
            Invoice line items
          </p>
          {lineItemsQuery.isError ? (
            <ErrorState
              error={lineItemsQuery.error}
              title="Could not load line items"
              onRetry={() => void lineItemsQuery.refetch()}
            />
          ) : lineItemsQuery.isPending ? (
            <div className="h-12 animate-pulse rounded bg-muted" role="status" aria-label="Loading line items" />
          ) : (lineItemsQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No line items recorded for this invoice.</p>
          ) : (
            <div className="overflow-hidden rounded-md border">
              <table className="w-full text-left text-sm">
                <thead className="border-b bg-panel/70 font-mono text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">Description</th>
                    <th scope="col" className="px-3 py-2 font-medium">Qty</th>
                    <th scope="col" className="px-3 py-2 font-medium">Unit price</th>
                    <th scope="col" className="px-3 py-2 font-medium">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {(lineItemsQuery.data ?? []).map((item) => (
                    <tr key={item.id} className="border-b last:border-b-0">
                      <td className="max-w-[16rem] truncate px-3 py-2" title={item.description ?? undefined}>
                        {item.description ?? "—"}
                      </td>
                      <td className="px-3 py-2">{item.quantity ?? "—"}</td>
                      <td className="px-3 py-2">{item.unit_price ?? "—"}</td>
                      <td className="px-3 py-2 font-medium">{item.line_total ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AmountObservation({
  invoiceAmount,
  poAmount,
  sameCurrency,
}: {
  invoiceAmount: string | null;
  poAmount: string | null;
  sameCurrency: boolean;
}) {
  if (invoiceAmount == null || poAmount == null) {
    return (
      <p className="text-xs text-muted-foreground">
        One of the amounts is not recorded, so no amount comparison is shown.
      </p>
    );
  }
  if (invoiceAmount === poAmount) {
    return (
      <p className="text-xs text-muted-foreground">
        The displayed amounts are equal. Equality of these numbers is an
        observation about the records, not a verdict on the invoice (R2).
      </p>
    );
  }
  return (
    <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
      The displayed amounts differ{sameCurrency ? "" : " (and the currencies are not recorded as the same)"}. The
      recorded machine observation is the <span className="font-medium">amount_mismatch</span>{" "}
      finding — see the risk findings panel for its severity and message.
    </p>
  );
}
