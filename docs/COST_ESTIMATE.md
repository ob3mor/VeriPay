# VeriPay — Azure Cost Estimate for the `AZURE_STUDENT_DEMO` profile

> **Status:** Research + estimate only. **Nothing was provisioned, nothing was run against Azure, no cloud access exists on this machine.**
> **Budget context:** ~$20 remaining in Azure for Students credits. Hard rules honored here: **never provision a paid resource without explicit owner approval; never upgrade the subscription; never remove the spending limit.**
>
> **Prices verified 2026-10-17.** Sources: the public [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (queried this date, output excerpts in Appendix A) and official Microsoft documentation (linked inline). Prices are USD, **East US** region unless noted; they change — re-check before provisioning.

---

## 1. What the AZURE_STUDENT_DEMO profile uses

| # | Resource | SKU / Plan | Free allowance | What happens when the allowance is exceeded | Expected idle cost | Worst-case demo month |
|---|----------|-----------|----------------|---------------------------------------------|--------------------|-----------------------|
| 1 | Azure Static Web Apps (frontend) | **Free** plan | $0 plan; 100 GB bandwidth/month; 10 apps; 250 MB app size; 2 custom domains (SWA quotas doc, fetched 2026-10-17) | **Overage is "Unavailable" on Free** — traffic beyond 100 GB/month is not served (no billing, service stops/throttles). Paying requires upgrading to Standard: **$9/app/month**, then $0.20/GB overage | **$0.00** | **$0.00** (only if upgraded to Standard: +$9.00 — do not) |
| 2 | Azure Container Apps (FastAPI API) | **Consumption plan**, scale-to-zero (`min replicas = 0`) | Per subscription per calendar month: **first 180,000 vCPU-seconds, first 360,000 GiB-seconds, first 2,000,000 HTTP requests** (CA billing doc, fetched 2026-10-17) | Billed beyond grant at active rates: **$0.000024/vCPU-s** ($0.0864/vCPU-hr), **$0.000003/GiB-s** ($0.0108/GiB-hr), **$0.40 per 1M requests** (Retail Prices API, East US). Idle replicas (min replicas > 0) bill at reduced idle rate $0.000003/vCPU-s | **$0.00** (0 replicas → "no resource consumption charges are incurred" — CA billing doc) | **≈ $4.29** if min replicas stuck at 1 and idle; **≈ $14.31** if min replicas 1 with active demo traffic; +$0.40 per 1M requests over grant (math in §3) |
| 3 | Azure Database for PostgreSQL Flexible Server (database) | **Burstable B1ms** via the **12-month free offer** (750 hrs/month B1ms + 32 GB storage + 32 GB backup) | Free offer listed on the [Azure for Students page](https://azure.microsoft.com/en-us/free/students) (fetched 2026-10-17): *"750 hours of Flexible Server: Burstable B1MS Instance, 32 GB storage, and 32 GB backup storage"*; a `Compute - Free vCore` meter at $0.00/hr exists in the Retail Prices API | Billed as pay-as-you-go: B1ms **$0.017/hr** (≈ **$12.41/730 hr-month**), storage **$0.115/GB-month** over 32 GB, backup LRS **$0.095/GB-month** over the covered 32 GB (Retail Prices API, East US). Community reports of ~$4/day bills when free limits are exceeded (MS Q&A 5828927) | **$0.00** *if the free offer activates* (750 hrs > 730 hrs in a month) | **$16.09/month idle** if the free offer cannot be activated ($12.41 compute + 32 GB × $0.115 = $3.68 storage) — see Gate in §5 |
| 4 | Azure AI Document Intelligence (OCR) | **F0 free tier** | **500 pages/month**, free meter `Free Transactions` at $0.00 (Retail Prices API). F0 limits: only the **first 2 pages of each request** analyzed, **4 MB** max file, 1 transaction/sec, 10 hrs/month free neural training (service-limits doc, updated 2026-10-14) | **No overage billing possible:** requests beyond 500 pages/month are rejected with **HTTP 403** until the next month (MS Q&A 5609989). Billing only starts if you manually upgrade to S0: Read **$1.50/1k pages**, prebuilt models ≈ **$10/1k pages** (e.g. `S0 pages for query fields` meter $10/1K in Retail Prices API) | **$0.00** | **$0.00** (F0 cannot bill). Only if manually upgraded to S0 and run at S0 prices — do not upgrade |
| 5 | Azure Blob Storage (invoice documents) | GPv2, **Hot LRS**, flat namespace, private container | **No free allowance** (blob is not a free-tier service; a 5 GB/12-month allowance exists for new Azure free accounts but is not relied on here) | Pay per use: capacity **$0.0208/GB-month** (first 50 TB, Hot LRS), writes **$0.05/10k ops**, reads **$0.004/10k ops**, deletes $0 (Retail Prices API, East US). Internet egress: **first 100 GB/month free**, then **$0.087/GB** (Bandwidth pricing page + Retail Prices API) | **≈ $0.04** (2 GB demo data) | **≈ $0.19** (5 GB stored + ~10k writes + ~10k reads) |
| 6 | Log Analytics workspace (created with the Container Apps environment) | Pay-as-you-go Analytics Logs | **First 5 GB/month ingestion free per billing account**; retention first 31 days free | ≈ **$2.30/GB** ingested beyond 5 GB (East US, approximate — region-dependent); retention beyond 31 days ≈ $0.10/GB/month (Azure Monitor pricing page) | **$0.00** (a quiet scale-to-zero app logs well under 5 GB) | **≈ $11.50** if verbose logging produces 10 GB in a month (5 GB free + 5 GB × $2.30) |
| 7 | Internet egress (all services) | — | First 100 GB/month free across Azure | **$0.087/GB** (zone 1) beyond 100 GB (Retail Prices API) | **$0.00** | **$0.00** for a demo (well under 100 GB) |

### Row-level notes

- **Static Web Apps Free** also has no SLA, no private endpoints, and — critically for wiring — **linked backends (connecting the Container Apps API through SWA) require the Standard plan** ([SWA + Container Apps doc](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-container-apps)). The demo therefore calls the Container Apps HTTPS URL **directly from the browser via CORS**. Standard would add **$9.00/month per app** (Retail Prices API `Standard App | 9.0 /Month`) — **do not upgrade**.
- **Container Apps environment fee:** the $0.10/hr "Management (hour)" meter applies to the **Dedicated plan, private endpoints, and planned maintenance** ([Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps); meter description per [GitHub issue microsoft/azure-container-apps#1596](https://github.com/microsoft/azure-container-apps/issues/1596)). A **Consumption-only environment with no private endpoints costs $0 for the environment itself**. Never enable dedicated workload profiles or private endpoints on this budget (that is ≈ $73/month).
- **PostgreSQL:** disable **high availability** (HA adds a standby billed at the same B1ms rate, roughly doubling compute — options per the [quickstart doc](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/quickstart-create-server)); **create with exactly 32 GB storage** (the CLI quickstart example uses `--storage-size 128`, which would cost 128 × $0.115 = **$14.72/month** if the free offer doesn't cover it); storage can only be increased, never shrunk.
- **Document Intelligence F0:** create the resource with SKU **F0**. Only the first 2 pages of any request are analyzed and files cap at 4 MB — for VeriPay, multi-page invoices beyond page 2 on F0 must go through the **human-review path** (which is also what the product rules demand: uncertain OCR must not become confident fraud evidence). Do **not** enable paid add-ons (e.g., high-resolution extraction) — they can bill even on F0 (MS Q&A 2225662).

---

## 2. Idle-cost analysis

What "idle" means for each resource of the demo, at steady state (no demo traffic):

| Resource | Idle state | Idle cost mechanism | Idle $/month |
|---|---|---|---|
| SWA Free | Static files served; no compute | Free plan, no instance charge | $0.00 |
| Container Apps | **Scaled to 0 replicas** between demos | CA billing doc: *"When a revision is scaled to zero replicas, no resource consumption charges are incurred."* No requests → no request charges. Cold starts during a demo bill active rates for seconds — 100 requests/day × ~5 s × 0.5 vCPU ≈ 75,000 vCPU-s + 75,000 GiB-s/month, inside the free grants | $0.00 |
| PostgreSQL B1ms | **Runs 24/7** even when idle (it's a managed server) | Free offer covers 750 hrs/month (730 hrs in a 31-day month) + 32 GB storage → fully covered | $0.00 (free offer) / **$16.09** (without it) |
| Document Intelligence F0 | No pages processed | Free tier, no fixed charge | $0.00 |
| Blob Storage | 2 GB of documents at rest | Capacity-only charge, no minimum | ≈ $0.04 |
| Log Analytics | Scale-to-zero app emits little | Under the 5 GB/month free ingestion | $0.00 |

**Expected idle total: ≈ $0.04/month (call it $0.00–$0.05).** The single biggest idle risk is PostgreSQL **without** the free offer ($16.09/month — 80% of the remaining credit, before anything else).

### Worst-case demo-month scenarios

| Scenario | Description | Math | Total |
|---|---|---|---|
| A — nominal | Correct config (min replicas 0, F0, free-offer PG, modest logs, 5 GB blob) | Blob $0.19 + everything else $0 | **≈ $0.20** |
| B — replica trap | Someone sets min replicas = 1 (0.25 vCPU / 0.5 GiB) and the app mostly idles | vCPU idle: (657,000 s − 180,000) × $0.000003 = $1.43; memory: (1,314,000 GiB-s − 360,000) × $0.000003 = $2.86; + blob $0.19 | **≈ $4.50** |
| C — replica trap + traffic + verbose logs | Min replicas 1 with demo traffic at active rates; 10 GB of logs; 5 GB blob | vCPU active: 477,000 × $0.000024 = $11.45 + memory $2.86 + logs (10 − 5) × $2.30 = $11.50 + blob $0.19 | **≈ $26.00** |
| D — free offer unavailable | PG provisioned anyway without the free offer | + $12.41 + $3.68 = $16.09/month, idle | **+ $16.09** on any scenario |
| E — absolute worst | C + D + SWA Standard upgrade + dedicated plan features | Sum of everything misconfigured | **≈ $50 theoretical** — but see §4: the spending limit caps **actual** spend at the remaining credit; services get disabled instead of billing |

**Scenario E can never become a real invoice** as long as the spending limit stays on and nothing is bought from the Marketplace. The realistic danger is not debt — it is **running out of credit mid-demo** (subscription and all resources get disabled until the next billing period, storage goes read-only).

---

## 3. Charges NOT covered by free tiers (what can actually drain the ~$20)

1. **PostgreSQL without the free offer — the dominant risk.** B1ms $0.017/hr + $0.115/GB-month storage ≈ **$16.09/month idle**. Gate on the free-offer check before provisioning (§5).
2. **Container Apps min-replica trap.** Free grant covers scale-to-zero. `min replicas ≥ 1` bills continuously: ≈ $4.29/month idling, ≈ $14.31/month with demo traffic. Requests beyond 2M/month: $0.40 per million.
3. **Log Analytics beyond 5 GB/month.** ≈ $2.30/GB (East US, approximate) and retention beyond 31 days ≈ $0.10/GB/month. Verbose request logging in a noisy demo can produce 10+ GB.
4. **Azure Container Registry has no free tier** — Basic ≈ $5.00/month ($0.1666/day, Retail Prices API), Standard ≈ $20/month. **Do not create an ACR.** Build the API image in GitHub Actions (Ubuntu runners have Docker; this Windows machine does not) and push to a **public GHCR / Docker Hub image**, which Container Apps can pull at no cost.
5. **Blob is cheap but never free:** $0.0208/GB-month, writes $0.05/10k, reads $0.004/10k, egress $0.087/GB after 100 GB/month. Pennies at demo scale — nonzero, by design, because invoices must live somewhere.
6. **SWA Free has no overage.** Exceeding 100 GB bandwidth/month stops serving (no billing). The "fix" is the $9/month Standard plan — out of scope for this budget.
7. **Document Intelligence S0 / add-ons.** F0 cannot bill, but upgrading the resource to S0 bills per page (prebuilt ≈ $10/1k pages — a 5,000-page month ≈ $50), and some add-ons bill even on F0. Never upgrade the SKU; never enable add-ons.
8. **Marketplace & external services bypass the spending limit.** Per the [spending-limit doc](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit): "A spending limit doesn't prevent all charges" — e.g., Entra ID P1/P2, support plans, most third-party Marketplace offers. **Buy nothing.**
9. **Accidental SKU choices:** 128 GB PG storage (quickstart default in examples) = $14.72/month; HA = ~2× compute; dedicated workload profiles/private endpoints = $0.10/hr environment fee; SWA Standard = $9/month. All four are config mistakes, not necessities.

---

## 4. Guardrails: the spending limit and how the ~$20 behaves

Verified from the [Azure spending limit doc](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit) (fetched 2026-10-17) and the [Azure for Students page](https://azure.microsoft.com/en-us/free/students):

- The spending limit equals the credit amount and **cannot be changed** ("Custom spending limits aren't available"); it can only be removed entirely (requires a payment method — the owner must not do this, per the hard rule).
- **When usage exhausts the credit: "the services that you deployed are disabled for the rest of that billing period"**; VMs are de-allocated, storage data becomes read-only. Azure emails a notification. No invoice is issued.
- Marketplace/external services are the exception — they can bill separately **even with the spending limit on** (see §3.8).
- Practical guardrails for the demo:
  - Put **every resource in one resource group** (`veripay-demo-rg`) so teardown is one command and nothing orphaned keeps metering.
  - Set a **Cost Management budget with an alert at $1 and $5** for the month (budgets are free) and check Cost Analysis the day after each provisioning step.
  - After creating each resource, confirm its expected meters appear at $0.00 in Cost Analysis; investigate anything else immediately.
  - Re-check the SWA/CA scale settings after any manual portal edit — the portal sometimes nudges toward higher tiers.

---

## 5. The one gate that decides everything: PostgreSQL free-offer eligibility

- **Verified:** the [Azure for Students page](https://azure.microsoft.com/en-us/free/students) explicitly lists *"750 hours of Flexible Server: Burstable B1MS Instance, 32 GB storage, and 32 GB backup storage"* among free services, and a `Compute - Free vCore` $0 meter exists for PostgreSQL Flexible Server in the Retail Prices API (2026-10-17).
- **Unverified / cannot verify from this machine (no cloud access):** whether **this particular student subscription** still qualifies. The free-services list footnote says 12-month free services are *"available only to new customers who have not previously had an Azure account or received 12 months of free services"*, and community threads (MS Q&A 2086253) report student subscriptions where the offer did not activate. The portal shows a "Try free" / offer-eligibility indicator in the Flexible Server creation blade — **check it before creating anything.**
- **If the offer does not activate:** do **not** provision Flexible Server on credits ($16.09/month idle). Fall back to:
  1. **SQLite** in the Container App (already an accepted dev/test fallback in the stack; loses the PostgreSQL-canonical guarantee but costs $0), or
  2. A third-party free-tier Postgres, e.g. **Neon Free** (0.5 GB storage, 100 compute-unit-hours/month, auto-suspend after 5 min — per [neon.com/pricing](https://neon.com/pricing), terms change; verify) — no Azure credits involved, and the provider-agnostic data layer keeps the switch cheap.
  - Azure HorizonDB (Microsoft's newer PostgreSQL service) also showed **free-tier meters** ($0 compute/storage) in the Retail Prices API on 2026-10-17 — **terms not verified**; investigate in the portal before considering it.

---

## 6. Cleanup / teardown plan

Full commands live in [`DEPLOYMENT_AZURE.md`](./DEPLOYMENT_AZURE.md) §8; the cost-relevant contract is:

1. **One resource group for everything** (`veripay-demo-rg`): Container Apps env + app + Log Analytics workspace + PostgreSQL + storage account + Document Intelligence. SWA is region-global but still lands in the group.
2. **Teardown = `az group delete --name veripay-demo-rg --yes --no-wait`** — removes all metered resources at once, including the PostgreSQL server and its backups.
3. **Known orphan risks to check afterwards:**
   - The Log Analytics workspace is created alongside the CA environment — it must be in the same resource group; verify with `az resource list -g veripay-demo-rg` is empty after deletion.
   - The GitHub Actions workflows created for SWA/image builds: delete repo secrets and disable workflows (GitHub-side, $0 but hygiene).
   - The public GHCR image: delete the package (free, hygiene).
   - No ACR exists in this plan — nothing else to hunt.
4. **Verification that spending stopped:** next day, Cost Analysis shows zero new charges; `az consumption usage list` (or Cost Management → Invoices) shows no post-teardown meters. The spending limit itself never needs touching.

---

## 7. Verdict for a $20 budget

> **GO — conditionally.** Expected idle cost is **≈ $0.04/month** and a correctly configured demo month lands **under ~$0.50**; even the realistic worst-case misconfiguration (scenario C) is ≈ $26 of *theoretical* usage that the spending limit caps at the remaining credit — services get disabled, no invoice is possible. The four non-negotiable conditions:
> 1. **Gate on the PostgreSQL free offer in the portal first**; if it won't activate, use SQLite/Neon — never a pay-as-you-go Flexible Server ($16.09/month idle would eat the budget alone).
> 2. **`min replicas = 0`** on the Container App, always; never enable HA, dedicated workload profiles, private endpoints, or the SWA Standard upgrade.
> 3. **No ACR, no Marketplace, no add-ons** — build images on GitHub Actions to a public registry; buy nothing that bypasses the spending limit.
> 4. **One resource group + budget alerts + teardown after the demo.**

Residual risks (accepted, or flagged for portal verification): PG free-offer eligibility (gate above); whether Container Apps resource creation is permitted at all on an Azure for Students subscription (**not verifiable without the portal** — if creation fails, the API stays on the SQLite/MinIO local profile at $0); F0 regional availability and the one-F0-per-subscription limit (**not verified** — confirm in the creation blade); the exact SWA Free overage behavior (stop vs throttle — quotas doc says only "Unavailable").

---

## Appendix A — Price evidence (Azure Retail Prices API, queried 2026-10-17)

Query pattern (PowerShell; filters URL-encoded):

```
https://prices.azure.com/api/retail/prices?currencyCode=USD&$filter=<OData filter>
```

Key rows returned (`productName | meterName | skuName | retailPrice unitOfMeasure`):

| Query | Relevant rows |
|---|---|
| `serviceName eq 'Azure Container Apps' and armRegionName eq 'eastus'` | `Standard vCPU Active Usage | 0.000024 /1 Second` · `Standard Memory Active Usage | 0.000003 /1 GiB Second` · `Standard vCPU Idle Usage | 0.000003 /1 Second` · `Standard Memory Idle Usage | 0.000003 /1 GiB Second` · `Standard Requests | 0.4 /1M` · `Environment Private Endpoint | 0.1 /1 Hour` · `Dedicated Plan Management | 0.1 /1 Hour` |
| `contains(serviceName,'PostgreSQL') and armRegionName eq 'eastus'` | `Flexible Server Burstable BS Series Compute | B1MS | 0.017 /1 Hour` · `Flex Server Storage | Storage Data Stored | 0.115 /1 GB/Month` · `Flexible Server Backup Storage | Backup Storage LRS Data Stored | 0.095 /1 GB/Month` · `Flexible Server Compute | Compute - Free vCore | 0.0 /1 Hour` |
| `contains(productName,'Document Intelligence')` (East US rows) | `Free Transactions | Free | 0.0 /1K` · `S0 pages for query fields | S0 | 10.0 /1K` (+ commitment tiers, unused) |
| `serviceName eq 'Storage' … contains(meterName,'Hot')` (East US, `General Block Blob v2`) | `Hot LRS Data Stored | 0.0208 /1 GB/Month` · `Hot LRS Write Operations | 0.05 /10K` · `Hot Read Operations (LRS) | 0.004 /10K` · `Hot LRS Delete Operations | 0.0 /10K` |
| `serviceName eq 'Bandwidth' … 'Data Transfer Out'` (East US) | `Standard Data Transfer Out | 0.087 /1 GB` (zone 1 tiers 0.087 → 0.083 → …) |
| `serviceName eq 'Container Registry' and armRegionName eq 'eastus'` | `Basic Registry Unit | 0.1666 /1/Day` · `Standard Registry Unit | 0.6666 /1/Day` (no free tier) |
| `contains(productName,'Static Web Apps')` | `Standard App | 9.0 /1/Month` · `Standard Bandwidth Usage | 0.2 /1 GB` (overage rows; free-plan rows are $0/not metered) |

Not found via the API (meter names not exposed): Log Analytics Analytics Logs ingestion — taken from the [Azure Monitor pricing page](https://azure.microsoft.com/en-us/pricing/details/monitor) (first 5 GB/month per billing account free; ≈ $2.30/GB East US pay-as-you-go, approximate).

## Appendix B — Documentation sources

- Azure for Students offer & free services: https://azure.microsoft.com/en-us/free/students ; https://azure.microsoft.com/en-us/pricing/free-services
- Spending limit: https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit
- SWA plans/quotas: https://learn.microsoft.com/en-us/azure/static-web-apps/quotas ; pricing: https://azure.microsoft.com/en-us/pricing/details/app-service/static ; Container Apps backend integration: https://learn.microsoft.com/en-us/azure/static-web-apps/apis-container-apps
- Container Apps billing: https://learn.microsoft.com/en-us/azure/container-apps/billing ; pricing: https://azure.microsoft.com/en-us/pricing/details/container-apps
- PostgreSQL quickstart (SKU/HA/CLI flags): https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/quickstart-create-server ; product/free-offer: https://azure.microsoft.com/en-us/products/postgresql
- Document Intelligence limits: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0 ; pricing: https://azure.microsoft.com/en-us/pricing/details/document-intelligence
- Blob cost model: https://learn.microsoft.com/en-us/azure/storage/blobs/blob-storage-estimate-costs ; pricing: https://azure.microsoft.com/en-us/pricing/details/storage/blobs
- Bandwidth (free 100 GB egress): https://azure.microsoft.com/en-us/pricing/details/bandwidth
- Azure Monitor / Log Analytics: https://azure.microsoft.com/en-us/pricing/details/monitor
- F0 overage behavior (HTTP 403): https://learn.microsoft.com/en-us/answers/questions/5609989/azure-document-intelligence-f0-tier-ex-status-403
- Student-subscription PG free-offer caveats: https://learn.microsoft.com/en-us/answers/questions/2086253/how-to-create-postgresql-when-i-have-student-dev-p
- Container Apps environment-fee scope: https://github.com/microsoft/azure-container-apps/issues/1596
- Neon free plan (alternative): https://neon.com/pricing
