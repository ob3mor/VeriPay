#!/bin/sh
# VeriPay API container entrypoint: apply migrations, then exec the command.
#
# `alembic upgrade head` is idempotent (alembic_version guards it), so restarts
# and multi-replica starts are safe. set -e: a failed migration must never
# boot a half-migrated application.
set -e

echo "[veripay] applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[veripay] schema up to date — starting: $*"
exec "$@"
