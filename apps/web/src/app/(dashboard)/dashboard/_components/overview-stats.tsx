"use client";

import type { LucideIcon } from "lucide-react";
import { CircleX, ClipboardList, FileText, ShieldAlert, Siren } from "lucide-react";

import type { DashboardStatsOut } from "@veripay/api-contracts";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/skeleton";
import { cn } from "@/lib/utils";

/**
 * Overview stat cards + work-queue meters for GET /stats/dashboard.
 *
 * Honesty rules baked in (docs/ARCHITECTURE.md §8, normative):
 * - Every number comes verbatim from the API (`DashboardStatsOut`,
 *   packages/api-contracts) — nothing is derived, estimated or trended; the
 *   endpoint exposes current snapshot counts only, so no over-time chart is
 *   drawn. "Missing" numbers are never invented.
 * - Labels are work-queue sizes, never verdicts: there is no "approved",
 *   "genuine" or "safe" anywhere. "High-risk discrepancies" is the owner's
 *   honest outcome vocabulary (src/lib/status.ts).
 * - The two invoice-relative meters are INDEPENDENT counts over the same
 *   invoice set (an invoice can be in both — see the panel footnote), so they
 *   are rendered as two separate proportion bars, never as a stacked
 *   partition.
 */

type StatTone = "neutral" | "info" | "warning" | "danger";

const STAT_ICON_TONES: Record<StatTone, string> = {
  neutral: "bg-secondary/80 text-muted-foreground",
  info: "bg-primary/12 text-primary",
  warning: "bg-warning/15 text-warning",
  danger: "bg-destructive/15 text-destructive",
};

const METER_FILL_TONES: Record<StatTone, string> = {
  neutral: "bg-slate-500",
  info: "bg-primary",
  warning: "bg-warning",
  danger: "bg-destructive",
};

const CHIP_TONES: Record<StatTone, string> = {
  neutral: "border-border bg-secondary/70 text-secondary-foreground",
  info: "border-primary/30 bg-primary/12 text-primary",
  warning: "border-warning/40 bg-warning/12 text-warning",
  danger: "border-destructive/40 bg-destructive/12 text-destructive",
};

function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

// ---------------------------------------------------------------------------
// Stat cards
// ---------------------------------------------------------------------------

