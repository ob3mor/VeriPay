"""PostgreSQL-conditional retrieval tests (Prompt-03 §2/§7).

These run ONLY against a live PostgreSQL engine — the local dev machine has
none (no Docker/WSL), so they skip cleanly here and execute on the CI
workflow's PostgreSQL 16 leg (conftest honors a preset VERIPAY_DATABASE_URL).

Everything the portable suite asserts locally is re-verified here against the
canonical dialect: the full-text (to_tsvector) and pg_trgm technique branches
execute for real, and the org filter is proven to scope candidate generation
on PostgreSQL too.
"""

import uuid

import pytest

from app.core.db import SessionLocal, engine

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        engine.dialect.name != "postgresql",
        reason=(
            "requires a live PostgreSQL engine — runs on the CI PostgreSQL "
            "leg; the no-Docker dev machine runs SQLite so this skips"
        ),
    ),
]

import retrieval_helpers as rh  # noqa: E402  (after pytestmark for clarity)
from app.modules.retrieval import service  # noqa: E402
from app.modules.retrieval.indexing import build_search_index  # noqa: E402
from app.modules.retrieval.techniques import (  # noqa: E402
    TECH_TRIGRAM,
    TECH_VECTOR,
    PostgresBackend,
    get_backend,
    vector_search_available,
)


def test_backend_is_postgres_and_search_works_end_to_end(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        assert get_backend(db).name == "postgres"
        result = service.search(db, org_id=seed["org_id"], query=rh.INV_NOUR)
        assert result["meta"]["backend"] == "postgres"
        refs = {(h.entity_type, h.entity_id) for h in result["hits"]}
        assert ("invoice", seed["invoice_nour_id"]) in refs
        # The trust tiers behave identically on the canonical dialect.
        top = result["hits"][0]
        assert top.entity_type == "invoice"


def test_fulltext_branch_matches_on_postgres(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        backend = PostgresBackend()
        index = build_search_index(db, org_id=uuid.UUID(seed["org_id"]))
        results = backend.run(
            db,
            org_id=uuid.UUID(seed["org_id"]),
            query=f"{rh.NOUR_DISPLAY} {rh.INV_NOUR}",
            index=index,
        )
        text = next(r for r in results if r.technique == "text")
        assert text.hits, "to_tsvector branch must match on PostgreSQL"
        assert text.note is None


def test_trigram_branch_either_runs_or_reports_extension_missing(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        backend = PostgresBackend()
        index = build_search_index(db, org_id=uuid.UUID(seed["org_id"]))
        results = backend.run(
            db,
            org_id=uuid.UUID(seed["org_id"]),
            query=rh.NOUR_DISPLAY,
            index=index,
        )
        trigram = next(r for r in results if r.technique == TECH_TRIGRAM)
        if trigram.note is None:
            # pg_trgm available (CI image with the extension installed).
            assert trigram.hits
            assert all(h.score >= 0.3 for h in trigram.hits)
        else:
            # Plain postgres:16 has no pg_trgm — the explicit skip note.
            assert "pg_trgm" in trigram.note
            assert trigram.hits == []


def test_vector_technique_skips_while_optional_flag_is_off(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        assert vector_search_available(db) is False
        backend = PostgresBackend()
        results = backend.run(
            db,
            org_id=uuid.UUID(seed["org_id"]),
            query=rh.NOUR_DISPLAY,
            index=build_search_index(db, org_id=uuid.UUID(seed["org_id"])),
        )
        vector = next(r for r in results if r.technique == TECH_VECTOR)
        assert vector.hits == []
        assert "pgvector" in (vector.note or "")


def test_org_filter_scopes_candidates_on_postgres(client):
    """The leakage proof on the canonical dialect: two orgs with identical
    data; every technique branch carries the org predicate."""
    seed_a = rh.seed_retrieval_org(client, email="pga@acme.example")
    client.cookies.clear()
    seed_b = rh.seed_retrieval_org(client, email="pgb@corp.example")
    with SessionLocal() as db:
        refs_a = build_search_index(db, org_id=uuid.UUID(seed_a["org_id"])).refs()
        refs_b = build_search_index(db, org_id=uuid.UUID(seed_b["org_id"])).refs()
        assert refs_a.isdisjoint(refs_b)
        for org_id, other in (
            (seed_a["org_id"], refs_b),
            (seed_b["org_id"], refs_a),
        ):
            for query in (rh.INV_NOUR, rh.NOUR_DISPLAY):
                result = service.search(db, org_id=org_id, query=query)
                for hit in result["hits"]:
                    assert (hit.entity_type, hit.entity_id) not in other
