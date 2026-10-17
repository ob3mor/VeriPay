"""retrieval: OPTIONAL pgvector enablement (Prompt-03 §2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

pgvector is OPTIONAL and NEVER required. This migration is a documented NO-OP
unless BOTH of these hold at migration runtime:

1. the live dialect is PostgreSQL (SQLite dev/test/CI-scratch: no-op), and
2. ``VERIPAY_RETRIEVAL_PGVECTOR_ENABLED`` is truthy (default: off).

All DDL is raw SQL via ``exec_driver_sql`` — the ``pgvector`` Python package
is NOT required anywhere (the app's vector path in
``app/modules/retrieval/techniques.py`` likewise queries through raw SQL).

When enabled it creates ONLY:
- ``CREATE EXTENSION IF NOT EXISTS vector`` (free PostgreSQL extension — no
  paid service), and
- the ``retrieval_embeddings`` companion table (org-scoped entity → vector),
  deliberately NOT declared in ``app/models`` so the default schema and the
  ``alembic check`` drift gate stay untouched. On a pgvector-enabled
  deployment that companion table is managed by THIS migration only.

Default deployments and CI (flag off) upgrade through this revision without
any schema change. The retrieval module degrades gracefully when the
extension/table are absent (techniques.py ``vector_search_available``).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pgvector_enabled() -> bool:
    if not get_settings().retrieval_pgvector_enabled:
        return False
    bind = op.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _pgvector_enabled():
        # Deliberate no-op (see module docstring): pgvector stays optional and
        # the canonical schema is unchanged on SQLite and on flag-off PG.
        return
    dim = get_settings().retrieval_embedding_dim
    # op.execute works in BOTH modes: online it runs, offline it emits the
    # literal SQL into the --sql stream (a flag-on operator can preview it).
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE IF NOT EXISTS retrieval_embeddings (
                organization_id uuid NOT NULL,
                entity_type varchar(64) NOT NULL,
                entity_id uuid NOT NULL,
                embedding vector({dim}) NOT NULL,
                record_version timestamptz,
                PRIMARY KEY (organization_id, entity_type, entity_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_retrieval_embeddings_hnsw
            ON retrieval_embeddings USING hnsw (embedding vector_cosine_ops)
            """
        )
    )


def downgrade() -> None:
    # Symmetric with upgrade(): only touches anything when the flag says this
    # deployment owns the pgvector objects; otherwise nothing was created.
    if not _pgvector_enabled():
        return
    op.execute(sa.text("DROP INDEX IF EXISTS ix_retrieval_embeddings_hnsw"))
    op.execute(sa.text("DROP TABLE IF EXISTS retrieval_embeddings"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
