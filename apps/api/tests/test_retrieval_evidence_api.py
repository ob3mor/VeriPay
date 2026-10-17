"""API tests for GET /invoices/{id}/evidence (Prompt-03 §7): org-scoped 404,
role-guarded reads, citable evidence shape (source id / category / matched
field / explanation / document location / trust status / retrieval score),
and the tenant-isolation proof at the HTTP surface."""

import uuid

from role_helpers import add_user, login_as, register_second_org

import retrieval_helpers as rh

EVIDENCE_URL = "/api/v1/invoices/{invoice_id}/evidence"


def _get(client, invoice_id):
    return client.get(EVIDENCE_URL.format(invoice_id=invoice_id))


def test_evidence_endpoint_requires_authentication(client):
    seed = rh.seed_retrieval_org(client)
    client.cookies.clear()
    response = _get(client, seed["invoice_nour_id"])
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"]


def test_evidence_shape_has_citable_fields(client):
    seed = rh.seed_retrieval_org(client)
    response = _get(client, seed["invoice_nour_id"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["gaps"] == []  # fully connected invoice
    assert body["contradictions"] == []
    meta = body["meta"]
    assert meta["backend"] in {"portable", "postgres"}
    assert meta["weights"]["exact"] > 0
    assert meta["latency_ms"] >= 0

    items = body["evidence"]
    assert items, "a connected invoice must yield evidence"
    by_ref = {(i["entity_type"], str(i["entity_id"])) for i in items}
    # Graph relationships (deterministic):
    assert ("purchase_order", seed["po_nour_id"]) in by_ref
    assert ("vendor", seed["vendor_id"]) in by_ref
    assert ("vendor_bank_account", seed["approved_account_id"]) in by_ref
    # Fuzzy retrieval hit (the duplicate invoice, via the shared number).
    assert ("invoice", seed["duplicate_invoice_id"]) in by_ref

    for item in items:
        # Every item is citable: id, category, matched field, explanation,
        # document location, trust status, retrieval score.
        assert uuid.UUID(str(item["entity_id"]))
        assert item["entity_type"] in {
            "vendor",
            "vendor_bank_account",
            "invoice",
            "purchase_order",
            "extraction_field",
            "review_action",
        }
        assert item["match_explanation"]
        assert item["trust_status"] in {
            "trusted_registry",
            "previously_reviewed",
            "unverified_upload",
            "stale",
            "missing",
        }
        assert 0.0 < item["retrieval_score"] <= 1.0
        assert item["techniques"]
        assert "record_version" in item
    # Score ordering: descending (ranked for citation).
    scores = [i["retrieval_score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_evidence_po_item_carries_graph_explanation_and_field(client):
    seed = rh.seed_retrieval_org(client)
    body = _get(client, seed["invoice_nour_id"]).json()
    po = next(
        i for i in body["evidence"] if i["entity_type"] == "purchase_order"
    )
    assert po["matched_field"] == "purchase_order_id"
    assert "Graph relationship" in po["match_explanation"]
    assert po["techniques"] == ["graph"]
    assert po["trust_status"] == "trusted_registry"


def test_evidence_extraction_item_carries_document_location(client):
    seed = rh.seed_retrieval_org(client)
    body = _get(client, seed["invoice_nour_id"]).json()
    field_items = [
        i for i in body["evidence"] if i["entity_type"] == "extraction_field"
    ]
    assert field_items, "extraction fields must be retrievable evidence"
    located = next(
        i for i in field_items if i["document_location"] is not None
    )
    assert located["document_location"]["document_id"] == seed["document_id"]
    assert located["document_location"]["page"] == 1
    assert len(located["document_location"]["bbox"]) == 4


def test_cross_org_evidence_is_404(client):
    seed = rh.seed_retrieval_org(client, email="a4@acme.example")
    client.cookies.clear()
    assert register_second_org(client, email="b4@corp.example").status_code == 201
    response = _get(client, seed["invoice_nour_id"])
    # Cross-org is 404, not 403 — no existence leak (docs/API.md §5.4).
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_evidence_is_org_scoped_with_identical_tenant_data(client):
    """Org B seeds the SAME vendor name + invoice number; A's evidence must
    contain zero B entities and vice versa (leakage impossible)."""
    seed_a = rh.seed_retrieval_org(client, email="a5@acme.example")
    client.cookies.clear()
    seed_b = rh.seed_retrieval_org(client, email="b5@corp.example")

    # Currently authenticated as B (registration logs in) — read B's evidence.
    body_b = _get(client, seed_b["invoice_nour_id"]).json()
    ids_b = {str(i["entity_id"]) for i in body_b["evidence"]}
    # The invoice itself is not its own evidence; its duplicate-number
    # sibling (found via the shared identifier) is.
    assert seed_b["invoice_nour_id"] not in ids_b
    assert seed_b["duplicate_invoice_id"] in ids_b
    assert seed_b["vendor_id"] in ids_b
    assert seed_a["invoice_nour_id"] not in ids_b
    assert seed_a["vendor_id"] not in ids_b
    assert seed_a["duplicate_invoice_id"] not in ids_b

    # Switch back to A — A's evidence must contain zero B entities.
    assert login_as(client, "a5@acme.example").status_code == 200
    body_a = _get(client, seed_a["invoice_nour_id"]).json()
    ids_a = {str(i["entity_id"]) for i in body_a["evidence"]}
    for key in (
        "vendor_id",
        "approved_account_id",
        "po_nour_id",
        "duplicate_invoice_id",
    ):
        assert seed_a[key] in ids_a, key
        assert seed_b[key] not in ids_a, key
    assert seed_a["invoice_nour_id"] not in ids_a
    assert seed_b["invoice_nour_id"] not in ids_a


def test_evidence_readable_by_all_authenticated_roles(client):
    """Role-guarded like other invoice reads: any canonical role may read;
    unauthenticated is 401 (covered above)."""
    seed = rh.seed_retrieval_org(client, email="a6@acme.example")
    org_id = seed["org_id"]
    for role, email in (
        ("finance_officer", "fo6@acme.example"),
        ("reviewer", "rev6@acme.example"),
        ("auditor", "aud6@acme.example"),
    ):
        add_user(org_id, email, role)
        client.cookies.clear()
        login = login_as(client, email)
        assert login.status_code == 200, (role, login.text)
        response = _get(client, seed["invoice_nour_id"])
        assert response.status_code == 200, role


def test_evidence_never_echoes_the_raw_remittance_account(client):
    """docs/API.md §5.8 / retrieval schemas header: full account numbers never
    appear in any response. The raw remittance account seeds the FUZZY SEARCH
    server-side; the meta echo carries the masked last4 form only — exactly
    like the ordinary invoice read (remittance_account_last4)."""
    seed = rh.seed_retrieval_org(client)
    response = _get(client, seed["invoice_nour_id"])
    assert response.status_code == 200, response.text
    # The raw IBAN appears NOWHERE in the response body (seeds, explanations,
    # provenance, titles — nothing).
    assert rh.NOUR_IBAN not in response.text
    # The masked seed documents what was searched without exposing the value.
    masked = "remittance_account_last4:" + rh.NOUR_IBAN[-4:]
    assert masked in response.json()["meta"]["seeds"]


def test_evidence_reports_gaps_and_contradictions(client):
    seed = rh.seed_retrieval_org(client)
    # Zahra: no PO, no accounts → missing gaps.
    body = _get(client, seed["invoice_zahra_id"]).json()
    relationships = {g["relationship"] for g in body["gaps"]}
    assert "invoice→purchase_order" in relationships
    assert "vendor→approved_bank_account" in relationships
    for gap in body["gaps"]:
        assert gap["kind"] == "missing"
        assert gap["severity"] in {"low", "medium"}

    # Acme: total disagrees with PO amount → contradiction.
    body = _get(client, seed["invoice_acme_id"]).json()
    hits = [
        g for g in body["contradictions"] if g["relationship"] == "invoice↔purchase_order"
    ]
    assert hits and hits[0]["detail"]["invoice_total"] == "999.00"

    # Shadow remittance = pending account → contradiction.
    body = _get(client, seed["invoice_shadow_id"]).json()
    assert any(
        g["relationship"] == "invoice↔vendor_bank_account"
        for g in body["contradictions"]
    )
