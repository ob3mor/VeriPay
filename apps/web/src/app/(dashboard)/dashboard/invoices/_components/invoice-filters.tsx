"use client";

import { Filter, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { InvoiceStatus } from "@veripay/api-contracts";

export type ReviewStatusFilter = "all" | InvoiceStatus;
export type RiskFilter =
  | "all"
  | "not_assessed"
  | "no_material_discrepancies"
  | "manual_review_required"
  | "high_risk_discrepancy"
  | "processing_failed";
export type ProcessingFilter = "all" | "not_assessed" | "assessed" | "partial" | "failed";

export interface InvoiceFiltersValue {
  search: string;
  reviewStatus: ReviewStatusFilter;
  risk: RiskFilter;
  processing: ProcessingFilter;
}

export interface InvoiceFiltersProps {
  value: InvoiceFiltersValue;
  onChange: (next: InvoiceFiltersValue) => void;
}

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

/**
 * Search + filters for the invoices list. All of it runs client-side over the
 * loaded invoices because GET /invoices accepts only limit/offset (no search
 * or filter params — apps/api/app/api/v1/routes/procurement.py, list_invoices);
 * the page states that scope honestly next to the result count.
 */
export function InvoiceFilters({ value, onChange }: InvoiceFiltersProps) {
  const set = (patch: Partial<InvoiceFiltersValue>) => onChange({ ...value, ...patch });

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      <div className="relative">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          type="search"
          value={value.search}
          onChange={(event) => set({ search: event.target.value })}
          placeholder="Search vendor, number, amount, date…"
          aria-label="Search loaded invoices"
          className="pl-9"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="filter-review-status" className="text-xs text-muted-foreground">
            Review status
          </Label>
          <select
            id="filter-review-status"
            value={value.reviewStatus}
            onChange={(event) => set({ reviewStatus: event.target.value as ReviewStatusFilter })}
            className={SELECT_CLASS}
          >
            <option value="all">All statuses</option>
            <option value="received">Received</option>
            <option value="processing">Processing</option>
            <option value="needs_review">Review required</option>
            <option value="closed">Closed by reviewer</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="filter-risk" className="text-xs text-muted-foreground">
            Risk category
          </Label>
          <select
            id="filter-risk"
            value={value.risk}
            onChange={(event) => set({ risk: event.target.value as RiskFilter })}
            className={SELECT_CLASS}
          >
            <option value="all">All risk categories</option>
            <option value="no_material_discrepancies">No material discrepancies</option>
            <option value="manual_review_required">Manual review required</option>
            <option value="high_risk_discrepancy">High-risk discrepancy</option>
            <option value="processing_failed">Processing failed</option>
            <option value="not_assessed">Not assessed</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="filter-processing" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Filter aria-hidden="true" className="h-3 w-3" />
            Processing
          </Label>
          <select
            id="filter-processing"
            value={value.processing}
            onChange={(event) => set({ processing: event.target.value as ProcessingFilter })}
            className={SELECT_CLASS}
          >
            <option value="all">All processing states</option>
            <option value="not_assessed">Not assessed</option>
            <option value="assessed">Assessed</option>
            <option value="partial">Partially assessed</option>
            <option value="failed">Processing failed</option>
          </select>
        </div>
      </div>
    </div>
  );
}
