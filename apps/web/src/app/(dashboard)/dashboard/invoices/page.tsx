"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import { FileText, LoaderCircle, Upload } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { SkeletonList } from "@/components/skeleton";
import { useMe } from "@/hooks/use-session";
import { InvoicesTable, type InvoiceRow } from "@/app/(dashboard)/dashboard/invoices/_components/invoices-table";
import {
  InvoiceFilters,
  type InvoiceFiltersValue,
} from "@/app/(dashboard)/dashboard/invoices/_components/invoice-filters";
import { ListPagination } from "@/app/(dashboard)/dashboard/invoices/_components/list-pagination";
import {
  processingStateOf,
  riskCategoryOf,
} from "@/app/(dashboard)/dashboard/invoices/_components/derive";
import { getLatestAssessment, listCases, listInvoices, listVendors } from "@/lib/api";
import type { FraudAssessmentOut } from "@veripay/api-contracts";

/**
 * Invoices list — search, filters, columns and pagination, all fed by the
 * real API via TanStack Query.
 *
 * API reality (verified against apps/api/app/api/v1/routes/procurement.py and
 * packages/api-contracts): GET /invoices takes ONLY limit (≤ 100) / offset
 * and returns a bare array — no search, no filters, no total. The screen
 * therefore loads a window of invoices (100 per block, "Load more" extends
 * it) and runs search/filter/pagination client-side over exactly what is
 * loaded; the summary line and the hint below the filters state that scope
 * instead of pretending a global search. Risk category and processing state
 * come from each invoice's latest assessment (GET /invoices/{id}/assessment,
 * fetched per loaded row and cached by TanStack Query).
 *
 * Honesty: every status renders through src/lib/status.ts — no approved /
 * genuine vocabulary exists anywhere (R1/R2); "Unresolved" vendor and "Not
 * assessed" risk are stated as states, not errors.
 */

const PAGE_SIZE = 20;
const BLOCK_SIZE = 100; // server-side limit ceiling (docs/API.md §3)

const INITIAL_FILTERS: InvoiceFiltersValue = {
  search: "",
  reviewStatus: "all",
  risk: "all",
  processing: "all",
};

