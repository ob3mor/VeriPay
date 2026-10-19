"use client";

/**
 * Audit trail — GET /audit-events (append-only; org_admin/auditor only,
 * docs/API.md §5 role × action matrix).
 *
 * Wire shape (packages/api-contracts): the endpoint returns the API.md §3
 * envelope (Paginated<AuditEventOut>), takes `limit` (default/max here:
 * 50/100), `offset`, and an EXACT `action` filter; `pagination.total` counts
 * the same filtered set, so "load more" knows exactly when everything is
 * loaded. Stated honestly on screen:
 * - the action filter is a server-side exact match;
 * - the free-text search runs client-side over the loaded events only.
 *
 * Access (graceful 403): the nav shows this entry only to org_admin/auditor;
 * a direct URL as another role renders the restricted panel WITHOUT calling
 * the API, and a real 403 from the API renders the same panel.
 */

import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { History, ScrollText, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/page-header";
import { SkeletonList } from "@/components/skeleton";
import { useMe } from "@/hooks/use-session";
import { ApiError, listAuditEvents } from "@/lib/api";
import { roleLabel } from "@/lib/auth";
import type { AuditEventOut } from "@veripay/api-contracts";

const PAGE_SIZE = 50;

/** Roles allowed by the backend (apps/api/app/tenancy/permissions.py). */
const CAN_VIEW_AUDIT_ROLES = new Set(["org_admin", "auditor"]);

/** The dotted action vocabulary actually emitted by the backend modules
 *  (grep of record_audit call sites, 2026-10-17) — suggestion list for the
 *  exact-action filter. Unknown values are still filterable by hand. */
const KNOWN_ACTIONS = [
  "assessment.created",
  "case.closed",
  "case.opened",
  "document.deleted",
  "document.process_requested",
  "document.uploaded",
  "finding.dispositioned",
  "invoice.created",
  "invoice.line_item.created",
  "invoice.vendor_resolved",
  "match.reviewed",
  "purchase_order.created",
  "user.login_failed",
  "user.login_succeeded",
  "user.logout",
  "user.registered",
  "vendor.account.approved",
  "vendor.account.registered",
  "vendor.account.rejected",
  "vendor.account.revoked",
  "vendor.change.approved",
  "vendor.change.rejected",
  "vendor.change.requested",
  "vendor.contact.created",
  "vendor.created",
] as const;

function shortId(id: string | null): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** One row's searchable haystack (client-side text search over loaded events). */
function eventHaystack(event: AuditEventOut): string {
  const detail =
    event.detail && typeof event.detail === "object"
      ? JSON.stringify(event.detail)
      : "";
  return [
    event.action,
    event.entity_type ?? "",
    event.entity_id ?? "",
    event.actor_user_id ?? "",
    event.actor_type,
    detail,
  ]
    .join(" ")
    .toLowerCase();
}

export default function AuditPage() {
  const me = useMe();
  const role = me.data?.user.role;
  const canViewAudit = role !== undefined && CAN_VIEW_AUDIT_ROLES.has(role);

  // The exact-action filter is committed (Apply) — each commit is a new query.
  const [actionInput, setActionInput] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  // Free-text search filters the loaded events client-side, live.
  const [textSearch, setTextSearch] = useState("");

  const eventsQuery = useInfiniteQuery({
    queryKey: ["audit", "events", actionFilter],
    queryFn: ({ pageParam }) =>
      listAuditEvents({
        limit: PAGE_SIZE,
        offset: pageParam,
        action: actionFilter || undefined,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      // Exact: the §3 envelope's total counts the same filtered set.
      const { offset, total } = lastPage.pagination;
      const loaded = offset + lastPage.items.length;
      return loaded < total ? loaded : undefined;
    },
    enabled: canViewAudit,
  });

  const events = useMemo(
    () => (eventsQuery.data ? eventsQuery.data.pages.flatMap((page) => page.items) : []),
    [eventsQuery.data]
  );

  const visibleEvents = useMemo(() => {
    const needle = textSearch.trim().toLowerCase();
    if (!needle) return events;
    return events.filter((event) => eventHaystack(event).includes(needle));
  }, [events, textSearch]);

  // ---------------------------------------------------------------- guards
  if (me.isPending) {
    return (
      <div className="space-y-6">
        <PageHeader title="Audit trail" />
        <SkeletonList rows={6} />
      </div>
    );
  }

  if (!canViewAudit) {
    return (
      <div className="space-y-6">
        <PageHeader title="Audit trail" />
        <AccessRestricted
          reason={
            role
              ? `You are signed in as ${roleLabel(role)}. Audit events are visible to organization admins and auditors only (docs/API.md §5 role × action matrix), so this page made no API call.`
              : "Audit events are visible to organization admins and auditors only (docs/API.md §5 role × action matrix)."
          }
        />
      </div>
    );
  }

  const forbidden =
    eventsQuery.isError && eventsQuery.error instanceof ApiError && eventsQuery.error.status === 403;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit trail"
        description="Every significant action across the pipeline, newest first. The log is append-only — there is no edit or delete path anywhere."
      />

      {forbidden ? (
        <AccessRestricted reason="The API rejected audit access for this session. Audit events are visible to organization admins and auditors only (docs/API.md §5)." />
      ) : (
        <>
          {/* Filters: exact action (server-side) + free text (client-side) */}
          <div className="grid gap-4 sm:grid-cols-2" role="group" aria-label="Audit filters">
            <form
              className="space-y-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                setActionFilter(actionInput.trim());
              }}
            >
              <Label htmlFor="audit-action">Action (exact match — queries the API)</Label>
              <div className="flex gap-2">
                <Input
                  id="audit-action"
                  className="font-mono text-xs"
                  list="known-audit-actions"
                  placeholder="e.g. document.uploaded"
                  value={actionInput}
                  onChange={(event) => setActionInput(event.target.value)}
                />
                <datalist id="known-audit-actions">
                  {KNOWN_ACTIONS.map((action) => (
                    <option key={action} value={action} />
                  ))}
                </datalist>
                <Button type="submit" size="sm" variant="secondary">
                  Apply
                </Button>
              </div>
              {actionFilter ? (
                <p className="text-xs text-muted-foreground">
                  Filtering the API by action{" "}
                  <span className="font-mono">{actionFilter}</span>{" "}
                  <button
                    type="button"
                    className="underline underline-offset-2 hover:text-foreground"
                    onClick={() => {
                      setActionInput("");
                      setActionFilter("");
                    }}
                  >
                    clear
                  </button>
                </p>
              ) : null}
            </form>
            <div className="space-y-1.5">
              <Label htmlFor="audit-search">Search loaded events</Label>
              <Input
                id="audit-search"
                type="search"
                placeholder="Action, entity, actor, detail…"
                value={textSearch}
                onChange={(event) => setTextSearch(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Free-text search covers the {events.length} loaded event{events.length === 1 ? "" : "s"} on this page.
              </p>
            </div>
          </div>

          {eventsQuery.isPending ? (
            <SkeletonList rows={6} />
          ) : eventsQuery.isError ? (
            <ErrorState error={eventsQuery.error} onRetry={() => void eventsQuery.refetch()} />
          ) : visibleEvents.length === 0 ? (
            <EmptyState
              icon={History}
              title={
                events.length === 0
                  ? actionFilter
                    ? "No events with this action"
                    : "No audit events yet"
                  : "No loaded events match the search"
              }
              description={
                events.length === 0
                  ? "Events appear as actions happen — uploads, assessments, case decisions, account verifications."
                  : "The free-text search runs over the loaded events only; load more or clear the search."
              }
            />
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground" aria-live="polite">
                Showing {visibleEvents.length} of {events.length} loaded event{events.length === 1 ? "" : "s"}
                {eventsQuery.hasNextPage ? " — older events load further down" : " (all loaded)"}
                {textSearch ? " (filtered by search)" : ""}.
              </p>
              <div className="overflow-x-auto rounded-lg border bg-card">
                <table className="w-full text-sm">
                  <caption className="sr-only">Audit events, newest first</caption>
                  <thead>
                    <tr className="border-b bg-panel/70 text-left font-mono text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      <th scope="col" className="px-4 py-3 font-medium">When</th>
                      <th scope="col" className="px-4 py-3 font-medium">Actor</th>
                      <th scope="col" className="px-4 py-3 font-medium">Action</th>
                      <th scope="col" className="px-4 py-3 font-medium">Entity</th>
                      <th scope="col" className="px-4 py-3 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleEvents.map((event) => (
                      <AuditRow key={event.id} event={event} />
                    ))}
                  </tbody>
                </table>
              </div>
              {eventsQuery.hasNextPage ? (
                <div className="flex justify-center pt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={eventsQuery.isFetchingNextPage}
                    onClick={() => void eventsQuery.fetchNextPage()}
                  >
                    {eventsQuery.isFetchingNextPage ? "Loading…" : "Load more"}
                  </Button>
                </div>
              ) : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function AuditRow({ event }: { event: AuditEventOut }) {
  const detailEntries = event.detail
    ? Object.entries(event.detail).slice(0, 3)
    : [];
  const fullDetail = event.detail
    ? (() => {
        try {
          return JSON.stringify(event.detail, null, 2);
        } catch {
          return null;
        }
      })()
    : null;

  return (
    <tr className="border-b border-border/60 align-top transition-colors last:border-0 hover:bg-secondary/40">
      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
        {formatDateTime(event.occurred_at)}
      </td>
      <td className="px-4 py-3">
        <span className="rounded-sm border border-border bg-secondary/80 px-1.5 py-0.5 text-xs font-medium text-secondary-foreground">
          {event.actor_type === "system" ? "System" : "User"}
        </span>
        <span className="mt-1 block font-mono text-xs text-muted-foreground" title={event.actor_user_id ?? undefined}>
          {shortId(event.actor_user_id)}
        </span>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-foreground/90">{event.action}</td>
      <td className="px-4 py-3">
        <span className="text-xs text-muted-foreground">{event.entity_type ?? "—"}</span>
        <span className="mt-0.5 block font-mono text-xs" title={event.entity_id ?? undefined}>
          {shortId(event.entity_id)}
        </span>
      </td>
      <td className="max-w-xs px-4 py-3">
        {detailEntries.length > 0 ? (
          <div className="space-y-0.5" title={fullDetail ?? undefined}>
            {detailEntries.map(([key, value]) => (
              <p key={key} className="truncate font-mono text-xs text-muted-foreground">
                {key}: {String(value)}
              </p>
            ))}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </td>
    </tr>
  );
}

/** The honest restricted panel — shown for a disallowed role (no API call)
 *  or for a real 403 from the API. Not an error, not a crash. */
function AccessRestricted({ reason }: { reason: string }) {
  return (
    <div
      role="note"
      className="flex flex-col items-center justify-center rounded-lg border border-border/70 bg-card/50 px-6 py-16 text-center"
    >
      <span
        aria-hidden="true"
        className="relative mb-5 flex h-16 w-14 items-center justify-center"
      >
        <span className="absolute inset-0 rounded-sm border border-dashed border-border" />
        <span className="absolute inset-x-0 bottom-0 h-[3px] rounded-b-sm bg-primary/70" />
        <span className="flex h-11 w-9 items-center justify-center rounded-[3px] border border-border bg-secondary/60 shadow-raise">
          <ShieldAlert className="h-5 w-5 text-muted-foreground" />
        </span>
      </span>
      <p className="font-display text-lg font-semibold text-foreground">Audit access is restricted</p>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{reason}</p>
      <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <ScrollText className="h-3.5 w-3.5" aria-hidden="true" />
        The audit log itself is append-only and tamper-evident by design.
      </p>
    </div>
  );
}
