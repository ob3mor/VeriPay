# PRODUCT.md — VeriPay (apps/web)

Product truth captured from the owner's brief and the implemented product (src comments, src/lib/status.ts, docs/ARCHITECTURE.md §2/§8 as cited in code). Written autonomously in place of the init interview — the run's brief supplies every fact below; nothing is invented.

## What VeriPay is

AI-assisted invoice & payment fraud detection for finance & procurement teams. VeriPay cross-checks every invoice against the organization's vendors, purchase orders and trusted bank accounts, and routes inconsistencies to human review. It is **decision support, not a payment system**: copy stays honest and English.

## Non-negotiable invariants (carry into every surface)

- R1 — never authorizes a payment; no payment-rail integration exists.
- R2 — never declares an invoice genuine; the strongest allowed label is "No material discrepancies" (vocabulary lives in src/lib/status.ts).
- R3 — uncertain OCR stays uncertain (confidence gate, OCR_CONFIDENCE_THRESHOLD).
- R4 — missing records are not fraud; missing evidence is capped at medium severity.
- R5 — only a human verifies a bank account, with an independent verification record.
- R6 — critical findings force a human case; cases close only by human decision with outcome + summary.

## Audience & scene

Finance ops, procurement, and auditors working org-scoped queues (roles: org_admin, finance_officer, reviewer, auditor). They read dense evidence for long sessions and must trust the instrument immediately: severity/status colors are judgment colors, spent only where the data carries them.

## Surfaces & modes

- Landing (/) — **Persuade**: first impression of a real, luxurious financial-security product; also a portfolio piece for the owner.
- Auth (/login, /register) — **Persuade** (supporting).
- Everything under /dashboard — **Operate**: scanability, precision, states, consistent severity/status system. The investigations workspace is the product's hero surface (split-screen evidence review).

## Brand & platform

- Owner logo: apps/web/public/logo.png (transparent lockup, shield-mark + wordmark, navy/cyan) — merge with no white box; mark-only crop apps/web/public/logo-mark.png for tight slots.
- Identity anchor: deep navy + turquoise/cyan (in the family of #1CA6C8).
- Next.js 16 App Router, Tailwind 3.4, static export (output: "export", images unoptimized). No new heavy dependencies.
