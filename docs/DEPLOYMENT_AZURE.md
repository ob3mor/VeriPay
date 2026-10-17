# VeriPay — Azure Deployment Plan (`AZURE_STUDENT_DEMO` profile)

> **STATUS: PLAN ONLY. Nothing in this document has been executed. No `az` command was run, no resource was provisioned, no cloud access exists on this machine. Every provisioning step below is gated on explicit owner approval.**
>
> Budget rules honored: ~$20 remaining in Azure for Students credits; **never provision a paid resource without the owner's explicit approval; never upgrade the subscription; never remove the spending limit.** Companion cost analysis: [`COST_ESTIMATE.md`](./COST_ESTIMATE.md) (all prices verified 2026-10-17; commands below are **not smoke-tested** — run them exactly as written and stop at the first error).

---

## 1. Target architecture

```
                      ┌──────────────────────────── Azure for Students subscription (spending limit ON) ───────────────────────────┐
                      │                                                                                                              │
  Browser ──HTTPS──►  │  Static Web Apps (Free)                Container Apps (Consumption, min replicas 0)                           │
                      │  veripay-web                           veripay-api  ──►  PostgreSQL Flexible Server B1ms (12-mo free offer)   │
                      │  Next.js static export                 FastAPI + SQLAlchemy      │                                             │
                      │      │                                        │                 ├─►  Document Intelligence F0 (OCR adapter)   │
                      │      └── CORS fetch to API URL ───────────────┘                 └─►  Blob Storage Hot LRS (private container)  │
                      │                                                                                                              │
                      └──────────────────────── everything in ONE resource group: veripay-demo-rg (one-command teardown) ─────────────┘
```

**Key wiring decision:** the frontend calls the Container Apps HTTPS URL **directly via CORS**. It does **not** use SWA "linked backends", because linking an existing backend requires the SWA **Standard plan ($9/app/month)** ([SWA + Container Apps doc](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-container-apps)) — out of budget.

**Product-rule alignment (config, not code):**
- Document Intelligence F0 analyzes only the **first 2 pages** of each request (4 MB cap) — anything longer, low-confidence, or missing from F0 output must flow into the **human-review queue** with its uncertainty preserved. The OCR adapter must never convert an F0 result into confident fraud evidence on its own (uncertain OCR ≠ confident fraud evidence).
- The API continues to expose detection **results only**; no endpoint or job in the demo may authorize payments automatically, and a new bank account still requires the independent-verification flow. The demo deployment changes hosting, not these behaviors.

## 2. Prerequisites and local constraints

| Prerequisite | Status / note |
|---|---|
| Azure CLI on the owner's machine | **Not installed here** — owner installs (`winget install Microsoft.AzureCLI`) and runs `az login`. No command in this doc was executed. |
| Docker | **NOT available on this machine and WSL is unavailable** — local image builds are impossible. Build in **GitHub Actions** (Ubuntu runners include Docker) and push to a **public GHCR image**. Do **not** create Azure Container Registry (no free tier, ≈ $5/month). |
| GitHub repository | Needed by SWA (deploy workflow) and GH Actions (image build). Public repo keeps Actions free; a private repo uses the 2,000 free minutes/month (GitHub billing, not Azure credits). |
| Next.js static export | Frontend must build with `output: 'export'` → static `out/` directory (SWA serves it as-is). |
| Region | **East US** for every resource (price basis of the estimate; keep resources colocated). |

## 3. Approval gates

Every step below begins behind a gate. **A gate is satisfied only by an explicit, recorded owner approval ("yes, run step N").**

