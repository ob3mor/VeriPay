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
 * Retry policy: one quick retry for network errors, never for 401 (an expired
 * token will not fix itself) and never for other API errors.
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
 * Clear the session (documented key: veripay:access_token) and its cache.
 *
 * The token is ALSO revoked server-side (POST /auth/logout) so a signed-out
 * bearer token is rejected by the API — clearing localStorage alone would
 * leave a leaked/copied token valid until its JWT expiry. Best-effort and
 * synchronous about capturing the token: the local session is cleared even
 * when the API is unreachable.
 */
export function useSignOut() {
  const router = useRouter();
  const queryClient = useQueryClient();

  return useCallback(() => {
    // logoutRequest reads the token synchronously before any await, so this
    // is safe to fire before clearAccessToken(); failures are ignored.
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
