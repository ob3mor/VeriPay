#!/usr/bin/env bash
# VeriPay — stop the local compose stack. Data volumes (postgres, minio) are kept.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/infrastructure/local/docker-compose.yml"

docker compose -f "$COMPOSE_FILE" down

cat <<'EOF'

VeriPay local stack stopped (volumes kept).
Wipe data as well: docker compose -f infrastructure/local/docker-compose.yml down -v
EOF
