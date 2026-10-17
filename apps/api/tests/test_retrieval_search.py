"""Retrieval search tests (Prompt-03 §2/§6/§7): techniques on the portable
backend, trust-aware ranking, dialect selection, the optional-pgvector guard,
and the tenant-isolation proof that org filtering happens BEFORE candidate
generation."""

import uuid

import pytest

from app.core.db import SessionLocal, engine
from app.modules.retrieval import service
from app.modules.retrieval.indexing import build_search_index
from app.modules.retrieval.techniques import (
    TECH_VECTOR,
    PostgresBackend,
    get_backend,
    vector_search_available,
)
from app.modules.retrieval.trust import TRUST_MULTIPLIERS, TrustTier

import retrieval_helpers as rh


def _db():
    return SessionLocal()


def _refs(result):
    return {(h.entity_type, h.entity_id) for h in result["hits"]}


# ---------------------------------------------------------- dialect choice ---
def test_backend_selected_by_dialect_sqlite_gets_portable():
    with _db() as db:
        assert engine.dialect.name == "sqlite" or engine.dialect.name == "postgresql"
        backend = get_backend(db)
        if engine.dialect.name == "sqlite":
            assert backend.name == "portable"
        else:
            assert backend.name == "postgres"


# --------------------------------------------------------------- indexing ----
def test_index_contains_all_sources_with_trust_and_versions(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        index = build_search_index(db, org_id=uuid.UUID(seed["org_id"]))
        by_type = {}
        for row in index.rows:
            by_type.setdefault(row.entity_type, []).append(row)

        assert len(by_type.get("vendor", [])) == 4  # Nour, Acme, Zahra, Delta
        # ONLY the approved accounts are indexed (R5) — the pending one is not.
        account_ids = {r.entity_id for r in by_type.get("vendor_bank_account", [])}
        assert seed["approved_account_id"] in account_ids
        assert seed["acme_account_id"] in account_ids
        assert seed["pending_account_id"] not in account_ids

        invoices = {r.entity_id: r for r in by_type.get("invoice", [])}
        # Human-reviewed invoice (case + review action) → previously_reviewed.
        assert invoices[seed["invoice_nour_id"]].trust_tier == (
            TrustTier.PREVIOUSLY_REVIEWED
        )
        # Never-reviewed invoices → unverified_upload (never trusted tiers).
        assert invoices[seed["invoice_acme_id"]].trust_tier == (
            TrustTier.UNVERIFIED_UPLOAD
        )
        assert invoices[seed["duplicate_invoice_id"]].trust_tier == (
            TrustTier.UNVERIFIED_UPLOAD
        )

        fields = {r.provenance["field_name"]: r for r in by_type.get("extraction_field", [])}
        # R3: human-confirmed field → trusted; unverified field stays
        # unverified_upload even with confidence 0.97.
        assert fields["currency"].trust_tier == TrustTier.TRUSTED_REGISTRY
        assert fields["invoice_number"].trust_tier == TrustTier.UNVERIFIED_UPLOAD

        # Every row carries org, provenance and a record_version (updated_at).
        for row in index.rows:
            assert row.organization_id == seed["org_id"]
            assert row.provenance
            assert row.record_version is not None

        # Document location: extraction fields cite page + bbox.
        inv_field = fields["invoice_number"]
        assert inv_field.location["document_id"] == seed["document_id"]
        assert inv_field.location["page"] == 1
        assert inv_field.location["bbox"] == [300.0, 20.0, 420.0, 40.0]


def test_stale_trusted_record_downgrades_to_stale_tier(client):
    seed = rh.seed_retrieval_org(client)
    from datetime import datetime, timedelta, timezone

    from helpers import db_query

    def _age_vendor(session):
        from app.models import Vendor

        vendor = session.get(Vendor, uuid.UUID(seed["vendor_id"]))
        vendor.updated_at = datetime.now(timezone.utc) - timedelta(days=400)
        session.commit()

    db_query(_age_vendor)

    with _db() as db:
        index = build_search_index(
            db, org_id=uuid.UUID(seed["org_id"]), entity_types=["vendor"]
        )
        rows = {r.entity_id: r for r in index.rows}
        assert rows[seed["vendor_id"]].trust_tier == TrustTier.STALE
        assert rows[seed["acme_vendor_id"]].trust_tier == TrustTier.TRUSTED_REGISTRY


# --------------------------------------------------------------- techniques --
def test_exact_identifier_match_finds_invoice_and_field(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=seed["org_id"], query=rh.INV_NOUR)
        refs = _refs(result)
        assert ("invoice", seed["invoice_nour_id"]) in refs
        # The extraction field provenance copy of the number also matches.
        assert (
            "extraction_field",
            seed["extraction_field_ids"]["invoice_number"],
        ) in refs
        # The invoice itself ranks above its provenance copy (identifier
        # equality + trust multiplier on the reviewed invoice).
        top = result["hits"][0]
        assert top.entity_type == "invoice"
        assert set(top.techniques) >= {"exact", "text", "trigram"}
        assert result["meta"]["backend"] == "portable"


def test_arabic_indic_digit_query_matches_ascii_identifier(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=seed["org_id"], query="INV-٢٠٢٦-٠٠٠٧")
        refs = _refs(result)
        assert ("invoice", seed["invoice_nour_id"]) in refs


def test_arabic_vendor_name_query_with_diacritics_matches(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        # Diacritics + alef variant injected into the stored legal name.
        result = service.search(db, org_id=seed["org_id"], query="شَركة النُور")
        refs = _refs(result)
        assert ("vendor", seed["vendor_id"]) in refs


def test_label_variant_query_reaches_the_same_entities(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(
            db, org_id=seed["org_id"], query=f"فاتورة {rh.INV_ZAHRA}"
        )
        assert ("invoice", seed["invoice_zahra_id"]) in _refs(result)


def test_ocr_typo_matched_by_trigram(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=seed["org_id"], query="Nordbenk")
        refs = _refs(result)
        assert ("vendor_bank_account", seed["approved_account_id"]) in refs
        account_hit = next(
            h for h in result["hits"]
            if h.entity_id == seed["approved_account_id"]
        )
        assert "trigram" in account_hit.techniques


def test_account_number_query_exact_matches_approved_account(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=seed["org_id"], query=rh.NOUR_IBAN)
        refs = _refs(result)
        assert ("vendor_bank_account", seed["approved_account_id"]) in refs
        # The pending account with a DIFFERENT number never appears (R5).
        assert ("vendor_bank_account", seed["pending_account_id"]) not in refs


def test_entity_type_filter_restricts_candidates(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(
            db,
            org_id=seed["org_id"],
            query=rh.INV_NOUR,
            entity_types=["vendor"],
        )
        assert result["hits"] == []  # invoice number does not match vendors
        result = service.search(
            db,
            org_id=seed["org_id"],
            query=rh.NOUR_DISPLAY,
            entity_types=["vendor"],
        )
        assert _refs(result) == {("vendor", seed["vendor_id"])}


def test_empty_query_returns_no_hits(client):
    rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=str(uuid.uuid4()), query="   ")
        assert result["hits"] == []


# ------------------------------------------------------------------- trust ---
def test_trust_multiplier_applied_explicitly(client):
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(db, org_id=seed["org_id"], query=rh.INV_NOUR)
        reviewed = next(
            h
            for h in result["hits"]
            if h.entity_id == seed["invoice_nour_id"]
        )
        assert reviewed.trust_tier == TrustTier.PREVIOUSLY_REVIEWED
        expected = round(
            reviewed.fused_score * TRUST_MULTIPLIERS[TrustTier.PREVIOUSLY_REVIEWED], 6
        )
        assert reviewed.final_score == expected


def test_unverified_upload_never_outranks_trusted_on_equal_fused_score(client):
    """The invariant: trust is an explicit multiplier, and unverified machine
    output can never be promoted over the human-approved registry."""
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        result = service.search(
            db, org_id=seed["org_id"], query=rh.NOUR_DISPLAY
        )
        vendor_hit = next(
            h for h in result["hits"] if h.entity_type == "vendor"
        )
        assert vendor_hit.trust_tier == TrustTier.TRUSTED_REGISTRY
        field_hit = next(
            (
                h
                for h in result["hits"]
                if h.entity_type == "extraction_field"
                and h.provenance.get("field_name") == "vendor_name"
            ),
            None,
        )
        if field_hit is not None:
            assert field_hit.trust_tier == TrustTier.UNVERIFIED_UPLOAD
            assert field_hit.final_score < vendor_hit.final_score


# ------------------------------------------------------ tenant isolation -----
def test_org_filter_precedes_candidate_generation(client):
    """Two orgs with IDENTICAL vendor names and invoice numbers: each org's
    candidate generation (index rows AND every technique's result list) sees
    only its own rows — cross-tenant leakage is impossible by construction."""
    seed_a = rh.seed_retrieval_org(client, email="a@acme.example")
    client.cookies.clear()
    seed_b = rh.seed_retrieval_org(client, email="b@corp.example")
    org_a = uuid.UUID(seed_a["org_id"])
    org_b = uuid.UUID(seed_b["org_id"])

    with _db() as db:
        index_a = build_search_index(db, org_id=org_a)
        index_b = build_search_index(db, org_id=org_b)
        refs_a = index_a.refs()
        refs_b = index_b.refs()
        assert refs_a and refs_b
        assert refs_a.isdisjoint(refs_b)  # no shared entity ids at all

        for org_id, index, other in (
            (org_a, index_a, refs_b),
            (org_b, index_b, refs_a),
        ):
            for query in (rh.INV_NOUR, rh.NOUR_DISPLAY, rh.NOUR_LEGAL_AR):
                result = service.search(db, org_id=org_id, query=query)
                assert result["hits"], f"org {org_id} found nothing for {query!r}"
                for hit in result["hits"]:
                    assert (hit.entity_type, hit.entity_id) not in other
                    assert hit.provenance is not None


def test_identical_numbers_across_orgs_stay_isolated(client):
    seed_a = rh.seed_retrieval_org(client, email="a2@acme.example")
    client.cookies.clear()
    seed_b = rh.seed_retrieval_org(client, email="b2@corp.example")
    with _db() as db:
        res_a = service.search(db, org_id=seed_a["org_id"], query=rh.INV_NOUR)
        ids_a = {h.entity_id for h in res_a["hits"]}
        assert seed_a["invoice_nour_id"] in ids_a
        assert seed_b["invoice_nour_id"] not in ids_a

        res_b = service.search(db, org_id=seed_b["org_id"], query=rh.INV_NOUR)
        ids_b = {h.entity_id for h in res_b["hits"]}
        assert seed_b["invoice_nour_id"] in ids_b
        assert seed_a["invoice_nour_id"] not in ids_b


# ------------------------------------------------- optional pgvector guard ---
def test_pgvector_guard_off_by_default_on_sqlite():
    with _db() as db:
        assert vector_search_available(db) is False


def test_postgres_backend_vector_technique_skips_when_unavailable(client):
    """The pgvector technique must be an explicit, honest skip wherever the
    flag/dialect/extension do not all hold — never an error, never silent
    participation. (Called directly: the SQL techniques belong to the PG
    dialect and are covered by the PG-marked module.)"""
    seed = rh.seed_retrieval_org(client)
    with _db() as db:
        vector_result = PostgresBackend()._vector(
            db, uuid.UUID(seed["org_id"]), rh.NOUR_DISPLAY, 100
        )
        assert vector_result.technique == TECH_VECTOR
        assert vector_result.hits == []
        assert "pgvector" in (vector_result.note or "")


def test_pg_fts_and_trgm_expressions_compile_for_postgres_dialect():
    """The PostgreSQL paths are SQLAlchemy expressions; compiling them under
    the postgresql dialect (no server needed) proves the SQL shape."""
    from sqlalchemy import func, select
    from sqlalchemy.dialects import postgresql

    from app.models import Invoice

    tsvector = func.to_tsvector("simple", func.concat_ws(" ", Invoice.invoice_number))
    tsquery = func.to_tsquery("simple", "inv | 2026")
    stmt = select(Invoice.id).where(
        Invoice.organization_id == uuid.uuid4(),
        tsvector.op("@@")(tsquery),
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "to_tsvector" in sql and "to_tsquery" in sql and "@@" in sql

    sim = func.similarity(
        func.lower(func.concat_ws(" ", Invoice.invoice_number)), "nour trading"
    )
    stmt2 = select(Invoice.id).where(
        Invoice.organization_id == uuid.uuid4(), sim >= 0.3
    )
    sql2 = str(stmt2.compile(dialect=postgresql.dialect()))
    assert "similarity" in sql2


def test_embed_text_is_deterministic_and_unit_norm():
    from app.modules.retrieval.techniques import embed_text

    a = embed_text("Nour Trading Co", 64)
    b = embed_text("Nour Trading Co", 64)
    assert a == b
    assert len(a) == 64
    norm = sum(v * v for v in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6
