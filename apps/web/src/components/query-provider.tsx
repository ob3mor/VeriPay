"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Root TanStack Query provider. The client is created in useState so each
 * browser session gets exactly one instance (and a fresh one per SSR render,
 * avoiding cross-request cache leakage).
 *
 * Default retry is 1 — with the API offline the UI should surface a friendly
 * offline state quickly instead of hammering a dead port.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
            staleTime: 30_000,
          },
        },
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
