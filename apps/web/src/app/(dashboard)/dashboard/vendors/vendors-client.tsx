"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, Search } from "lucide-react";

import { FormDialog } from "@/components/form-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { SkeletonList } from "@/components/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-session";
import { createVendor, listVendors } from "@/lib/api";
import { vendorStatusPresentation } from "@/lib/status";
import type { VendorOut } from "@veripay/api-contracts";

import { mutationMessage } from "./screen-helpers";
import { VendorDetail } from "./vendor-detail";

/**
 * Vendor management (Prompt 05). Route state in the URL:
 *   /dashboard/vendors                 → registry list + create
 *   /dashboard/vendors?vendor=<id>     → per-vendor workspace
 *
 * Role gating mirrors apps/api tenancy/permissions.py: creating vendors,
 * contacts, accounts and change requests needs org_admin/finance_officer/
 * reviewer; verifying/rejecting/revoking accounts and deciding change
 * requests need org_admin/reviewer. The server enforces the same matrix —
 * these flags only keep non-permitted buttons out of the UI.
 */
export function VendorsClient() {
  const searchParams = useSearchParams();
  const vendorId = searchParams.get("vendor") ?? "";
  const router = useRouter();

  if (!vendorId) {
    return <VendorsList onOpen={(id) => router.push(`/dashboard/vendors?vendor=${encodeURIComponent(id)}`)} />;
  }
  return (
    <VendorDetail
      vendorId={vendorId}
      onBack={() => router.push("/dashboard/vendors")}
    />
  );
}

// ---------------------------------------------------------------------------
// Registry list + create
// ---------------------------------------------------------------------------

function VendorsList({ onOpen }: { onOpen: (vendorId: string) => void }) {
  const me = useMe();
  const role = me.data?.user.role;
  const canContribute = role === "org_admin" || role === "finance_officer" || role === "reviewer";

  const vendorsQuery = useQuery({
    queryKey: ["vendors"],
    queryFn: async () => (await listVendors({ limit: 100 })).items,
  });

  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    const vendors = vendorsQuery.data ?? [];
    if (!term) return vendors;
    return vendors.filter(
      (vendor) =>
        vendor.display_name.toLowerCase().includes(term) ||
        (vendor.legal_name ?? "").toLowerCase().includes(term)
    );
  }, [vendorsQuery.data, search]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Vendors"
        description="The vendor registry and trusted bank accounts. New accounts always start pending — only a human, with an independent verification record, can approve one (invariant R5). Tax IDs and account numbers are shown masked; full values are never stored or returned by the API."
        actions={
          canContribute ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus />
              New vendor
            </Button>
          ) : null
        }
      />

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search vendors…"
          aria-label="Search vendors"
          className="pl-9"
        />
      </div>

      {vendorsQuery.isPending ? (
        <SkeletonList rows={6} />
      ) : vendorsQuery.isError ? (
        <ErrorState
          error={vendorsQuery.error}
          onRetry={() => void vendorsQuery.refetch()}
        />
      ) : (vendorsQuery.data ?? []).length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No vendors yet"
          description="Create a vendor to register its authorized contacts and trusted bank accounts. Vendors also appear automatically when an invoice's vendor is resolved."
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No vendors match this search"
          description="Try a different name."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-panel/70 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Name</th>
                <th scope="col" className="px-4 py-3 font-medium">Legal name</th>
                <th scope="col" className="px-4 py-3 font-medium">Tax ID</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3" aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((vendor) => (
                <VendorRow key={vendor.id} vendor={vendor} onOpen={onOpen} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateVendorDialog open={createOpen} onClose={() => setCreateOpen(false)} onOpenVendor={onOpen} />
    </div>
  );
}

function VendorRow({ vendor, onOpen }: { vendor: VendorOut; onOpen: (id: string) => void }) {
  return (
    <tr className="border-b transition-colors last:border-b-0 hover:bg-secondary/40">
      <td className="px-4 py-3 font-medium">{vendor.display_name}</td>
      <td className="px-4 py-3 text-muted-foreground">{vendor.legal_name ?? "—"}</td>
      <td className="px-4 py-3 font-mono text-xs">{vendor.tax_id_masked ?? "—"}</td>
      <td className="px-4 py-3">
        <StatusBadge presentation={vendorStatusPresentation(vendor.status)} />
      </td>
      <td className="px-4 py-3 text-right">
        <button
          type="button"
          onClick={() => onOpen(vendor.id)}
          className="rounded-md px-2 py-1 text-sm font-medium text-primary transition-colors hover:bg-secondary hover:text-accent hover:underline"
        >
          Manage
        </button>
      </td>
    </tr>
  );
}

function CreateVendorDialog({
  open,
  onClose,
  onOpenVendor,
}: {
  open: boolean;
  onClose: () => void;
  onOpenVendor: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [taxId, setTaxId] = useState("");
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createVendor({
        display_name: displayName.trim(),
        legal_name: legalName.trim() ? legalName.trim() : null,
        tax_id: taxId.trim() ? taxId.trim() : null,
        notes: notes.trim() ? notes.trim() : null,
      }),
    onSuccess: (vendor) => {
      void queryClient.invalidateQueries({ queryKey: ["vendors"] });
      onClose();
      onOpenVendor(vendor.id);
    },
  });

  const submit = () => {
    setLocalError(null);
    if (displayName.trim().length === 0) {
      setLocalError("A display name is required.");
      return;
    }
    mutation.mutate();
  };

  return (
    <FormDialog
      open={open}
      title="New vendor"
      description="Creates the vendor in your organization. The tax id, if provided, is used for matching only and is returned masked — the full value never round-trips."
      confirmLabel="Create vendor"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={() => {
        mutation.reset();
        setLocalError(null);
        onClose();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="vendor-display-name">Display name *</Label>
        <Input
          id="vendor-display-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="e.g. Nord Supplies GmbH"
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="vendor-legal-name">Legal name</Label>
        <Input
          id="vendor-legal-name"
          value={legalName}
          onChange={(event) => setLegalName(event.target.value)}
          placeholder="Registered legal entity (optional)"
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="vendor-tax-id">Tax ID</Label>
        <Input
          id="vendor-tax-id"
          value={taxId}
          onChange={(event) => setTaxId(event.target.value)}
          placeholder="Used for matching; shown masked everywhere"
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="vendor-notes">Notes</Label>
        <textarea
          id="vendor-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          placeholder="Free-text context for analysts (optional)"
          className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-card"
        />
      </div>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The vendor could not be created.")}
        </p>
      ) : null}
    </FormDialog>
  );
}
