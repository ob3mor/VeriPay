"""Tenant isolation per resource (docs/API.md §5 rule 6): A's principal gets
404 on every B-owned object and write against it; B's objects never appear in
A's lists. Covers the resources the auditor found untested: invoices, POs,
cases, assessments, extraction reads, line items, processing jobs, matches,
findings, plus the cross-org assignee case and source-document binding."""

import io
import uuid

from helpers import db_query, login, register
from role_helpers import register_second_org

PDF_BYTES = b"%PDF-1.4\ntenant isolation test\n"


def _seed_org_a(client):
    """Org A with one of every resource, cross-linked where the API allows."""
    assert register(client).status_code == 201
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Isolation Vendor"}
    ).json()
    document = client.post(
        "/api/v1/documents",
        files={"file": ("iso.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    ).json()
    po = client.post(
        "/api/v1/purchase-orders", json={"po_number": "PO-ISO", "amount": "10.00"}
    ).json()
    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-ISO",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "source_document_id": document["id"],
        },
    ).json()
    line_item = client.post(
        f"/api/v1/invoices/{invoice['id']}/line-items",
        json={"description": "Widget", "quantity": "1", "line_total": "10.00"},
    )
    assert line_item.status_code == 201, line_item.text
    assessment = client.post(f"/api/v1/invoices/{invoice['id']}/assess")
    assert assessment.status_code == 200, assessment.text
    finding = assessment.json()["findings"][0]
    case = client.post(
        "/api/v1/cases",
        json={
            "title": "Isolation case",
            "severity": "medium",
            "invoice_id": invoice["id"],
        },
    ).json()

    # The duplicate pair (for an evidence match).
    duplicate = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-ISO", "vendor_id": vendor["id"]},
    ).json()

    return {
        "vendor_id": vendor["id"],
        "document_id": document["id"],
        "po_id": po["id"],
        "invoice_id": invoice["id"],
        "line_item_id": line_item.json()["id"],
        "assessment_id": assessment.json()["id"],
        "finding_id": finding["id"],
        "case_id": case["id"],
        "duplicate_id": duplicate["id"],
        "processing_job_id": document.get("job_id"),
    }


def _an_evidence_match_id(org_id: str) -> str:
    org_uuid = uuid.UUID(org_id)

    def _first_match(session):
        from app.models import EvidenceMatch

        row = (
            session.query(EvidenceMatch)
            .filter(EvidenceMatch.organization_id == org_uuid)
            .first()
        )
        assert row is not None
        return str(row.id)

    return db_query(_first_match)


def test_every_resource_is_404_across_orgs(client):
    ids = _seed_org_a(client)
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    match_id = _an_evidence_match_id(org_id)

    # Switch to org B.
    client.cookies.clear()
    assert register_second_org(client).status_code == 201

    # --- reads are 404 (nonexistent, no existence leak) ---------------------
    assert client.get(f"/api/v1/invoices/{ids['invoice_id']}").status_code == 404
    assert client.get(f"/api/v1/purchase-orders/{ids['po_id']}").status_code == 404
    assert client.get(f"/api/v1/cases/{ids['case_id']}").status_code == 404
    assert (
        client.get(f"/api/v1/invoices/{ids['invoice_id']}/assessment").status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/invoices/{ids['invoice_id']}/line-items").status_code
        == 404
    )
    assert client.get(f"/api/v1/documents/{ids['document_id']}").status_code == 404
    assert (
        client.get(f"/api/v1/documents/{ids['document_id']}/fields").status_code == 404
    )
    assert (
        client.get(f"/api/v1/documents/{ids['document_id']}/extraction").status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/documents/{ids['document_id']}/file").status_code == 404
    )
    if ids["processing_job_id"]:
        assert (
            client.get(f"/api/v1/processing-jobs/{ids['processing_job_id']}").status_code
            == 404
        )
    assert client.get(f"/api/v1/matches/{match_id}").status_code == 404

    # --- writes against A-owned ids are 404 too ------------------------------
    assert (
        client.post(f"/api/v1/invoices/{ids['invoice_id']}/assess").status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/invoices/{ids['invoice_id']}/line-items",
            json={"description": "x"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/invoices/{ids['invoice_id']}/resolve-vendor", json={}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/findings/{ids['finding_id']}/disposition",
            json={"disposition": "dismissed", "reason": "tenant probe"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/matches/{match_id}/review",
            json={"status": "confirmed", "reason": "tenant probe"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/cases/{ids['case_id']}/close",
            json={"outcome": "false_positive", "resolution_summary": "x"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/cases/{ids['case_id']}/actions",
            json={"action_type": "comment", "body": "x"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/documents/{ids['document_id']}").status_code == 404

    # Binding another org's document as a source document is a 404 as well.
    assert (
        client.post(
            "/api/v1/invoices",
            json={
                "invoice_number": "INV-STEAL",
                "source_document_id": ids["document_id"],
            },
        ).status_code
        == 404
    )

    # --- lists never leak org A rows ----------------------------------------
    assert ids["invoice_id"] not in [
        i["id"] for i in client.get("/api/v1/invoices").json()["items"]
    ]
    assert ids["po_id"] not in [
        p["id"] for p in client.get("/api/v1/purchase-orders").json()["items"]
    ]
    assert ids["case_id"] not in [c["id"] for c in client.get("/api/v1/cases").json()["items"]]
    assert ids["document_id"] not in [
        d["id"] for d in client.get("/api/v1/documents").json()["items"]
    ]
    assert ids["vendor_id"] not in [
        v["id"] for v in client.get("/api/v1/vendors").json()["items"]
    ]


def test_assign_case_to_user_of_another_org_is_404(client):
    """investigations.py assign: an assignee outside the caller's org is 404
    (no existence leak), and the case stays unassigned."""
    ids = _seed_org_a(client)
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    foreign_user = client.get("/api/v1/auth/me").json()["user"]["id"]

    response = client.post(
        f"/api/v1/cases/{ids['case_id']}/assign", json={"user_id": foreign_user}
    )
    assert response.status_code == 404

    # Back in org A: the case was never assigned.
    client.cookies.clear()
    assert login(client).status_code == 200
    case = client.get(f"/api/v1/cases/{ids['case_id']}").json()
    assert case["assigned_to"] is None