| Gate | What the owner is approving | Cost exposure |
|---|---|---|
| **G0** | Pre-flight read-only checks (subscription type, remaining credit) | $0 |
| **G1** | Resource group `veripay-demo-rg` (East US) | $0 |
| **G2** | PostgreSQL Flexible Server B1ms — **only if the free offer is confirmed eligible in the portal** | $0/mo with offer; **$16.09/mo without → abort** |
| **G3** | Container Apps environment (Consumption-only) + Log Analytics workspace | $0 at rest (≤5 GB logs/mo free) |
| **G4** | Container App `veripay-api` from public GHCR image, scale-to-zero | $0 at rest; ≤ free grant in demos |
| **G5** | Document Intelligence resource, SKU **F0** | $0 (F0 hard-stops at 500 pages/mo) |
| **G6** | Storage account (Hot LRS) + **private** `invoices` container | ≈ $0.04/mo at 2 GB |
| **G7** | Static Web App, **Free** plan + GitHub Actions deploy | $0 |
| — | Teardown (§8) — approved implicitly by "the demo is over", or explicitly at any time | $0 |

**Cost stop-loss rule:** if Cost Analysis shows **>$1 total** spend at any point, stop, tear down (§8), and investigate before re-provisioning.

## 4. Pre-flight (Gate G0) — read-only, no resources created

```bash
az login
az account show --query "{name:name, type:subscriptionPolicies.spendingLimit, quota:subscriptionPolicies.quotaId}"
# Expect: spendingLimit = "On" (never remove it — hard rule) and a student offer quotaId (e.g. MSDNDevTest-like student offer id).

az consumption usage list --top 5 --query "[].{cost:pretaxCost, service:meterDetails.meterCategory}" -o table
# Confirms the ~$20 remaining reality: current-month spend should be near zero.
```

