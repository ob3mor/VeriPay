"""Evidence graph tests (Prompt-03 §5): the five relationship families, gaps
(R4: missing is never fraud — severity capped at medium), and structured data
disagreements. All reads org-scoped."""

import uuid

import pytest

from app.core.db import SessionLocal
from app.modules.procurement import service as procurement_service
from app.modules.retrieval.graph import (
    GAP_CONTRADICTION,
    GAP_MISSING,
    invoice_evidence_graph,
    vendor_evidence_graph,
)

import retrieval_helpers as rh


def _graph(seed, invoice_id):
    with SessionLocal() as db:
        invoice = procurement_service.get_invoice(
            db, org_id=uuid.UUID(seed["org_id"]), invoice_id=uuid.UUID(invoice_id)
        )
        return invoice_evidence_graph(
            db, org_id=uuid.UUID(seed["org_id"]), invoice=invoice
        )


def test_vendor_to_invoices_relationship(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_nour_id"])
    assert graph.vendor is not None
    assert str(graph.vendor.id) == seed["vendor_id"]
    invoice_ids = {str(i.id) for i in graph.historical_invoices}
    assert seed["invoice_nour_id"] not in invoice_ids  # self excluded
    assert seed["duplicate_invoice_id"] in invoice_ids
    assert seed["invoice_shadow_id"] in invoice_ids


def test_vendor_to_approved_accounts_only(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_nour_id"])
    account_ids = {str(a.id) for a in graph.approved_accounts}
    assert seed["approved_account_id"] in account_ids
    assert seed["pending_account_id"] not in account_ids  # R5: approved only


def test_invoice_to_purchase_order_via_fk_and_via_printed_reference(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_nour_id"])
    assert graph.purchase_order is not None
    assert str(graph.purchase_order.id) == seed["po_nour_id"]
    assert graph.printed_po_reference == rh.PO_NOUR
    assert graph.po_by_reference is not None


def test_po_reference_resolves_without_fk(client):
    """An invoice whose PO is only *printed* (extraction po_reference), not
    FK-linked, still reaches the org's PO registry."""
    seed = rh.seed_retrieval_org(client)

    from helpers import db_query

    def _create(session):
        from app.models import Invoice

        row = Invoice(
            organization_id=uuid.UUID(seed["org_id"]),
            vendor_id=uuid.UUID(seed["vendor_id"]),
            invoice_number="INV-REF-ONLY",
            source_document_id=uuid.UUID(seed["document_id"]),
        )
        session.add(row)
        session.commit()
        return str(row.id)

    invoice_id = db_query(_create)
    graph = _graph(seed, invoice_id)
    assert graph.purchase_order is None
    assert graph.printed_po_reference == rh.PO_NOUR
    assert graph.po_by_reference is not None
    assert str(graph.po_by_reference.id) == seed["po_nour_id"]


def test_vendor_verification_events_include_account_and_review_records(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        from app.modules.vendors import service as vendors_service

        vendor = vendors_service.get_vendor(
            db, org_id=uuid.UUID(seed["org_id"]), vendor_id=uuid.UUID(seed["vendor_id"])
        )
        graph = vendor_evidence_graph(db, org_id=uuid.UUID(seed["org_id"]), vendor=vendor)
    kinds = {e["type"] for e in graph.verification_events}
    assert "bank_account_approved" in kinds
    approved = next(
        e for e in graph.verification_events if e["type"] == "bank_account_approved"
    )
    # The independent verification record is citable (R5 provenance).
    assert approved["verification_method"] == "callback_to_known_contact"
    assert approved["verification_reference"] == "ticket-77"
    assert approved["verified_by"] is not None


def test_invoice_to_historical_and_evidence_matches(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["duplicate_invoice_id"])
    match_pairs = [
        (str(m.source_entity_id), str(m.target_entity_id), m.match_kind)
        for m in graph.evidence_matches
    ]
    assert match_pairs, "duplicate number must produce an evidence match"
    assert any(
        seed["invoice_nour_id"] in pair[:2] for pair in match_pairs
    )


def test_missing_relationships_are_structured_and_capped(client):
    """R4: absence is typed missing_evidence-style, severity ≤ medium, message
    states the record may simply not exist in VeriPay."""
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_zahra_id"])  # no PO, no accounts
    missing = graph.missing_gaps()
    relationships = {g.relationship for g in missing}
    assert "invoice→purchase_order" in relationships
    assert "vendor→approved_bank_account" in relationships
    for gap in missing:
        assert gap.kind == GAP_MISSING
        assert gap.severity in {"low", "medium"}
        assert "may simply not exist" in gap.message
    # A fully-connected invoice has no missing edges.
    complete = _graph(seed, seed["invoice_nour_id"])
    assert complete.missing_gaps() == []


def test_unresolved_vendor_is_a_missing_relationship_not_a_guess(client):
    seed = rh.seed_retrieval_org(client)
    with SessionLocal() as db:
        from app.models import Invoice

        from helpers import db_query

        def _create_unresolved(session):
            row = Invoice(
                organization_id=uuid.UUID(seed["org_id"]),
                invoice_number="INV-UNRESOLVED",
            )
            session.add(row)
            session.commit()
            return str(row.id)

        invoice_id = db_query(_create_unresolved)
        invoice = procurement_service.get_invoice(
            db, org_id=uuid.UUID(seed["org_id"]), invoice_id=uuid.UUID(invoice_id)
        )
        graph = invoice_evidence_graph(
            db, org_id=uuid.UUID(seed["org_id"]), invoice=invoice
        )
    relationships = {g.relationship for g in graph.missing_gaps()}
    assert "invoice→vendor" in relationships
    assert graph.vendor is None


def test_amount_disagreement_with_po_is_a_structured_contradiction(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_acme_id"])  # invoice 999.00 vs PO 830.50
    contradictions = graph.contradictions()
    hit = next(
        (g for g in contradictions if g.relationship == "invoice↔purchase_order"),
        None,
    )
    assert hit is not None
    assert hit.kind == GAP_CONTRADICTION
    assert hit.detail["invoice_total"] == "999.00"
    assert hit.detail["po_amount"] == "830.50"
    # It is a data disagreement for review — never a fraud verdict.
    assert "fraud" not in hit.message.lower()
    assert "genuine" not in hit.message.lower()


def test_remittance_matching_nonapproved_account_contradiction(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_shadow_id"])
    contradictions = graph.contradictions()
    hit = next(
        (
            g
            for g in contradictions
            if g.relationship == "invoice↔vendor_bank_account"
        ),
        None,
    )
    assert hit is not None
    assert hit.detail["account_status"] == "pending"


def test_remittance_matching_approved_account_is_no_contradiction(client):
    seed = rh.seed_retrieval_org(client)
    graph = _graph(seed, seed["invoice_nour_id"])
    assert not [
        g
        for g in graph.contradictions()
        if g.relationship == "invoice↔vendor_bank_account"
    ]


def test_no_gap_or_contradiction_ever_claims_genuineness_or_fraud(client):
    seed = rh.seed_retrieval_org(client)
    for invoice_id in (
        seed["invoice_nour_id"],
        seed["invoice_acme_id"],
        seed["invoice_zahra_id"],
        seed["invoice_shadow_id"],
    ):
        graph = _graph(seed, invoice_id)
        for gap in graph.gaps:
            text = (gap.message + " " + gap.relationship).lower()
            assert "genuine" not in text
            assert "not fraud" not in text
            assert gap.severity != "critical"
