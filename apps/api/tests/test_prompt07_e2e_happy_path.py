"""Prompt-07 QA — E2E happy path in ONE test.

The whole product story on a real backend (TestClient, no mocks):
register org → login (cookies+CSRF) → create vendor → register bank account
→ verify it (reviewer, R5) → create PO → upload a synthetic invoice PDF
(text-layer OCR provider) → extraction fields exist → assess (EVC v1) →
evidence retrieval returns citable evidence → case open/close with a human
justification (R6) → audit events recorded for every step.

Business invariants asserted inline: the assessment never claims genuineness
(R2), the account is approved ONLY by a human reviewer with an independent
verification record (R5), and the case closes only with outcome + summary
(R6). No payment-authorization or genuineness vocabulary exists anywhere in
the exercised surface.
"""

import io
import sys
from pathlib import Path

# Reuse the deterministic synthetic-PDF builder from the fixture generator
# (same layout conventions as tests/test_extraction_pipeline.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from helpers import login, register  # noqa: E402
from role_helpers import add_user, login_as  # noqa: E402

OWNER_EMAIL = "owner@kranich.example"
REVIEWER_EMAIL = "reviewer@kranich.example"
PASSWORD = "correct-horse-battery-staple"
APPROVED_IBAN = "DE89370400440532013000"

# Ground truth drawn into the synthetic invoice PDF (extraction must agree
# with the manual invoice columns — amounts/dates that disagree would fire
# field_provenance_conflict instead of the clean path under test).
PDF_LINES = [
    "INVOICE",
    "Vendor: Kranich Consulting GmbH",
    "VAT No: DE812345678",
    "Bank: Stadtbank Berlin",
    f"IBAN: DE89 3704 0044 0532 0130 00",
    "Invoice Number: INV-2026-0300",
    # ISO dates so the drawn raw text equals the invoice column values —
    # the EVC provenance check compares raw strings (fraud/evc.py), and the
    # clean path under test must carry no field_provenance_conflict.
    "Invoice Date: 2026-10-15",
    "Due Date: 2026-11-14",
    "Currency: EUR",
    "PO Number: PO-2026-0700",
    "",
    "Subtotal: 1050.00",
    "Tax (19%): 200.00",
    "Total: 1250.00",
]

EXPECTED_FIELD_NAMES = {
    "vendor_name",
    "vendor_tax_id",
    "bank_name",
    "iban",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "po_reference",
    "subtotal",
    "tax",
    "total",
}

# Every step of the story must leave an audit event (docs/DATABASE.md §15
# dotted vocabulary; documents.py/vendors.py/procurement.py/investigations.py/
# auth service are the writers).
EXPECTED_AUDIT_ACTIONS = {
    "user.registered",
    "user.login_succeeded",
    "vendor.created",
    "vendor.account.registered",
    "vendor.account.approved",
    "purchase_order.created",
    "document.uploaded",
    "invoice.created",
    "assessment.created",
    "case.opened",
    "case.closed",
}


