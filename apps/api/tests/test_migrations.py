"""Alembic executability on a scratch SQLite file (docs/DATABASE.md §17):
upgrade head → all 20 tables exist; downgrade base → clean. Previously this
check only ran in the never-executed CI workflow; now the suite runs it on
every test pass. It validates migration EXECUTABILITY only — it is not a
PostgreSQL substitute (docs/ARCHITECTURE.md §6)."""

import sqlalchemy
from alembic import command
from alembic.config import Config

from app.core.config import get_settings

EXPECTED_TABLES = {
    "organizations",
    "users",
    "sessions",
    "vendors",
    "vendor_authorized_contacts",
    "vendor_bank_accounts",
    "bank_account_change_requests",
    "purchase_orders",
    "invoices",
    "invoice_line_items",
    "documents",
    "extraction_results",
    "extraction_fields",
    "fraud_assessments",
    "fraud_findings",
    "evidence_matches",
    "investigation_cases",
    "review_actions",
    "processing_jobs",
    "audit_events",
}


def _tables(url: str) -> set[str]:
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            return {row[0] for row in rows}
    finally:
        engine.dispose()


def test_migrations_upgrade_head_and_downgrade_base_on_scratch_sqlite(tmp_path):
    settings = get_settings()
    scratch_url = "sqlite:///" + str(tmp_path / "scratch.db").replace("\\", "/")
    original_url = settings.database_url
    settings.database_url = scratch_url  # alembic/env.py reads get_settings()
    try:
        config = Config(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")

        tables = _tables(scratch_url)
        assert "alembic_version" in tables
        missing = EXPECTED_TABLES - tables
        assert missing == set(), f"migration is missing tables: {sorted(missing)}"

        command.downgrade(config, "base")
        remaining = _tables(scratch_url)
        assert EXPECTED_TABLES & remaining == set(), (
            f"downgrade left tables behind: {sorted(EXPECTED_TABLES & remaining)}"
        )
    finally:
        settings.database_url = original_url
