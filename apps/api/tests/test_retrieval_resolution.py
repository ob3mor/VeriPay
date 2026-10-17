"""Vendor entity resolution tests (Prompt-03 §4): Arabic/English variants,
abbreviations, OCR-error tolerance — candidates with scores, and the hard
rule that NOTHING is ever merged automatically."""

import uuid

from app.core.db import SessionLocal
from app.modules.retrieval import service

import retrieval_helpers as rh


def _vendor_count(org_id: str) -> int:
    def _count(session):
        from sqlalchemy import select

        from app.models import Vendor

        return len(
            session.scalars(
                select(Vendor).where(
                    Vendor.organization_id == uuid.UUID(org_id)
                )
            )
            .unique()
            .all()
        )

    from helpers import db_query

    return db_query(_count)


def _invoice_vendor_id(org_id: str, invoice_id: str):
    def _get(session):
        from app.models import Invoice

        invoice = session.get(Invoice, uuid.UUID(invoice_id))
        assert invoice is not None
        assert str(invoice.organization_id) == org_id
        return str(invoice.vendor_id)

    from helpers import db_query

    return db_query(_get)


def test_exact_name_candidate_scores_one(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        candidates = service.suggest_vendor_resolutions(
            db, org_id=seed["org_id"], name=rh.NOUR_DISPLAY
        )
        assert candidates
        top = candidates[0]
        assert top.vendor_id == seed["vendor_id"]
        assert top.score == 1.0


def test_abbreviation_and_legal_form_variants_match(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        for variant in ("Nour Trading Company", "Nour Trading", "شركة Nour"):
            candidates = service.suggest_vendor_resolutions(
                db, org_id=seed["org_id"], name=variant
            )
            assert candidates, f"no candidate for {variant!r}"
            assert candidates[0].vendor_id == seed["vendor_id"], variant
            assert candidates[0].score >= 0.9, (variant, candidates[0].score)


def test_arabic_legal_name_query_matches_via_legal_surface(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        candidates = service.suggest_vendor_resolutions(
            db, org_id=seed["org_id"], name=rh.NOUR_LEGAL_AR
        )
        assert candidates
        assert candidates[0].vendor_id == seed["vendor_id"]


def test_ocr_error_tolerance_via_trigram(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        candidates = service.suggest_vendor_resolutions(
            db, org_id=seed["org_id"], name="Nour Trading Comapny"  # mis-OCR
        )
        assert candidates
        top = candidates[0]
        assert top.vendor_id == seed["vendor_id"]
        assert any("trigram" in via for via in top.matched_via)


def test_common_name_differences_via_token_overlap(client):
    """Token-SET equality with different word order — a common real-world
    name difference (legal-form words are stripped on both sides first)."""
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        candidates = service.suggest_vendor_resolutions(
            db, org_id=seed["org_id"], name="Industrial Acme"
        )
        assert candidates
        assert candidates[0].vendor_id == seed["acme_vendor_id"]
        assert any("token overlap" in via for via in candidates[0].matched_via)


def test_ocr_variant_provenance_listed(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        candidates = service.suggest_vendor_resolutions(
            db, org_id=seed["org_id"], name="Nour Trading"
        )
        top = candidates[0]
        # The extraction field's OCR variant ("Nour Trading Co", no dot) is
        # bound to the vendor via the invoice — provenance, citable.
        assert "Nour Trading Co" in top.ocr_variants
        assert top.ocr_variants


def test_unrelated_name_yields_no_candidates_on_seeded_org(client):
    """Names sharing no token (and no substring) with any vendor produce no
    candidates above the floor. (Sharing a generic word like 'Industrial'
    legitimately yields a low-confidence candidate — a human confirms.)"""
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        for garbage in ("Zzzqwerxvy Qqwxvb", "Flopqing Bantamworks"):
            candidates = service.suggest_vendor_resolutions(
                db, org_id=seed["org_id"], name=garbage
            )
            assert candidates == [], garbage


def test_candidates_are_org_scoped(client):
    seed_a = rh.seed_retrieval_org(client, email="a3@acme.example")
    client.cookies.clear()
    seed_b = rh.seed_retrieval_org(client, email="b3@corp.example")
    with SessionLocal() as db:
        # Same printed name, two orgs: each org resolves to its own vendor.
        for seed in (seed_a, seed_b):
            candidates = service.suggest_vendor_resolutions(
                db, org_id=seed["org_id"], name=rh.NOUR_DISPLAY
            )
            assert {c.vendor_id for c in candidates} == {seed["vendor_id"]}


def test_resolution_never_merges_or_writes(client):
    """The invariant: candidates are read-only; the human confirm flow
    (POST /invoices/{id}/resolve-vendor) remains the only merge path."""
    seed = rh.seed_retrieval_org(client)
    count_before = _vendor_count(seed["org_id"])
    vendor_before = _invoice_vendor_id(seed["org_id"], seed["invoice_nour_id"])

    with SessionLocal() as db:
        db.commit()  # ensure a clean boundary
        for name in (
            rh.NOUR_DISPLAY,
            "Nour Trading Company",
            "Nour Trading Comapny",
        ):
            candidates = service.suggest_vendor_resolutions(
                db, org_id=seed["org_id"], name=name
            )
            assert candidates
        db.rollback()

    assert _vendor_count(seed["org_id"]) == count_before
    assert _invoice_vendor_id(seed["org_id"], seed["invoice_nour_id"]) == vendor_before
    assert vendor_before == seed["vendor_id"]
