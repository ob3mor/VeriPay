# VeriPay web (`@veripay/web`)

Next.js App Router frontend for VeriPay, deployed as a **pure static export**
(`output: "export"`) to Azure Static Web Apps (Free plan). Hand-scaffolded —
no create-next-app.

## Run

```bash
# from the repo root
npm install                     # installs all workspaces (long first run)
npm run dev -w @veripay/web     # dev server on http://localhost:3000
npm run build -w @veripay/web   # static export -> apps/web/out
```

Quality gate (runs the exact production build from the repo root):

```bash
node apps/web/node_modules/next/dist/bin/next build apps/web
```

> npm workspaces normally hoist `next` into the root `node_modules`, which
> would break the gate's path into `apps/web/node_modules`. The workspace's
> `postinstall` hook (`scripts/ensure-next-link.mjs`) links the hoisted copy
> into `apps/web/node_modules` when needed — no files copied, no version drift.

## Environment

See `.env.example`. Nothing is required at build time: unset,
`src/lib/api.ts` defaults to `http://localhost:8000`. Both base forms (with or
without the `/api/v1` suffix) are normalized — endpoints are never
double-prefixed. The value is inlined at **build** time; rebuild after
changing it.

## Session token (documented key)

The JWT from `POST /api/v1/auth/login|register` is stored in
`localStorage` under:

```
veripay:access_token
```

and sent as `Authorization: Bearer <jwt>` on API calls (`src/lib/auth.ts`,
`src/lib/api.ts`). Known tradeoff: localStorage is readable by any script on
the origin (XSS exposure) — a deliberate Phase 1 simplification; the reserved
`POST /api/v1/auth/refresh` (httpOnly cookie, docs/API.md §4) is the Phase 2
upgrade path.

Mitigations shipped in Phase 1:

- **Server-side sign-out.** `useSignOut` (`src/hooks/use-session.ts`) also
  calls `POST /api/v1/auth/logout`, which revokes the presented token
  server-side — a signed-out or stolen token is rejected by the API instead of
  living out its full JWT expiry.
- **Security headers.** `public/staticwebapp.config.json` (copied into `out/`
  by the static export) makes Azure Static Web Apps serve a CSP and hardening
  headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, HSTS). The CSP's `connect-src` allows any `https:`
  origin because `NEXT_PUBLIC_API_BASE_URL` is a build-time variable —
  **tighten it to the real API origin when it is known.**

## Static-export rules (enforced by convention)

- No server actions, no API routes, no server-side data fetching.
- No `next/image` optimization (`images.unoptimized: true`), no network fonts.
- All API access is client-side (`src/lib/api.ts`) and must degrade gracefully:
  with the backend offline, every page still renders (offline hints, empty
  states, `ApiNetworkError` handling) — never a crash.
- `localStorage` is only touched in effects/handlers; the prerender in Node
  sees guarded `typeof window` shims.

## Layout

```
src/
  app/
    page.tsx                  landing (server component, static)
    (auth)/layout.tsx         centered card shell
    (auth)/login|register     controlled forms -> real API -> /dashboard
    (dashboard)/layout.tsx    server wrapper + metadata
    (dashboard)/dashboard/    Overview (live /auth/me + placeholder stats),
                              Vendors, Invoices, Investigations, Settings
  components/
    ui/                       shadcn/ui-style button, card, input, label (cva)
    dashboard-shell.tsx       auth guard + sidebar/topbar
    placeholder-page.tsx      shared scaffold for Phase 3+ pages
  hooks/use-session.ts        useMe (TanStack Query) + useSignOut
  lib/api.ts                  fetch wrapper: base URL, Bearer token, ApiError
  lib/auth.ts                 token storage (documented key) + window guards
  lib/utils.ts                cn()
```

Placeholder pages list the API surface they will consume, traced to
docs/API.md §6, so reviewers can check every planned call against the contract.
