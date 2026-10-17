# VeriPay — start the local compose stack (PROFILE A: postgres, minio, api).
# Requires Docker. The web app does NOT run in compose: cd apps/web; npm run dev.

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
Write-Host "  2. Web (on the host, not compose): cd apps/web; npm run dev  ->  http://localhost:3000"
Write-Host "  3. Optional worker profile: docker compose -f infrastructure/local/docker-compose.yml --profile worker up -d"
Write-Host "  4. Stop everything: ./scripts/dev-down.ps1"
