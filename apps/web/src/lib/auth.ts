/**
 * Session store for the VeriPay SPA.
 *
 * Owner's hard rules (Phase 2):
 * - "Never store long-lived sensitive authentication tokens in browser
 *   localStorage." The short-lived Bearer access token therefore lives in a
 *   MODULE-SCOPED variable only — it dies with the page and survives nowhere.
 *   The durable session is the httpOnly `veripay_session` cookie, which JS
 *   cannot read at all (XSS cannot exfiltrate it).
 * - The readable `veripay_csrf` cookie is echoed in the X-CSRF-Token header on
 *   mutating requests by src/lib/api.ts (CSRF double-submit; the backend
 *   enforces it).
 *
 * On a fresh page load the SPA needs NO stored token: GET /auth/me
 * authenticates through the session cookie alone (credentials: "include").
 * 401s are transparently refreshed against POST /auth/refresh by api.ts.
 *
 * All helpers guard on `typeof window`: the static export prerenders pages in
 * Node at build time, where neither memory-persistence nor cookies matter.
 */

const CSRF_COOKIE_NAME = "veripay_csrf";

/** Module-scoped, memory-only access token (short-lived, 30 minutes). */
let accessToken: string | null = null;

/** Store the access token returned by login/register/refresh — memory only. */
export function setAccessToken(token: string): void {
  accessToken = token;
}

/** Current in-memory access token, or null after a fresh page load. */
export function getAccessToken(): string | null {
  return accessToken;
}

/** Drop the in-memory token (logout, failed refresh). */
export function clearAccessToken(): void {
  accessToken = null;
}

/** Read the CSRF cookie (not httpOnly by design — that is the double submit). */
export function getCsrfToken(): string | null {
  if (typeof window === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith(`${CSRF_COOKIE_NAME}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE_NAME.length + 1)) : null;
}

/** Canonical role → display label (the owner's four roles). */
export const ROLE_LABELS: Record<string, string> = {
  org_admin: "Organization Admin",
  finance_officer: "Finance Officer",
  reviewer: "Reviewer",
  auditor: "Auditor",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
