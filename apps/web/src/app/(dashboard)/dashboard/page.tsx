"use client";

import { Building2, FileSearch, FileText, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { isSessionExpired, useMe, useSignOut } from "@/hooks/use-session";
import { ApiError, ApiNetworkError, getApiRoot } from "@/lib/api";
import type { MeResponse } from "@veripay/api-contracts";

/**
 * Overview — Phase 1 scaffold. Stat cards are honest placeholders (the data
 * behind them arrives in Phase 2+); the signed-in user's email is fetched live
 * from GET /auth/me via TanStack Query. When the API is offline the page still
 * renders fully, with a friendly offline state instead of a crash.
 */

const STATS = [
  { label: "Invoices needing review", phase: "Phase 3", icon: FileText },
  { label: "Open investigations", phase: "Phase 5", icon: ShieldAlert },
  { label: "Vendors on file", phase: "Phase 3", icon: Building2 },
  { label: "Documents processed", phase: "Phase 2", icon: FileSearch },
] as const;

const ACCOUNT_FIELDS: readonly (readonly [string, (me: MeResponse) => string])[] = [
  ["Email", (me) => me.user.email],
  ["Full name", (me) => me.user.full_name],
  ["Role", (me) => me.user.role],
  ["Organization", (me) => me.organization.name],
  ["Org slug", (me) => me.organization.slug],
  ["User ID", (me) => me.user.id],
];

export default function OverviewPage() {
  const me = useMe();
  const signOut = useSignOut();
  // Local const so TS narrowing survives into the render callbacks below.
  const data = me.data;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {me.data ? `Welcome back, ${me.data.user.full_name}.` : "Your workspace at a glance."}
        </p>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <p className="font-medium">Phase 1 scaffold — static preview.</p>
        <p className="mt-1 leading-relaxed">
          Stat values below are deliberate placeholders; live data arrives in Phase 2. This page
          renders fully even when the API at{" "}
          <span className="font-mono text-xs">{getApiRoot()}</span> is offline.
        </p>
      </div>

      <section aria-labelledby="signals-heading">
        <h2 id="signals-heading" className="text-sm font-medium text-muted-foreground">
          Signals overview
        </h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {STATS.map((stat) => (
            <Card key={stat.label}>
              <CardHeader className="pb-2">
                <CardDescription className="flex items-center gap-2">
                  <stat.icon className="h-4 w-4" />
                  {stat.label}
                </CardDescription>
                <CardTitle className="text-3xl">—</CardTitle>
              </CardHeader>
              <CardFooter className="pb-4">
                <span className="text-xs text-muted-foreground">Live data in {stat.phase}</span>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="account-heading" className="max-w-2xl">
        <h2 id="account-heading" className="text-sm font-medium text-muted-foreground">
          Account
        </h2>
        <Card className="mt-3">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Signed-in user</CardTitle>
            <CardDescription>
              Loaded from <span className="font-mono text-xs">GET /auth/me</span> via TanStack Query.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {me.isPending ? (
              <div className="space-y-3" aria-label="Loading account details">
                <div className="h-4 w-48 animate-pulse rounded bg-muted" />
                <div className="h-4 w-64 animate-pulse rounded bg-muted" />
                <div className="h-4 w-40 animate-pulse rounded bg-muted" />
              </div>
            ) : data ? (
              <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                {ACCOUNT_FIELDS.map(([term, getValue]) => (
                  <div key={term} className="min-w-0">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {term}
                    </dt>
                    <dd className="mt-1 break-words font-mono text-sm">{getValue(data)}</dd>
                  </div>
                ))}
              </dl>
            ) : me.isError ? (
              <div className="space-y-3 text-sm">
                {me.error instanceof ApiNetworkError ? (
                  <p className="text-muted-foreground">
                    Can&apos;t reach the API at{" "}
                    <span className="font-mono text-xs">{getApiRoot()}</span>. The dashboard still
                    renders — live account data arrives in Phase 2. Check that the backend is
                    running and try reloading.
                  </p>
                ) : isSessionExpired(me.error) ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p>Your session has expired or is invalid.</p>
                    <Button variant="outline" size="sm" onClick={signOut}>
                      Sign in again
                    </Button>
                  </div>
                ) : me.error instanceof ApiError ? (
                  <p className="text-muted-foreground">{me.error.message}</p>
                ) : (
                  <p className="text-muted-foreground">Something went wrong loading your session.</p>
                )}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
