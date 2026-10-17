# =============================================================================
# VeriPay API — PROFILE A container image (python:3.12-slim, multi-stage).
#
# The entrypoint applies Alembic migrations BEFORE serving, so a fresh
# `docker compose up` yields a migrated, working database (this closes the
# documented Phase 1 gap where an unmigrated fresh DB 500'd on first auth).
#
# HONESTY NOTE: this file was authored on a machine without Docker/WSL, so it
# has never been built or run. Validate with `docker build` / `docker compose
# config` on a Docker-equipped machine (or CI) before the first real use.
# =============================================================================

# --- Stage 1: builder — install the package + dependencies into /opt/venv ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/veripay

# pyproject.toml declares no readme field, and apps/api/README.md does not
# exist — copying it would break the build.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Editable install: `import app` maps to /srv/veripay/app. The runtime stage
# recreates the exact same path, so the editable finder stays valid. The
# celery extra is baked in so the compose 'worker' profile can reuse THIS
# exact image (psycopg + pypdf are core dependencies in pyproject).
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -e ".[celery]"

# PROFILE A runtime requirement that is NOT (yet) declared in pyproject.toml
# (backend owner's file — promote it there, e.g. as an s3/minio extra, and
# drop this layer when that happens):
#   - boto3: MinIO/S3 storage adapter (app/adapters/storage/s3.py imports it
#     lazily at first use; without it a minio-configured API fails on upload).
RUN /opt/venv/bin/pip install "boto3>=1.34"

# --- Stage 2: runtime — non-root, migrate-then-serve --------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Same base image as the builder, so the venv's python symlinks/shebangs
# (/opt/venv/bin/* -> /usr/local/bin/python3.12) stay valid after the copy.
COPY --from=builder /opt/venv /opt/venv

# Non-root runtime user (created before the chown'd COPYs below).
RUN groupadd --system veripay \
    && useradd --system --gid veripay --create-home veripay

WORKDIR /srv/veripay

# The editable install maps `import app` to /srv/veripay/app — recreate the
# builder's path exactly. alembic/ + alembic.ini are needed at runtime by
# `alembic upgrade head`.
COPY --chown=veripay:veripay pyproject.toml alembic.ini ./
COPY --chown=veripay:veripay app ./app
COPY --chown=veripay:veripay alembic ./alembic
COPY --chown=veripay:veripay docker-entrypoint.sh ./

RUN chmod +x /srv/veripay/docker-entrypoint.sh \
    && chown -R veripay:veripay /srv/veripay

USER veripay

EXPOSE 8000

# Liveness: the public health endpoint (docs/API.md §4). Python stdlib only —
# python:3.12-slim ships neither curl nor wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

# Migrate, then exec the given command (uvicorn by default). `alembic upgrade
# head` is idempotent (alembic_version guards it), so restarts and multi-
# replica starts are safe — and every service sharing this image (the celery
# worker) gets the same migration barrier before it starts.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
