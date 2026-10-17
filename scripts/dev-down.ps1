# VeriPay — stop the local compose stack. Data volumes (postgres, minio) are kept.

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "..\infrastructure\local\docker-compose.yml"

docker compose -f $composeFile down
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "VeriPay local stack stopped (volumes kept)."
Write-Host "Wipe data as well: docker compose -f infrastructure/local/docker-compose.yml down -v"
