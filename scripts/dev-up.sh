#!/usr/bin/env bash
# VeriPay — start the local compose stack (PROFILE A: postgres, minio, api, web).
# Requires Docker. The web app runs IN compose as a Next.js dev server; the
# production target remains the static export on Azure Static Web Apps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/infrastructure/local/docker-compose.yml"

docker compose -f "$COMPOSE_FILE" up -d --build

cat <<'EOF'

VeriPay local stack is up.
  API:        http://localhost:8000  (docs at /docs)
  MinIO:      http://localhost:9000  (console http://localhost:9001)
  PostgreSQL: localhost:5432  (veripay / veripay_dev)

Next steps:
  1. Copy .env.example to .env if you have not yet.
  2. Web (in compose): http://localhost:3000 — or on the host: cd apps/web && npm run dev
  3. Demo data: apps/api/.venv/Scripts/python.exe scripts/seed_demo.py
  4. Optional worker profile:
     docker compose -f infrastructure/local/docker-compose.yml --profile worker up -d
  5. Stop everything: ./scripts/dev-down.sh
EOF
