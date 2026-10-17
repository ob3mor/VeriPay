/**
 * Phase 1 session-token storage.
 *
 * The JWT returned by POST /api/v1/auth/login|register is kept in localStorage
 * under the documented key below and attached as `Authorization: Bearer <jwt>`
 * to every request by src/lib/api.ts (docs/API.md §1).
 *
 * Documented key: `veripay:access_token` (also in apps/web/README.md).
 *
 * Known tradeoff: localStorage is readable by any script running on the origin
 * (XSS exposure). This is a deliberate Phase 1 simplification; docs/API.md §4
 * reserves POST /api/v1/auth/refresh (httpOnly cookie) as the Phase 2 upgrade
 * path, at which point this module shrinks to a thin wrapper around the
 * session cookie. Mitigations shipped in the meantime:
 * - POST /api/v1/auth/logout revokes the presented token server-side
 *   (use-session.ts fires it on sign-out), so a stolen token dies at logout
 *   instead of living out its full 8-hour JWT expiry;
 * - apps/web/public/staticwebapp.config.json serves a CSP and hardening
 *   headers on Azure Static Web Apps (default-src 'self' blocks third-party
 *   script origins; inline script stays allowed because the static export
 *   cannot inject per-response nonces).
 *
 * All helpers guard on `window`: the static export prerenders every page in
 * Node at build time, where localStorage does not exist.
 */

export const ACCESS_TOKEN_STORAGE_KEY = "veripay:access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
}
