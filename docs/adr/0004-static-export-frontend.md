# ADR 0004 — Static-export frontend

Status: Accepted · 2026-10-17

## Context

Hosting is Azure Static Web Apps **Free** — static file serving only; there is no Node server budget. VeriPay is authenticated internal tooling for finance teams, so SSR/SEO have no value, and the FastAPI backend is the security boundary by design.

## Decision

The Next.js App Router frontend runs with **`output: 'export'`**:

- All data access is client-side via **TanStack Query** against `/api/v1`; client types are generated from FastAPI's OpenAPI schema.
- **No** Next.js API routes, server actions, ISR, or middleware — nothing that requires a server.
- Route protection is client-side UX only (redirect to `/login`); **all authorization is enforced by the API** (API.md §5).
- Auth token handling: short-lived access token held in memory; the final refresh mechanism (httpOnly cookie vs. silent re-login) is settled during Phase 1 auth implementation and documented in API.md — XSS-safety is the deciding criterion. Its endpoint (`POST /api/v1/auth/refresh`) is already reserved in API.md §4, so the "v1 frozen except additive" rule cannot block the decision.
- Environment values are build-time only (`NEXT_PUBLIC_*`); `next/image` runs `unoptimized`; dynamic routes fetch client-side or declare `generateStaticParams`.

## Consequences

**Positive:** cheapest possible hosting; trivial CI (`next build` → upload `out/`); no server-side frontend to operate or patch.

**Negative:** no server-side redirects or auth guards (an unauthenticated user may briefly see a protected shell before the client guard fires); no request-time env; the API alone is the security perimeter, which raises the bar on API.md §5 compliance and its mandatory tenant-isolation tests.