def test_full_happy_path_end_to_end(client, tmp_path):
    # -- 1. register the organization + its owner ---------------------------
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": OWNER_EMAIL,
            "password": PASSWORD,
            "full_name": "Ola Owner",
            "organization_name": "Kranich Purchasing GmbH",
        },
    )
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["user"]["role"] == "org_admin"
    assert body["access_token"]
    org_id = body["organization"]["id"]
    # The browser session: httpOnly session cookie + readable CSRF cookie.
    assert client.cookies.get("veripay_session")
    assert client.cookies.get("veripay_csrf")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["organization"]["id"] == org_id

    # -- 2. explicit login (cookies + CSRF) ---------------------------------
    client.cookies.clear()
    logged_in = login(client, username=OWNER_EMAIL, password=PASSWORD)
    assert logged_in.status_code == 200, logged_in.text
    assert client.cookies.get("veripay_session")
    assert client.cookies.get("veripay_csrf")
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == OWNER_EMAIL

    # -- 3. create the vendor ------------------------------------------------
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Kranich Consulting GmbH"}
    )
    assert vendor.status_code == 201, vendor.text
    vendor_id = vendor.json()["id"]
    assert vendor.json()["status"] == "active"

    # -- 4. register a bank account — ALWAYS born pending (R5) ---------------
    account = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={
            "account_holder_name": "Kranich Consulting GmbH",
            "account_number": APPROVED_IBAN,
            "bank_name": "Stadtbank Berlin",
            "bank_country": "DE",
        },
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]
    assert account.json()["status"] == "pending"
    # Masking: last4 only — the full number is in the request body exactly once.
    assert account.json()["account_number_last4"] == "3000"
    assert APPROVED_IBAN not in account.text

    # -- 5. a human reviewer verifies it with an independent record (R5) -----
    add_user(org_id, REVIEWER_EMAIL, "reviewer")
    client.cookies.clear()
    assert login_as(client, REVIEWER_EMAIL).status_code == 200
    reviewer_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    verified = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts/{account_id}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "Callback to known signatory, ticket KB-42.",
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "approved"
    assert verified.json()["verification_method"] == "callback_to_known_contact"
    assert verified.json()["verified_by"] == reviewer_id

    # -- 6. create the purchase order ----------------------------------------
    po = client.post(
        "/api/v1/purchase-orders",
        json={
            "po_number": "PO-2026-0700",
            "vendor_id": vendor_id,
            "amount": "1250.00",
            "currency": "EUR",
            "description": "Consulting retainer Q4",
        },
    )
    assert po.status_code == 201, po.text
    po_id = po.json()["id"]

    # -- 7. upload the synthetic invoice PDF (inline text-layer extraction) --
    pdf_path = tmp_path / "invoice_happy.pdf"
    gf._pdf(PDF_LINES, pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("invoice_happy.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        data={"kind": "invoice", "vendor_id": vendor_id},
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()
    assert document["processing_status"] == "completed"
    assert document["job_status"] == "completed"
    assert document["deduplicated"] is False
    document_id = document["id"]

    # -- 8. extraction fields exist with evidence spans + confidence (R3) ----
    fields = client.get(f"/api/v1/documents/{document_id}/fields").json()["items"]
    by_name = {f["field_name"]: f for f in fields}
    assert EXPECTED_FIELD_NAMES <= set(by_name), sorted(by_name)
    for name in EXPECTED_FIELD_NAMES:
        field = by_name[name]
        assert field["evidence_spans"], f"{name} carries no evidence spans"
        assert field["confidence"] == 1.0  # text layer — full confidence
        # Machine output starts unverified; only a human flips it.
        assert field["verification_status"] == "unverified"
    assert by_name["total"]["field_value"] == "1250.00"
    assert by_name["iban"]["field_value"] == APPROVED_IBAN

    # -- 9. create the invoice bound to vendor, PO and document --------------
    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-2026-0300",
            "vendor_id": vendor_id,
            "purchase_order_id": po_id,
            "source_document_id": document_id,
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-14",
            "currency": "EUR",
            "subtotal_amount": "1050.00",
            "tax_amount": "200.00",
            "total_amount": "1250.00",
            "remittance_bank_name_raw": "Stadtbank Berlin",
            "remittance_account_raw": APPROVED_IBAN,
        },
    )
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["id"]
    assert invoice.json()["status"] == "received"

    # -- 10. assess (EVC v1) — explainable, never a genuineness claim (R2) ---
    assessment = client.post(f"/api/v1/invoices/{invoice_id}/assess")
    assert assessment.status_code == 200, assessment.text
    assessed = assessment.json()
    evc = assessed["evc"]
    assert evc is not None
    assert evc["policy_version"] == "evc-1.0"
    assert evc["result_state"] == "no_material_discrepancies"
    assert assessed["risk_level"] in ("none", "low")
    assert evc["score"] == 0.0
    assert set(evc["features"]) == {
        "bank_account_consistency",
        "po_mismatch",
        "duplicate_indicators",
        "identity_consistency",
        "historical_anomalies",
        "untrusted_source_indicators",
    }
    assert evc["manual_verification_required"] is False
    for finding in assessed["findings"]:
        assert finding["disposition"] == "open"
    raw_assessment = str(assessed).lower()
    assert "is_genuine" not in raw_assessment and "is_fraud" not in raw_assessment
    assert assessed["explanation"][-1].endswith(
        "never certifies an invoice as genuine."
    )

    # -- 11. evidence retrieval returns citable evidence ---------------------
    evidence = client.get(f"/api/v1/invoices/{invoice_id}/evidence")
    assert evidence.status_code == 200, evidence.text
    evidence_body = evidence.json()
    items = evidence_body["evidence"]
    types = {item["entity_type"] for item in items}
    assert {"vendor", "purchase_order", "vendor_bank_account"} <= types, types
    for item in items:
        assert item["entity_id"]
        assert item["title"]
        assert item["match_explanation"]
        assert item["techniques"]
        assert item["provenance"] is not None
        assert item["trust_status"] in {
            "trusted_registry",
            "previously_reviewed",
            "unverified_upload",
            "stale",
            "missing",
        }
    # The approved account is human-approved registry evidence (R5 provenance).
    bank_items = [i for i in items if i["entity_type"] == "vendor_bank_account"]
    assert bank_items and any(
        i["trust_status"] == "trusted_registry" for i in bank_items
    )
    vendor_item = next(i for i in items if i["entity_type"] == "vendor")
    assert vendor_item["matched_field"] == "vendor_id"

    # -- 12. case open/close with a human justification (R6) -----------------
    case = client.post(
        "/api/v1/cases",
        json={
            "title": "Routine verification of INV-2026-0300",
            "severity": "low",
            "invoice_id": invoice_id,
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    assert case.json()["status"] == "open"
    assert case.json()["case_number"].startswith("CASE-")

    noted = client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "comment",
            "body": "Extraction, PO and approved account all agree; "
            "confirming with the vendor contact.",
        },
    )
    assert noted.status_code == 201, noted.text

    # A close without the mandatory human outcome/summary is refused.
    incomplete = client.post(
        f"/api/v1/cases/{case_id}/close", json={"outcome": "false_positive"}
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "validation_error"

    closed = client.post(
        f"/api/v1/cases/{case_id}/close",
        json={
            "outcome": "no_critical_findings",
            "resolution_summary": "Extraction, PO amount and the human-approved "
            "bank account all agree; no critical findings. Disposition recorded "
            "after vendor contact confirmation.",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["outcome"] == "no_critical_findings"
    actions = client.get(f"/api/v1/cases/{case_id}/actions").json()["items"]
    assert any(a["action_type"] == "decision" for a in actions)

    # -- 13. audit events recorded for every step -----------------------------
    client.cookies.clear()
    assert login(client, username=OWNER_EMAIL, password=PASSWORD).status_code == 200
    events = client.get("/api/v1/audit-events?limit=100")
    assert events.status_code == 200, events.text
    recorded_actions = {e["action"] for e in events.json()["items"]}
    missing = EXPECTED_AUDIT_ACTIONS - recorded_actions
    assert not missing, f"missing audit actions: {missing}"
    for event in events.json()["items"]:
        assert event["occurred_at"]
        assert isinstance(event["detail"], dict)
        # Provenance travels with the event (docs/DATABASE.md §15).
        assert event["organization_id"] == org_id