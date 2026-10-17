"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/error-state";
import { SkeletonList } from "@/components/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { getVendor } from "@/lib/api";
import { vendorStatusPresentation } from "@/lib/status";

import { AccountsPanel } from "./accounts-panel";
import { ChangeRequestsPanel } from "./change-requests-panel";
import { ContactsPanel } from "./contacts-panel";
import { formatDate } from "./screen-helpers";

export interface VendorDetailProps {
  vendorId: string;
  onBack: () => void;
}

/**
 * Per-vendor management workspace (Prompt 05): identity, authorized contacts,
 * trusted bank accounts with the human-only verify/reject/revoke flow (R5),
 * and bank-account change requests with the reviewer approve/reject flow.
 *
 * Masking is respected end-to-end: the API returns only masked tax ids and
 * account last-4; verification provenance (method/reference/document) arrives
 * only for reviewer/org_admin (the server decides — API.md §5.8) and never
 * includes a fingerprint or a full number.
 */
export function VendorDetail({ vendorId, onBack }: VendorDetailProps) {
  const vendorQuery = useQuery({
    queryKey: ["vendor", vendorId],
    queryFn: () => getVendor(vendorId),
  });

  const vendor = vendorQuery.data ?? null;

  return (
    <div className="space-y-6">
      <button type="button" onClick={onBack} className="text-sm text-primary hover:underline">
        ← All vendors
      </button>

      {vendorQuery.isPending ? (
        <SkeletonList rows={4} />
      ) : vendorQuery.isError ? (
        <ErrorState
          error={vendorQuery.error}
          title="Could not load this vendor"
          onRetry={() => void vendorQuery.refetch()}
        />
      ) : vendor ? (
        <>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-lg">
                <span className="flex items-center gap-2">
                  <Building2 className="h-5 w-5 text-muted-foreground" />
                  {vendor.display_name}
                </span>
                <StatusBadge presentation={vendorStatusPresentation(vendor.status)} />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Legal name
                  </dt>
                  <dd className="mt-0.5">{vendor.legal_name ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Tax ID (masked)
                  </dt>
                  <dd className="mt-0.5 font-mono text-xs">{vendor.tax_id_masked ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Created
                  </dt>
                  <dd className="mt-0.5">{formatDate(vendor.created_at)}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <AccountsPanel vendorId={vendor.id} />
          <ChangeRequestsPanel vendorId={vendor.id} />
          <ContactsPanel vendorId={vendor.id} />
        </>
      ) : null}
    </div>
  );
}