export default function InvoicesListPage() {
  const me = useMe();
  // POST /documents (upload) is contributor-only (org_admin/finance_officer/
  // reviewer — apps/api tenancy/permissions.py CAN_CONTRIBUTE); the auditor is
  // read-only here, so the upload button is hidden AND the upload page itself
  // renders an honest restricted state for that role.
  const canUpload =
    me.data !== undefined &&
    ["org_admin", "finance_officer", "reviewer"].includes(me.data.user.role);
  const [blocks, setBlocks] = useState(1);
  const [filters, setFilters] = useState<InvoiceFiltersValue>(INITIAL_FILTERS);
  const [page, setPage] = useState(1);

  // Loaded window: `blocks` consecutive server pages of 100, concatenated.
  const invoicesQuery = useQuery({
    queryKey: ["invoices", "list", blocks],
    queryFn: async () => {
      const serverPages = await Promise.all(
        Array.from({ length: blocks }, (_, index) =>
          listInvoices({ limit: BLOCK_SIZE, offset: index * BLOCK_SIZE })
        )
      );
      return serverPages.flat();
    },
  });

  // Vendor names (id → display_name). Failure degrades to "Unknown vendor"
  // labels — the list itself still works.
  const vendorsQuery = useQuery({
    queryKey: ["vendors", "list"],
    queryFn: () => listVendors({ limit: 100 }),
    staleTime: 60_000,
  });

  // Cases for the row → investigation links (first case per invoice wins).
  const casesQuery = useQuery({
    queryKey: ["cases", "list"],
    queryFn: () => listCases({ limit: 100 }),
    staleTime: 30_000,
  });

  const invoices = invoicesQuery.data ?? [];
  const hasMore = invoicesQuery.data !== undefined && invoices.length === blocks * BLOCK_SIZE;

  const vendorNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const vendor of vendorsQuery.data ?? []) map.set(vendor.id, vendor.display_name);
    return map;
  }, [vendorsQuery.data]);

  const caseByInvoice = useMemo(() => {
    const map = new Map<string, { id: string; caseNumber: string }>();
    for (const item of casesQuery.data ?? []) {
      if (item.invoice_id && !map.has(item.invoice_id)) {
        map.set(item.invoice_id, { id: item.id, caseNumber: item.case_number });
      }
    }
    return map;
  }, [casesQuery.data]);

  // Latest assessment per loaded invoice (small per-row GETs, cached).
  const assessmentQueries = useQueries({
    queries: invoices.map((invoice) => ({
      queryKey: ["invoices", invoice.id, "assessment"],
      queryFn: () => getLatestAssessment(invoice.id),
      staleTime: 60_000,
      retry: false,
    })),
  });
  // Rebuilt every render on purpose: when a per-invoice assessment query
  // resolves, the useQueries state changes and the enriched rows (below) must
  // see it — a memo keyed on the query array would go stale. Filtering a few
  // hundred rows per render is trivially cheap.
  const assessmentsById = new Map<string, FraudAssessmentOut | null>();
  invoices.forEach((invoice, index) => {
    const query = assessmentQueries[index];
    if (query && query.data !== undefined) assessmentsById.set(invoice.id, query.data);
  });

  const rows: InvoiceRow[] = (() => {
    const needle = filters.search.trim().toLowerCase();
    return invoices
      .map((invoice) => ({
        invoice,
        vendorName: invoice.vendor_id ? vendorNames.get(invoice.vendor_id) ?? null : null,
        assessment: assessmentsById.get(invoice.id),
        linkedCase: caseByInvoice.get(invoice.id) ?? null,
      }))
      .filter((row) => {
        if (filters.reviewStatus !== "all" && row.invoice.status !== filters.reviewStatus) {
          return false;
        }
        if (filters.risk !== "all" && riskCategoryOf(row.assessment) !== filters.risk) return false;
        if (
          filters.processing !== "all" &&
          processingStateOf(row.assessment) !== filters.processing
        ) {
          return false;
        }
        if (needle) {
          const haystack =
            [
              row.vendorName ?? "",
              row.invoice.invoice_number,
              row.invoice.total_amount ?? "",
              row.invoice.currency ?? "",
              row.invoice.invoice_date ?? "",
            ]
              .join(" ")
              .toLowerCase();
          if (!haystack.includes(needle)) return false;
        }
        return true;
      });
  })();

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const rangeStart = rows.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(safePage * PAGE_SIZE, rows.length);
  const pageRows = rows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  function updateFilters(next: InvoiceFiltersValue) {
    setFilters(next);
    setPage(1); // a new filter/search always restarts at the first page
  }

  const clearFilters = () => updateFilters(INITIAL_FILTERS);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Invoices"
        description="Invoice intake, assessments and review states — evidence for human decisions, never verdicts."
        actions={
          canUpload ? (
            <Link href="/dashboard/invoices/upload" className={buttonVariants({ size: "sm" })}>
              <Upload />
              Upload document
            </Link>
          ) : null
        }
      />

      <InvoiceFilters value={filters} onChange={updateFilters} />

      {invoicesQuery.isPending ? (
        <SkeletonList rows={6} />
      ) : invoicesQuery.isError ? (
        <ErrorState
          error={invoicesQuery.error}
          title="Could not load invoices"
          onRetry={() => invoicesQuery.refetch()}
        />
      ) : invoices.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No invoices yet"
          description="Upload an invoice document to start the pipeline, or create invoice records through the API. Nothing here implies approval or genuineness — states are factual."
          action={
            canUpload ? (
              <Link href="/dashboard/invoices/upload" className={buttonVariants({ size: "sm" })}>
                <Upload />
                Upload document
              </Link>
            ) : undefined
          }
        />
      ) : (
        <>
          {pageRows.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No invoices match"
              description="No loaded invoice matches the current search or filters."
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear search and filters
                </Button>
              }
            />
          ) : (
            <InvoicesTable rows={pageRows} />
          )}

          <ListPagination
            page={safePage}
            pageCount={pageCount}
            onPageChange={setPage}
            rangeStart={rangeStart}
            rangeEnd={rangeEnd}
            totalRows={rows.length}
          />

          <div className="flex flex-wrap items-center gap-3">
            {hasMore && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setBlocks((current) => current + 1)}
                disabled={invoicesQuery.isFetching}
              >
                {invoicesQuery.isFetching && (
                  <LoaderCircle aria-hidden="true" className="animate-spin" />
                )}
                Load 100 more
              </Button>
            )}
            <p className="text-xs text-muted-foreground">
              Search, filters and pagination apply to the {invoices.length} invoices loaded from
              the API{hasMore ? " — load more to search older ones" : ""}.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
