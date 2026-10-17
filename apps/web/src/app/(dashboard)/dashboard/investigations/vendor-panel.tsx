"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Building2, ExternalLink } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { getVendor, listBankAccounts } from "@/lib/api";
import { bankAccountStatusPresentation, vendorStatusPresentation } from "@/lib/status";
import type { InvoiceOut } from "@veripay/api-contracts";

export interface VendorPanelProps {
  vendorId: string | null;
  invoice: InvoiceOut | null;
}

/**
 * Matched vendor + trusted bank-account comparison (R5 context).
 *
 * The comparison shown here is informational only: the printed pay-to details
 * (bank name + last four digits, both masked on the wire) are displayed next
 * to the vendor's on-file accounts with their human verification status. The
 * authoritative match decision is the server's fingerprint match — recorded
 * on the invoice as `payment_account_id` and surfaced as the
 * `bank_account_unverified` finding in the assessment, never recomputed here.
 *
 * No fingerprints and no full account numbers exist on this screen: the API
 * never returns them (docs/API.md §5.8) and nothing here pretends otherwise.
 */
export function VendorPanel({ vendorId, invoice }: VendorPanelProps) {
  if (!vendorId) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Vendor</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={Building2}
            title="Vendor not resolved"
            description="The invoice has no vendor attached yet — vendor resolution is an explicit workflow step on the Invoices screen. Unresolved vendors stay unresolved; VeriPay never guesses a match."
          />
        </CardContent>
      </Card>
    );
  }
  return <VendorForId vendorId={vendorId} invoice={invoice} />;
}

function VendorForId({
  vendorId,
  invoice,
}: {
  vendorId: string;
  invoice: InvoiceOut | null;
}) {
  const vendorQuery = useQuery({
    queryKey: ["vendor", vendorId],
    queryFn: () => getVendor(vendorId),
  });
  const accountsQuery = useQuery({
    queryKey: ["accounts", vendorId],
    queryFn: async () => (await listBankAccounts(vendorId)).items,
  });

  const vendor = vendorQuery.data ?? null;
  const accounts = accountsQuery.data ?? [];
  const matchedAccountId = invoice?.payment_account_id ?? null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Vendor &amp; trusted accounts</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {vendorQuery.isError ? (
          <ErrorState
            error={vendorQuery.error}
            title="Could not load the vendor"
            onRetry={() => void vendorQuery.refetch()}
          />
        ) : accountsQuery.isError ? (
          <ErrorState
            error={accountsQuery.error}
            title="Could not load the vendor's bank accounts"
            onRetry={() => void accountsQuery.refetch()}
          />
        ) : vendorQuery.isPending ? (
          <div className="h-16 animate-pulse rounded bg-muted" role="status" aria-label="Loading vendor" />
        ) : vendor ? (
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-semibold">{vendor.display_name}</p>
              {vendor.legal_name ? (
                <p className="text-xs text-muted-foreground">{vendor.legal_name}</p>
              ) : null}
              <p className="mt-0.5 text-xs text-muted-foreground">
                Tax ID on file: {vendor.tax_id_masked ?? "none"} (masked — matching-only access)
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge presentation={vendorStatusPresentation(vendor.status)} hideDot />
              <Link
                href={`/dashboard/vendors?vendor=${encodeURIComponent(vendor.id)}`}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Open vendor workspace
              </Link>
            </div>
          </div>
        ) : null}

        {invoice ? (
          <div className="rounded-md border bg-muted/30 p-3 text-sm">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Pay-to details as printed on the invoice
            </p>
            <p className="mt-1">
              Bank: {invoice.remittance_bank_name_raw ?? "—"} · Account:{" "}
              {invoice.remittance_account_last4
                ? `•••• ${invoice.remittance_account_last4}`
                : "none printed"}
            </p>
          </div>
        ) : null}

        {accountsQuery.isPending && vendorId ? (
          <div className="h-20 animate-pulse rounded bg-muted" role="status" aria-label="Loading accounts" />
        ) : accounts.length === 0 ? (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            No bank accounts are on file for this vendor. A missing record is a{" "}
            <span className="font-medium">missing_evidence</span> signal (capped at medium
            severity) — it may simply not exist in VeriPay — while any payment to an
            unverified payee is flagged separately for human review.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border">
            <table className="w-full text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Holder</th>
                  <th scope="col" className="px-3 py-2 font-medium">Bank</th>
                  <th scope="col" className="px-3 py-2 font-medium">Account</th>
                  <th scope="col" className="px-3 py-2 font-medium">Verification</th>
                  <th scope="col" className="px-3 py-2" aria-label="Flags" />
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const matched = matchedAccountId !== null && account.id === matchedAccountId;
                  const last4Same =
                    invoice?.remittance_account_last4 != null &&
                    account.account_number_last4 === invoice.remittance_account_last4;
                  return (
                    <tr
                      key={account.id}
                      className={matched ? "border-b bg-primary/5 last:border-b-0" : "border-b last:border-b-0"}
                    >
                      <td className="px-3 py-2 font-medium">{account.account_holder_name}</td>
                      <td className="px-3 py-2">
                        {account.bank_name ?? "—"}
                        {account.bank_country ? (
                          <span className="ml-1 text-xs text-muted-foreground">
                            ({account.bank_country})
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {account.account_number_last4 ? `•••• ${account.account_number_last4}` : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge
                          presentation={bankAccountStatusPresentation(account.status)}
                        />
                      </td>
                      <td className="px-3 py-2 text-right text-xs">
                        {matched ? (
                          <span className="font-medium text-primary">Matched to this invoice</span>
                        ) : last4Same ? (
                          <span className="text-muted-foreground">Last 4 match (informational)</span>
                        ) : account.is_current ? (
                          <span className="text-muted-foreground">Current on file</span>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          Matching is decided server-side by fingerprint over the full account
          identifier — this display only compares masked details. Any mismatch
          or unverified pay-to destination appears as a finding above, and only
          a human can approve an account (R5).
        </p>
      </CardContent>
    </Card>
  );
}
