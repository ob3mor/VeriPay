"""Fraud rules v0.1: the R2/R3/R4/R5 invariants as executable tests."""

import io

from role_helpers import login_as
from helpers import db_query, register
from role_helpers import add_user


def _setup_vendor_with_approved_account(client):
    assert register(client).status_code == 201
    me = client.get("/api/v1/auth/me").json()
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Trusted Vendor Ltd"}
    ).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": "Trusted Vendor Ltd",
            "account_number": "DE89370400440532013000",
            "bank_country": "DE",
        },
    ).json()
    client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "written_confirmation",
            "verification_reference": "Signed bank letter on file.",
        },
    )
    return me["user"]["organization_id"], vendor["id"]


def _make_po(client, number: str, amount: str) -> str:
    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": number, "amount": amount, "currency": "EUR"},
    )
    assert po.status_code == 201, po.text
    return po.json()["id"]


def _make_invoice(client, **overrides):
    payload = {
        "invoice_number": "INV-001",
        "currency": "EUR",
        "total_amount": "1250.00",
        "remittance_account_raw": "DE89370400440532013000",
        "remittance_bank_name_raw": "Deutsche Bank",
    }
    payload.update(overrides)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _assess(client, invoice_id):
    return client.post(f"/api/v1/invoices/{invoice_id}/assess")


def test_matching_approved_account_produces_no_bank_signal(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-1", "1250.00")
    invoice = _make_invoice(client, vendor_id=vendor_id, purchase_order_id=po_id)
    assessment = _assess(client, invoice["id"])
    assert assessment.status_code == 200
    body = assessment.json()
    types = [f["signal_type"] for f in body["findings"]]
    assert "bank_account_unverified" not in types
    assert body["risk_level"] in ("none", "low")


def test_unverified_remittance_is_high_and_forces_review(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    invoice = _make_invoice(
        client,
        vendor_id=vendor_id,
        remittance_account_raw="GB29NWBK60161331926819",  # NOT the approved one
    )
    body = _assess(client, invoice["id"]).json()
    bank = [f for f in body["findings"] if f["signal_type"] == "bank_account_unverified"]
    assert bank and bank[0]["severity"] == "high"  # floor â€” never downgraded
    assert client.get(f"/api/v1/invoices/{invoice['id']}").json()["status"] == "needs_review"


def test_missing_po_is_capped_at_medium(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    invoice = _make_invoice(client, vendor_id=vendor_id)  # no PO linked
    body = _assess(client, invoice["id"]).json()
    missing = [f for f in body["findings"] if f["signal_type"] == "missing_evidence"]
    assert missing
    assert all(f["severity"] in ("low", "medium") for f in missing)


def test_amount_mismatch_is_high(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-2", "1000.00")
    invoice = _make_invoice(
        client, vendor_id=vendor_id, purchase_order_id=po_id, total_amount="2500.00"
    )
    body = _assess(client, invoice["id"]).json()
    mismatch = [f for f in body["findings"] if f["signal_type"] == "amount_mismatch"]
    assert mismatch and mismatch[0]["severity"] == "high"


def test_duplicate_invoice_number_becomes_signal_not_409(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    first = _make_invoice(client, vendor_id=vendor_id, invoice_number="INV-DUP")
    second = _make_invoice(client, vendor_id=vendor_id, invoice_number="INV-DUP")
    assert first["id"] != second["id"]
    body = _assess(client, second["id"]).json()
    dupes = [f for f in body["findings"] if f["signal_type"] == "duplicate_candidate"]
    assert dupes
    # The evidence match row exists and is open for human disposition.
    assert any(f["evidence_refs"] for f in dupes)


def test_no_genuineness_anywhere(client):
    """R2: the assessment vocabulary contains no is_fraud/is_genuine concept."""
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    invoice = _make_invoice(client, vendor_id=vendor_id)
    body = _assess(client, invoice["id"]).json()
    raw = str(body).lower()
    assert "is_genuine" not in raw and "is_fraud" not in raw
    assert body["explanation"]  # explainability is the deliverable
    assert body["explanation"][-1].endswith("genuine.") or "never" in body["explanation"][-1].lower()


def test_assessment_requires_contributor_role(client):
    _org_id, vendor_id = _setup_vendor_with_approved_account(client)
    invoice = _make_invoice(client, vendor_id=vendor_id)
    org_id = _org_id
    add_user(org_id, "aud@acme.example", "auditor")
    client.cookies.clear()
    login_as(client, "aud@acme.example")
    assert _assess(client, invoice["id"]).status_code == 403
