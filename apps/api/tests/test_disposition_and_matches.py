"""Human dispositions: findings + evidence matches (reviewer/org_admin).

Dispositions are annotations, never downgrades: severity floors and the
needs_review forcing stay intact; every disposition is audited. This closes
the auditor's gap — FraudFinding.disposition / EvidenceMatch.status were
columns without any write path.
"""

import io
import uuid

from helpers import db_query, register
from role_helpers import add_user, login_as, register_second_org

PDF_BYTES = b"%PDF-1.4\ndisposition test\n"


def _assessed_finding(client):
    """Register, create an invoice, assess it, return (org_id, finding)."""
    assert register(client).status_code == 201
    me = client.get("/api/v1/auth/me").json()
    org_id = me["user"]["organization_id"]
    invoice = client.post(
        "/api/v1/invoices", json={"invoice_number": "INV-DISP"}
    ).json()
    assessment = client.post(f"/api/v1/invoices/{invoice['id']}/assess")
    assert assessment.status_code == 200, assessment.text
    findings = assessment.json()["findings"]
    assert findings  # missing-PO and no-remittance signals at minimum
    return org_id, invoice["id"], findings[0]


def _add_org_roles(client, org_id: str) -> None:
    add_user(org_id, "fin@acme.example", "finance_officer")
    add_user(org_id, "rev@acme.example", "reviewer")
    add_user(org_id, "aud@acme.example", "auditor")


def test_reviewer_dispositions_a_finding(client):
    org_id, invoice_id, finding = _assessed_finding(client)
    _add_org_roles(client, org_id)
    client.cookies.clear()
    assert login_as(client, "rev@acme.example").status_code == 200

    response = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "acknowledged", "note": "Investigating."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disposition"] == "acknowledged"
    assert body["dispositioned_at"] is not None

    # The latest assessment read reflects the disposition.
    latest = client.get(f"/api/v1/invoices/{invoice_id}/assessment").json()
    stamped = [f for f in latest["findings"] if f["id"] == finding["id"]]
    assert stamped and stamped[0]["disposition"] == "acknowledged"


def test_disposition_is_role_guarded(client):
    org_id, _invoice_id, finding = _assessed_finding(client)
    _add_org_roles(client, org_id)

    # finance_officer may work cases but NOT disposition (reviewer/org_admin).
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    assert (
        client.post(
            f"/api/v1/findings/{finding['id']}/disposition",
            json={"disposition": "dismissed"},
        ).status_code
        == 403
    )

    # auditor is read-only.
    client.cookies.clear()
    login_as(client, "aud@acme.example")
    assert (
        client.post(
            f"/api/v1/findings/{finding['id']}/disposition",
            json={"disposition": "dismissed"},
        ).status_code
        == 403
    )


def test_disposition_unknown_value_is_422(client):
    org_id, _invoice_id, finding = _assessed_finding(client)
    response = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "not-a-disposition"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_disposition_is_audited(client):
    org_id, _invoice_id, finding = _assessed_finding(client)
    client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed", "note": "Reviewed, not actionable."},
    )
    client.cookies.clear()
    add_user(org_id, "aud2@acme.example", "auditor")
    login_as(client, "aud2@acme.example")
    events = client.get("/api/v1/audit-events?action=finding.dispositioned").json()
    assert any(
        e["entity_id"] == finding["id"]
        and e["detail"]["from"] == "open"
        and e["detail"]["to"] == "dismissed"
        for e in events
    )


def test_duplicate_match_can_be_reviewed(client):
    """duplicate_candidate findings point at evidence matches via
    evidence_refs — the match itself is reviewable (the docs' duplicates
    review path)."""
    org_id, _invoice_id, _finding = _assessed_finding(client)
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Dup Vendor"}
    ).json()
    client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "DE89370400440532013000"},
    )
    first = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-DUP", "vendor_id": vendor["id"]},
    ).json()
    second = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-DUP", "vendor_id": vendor["id"]},
    ).json()

    def _match_id(session):
        from app.models import EvidenceMatch

        row = (
            session.query(EvidenceMatch)
            .filter(EvidenceMatch.organization_id == uuid.UUID(org_id))
            .first()
        )
        return str(row.id), row.status

    match_id, status = db_query(_match_id)
    assert status == "open"

    # GET is readable by any member.
    fetched = client.get(f"/api/v1/matches/{match_id}")
    assert fetched.status_code == 200
    assert fetched.json()["match_kind"] == "invoice_number"

    # finance_officer cannot review.
    _add_org_roles(client, org_id)
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    assert (
        client.post(
            f"/api/v1/matches/{match_id}/review", json={"status": "confirmed"}
        ).status_code
        == 403
    )

    # reviewer confirms it.
    client.cookies.clear()
    login_as(client, "rev@acme.example")
    reviewed = client.post(
        f"/api/v1/matches/{match_id}/review",
        json={"status": "confirmed", "note": "Second billing confirmed."},
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["status"] == "confirmed"
    assert body["reviewed_at"] is not None

    # 'open' is not a decision — it cannot be written back.
    reopen = client.post(
        f"/api/v1/matches/{match_id}/review", json={"status": "open"}
    )
    assert reopen.status_code == 422


def test_finance_officer_cannot_close_a_case(client):
    """R6: closing is an org_admin/reviewer decision (docs/API.md §5 matrix)."""
    assert register(client).status_code == 201
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    invoice = client.post("/api/v1/invoices", json={"invoice_number": "INV-C"}).json()
    case = client.post(
        "/api/v1/cases",
        json={"title": "T", "severity": "medium", "invoice_id": invoice["id"]},
    ).json()
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    forbidden = client.post(
        f"/api/v1/cases/{case['id']}/close",
        json={"outcome": "false_positive", "resolution_summary": "x"},
    )
    assert forbidden.status_code == 403
    still_open = client.get(f"/api/v1/cases/{case['id']}").json()
    assert still_open["status"] == "open"


def test_match_endpoints_are_tenant_scoped(client):
    _org_id, _invoice_id, _finding = _assessed_finding(client)
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    # A random UUID in org B is indistinguishable from nonexistent (404).
    # Probe bodies carry a reason: the request must be WELL-FORMED so the
    # 404 measures tenancy, not the mandatory-reason validation (422).
    foreign = uuid.uuid4()
    assert client.get(f"/api/v1/matches/{foreign}").status_code == 404
    assert (
        client.post(
            f"/api/v1/matches/{foreign}/review",
            json={"status": "confirmed", "reason": "tenant probe"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/findings/{foreign}/disposition",
            json={"disposition": "dismissed", "reason": "tenant probe"},
        ).status_code
        == 404
    )
