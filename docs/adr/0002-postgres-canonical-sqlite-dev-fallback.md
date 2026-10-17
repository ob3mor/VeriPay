# ADR 0002 — PostgreSQL canonical, SQLite dev/test fallback

Status: Accepted · 2026-10-17

## Context

PostgreSQL is the production database for PROFILE A and PROFILE B. The development machine has **no Docker and no WSL**, so a local PostgreSQL server is not guaranteed, while tests must run on this machine today (Windows, Python 3.12). Carrying two schema definitions (one per dialect) is a known maintenance trap.

## Decision

- PostgreSQL remains **canonical** for all migrations and all deployed profiles; Alembic is authored against PostgreSQL only.
- Models use **SQLAlchemy 2 portable types exclusively**: `sa.Uuid`, `sa.JSON`, `DateTime(timezone=True)`, `Numeric`. No native enums, no array columns, no PG-only operators or functions, no JSON-path SQL — statuses are `String(32)` validated by Python enums; JSON is read/written whole.
- Tests and no-Docker local dev build the schema from `Base.metadata.create_all` on **SQLite**; Alembic runs against SQLite **only** as a scratch-file executability smoke test (it catches model/migration drift that offline `--sql` cannot), never as a test database.
- Features portable to both dialects are allowed where needed (e.g. partial unique indexes, CHECK constraints).
- On this machine, migrations are validated **offline** (`alembic upgrade head --sql`); the first live `upgrade head` against PostgreSQL happens under PROFILE A/CI.

## Consequences

**Positive:** zero-dependency test runs on any machine; one model set to maintain; migration intent still reviewable as SQL before it ever touches PostgreSQL.

**Negative:** dialect drift is a real risk (transaction/isolation semantics, collation, JSON storage). Mitigations: the type conventions above are enforced in review; the tenant-isolation suite must run on PostgreSQL under PROFILE A/CI before any release; `audit_logs`/timestamp behavior must not rely on server-side date arithmetic; migrations are additionally smoke-tested against a scratch SQLite file; and partial unique indexes must declare **both** `postgresql_where` and `sqlite_where` — with `postgresql_where` alone the predicate silently disappears on SQLite and the index becomes full (design-reviewer-verified: it broke the `is_current` history flow on SQLAlchemy 2.1.5 / SQLite 3.42.0).
