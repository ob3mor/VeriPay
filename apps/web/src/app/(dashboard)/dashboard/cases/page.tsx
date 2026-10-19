"use client";

/**
 * Cases — the human review queue (R6, docs/API.md §6 cases surface).
 *
 * Data: GET /cases (org-scoped). Honest wire-shape note: the API currently
 * accepts ONLY limit/offset on this endpoint (apps/api …/routes/investigations.py),
 * so the status / severity ("priority") / assignee filters below run
 * client-side over the fetched window, and the UI says so.
 *
 * Invariants carried here:
 * - R6: a case is a human-review obligation (auto-opened for critical
 *   assessments); it is closed only from the detail screen by an allowed
 *   human role with an outcome + resolution summary.
 * - R2: status/outcome labels come from src/lib/status.ts — no genuineness
 *   language anywhere.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { SeverityBadge } from "@/components/severity-badge";
import { SkeletonList } from "@/components/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-session";
import { listCases } from "@/lib/api";
import { caseOutcomePresentation, caseStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";

const PAGE_LIMIT = 100; // the backend clamps to 100 — the maximum window

const STATUS_FILTERS = [
  { value: "open", label: "Open" },
  { value: "in_review", label: "In review" },
  { value: "waiting_vendor", label: "Waiting on vendor" },
  { value: "closed", label: "Closed" },
] as const;

const SEVERITY_FILTERS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
] as const;

/** Sentinel for the assignee select ("" means "all assignees"). */
const UNASSIGNED = "__unassigned__";

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-input bg-background/60 px-3 text-sm shadow-[inset_0_1px_2px_hsl(214_56%_4%/0.4)] transition-[border-color,box-shadow] focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-transparent";

function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function assigneeLabel(
  assignedTo: string | null,
  meId: string | null
): string {
  if (!assignedTo) return "Unassigned";
  if (meId && assignedTo === meId) return "You";
  return shortId(assignedTo);
}

export default function CasesPage() {
  const me = useMe();
  const meId = me.data?.user.id ?? null;

  const casesQuery = useQuery({
    queryKey: ["cases", "list", { limit: PAGE_LIMIT }],
    queryFn: async () => (await listCases({ limit: PAGE_LIMIT })).items,
  });

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [assigneeFilter, setAssigneeFilter] = useState<string>("");

  const cases = casesQuery.data ?? [];

  // Assignee options derived from what the API actually returned — the
  // backend has no user-directory endpoint to enumerate members from.
  const assigneeIds = useMemo(() => {
    return Array.from(
      new Set(
        cases
          .map((c) => c.assigned_to)
          .filter((id): id is string => typeof id === "string" && id.length > 0)
      )
    ).sort();
  }, [cases]);

  const filtered = useMemo(() => {
    return cases.filter((c) => {
      if (statusFilter && c.status !== statusFilter) return false;
      if (severityFilter && c.severity !== severityFilter) return false;
      if (assigneeFilter === UNASSIGNED && c.assigned_to !== null) return false;
      if (
        assigneeFilter &&
        assigneeFilter !== UNASSIGNED &&
        c.assigned_to !== assigneeFilter
      )
        return false;
      return true;
    });
  }, [cases, statusFilter, severityFilter, assigneeFilter]);

  const hasAnyFilter = Boolean(statusFilter || severityFilter || assigneeFilter);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cases"
        description="The human review queue. Critical findings open a case automatically; cases close only when a human records an outcome and resolution summary (docs/ARCHITECTURE.md §8.6)."
      />

      {/* Filters — client-side over the fetched window (stated honestly). */}
      <div className="grid gap-4 sm:grid-cols-3" role="group" aria-label="Case filters">
        <div className="space-y-1.5">
          <Label htmlFor="filter-status">Status</Label>
          <select
            id="filter-status"
            className={SELECT_CLASS}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            {STATUS_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="filter-severity">Severity (priority)</Label>
          <select
            id="filter-severity"
            className={SELECT_CLASS}
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value)}
          >
            <option value="">All severities</option>
            {SEVERITY_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="filter-assignee">Assignee</Label>
          <select
            id="filter-assignee"
            className={SELECT_CLASS}
            value={assigneeFilter}
            onChange={(event) => setAssigneeFilter(event.target.value)}
          >
            <option value="">All assignees</option>
            {meId ? (
              <option value={meId}>Assigned to me</option>
            ) : null}
            <option value={UNASSIGNED}>Unassigned</option>
            {assigneeIds
              .filter((id) => id !== meId)
              .map((id) => (
                <option key={id} value={id}>
                  {shortId(id)}
                </option>
              ))}
          </select>
        </div>
      </div>

      {casesQuery.isPending ? (
        <SkeletonList rows={6} />
      ) : casesQuery.isError ? (
        <ErrorState
          error={casesQuery.error}
          onRetry={() => void casesQuery.refetch()}
        />
      ) : cases.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="No cases yet"
          description="Cases appear here when a critical finding requires human investigation, or when a reviewer opens one manually (R6)."
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="No cases match these filters"
          description="Adjust or clear the filters above — they apply to the loaded cases only."
        />
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground" aria-live="polite">
            Showing {filtered.length} of {cases.length} case{cases.length === 1 ? "" : "s"}
            {hasAnyFilter
              ? " — filters run on this page over the cases the API returned"
              : ""}
            {cases.length >= PAGE_LIMIT
              ? ` (the request window is capped at ${PAGE_LIMIT}; older cases may exist beyond it)`
              : ""}
            .
          </p>
          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full text-sm">
              <caption className="sr-only">Investigation cases, newest first</caption>
              <thead>
                <tr className="border-b bg-panel/70 text-left font-mono text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  <th scope="col" className="px-4 py-3 font-medium">Case</th>
                  <th scope="col" className="px-4 py-3 font-medium">Severity</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 font-medium">Outcome</th>
                  <th scope="col" className="px-4 py-3 font-medium">Assignee</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-secondary/40"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/dashboard/cases/detail?id=${encodeURIComponent(c.id)}`}
                        className="block"
                      >
                        <span className="font-mono text-xs text-muted-foreground">
                          {c.case_number}
                        </span>
                        <span className="block font-medium text-foreground underline-offset-4 hover:underline">
                          {c.title}
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <SeverityBadge severity={c.severity} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge presentation={caseStatusPresentation(c.status)} />
                    </td>
                    <td className="px-4 py-3">
                      {c.outcome ? (
                        <StatusBadge
                          presentation={caseOutcomePresentation(c.outcome)}
                        />
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {c.status === "closed"
                            ? "Recorded on the case record"
                            : "Not closed"}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "font-mono text-xs",
                          c.assigned_to ? "text-foreground" : "text-muted-foreground"
                        )}
                        title={c.assigned_to ?? undefined}
                      >
                        {assigneeLabel(c.assigned_to, meId)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
