# VeriPay API — PROFILE A container (python:3.12-slim)
# The entrypoint applies Alembic migrations BEFORE serving, so a fresh
# `docker compose up` produces a working database (the Phase 1 gap: nothing
# migrated automatically and auth 500'd on an unmigrated DB).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/veripay

# Install the package first so dependency layers cache independently of code.
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .

EXPOSE 8000

# Migrate, then serve. `alembic upgrade head` is idempotent (alembic_version
# guards it), so restarts and multi-replica starts are safe.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
