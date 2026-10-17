# VeriPay — Azure Pre-flight Report (Gate G0)

Status: **READ-ONLY pre-flight complete — NOTHING provisioned.** Provisioning requires the
owner's explicit approval (docs/DEPLOYMENT_AZURE.md §3 gates G1–G7).

Executed: 2026-10-17 · By: engineering agent (read-only `az` queries only)

## 1. Verified subscription facts (real `az` outputs)

| Check | Result | Notes |
|---|---|---|
| Active subscription | `Azure for Students` (`e666d34a-ebbf-42ad-8c18-35c2250278e0`), state `Enabled` | Switched from the Ambassador subscription per owner instruction |
| quotaId / spendingLimit via CLI | **null (not exposed)** | `az account show` does not surface these on this offer — **verify `Spending limit = On` in the Portal before G1** (hard rule: never remove it) |
| Existing resource groups | `rg-flexedit-licensing` (uaenorth) — **another project (FlexEdit)** | Functions + App Service F1 (Free) + Storage Tables meters visible in `az consumption usage list` |
| ⚠️ Budget-sharing discovery | The $20 student credits are **SHARED with the FlexEdit project** | VeriPay must deploy into its **own resource group** (`rg-veripay-demo`) and the demo-month budget must be re-checked against *combined* usage in Cost Analysis before G1 |
| Region | `uaenorth` — where the existing FlexEdit resources live | Container Apps availability in `uaenorth` to be confirmed by the first `az containerapp env create` attempt (the CLI location query returned no rows this session) |

## 2. What is already deployment-ready in the repo

- `apps/web/out/` static export builds green (`output: 'export'`) + `staticwebapp.config.json`
  (CSP + headers + SWA routing).
- `apps/api/Dockerfile` + `docker-entrypoint.sh` (runs `alembic upgrade head` then uvicorn,
  HEALTHCHECK on `/api/v1/health`) — image build happens in CI/GHCR, not locally (no Docker here).
- `.github/workflows/ci.yml` (tests + build + migration checks on a real PG 16 service container).
- Full local verification passed before this report: **293 pytest passed / 6 honest skips**,
  `next build` exit 0, contracts `tsc` exit 0, and a live end-to-end demo on localhost
  (login → vendors → bank-account workflow → upload → EVC assessment → cases) — screenshots and
  seeded synthetic data (`scripts/seed_demo.py`, 12 invoices, 3 auto-opened cases).

## 3. Provisioning plan summary (details + commands: docs/DEPLOYMENT_AZURE.md)

| Gate | Resource | Spec | Expected cost |
|---|---|---|---|
| G1 | Resource group `rg-veripay-demo` (uaenorth) | — | free |
| G2 | PostgreSQL Flexible Server **create in Portal** | B1ms + free-offer eligibility confirmed in Portal FIRST; fallback: external free tier (e.g. Neon) | ~$0 if free offer applies, else ~$13/mo → **do not proceed without portal confirmation** |
| G3 | Container Apps environment | Consumption only | ~$0 idle |
| G4 | Container App `api-veripay-demo` | minReplicas=0, maxReplicas=1, image from GHCR | ~$0 idle, cents per demo hour |
| G5 | Document Intelligence **F0** | 500 pages/mo quota; never auto-upgrade | $0 |
| G6 | Blob Storage (private container) | LRS, short retention, synthetic data only | cents |
| G7 | Static Web App **Free** | serves `apps/web/out` | $0 |

Idle target ≈ **$0.04/mo**; hard stop = the subscription spending limit (an overrun stops the
service, it cannot bill). Cost analyst's verdict (docs/COST_ESTIMATE.md): **GO on ~$20 with four
conditions** — portal-confirm the PG free offer first, min replicas 0, no ACR/SWA-Standard/
Marketplace resources, one resource group torn down after the demo.

## 4. Approval checklist — owner must confirm BEFORE Gate G1

1. [ ] Portal: confirm `Spending limit = On` and remaining credit (CLI cannot read it on this offer).
2. [ ] Portal: confirm the PostgreSQL Flexible Server **free offer** is actually available on this
       subscription (else approve the Neon fallback — synthetic demo data only).
3. [ ] Acknowledge the shared subscription with FlexEdit and accept the combined-usage risk.
4. [ ] Approve the exact resource names/region in §3 (or amend).
5. [ ] Say the word — then provisioning runs **gate by gate**, each verified, with `az resource
       list` re-checked after every gate and a full teardown plan ready (§8 of the deployment doc).

## 5. Honest limitations of this pre-flight

- Every cost figure is the cost analyst's estimate against published pricing — **not** a reading of
  this subscription's billing (no billing API access on student offers).
- Container Apps region support for `uaenorth` was not confirmed by a successful CLI query this
  session (the location query returned nothing); first provisioning command will confirm.
- The `api-image.yml` / SWA deploy workflows referenced by the plan are **deliberately not added
  yet** — the deployment doc gates them on owner approval, and they are inert without Azure
  resources + secrets anyway.
