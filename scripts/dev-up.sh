#!/usr/bin/env bash
# VeriPay — start the local compose stack (PROFILE A: postgres, minio, api).
# Requires Docker. The web app does NOT run in compose: cd apps/web && npm run dev.
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
  2. Web (on the host, not compose): cd apps/web && npm run dev  ->  http://localhost:3000
  3. Optional worker profile:
     docker compose -f infrastructure/local/docker-compose.yml --profile worker up -d
  4. Stop everything: ./scripts/dev-down.sh
EOF