**PG free-offer eligibility check (no creation):** open the portal → *Create a resource → Azure Database for PostgreSQL Flexible Server* and look at the compute selection. The free-offer option ("Try Azure Database for PostgreSQL Flexible Server for free" / 750-hr B1ms offer toggle) **appears only if this subscription is eligible**. 
**This is the decisive check of the whole plan** ([Azure for Students page](https://azure.microsoft.com/en-us/free/students) lists the offer; community threads report student subscriptions where it did not activate — could not be verified from this machine). 
→ **If eligible:** proceed to G2 with the free offer selected. 
→ **If not eligible:** **abort the PostgreSQL step entirely.** Do not provision pay-as-you-go B1ms ($16.09/mo idle). Fall back to SQLite inside the container image (already an accepted dev/test fallback in the stack) or a third-party free-tier Postgres (e.g. Neon Free — 0.5 GB, auto-suspend; terms change, verify) and skip §5 Step 2. Alembic migrations against SQLite are already exercised by the dev/test profile.

## 5. Provisioning steps

### Step 1 — Resource group (Gate G1)

```bash
az group create --name veripay-demo-rg --location eastus
```
- Cost: $0. Everything else lands here; teardown = delete this group.

### Step 2 — PostgreSQL Flexible Server, B1ms, free offer (Gate G2) — *create in the PORTAL*

The free-offer activation is a portal creation-blade option (a CLI equivalent flag could not be verified — **unverified**), so this one resource is created by hand:

1. Portal → Create → **Azure Database for PostgreSQL flexible server**.
2. Resource group `veripay-demo-rg`, region **East US**, name `veripay-pg`, version 16, workload type **Development**.
3. Compute: select the **free offer (750-hr B1ms)** if offered; SKU must end up **B1ms**; **High availability: Disabled** (HA doubles compute cost); **storage exactly 32 GB** — never the 128 GB shown in CLI quickstart examples ($14.72/mo if uncovered); storage autogrow **off** (autogrow can silently bill beyond 32 GB).
4. Backup retention 7 days, redundancy **locally-redundant**.
5. Networking: **Public access** with firewall rules for (a) the owner's current IP and (b) the Container Apps environment's outbound IPs (added in Step 4 once known; the environment has documented static outbound IPs, which **can change on rebuild** — re-check then). Do not blanket-allow all Azure services unless the per-environment IPs fail.
6. Record the admin password in the local secret store; the connection string will be `host=veripay-pg.postgres.database.azure.com port=5432 dbname=veripay user=veripayadmin password=... sslmode=require`.

Verify (owner, after creation): portal shows SKU **B1ms**, storage **32 GB**, HA **Disabled**; `az postgres flexible-server show -g veripay-demo-rg -n veripay-pg`. Cost check: Cost Analysis must show **$0.00** for the `Microsoft.DBforPostgreSQL` meters the following day (free offer active). If any B1ms-hour meter bills — **delete the server and switch to the SQLite fallback.**

### Step 3 — Container Apps environment, Consumption-only (Gate G3)

```bash
az containerapp env create --name veripay-env --resource-group veripay-demo-rg --location eastus
az containerapp env show -n veripay-env -g veripay-demo-rg --query "properties.workloadProfiles"
```
- Creates a **Log Analytics workspace** in the same group automatically (the environment publishes app logs there; first 5 GB/month ingestion is free per billing account).
- The environment itself is **free** as long as it stays Consumption-only: the $0.10/hr management meter applies only to **Dedicated workload profiles, private endpoints, and planned maintenance** ([Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps), [billing doc](https://learn.microsoft.com/en-us/azure/container-apps/billing)). **Never add a dedicated workload profile or private endpoint.**
- The `workloadProfiles` query should show only Consumption entries (default/newer CLIs may create a workload-profiles-capable environment — acceptable **only** while no dedicated profile is attached; if a `Dedicated` profile is attached by default, recreate the environment and verify Cost Analysis stays at $0).
- Capture the static outbound IPs now: `az containerapp env show -n veripay-env -g veripay-demo-rg -o json` → `properties.staticIp` / outbound IP docs → add them to the PG firewall (Step 2.5).

### Step 4 — API image build (no Azure cost, no gate) + Container App (Gate G4)

**Image build — GitHub Actions (because Docker is unavailable locally):** a workflow on the repo builds the FastAPI image and pushes to GHCR:

```yaml
# .github/workflows/api-image.yml (owner approves adding this file)
name: api-image
on: { push: { branches: [main], paths: ["backend/**"] } }
permissions: { contents: read, packages: write }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - uses: docker/build-push-action@v6
        with:
          context: ./backend          # FastAPI app + Dockerfile location per repo layout
          push: true
          tags: ghcr.io/${{ github.repository }}/veripay-api:latest
```

**Create the app (scale-to-zero is the cost-critical setting):**

```bash
az containerapp create \
  --name veripay-api --resource-group veripay-demo-rg --environment veripay-env \
  --image ghcr.io/<owner>/<repo>/veripay-api:latest \
  --target-port 8000 --ingress external \
  --min-replicas 0 --max-replicas 2 --cpu 0.5 --memory 1.0Gi \
  --secrets pg-conn="host=veripay-pg.postgres.database.azure.com port=5432 dbname=veripay user=veripayadmin password=<PGPASSWORD> sslmode=require" \
            di-key="<DOCUMENT_INTELLIGENCE_KEY>" \
  --env-vars DATABASE_URL=secretref:pg-conn \
             DOCUMENT_INTELLIGENCE_ENDPOINT="<DI_ENDPOINT>" DOCUMENT_INTELLIGENCE_KEY=secretref:di-key \
             AZURE_STORAGE_ACCOUNT_NAME=veripaydocs AZURE_STORAGE_CONTAINER=invoices \
             CORS_ORIGINS="https://<swa-domain>" \
             OCR_PROVIDER=azure-di STORAGE_PROVIDER=azure-blob
```

Cost mechanics (verified in [`COST_ESTIMATE.md`](./COST_ESTIMATE.md) §1): 0 replicas → **no compute charges**; cold starts + demo traffic stay inside the monthly free grant (180k vCPU-s / 360k GiB-s / 2M requests); a *min-replica ≥ 1* config bills ≈ $4.29/mo idle, ≈ $14.31/mo active — **`--min-replicas 0` is non-negotiable**.

Verify: `az containerapp show -n veripay-api -g veripay-demo-rg --query "properties.configuration.ingress.fqdn"` → HTTPS URL; `curl https://<fqdn>/health` (first request pays a cold start of ~10–30 s); scale rules show min 0.

### Step 5 — Document Intelligence F0 (Gate G5)

```bash
az cognitiveservices account create --name veripay-docintel --resource-group veripay-demo-rg --location eastus \
  --kind FormRecognizer --sku F0 --yes
az cognitiveservices account keys list -n veripay-docintel -g veripay-demo-rg   # → DI_KEY secret in Step 4
```
- `--kind FormRecognizer` is the CLI's name for Document Intelligence. **SKU must be F0** — if F0 is unavailable in East US or already used by another resource (one-F0-per-subscription limit: **unverified** — the creation blade will say), do **not** fall back to S0; keep the local OCR provider instead.
- Wiring via the existing provider-agnostic OCR adapter (`OCR_PROVIDER=azure-di`): endpoint + key come from env/secret. F0 limits that the adapter must respect: 500 pages/month, **first 2 pages per request only**, 4 MB max, 1 TPS ([service limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0)); overage returns **HTTP 403 — never billed**. The adapter must map 403/4xx and low-confidence output to the **human-review path**, never to a fraud verdict (uncertain OCR must not become confident fraud evidence).
- **Do not enable paid add-ons** (e.g., high-resolution extraction) — they can bill even on F0.

### Step 6 — Private Blob storage (Gate G6)

```bash
az storage account create --name veripaydocs --resource-group veripay-demo-rg --location eastus \
  --sku Standard_LRS --kind StorageV2 --allow-blob-public-access false --min-tls-version TLS1_2 --https-only true
az storage container create --account-name veripaydocs --name invoices --auth-mode login   # private by default
```

**Managed-identity access (no connection strings in the app):**

```bash
PRINCIPAL=$(az containerapp show -n veripay-api -g veripay-demo-rg \
  --query "identity.principalId" -o tsv)   # after: az containerapp identity assign -n veripay-api -g veripay-demo-rg --system-assigned
az role assignment create --assignee $PRINCIPAL --role "Storage Blob Data Contributor" \
  --scope $(az storage account show -n veripaydocs -g veripay-demo-rg --query id -o tsv)
```

- Private by construction: `--allow-blob-public-access false` + no public container access; the app reads/writes with `DefaultAzureCredential` (system-assigned managed identity) through the existing `STORAGE_PROVIDER=azure-blob` adapter (local dev keeps MinIO).
- Cost: ≈ $0.04/mo at 2 GB of demo documents ([COST_ESTIMATE.md](./COST_ESTIMATE.md) §1). No lifecycle policy needed at demo scale.

### Step 7 — Static Web App Free + CORS wiring (Gate G7)

```bash
az staticwebapp create --name veripay-web --resource-group veripay-demo-rg \
  --source https://github.com/<owner>/<repo> --branch main \
  --app-location "frontend" --output-location "out" --login-with-github
# Default SKU is Free — never pass --sku Standard.
```

- The command registers a GitHub Actions workflow that runs `next build` (static export → `out/`) and deploys. **Free plan**: $0, 100 GB bandwidth/month (overage unavailable — fine for a demo), no SLA.
- **API wiring:** the frontend calls `https://<veripay-api-fqdn>` directly (bake it as `NEXT_PUBLIC_API_BASE_URL` in the SWA workflow or app config); the API's `CORS_ORIGINS` must list the SWA domain (`https://<swa-domain>`). Linked backends are deliberately **not** used (Standard plan required).
- Verify: open the SWA URL, log in, upload a sample invoice, confirm end-to-end: OCR → detection results → **human-review queue** for anything uncertain → no payment is ever authorized automatically.
- **Migrations:** with the PG firewall allowing the owner IP, run `alembic upgrade head` locally against `veripay-pg` (SSL required). Alternative: a one-off Container Apps Job — optional, skip for simplicity.

## 6. Never-do list (violates the budget or the product rules)

1. Do **not** remove or upgrade around the spending limit; do not upgrade the subscription type.
2. Do **not** create: Container Registry, App Service plans, SWA **Standard**, dedicated workload profiles, private endpoints, Cosmos DB free tier (would conflict with the one-free-tier-per-subscription pattern), VPN gateways, any Marketplace/offer that bypasses the spending limit (Entra ID P1/P2, support plans, third-party).
3. Do **not** set `--min-replicas 1` on the Container App; do not enable PG HA or storage autogrow; do not create PG with 128 GB storage; do not upgrade Document Intelligence to S0; do not enable DI add-ons.
4. Do **not** put real customer invoices or production bank-account data in the demo storage/database; the demo keeps the human-review and independent-verification flows intact — a cloud demo is not a compliance boundary.

## 7. Cost monitoring during the demo

- Day after provisioning and then 2×/week: **Cost Management → Cost analysis** filtered to `veripay-demo-rg` — expected ≈ $0.00–$0.05 total. Create a **budget of $5 with alerts at $1/$5** (free feature) on day one.
- Known early-warning signs: `Standard vCPU Active Usage` non-zero while the demo is idle → min-replicas > 0 (`az containerapp revision list … ` or scale tab); `Log Analytics` ingestion > a few hundred MB → lower log verbosity; any `Microsoft.DBforPostgreSQL` compute meter > $0 → free offer not active → tear down and switch to SQLite.

## 8. Full teardown

```bash
# 1. Optional: export anything worth keeping (demo data only)
#    pg_dump the DB and azcopy the invoices container if needed.

# 2. Delete EVERYTHING (CA env + app, Log Analytics workspace, PG server + backups,
#    storage account, Document Intelligence, SWA) in one command:
az group delete --name veripay-demo-rg --yes --no-wait

# 3. Verify nothing survived (must print an empty list):
az resource list --resource-group veripay-demo-rg -o table
az group exists --name veripay-demo-rg    # expect: false

# 4. GitHub-side cleanup (free, hygiene): delete repo secrets (PG password, DI key),
#    disable the api-image and SWA deploy workflows, delete the public GHCR package.

# 5. Verify spending stopped: next day, Cost Analysis shows no new meters;
#    az consumption usage list --top 5 shows only pre-teardown dates.
```

**Orphan risks checked:** the Log Analytics workspace is created inside `veripay-demo-rg` by the environment creation — covered by the group delete (verify via step 3); no ACR exists in this plan; no resource outside the group is created. If any *Dedicated plan* feature had been enabled (it must not be), the group delete still removes it — the stop-loss is that the spending limit caps total loss at the remaining credit.

## 9. What was NOT done in preparing this plan (honesty list)

- **Nothing was provisioned and no `az`/cloud command was executed** — no cloud access exists on this machine; every command is untested here.
- **PG free-offer eligibility on this specific student subscription is unverified** (portal-only check; G0 gates it). Community reports conflict; the official Azure for Students page lists the offer.
- **Whether Container Apps resource creation succeeds on an Azure for Students subscription is unverified** (no portal access). If creation is blocked, the API stays on the local SQLite/MinIO profile at $0 and the plan stops after Step 1.
- **F0 regional availability and the one-F0-per-subscription limit are unverified** — confirm in the creation blade (G5); fallback is keeping the local OCR provider.
- **Docker is unavailable locally and WSL is absent** — image builds happen in GitHub Actions only; the compose files in the repo were never and cannot be run on this machine.
- Prices/quotas verified 2026-10-17 (Retail Prices API + linked docs in [`COST_ESTIMATE.md`](./COST_ESTIMATE.md) Appendix A/B); they change — re-verify at the gate before each provisioning step.
