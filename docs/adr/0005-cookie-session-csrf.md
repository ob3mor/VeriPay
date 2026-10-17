# ADR 0005: Cookie sessions + CSRF for the browser, short Bearer tokens for programs

Date: 2026-10-17 · Status: accepted (Phase 2)

## Context

The owner's Phase 2 requirements: never store long-lived sensitive tokens in
browser localStorage; support a future cross-origin Azure Static Web Apps
frontend without depending on third-party cookies; rate-limited auth;
server-side sign-out. Phase 1 shipped an 8-hour Bearer JWT in localStorage
(documented tradeoff + CSP mitigation).

## Decision

Two credential channels over one identity:

1. **Browser: httpOnly cookie session.** `POST /auth/login|register` set
   `veripay_session` (httpOnly, SameSite=Lax, Secure in production) holding an
   opaque random token; only its SHA-256 hash is stored (durable `sessions`
   table, 7-day TTL, server-side revocation). `POST /auth/refresh` mints a
   fresh short Bearer token from the cookie. `POST /auth/logout` revokes the
   row (or the presented Bearer jti) and clears cookies.
2. **Programs: `Authorization: Bearer <JWT>`** with a 30-minute expiry — the
   FastAPI "Authorize" button, curl, and CI scripts keep working unchanged.

**CSRF**: a mutating request that authenticates by cookie must echo the
readable `veripay_csrf` cookie in `X-CSRF-Token` (double-submit) and pass an
Origin/Referer allowlist check; Bearer requests are exempt (not ambient
authority). Enforced once in `core/csrf.py` middleware.

**Azure demo shape**: the SWA `staticwebapp.config.json` proxies `/api/*` to
the Container App, making the API same-origin — cookies stay first-party; no
third-party-cookie dependence.

## Consequences

- No tokens in web storage anywhere (verified by grep + tests).
- Role changes take effect on the next request (role read fresh from the user
  row, not frozen in a long-lived token).
- The sessions table makes revocation durable and replica-safe (the Phase 1
  in-process registry remains only for Bearer jti revocation).
- One middleware owns CSRF — routes never hand-roll it.
