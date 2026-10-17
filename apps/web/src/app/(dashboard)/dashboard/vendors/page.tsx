"use client";

import { Suspense } from "react";

import { SkeletonList } from "@/components/skeleton";

import { VendorsClient } from "./vendors-client";

/**
 * Vendors route (Prompt 05): vendor registry + per-vendor management
 * (authorized contacts, trusted bank accounts with the human-only R5
 * verification flow, and bank-account change requests). Client page — the
 * client reads the `?vendor=` query param, which must sit inside a Suspense
 * boundary so the static export can prerender the shell (useSearchParams
 * CSR-bailout rule).
 */
export default function VendorsPage() {
  return (
    <Suspense fallback={<SkeletonList rows={6} />}>
      <VendorsClient />
    </Suspense>
  );
}
