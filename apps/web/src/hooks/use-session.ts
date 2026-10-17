"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, ApiNetworkError, fetchMe, logoutRequest } from "@/lib/api";
import { clearAccessToken } from "@/lib/auth";

/**
 * GET /auth/me via TanStack Query (docs/API.md §4). One request per app —
 * the dashboard shell and the Overview page share the ["auth", "me"] cache.
 *
 * The session cookie authenticates this call (credentials: "include") — a
 * fresh page load needs no stored token. 401s are transparently refreshed by
 * lib/api.ts before they ever reach this query.
 *
 * Retry policy: one quick retry for network errors, never for 401 (an expired
 * session will not fix itself) and never for other API errors.
 */
export function useMe(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
    retry: (failureCount, error) => error instanceof ApiNetworkError && failureCount < 1,
  });
}

/**
 * Clear the session and its cache.
 *
 * POST /auth/logout revokes the durable session row server-side and clears
 * both cookies; the in-memory access token dies here too. Best-effort: the
 * local session is cleared even when the API is unreachable.
 */
export function useSignOut() {
  const router = useRouter();
  const queryClient = useQueryClient();

  return useCallback(() => {
    void logoutRequest().catch(() => undefined);
    clearAccessToken();
    // Drop cached /auth/me etc. so nothing leaks into the next session.
    queryClient.removeQueries();
    router.replace("/login");
  }, [queryClient, router]);
}

/** True when an error means "sign in again" rather than "try later". */
export function isSessionExpired(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}
