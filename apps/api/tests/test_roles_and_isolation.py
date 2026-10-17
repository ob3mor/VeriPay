"""Role Ã— action matrix and cross-tenant isolation for the domain surface."""

import io

from role_helpers import login_as, register_second_org
from helpers import register
from role_helpers import add_user

PDF_BYTES = b"%PDF-1.4\nrole test\n"


def _register_and_vendor(client):
    assert register(client).status_code == 201
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Isolation Vendor"}
    ).json()
    return vendor["id"]


def test_auditor_can_read_audit_events_but_cannot_upload(client):
    vendor_id = _register_and_vendor(client)
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "auditor@acme.example", "auditor")
    client.cookies.clear()
    assert login_as(client, "auditor@acme.example").status_code == 200

    events = client.get("/api/v1/audit-events")
    assert events.status_code == 200
    assert len(events.json()["items"]) > 0  # registration itself is audited

    forbidden = client.post(
        "/api/v1/documents",
        files={"file": ("x.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )
    assert forbidden.status_code == 403


def test_finance_officer_can_contribute_but_not_verify(client):
    vendor_id = _register_and_vendor(client)
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin@acme.example")

    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": "PO-ROLES", "amount": "10.00"},
    )
    assert po.status_code == 201

    account = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "12345678"},
    )
    assert account.status_code == 201
    verify = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account.json()['id']}/verify",
        json={
            "verification_method": "registry_check",
            "verification_reference": "x",
        },
    )
    assert verify.status_code == 403

    # And the audit trail is invisible to non-admin/auditor roles.
    events = client.get("/api/v1/audit-events")
    assert events.status_code == 403


def test_reviewer_can_verify_and_close_cases(client):
    vendor_id = _register_and_vendor(client)
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    login_as(client, "rev@acme.example")

    account = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "87654321"},
    ).json()
    verified = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "Contact confirmed.",
        },
    )
    assert verified.status_code == 200

    case = client.post(
        "/api/v1/cases",
        json={"title": "Check vendor", "severity": "high", "vendor_id": vendor_id},
    )
    assert case.status_code == 201
    closed = client.post(
        f"/api/v1/cases/{case.json()['id']}/close",
        json={"outcome": "false_positive", "resolution_summary": "Verified with vendor."},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


def test_close_without_outcome_is_rejected(client):
    vendor_id = _register_and_vendor(client)
    case = client.post(
        "/api/v1/cases",
        json={"title": "Needs decision", "severity": "medium", "vendor_id": vendor_id},
    ).json()
    incomplete = client.post(
        f"/api/v1/cases/{case['id']}/close", json={"outcome": "false_positive"}
    )
    assert incomplete.status_code == 422
    still_open = client.get(f"/api/v1/cases/{case['id']}").json()
    assert still_open["status"] == "open"


def test_cross_tenant_access_is_404_everywhere(client):
    vendor_id = _register_and_vendor(client)
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    from role_helpers import add_user  # noqa: F401  (ensures helpers loaded)

    account = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "11112222"},
    ).json()
    document = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    ).json()

    client.cookies.clear()
    assert register_second_org(client).status_code == 201

    assert client.get(f"/api/v1/vendors/{vendor_id}").status_code == 404
    assert (
        client.get(
            f"/api/v1/vendors/{vendor_id}/bank-accounts/{account['id']}"
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/documents/{document['id']}/file").status_code == 404
    events = client.get("/api/v1/audit-events").json()["items"]
    # Org B sees only its own trail — no org A event ids leak in.
    foreign_ids = {
        e["id"] for e in events if e["entity_id"] in (vendor_id, document["id"])
    }
    assert foreign_ids == set()

    # Writes against another org's vendor also 404 (no existence leak).
    attempt = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "Evil", "account_number": "99998888"},
    )
    assert attempt.status_code == 404