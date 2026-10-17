# VeriPay — start the local compose stack (PROFILE A: postgres, minio, api, web).
# Requires Docker. The web app runs IN compose as a Next.js dev server; the
# production target remains the static export on Azure Static Web Apps.

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "..\infrastructure\local\docker-compose.yml"

docker compose -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "VeriPay local stack is up."
Write-Host "  API:        http://localhost:8000  (docs at /docs)"
Write-Host "  MinIO:      http://localhost:9000  (console http://localhost:9001)"
Write-Host "  PostgreSQL: localhost:5432  (veripay / veripay_dev)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Copy .env.example to .env if you have not yet."
Write-Host "  2. Web (in compose): http://localhost:3000 — or on the host: cd apps/web; npm run dev"
Write-Host "  3. Demo data: apps\api\.venv\Scripts\python.exe scripts\seed_demo.py"
Write-Host "  4. Optional worker profile: docker compose -f infrastructure/local/docker-compose.yml --profile worker up -d"
Write-Host "  5. Stop everything: ./scripts/dev-down.ps1"