export function OverviewStatCards({ stats }: { stats: DashboardStatsOut }) {
  const cards: {
    label: string;
    value: number;
    caption: string;
    icon: LucideIcon;
    tone: StatTone;
  }[] = [
    {
      label: "Total invoices",
      value: stats.total_invoices,
      caption: "Every invoice recorded for your organization.",
      icon: FileText,
      tone: "neutral",
    },
    {
      label: "Awaiting review",
      value: stats.needs_review_invoices,
      caption: "Flagged for review by machine rules — a human decides.",
      icon: ClipboardList,
      tone: "warning",
    },
    {
      label: "Pending investigations",
      value: stats.open_cases,
      caption: "Cases not yet closed; closure requires a human outcome.",
      icon: ShieldAlert,
      tone: "info",
    },
    {
      label: "High-risk discrepancies",
      value: stats.high_risk_invoices,
      caption: "Latest assessment risk level: high or critical.",
      icon: Siren,
      tone: "danger",
    },
    {
      label: "Processing failures",
      value: stats.processing_failures,
      caption: "Documents whose processing job failed — retryable.",
      icon: CircleX,
      tone: "danger",
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", STAT_ICON_TONES[card.tone])}
              >
                <card.icon className="h-4 w-4" />
              </span>
              <span className="text-xs font-medium">{card.label}</span>
            </CardDescription>
            <CardTitle className="mt-2 font-display text-[2rem] leading-none tracking-tight tabular-nums">
              {formatCount(card.value)}
            </CardTitle>
          </CardHeader>
          <CardFooter className="pb-4 pt-2">
            <span className="text-xs leading-relaxed text-muted-foreground">{card.caption}</span>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}

export function OverviewStatCardsSkeleton() {
  return (
    <div role="status" aria-label="Loading statistics" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {Array.from({ length: 5 }, (_, index) => (
        <Card key={index}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-7 w-7 rounded-md" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="mt-3 h-9 w-16" />
          </CardHeader>
          <CardFooter className="pb-4 pt-2">
            <Skeleton className="h-3 w-full max-w-[10rem]" />
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Work-queue meters (the visualization)
// ---------------------------------------------------------------------------

function MeterRow({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: StatTone;
}) {
  // Proportion of total invoices; clamped so a count can never overflow the bar.
  const pct = total > 0 ? Math.min(100, Math.round((value / total) * 1000) / 10) : 0;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
        <span className="font-medium text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {formatCount(value)} of {formatCount(total)} invoices
        </span>
      </div>
      <div
        role="meter"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={value}
        aria-label={`${label}: ${formatCount(value)} of ${formatCount(total)} invoices`}
        className="mt-2 h-2 w-full overflow-hidden rounded-full bg-secondary/80"
      >
        <div className={cn("h-full rounded-full", METER_FILL_TONES[tone])} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function CountRow({
  label,
  value,
  unit,
  tone,
  icon: Icon,
}: {
  label: string;
  value: number;
  unit: string;
  tone: StatTone;
  icon: LucideIcon;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
      <span className="flex items-center gap-2 font-medium text-foreground">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        {label}
      </span>
      <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-medium tabular-nums", CHIP_TONES[tone])}>
        {formatCount(value)} {unit}
      </span>
    </div>
  );
}

export function QueueMeters({ stats }: { stats: DashboardStatsOut }) {
  const total = stats.total_invoices;

  return (
    <section aria-label="Work queues at a glance">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Where the work is waiting</CardTitle>
          <CardDescription>
            Current queue sizes from <span className="font-mono text-xs">GET /stats/dashboard</span>
            {total > 0 ? ` — bars show proportions of your ${formatCount(total)} invoice${total === 1 ? "" : "s"}.` : "."}
          </CardDescription>
        </CardHeader>
        <CardContent className="max-w-3xl space-y-5">
          {total > 0 ? (
            <>
              <MeterRow
                label="Awaiting review"
                value={stats.needs_review_invoices}
                total={total}
                tone="warning"
              />
              <MeterRow
                label="High-risk discrepancies"
                value={stats.high_risk_invoices}
                total={total}
                tone="danger"
              />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              No invoices recorded yet — the review-queue meters appear once invoices exist.
            </p>
          )}

          <div className="space-y-3 border-t pt-4">
            <CountRow
              label="Pending investigations"
              value={stats.open_cases}
              unit="open case(s)"
              tone="info"
              icon={ShieldAlert}
            />
            <CountRow
              label="Processing failures"
              value={stats.processing_failures}
              unit="failed job(s)"
              tone="danger"
              icon={CircleX}
            />
          </div>

          <div className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
            <p>
              The two bars are independent counts over the same invoice set — one invoice can be in
              both queues; they are proportions, not a partition. These are snapshot values: this
              endpoint carries no history, so no over-time trend is drawn.
            </p>
            <p>
              Decision support, not verdicts: nothing here says an invoice is genuine, and
              &ldquo;nothing flagged&rdquo; is not proof of correctness (docs/ARCHITECTURE.md §8).
            </p>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

export function QueueMetersSkeleton() {
  return (
    <section aria-label="Loading work queues" role="status">
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-72 max-w-full" />
        </CardHeader>
        <CardContent className="max-w-3xl space-y-5">
          <div>
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="mt-2 h-2.5 w-full rounded-full" />
          </div>
          <div>
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="mt-2 h-2.5 w-full rounded-full" />
          </div>
          <div className="space-y-3 border-t pt-4">
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-44" />
              <Skeleton className="h-5 w-24 rounded-full" />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-24 rounded-full" />
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
