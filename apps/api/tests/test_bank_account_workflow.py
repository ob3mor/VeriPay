"""R5 bank-account workflow: change control, masking, role restrictions.

The owner's hard rule under test: a new uploaded invoice can NEVER approve a
bank account â€” approval is human-only with an independent verification record.
"""

from role_helpers import login_as, register_second_org
from helpers import register
from role_helpers import add_user

VENDOR = {"display_name": "ACME Supplies GmbH"}


def _make_vendor(client):
    assert register(client).status_code == 201
    response = client.post("/api/v1/vendors", json=VENDOR)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_account(client, vendor_id: str, number: str = "DE89370400440532013000"):
    return client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={
            "account_holder_name": "ACME GmbH",
            "account_number": number,
            "bank_name": "Deutsche Bank",
            "bank_country": "DE",
        },
    )


def test_account_starts_pending_and_never_auto_approves(client):
    vendor_id = _make_vendor(client)
    response = _add_account(client, vendor_id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"

    # Uploading a document and running an assessment have NO approve path:
    # the account is still pending afterwards (structural R5).
    document = client.post(
        "/api/v1/documents",
        files={"file": ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")},
        data={"kind": "invoice"},
    )
    assert document.status_code == 201
    after = client.get(f"/api/v1/vendors/{vendor_id}/bank-accounts").json()[0]
    assert after["status"] == "pending"


def test_approval_requires_independent_verification_record(client):
    vendor_id = _make_vendor(client)
    account_id = _add_account(client, vendor_id).json()["id"]

    # Missing method entirely â†’ business rule violation.
    missing = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account_id}/verify",
        json={"verification_method": "no_such_method"},
    )
    assert missing.status_code == 422

    # Method without reference or document â†’ business rule violation.
    incomplete = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account_id}/verify",
        json={"verification_method": "callback_to_known_contact"},
    )
    assert incomplete.status_code == 422

    # finance_officer cannot approve (role restriction).
    from helpers import db_query

    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    assert login_as(client, "fin@acme.example").status_code == 200
    forbidden = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account_id}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "ticket-123",
        },
    )
    assert forbidden.status_code == 403

    # reviewer approves with the full record.
    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    assert login_as(client, "rev@acme.example").status_code == 200
    approved = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account_id}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "Called known contact, confirmed.",
        },
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved"
    assert body["verification_method"] == "callback_to_known_contact"


def test_responses_are_masked(client):
    """Ordinary views never expose fingerprints or verification provenance;
    the org_admin investigation view MAY include the R5 record (API.md §5.8),
    but a finance_officer's view must not."""
    vendor_id = _make_vendor(client)
    _add_account(client, vendor_id)

    # finance_officer (contributor) — the ordinary masked view.
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "fin-masked@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin-masked@acme.example")
    accounts = client.get(f"/api/v1/vendors/{vendor_id}/bank-accounts").json()
    assert accounts
    for account in accounts:
        assert "account_fingerprint" not in account
        assert "verification_reference" not in account
        assert "verification_document_id" not in account
        raw = str(account)
        assert "DE89370400440532013000" not in raw
        assert account["account_number_last4"] == "3000"


def test_change_request_human_decision_flow(client):
    vendor_id = _make_vendor(client)
    change = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests",
        json={
            "account_holder_name": "ACME GmbH",
            "account_number": "GB29NWBK60161331926819",
            "bank_name": "NatWest",
            "bank_country": "GB",
            "reason": "Vendor migrated banks.",
        },
    )
    assert change.status_code == 201
    request_id = change.json()["id"]

    # finance_officer cannot decide (org_admin/reviewer only).
    from helpers import db_query

    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    forbidden = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{request_id}/approve",
        json={},
    )
    assert forbidden.status_code == 403

    # reviewer approves â†’ resulting account is born approved + current.
    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    login_as(client, "rev@acme.example")
    approved = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{request_id}/approve",
        json={"resolution_note": "Written confirmation on file."},
    )
    assert approved.status_code == 200
    accounts = client.get(f"/api/v1/vendors/{vendor_id}/bank-accounts").json()
    current = [a for a in accounts if a["is_current"]]
    assert len(current) == 1
    assert current[0]["status"] == "approved"

    # A decided request cannot be decided again.
    again = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{request_id}/approve",
        json={},
    )
    assert again.status_code == 422
