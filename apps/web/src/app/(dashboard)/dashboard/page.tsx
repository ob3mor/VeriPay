"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FileUp, Inbox, RefreshCcw } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { useMe } from "@/hooks/use-session";
import { ApiNetworkError, fetchDashboardStats } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  OverviewStatCards,
  OverviewStatCardsSkeleton,
  QueueMeters,
  QueueMetersSkeleton,
} from "./_components/overview-stats";

/**
 * Overview — the live dashboard (Prompt 05).
 *
 * Data: GET /api/v1/stats/dashboard via TanStack Query (real API only — every
 * number shown comes verbatim from the org-scoped aggregate; when the API is
 * unreachable the page shows the error state, never placeholder numbers).
 *
 * States: loading skeletons while the query is pending; a retryable ErrorState
 * on failure (offline or API error — classified by src/components/error-state
 * .tsx); an honest empty state when every count is zero; otherwise the stat
 * cards + work-queue meters. The 401 case is handled one level up: the shell's
 * GET /auth/me guard redirects to /login.
 */

export default function OverviewPage() {
  const me = useMe();
  const stats = useQuery({
    queryKey: ["stats", "dashboard"],
    queryFn: fetchDashboardStats,
    // Same policy as useMe: one quick retry for network failures, never for
    // API errors (a 4xx will not fix itself by retrying).
    retry: (failureCount, error) => error instanceof ApiNetworkError && failureCount < 1,
  });

  const data = stats.data;
  // Empty state only when the ENTIRE org is empty — processing failures can
  // exist without invoices, so zeroing one count must not hide the others.
  const isWorkspaceEmpty =
    !!data &&
    data.total_invoices === 0 &&
    data.needs_review_invoices === 0 &&
    data.open_cases === 0 &&
    data.high_risk_invoices === 0 &&
    data.processing_failures === 0;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description={
          me.data
            ? `Welcome back, ${me.data.user.full_name}. Here is where your team's review work stands.`
            : "Your workspace at a glance."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void stats.refetch()}
            disabled={stats.isPending || stats.isFetching}
          >
            <RefreshCcw className={cn(stats.isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
      />

      {stats.isPending ? (
        <div className="space-y-6">
          <OverviewStatCardsSkeleton />
          <QueueMetersSkeleton />
        </div>
      ) : stats.isError ? (
        <ErrorState
          error={stats.error}
          title="Could not load dashboard statistics"
          onRetry={() => void stats.refetch()}
          retryLabel="Try again"
        />
      ) : isWorkspaceEmpty ? (
        <EmptyState
          icon={Inbox}
          title="Nothing to review yet"
          description="Your organization has no invoices, investigations or processing jobs on record. Upload your first invoice to start building the evidence trail — every check it runs is decision support for a human, never a verdict."
          action={
            <Link href="/dashboard/invoices" className={buttonVariants({ variant: "outline" })}>
              <FileUp />
              Go to invoices
            </Link>
          }
        />
      ) : (
        data && (
          <div className="space-y-6">
            <OverviewStatCards stats={data} />
            <QueueMeters stats={data} />
          </div>
        )
      )}
    </div>
  );
}
