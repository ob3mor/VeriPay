"use client";

import { Suspense } from "react";

import { SkeletonList } from "@/components/skeleton";

import { InvestigationsWorkspace } from "./workspace";

/**
 * Investigations route (Prompt 05): case list + split-screen investigation
 * workspace. Client page — the workspace reads the `?case=` (and `?doc=`)
 * query params, which must sit inside a Suspense boundary so the static
 * export can prerender the shell (Next.js CSR-bailout rule for
 * useSearchParams; docs: Static Export rules in apps/web/README.md).
 */
export default function InvestigationsPage() {
  return (
    <Suspense fallback={<SkeletonList rows={6} />}>
      <InvestigationsWorkspace />
    </Suspense>
  );
}
