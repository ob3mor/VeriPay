"""EVC (Prompt-04): review_actions.case_id becomes nullable.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17

The EVC human-override flow records every finding disposition / evidence-
match review as a ``review_actions`` row WITH its mandatory reason. Such an
override can happen outside any case context (e.g. dispositioning a
duplicate_candidate on an invoice whose assessment never reached critical),
so ``case_id`` becomes nullable — NULL means "override record written without
a case"; the payload column names the exact overridden entity.

The model change lives in ``app/models/cases.py`` (ReviewAction.case_id);
this migration brings PostgreSQL (canonical) in line. Tests create the
schema from ``Base.metadata.create_all`` and never run Alembic; on SQLite
(batch mode) this is also executable, keeping the CI scratch-SQLite gate
green. Both batch operations pass an explicit ``copy_from`` table so the
offline ``--sql`` emission works without live reflection.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _review_actions_table(metadata: sa.MetaData, *, case_id_nullable: bool) -> sa.Table:
    """The complete review_actions definition (columns + FKs + indexes) as it
    exists at 0002 (case_id NOT NULL) or 0003 (nullable). Batch mode recreates
    the table from ``copy_from`` + the batch operations, so the definition
    must carry EVERYTHING — a columns-only copy_from would silently drop the
    indexes and foreign keys (alembic check catches exactly that)."""
    return sa.Table(
        "review_actions",
        metadata,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "case_id", sa.Uuid(), nullable=case_id_nullable
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        # server_default MUST be carried here: SQLite batch mode recreates the
        # table from this definition, and dropping the defaults made every
        # INSERT without explicit timestamps fail with NOT NULL (seed/production
        # code relies on them — caught live by scripts/seed_demo.py).
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_review_actions_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_review_actions_actor_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["investigation_cases.id"],
            name="fk_review_actions_case_id_investigation_cases",
        ),
        sa.Index("ix_ra_org_case", "organization_id", "case_id"),
        sa.Index("ix_review_actions_organization_id", "organization_id"),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        "review_actions", copy_from=_review_actions_table(sa.MetaData(), case_id_nullable=False)
    ) as batch:
        batch.alter_column("case_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    # Re-asserting NOT NULL requires that no case-less override rows exist;
    # this is a dev-stage schema, so they are removed explicitly here.
    op.execute("DELETE FROM review_actions WHERE case_id IS NULL")
    with op.batch_alter_table(
        "review_actions", copy_from=_review_actions_table(sa.MetaData(), case_id_nullable=True)
    ) as batch:
        batch.alter_column("case_id", existing_type=sa.Uuid(), nullable=False)
