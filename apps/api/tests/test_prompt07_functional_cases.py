"""Prompt-07 QA — the 10 functional cases from the brief.

1.  normal invoice                      → clean EVC, no forcing
2.  unauthorized bank-account change    → bank_account_unverified (high floor)
3.  duplicate submission                → signal + needs_review, never 409
4.  unknown vendor                      → capped-medium review, never fraud
5.  PO mismatch                         → amount_mismatch (high)
6.  unreadable critical OCR field       → manual verification, NEVER a mismatch
7.  multi-org isolation                 → cross-org ids are 404 everywhere
8.  unauthorized account-change approval→ finance_officer denied (R5 matrix)
9.  reviewer resolves case with justification (R6)
10. processing fails and retries        → no duplicate records
"""

import io
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Deterministic synthetic-PDF builder (same pattern as test_extraction_pipeline).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from helpers import db_query, login, register  # noqa: E402
from role_helpers import add_user, login_as, register_second_org  # noqa: E402

APPROVED_IBAN = "DE89370400440532013000"
OTHER_IBAN = "GB29NWBK60161331926819"
PDF_BYTES = b"%PDF-1.4\nfunctional-case document\n"


# --------------------------------------------------------------- helpers ----
def _register_org(client, email: str = "case-owner@acme.example") -> str:
    assert register(client, email=email).status_code == 201
    return client.get("/api/v1/auth/me").json()["user"]["organization_id"]


def _vendor_with_approved_account(client, name: str, iban: str = APPROVED_IBAN) -> tuple[str, str]:
    vendor = client.post("/api/v1/vendors", json={"display_name": name}).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": name,
            "account_number": iban,
            "bank_country": "DE",
        },
    ).json()
    verified = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "written_confirmation",
            "verification_reference": "Signed bank letter on file.",
        },
    )
    assert verified.status_code == 200, verified.text
    return vendor["id"], account["id"]


def _make_po(client, number: str, amount: str, vendor_id: str | None = None) -> str:
    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": number, "amount": amount, "currency": "EUR",
              "vendor_id": vendor_id},
    )
    assert po.status_code == 201, po.text
    return po.json()["id"]


def _make_invoice(client, **overrides) -> dict:
    payload = {"invoice_number": "INV-CASE", "currency": "EUR"}
    payload.update(overrides)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _assess(client, invoice_id: str) -> dict:
    response = client.post(f"/api/v1/invoices/{invoice_id}/assess")
    assert response.status_code == 200, response.text
    return response.json()


def _signal_types(body: dict) -> set[str]:
    return {f["signal_type"] for f in body["findings"]}


def _invoice_status(client, invoice_id: str) -> str:
    return client.get(f"/api/v1/invoices/{invoice_id}").json()["status"]


# ------------------------------------------------ 1. normal invoice ---------
def test_case_1_normal_invoice_is_clean_and_unforced(client):
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Norma Trading Ltd")
    po_id = _make_po(client, "PO-N1", "1250.00", vendor_id)
    invoice = _make_invoice(
        client,
        invoice_number="INV-N1",
        vendor_id=vendor_id,
        purchase_order_id=po_id,
        total_amount="1250.00",
        invoice_date="2026-03-01",
        remittance_account_raw=APPROVED_IBAN,
        remittance_bank_name_raw="Stadtbank Berlin",
    )
    body = _assess(client, invoice["id"])
    assert body["evc"]["result_state"] == "no_material_discrepancies"
    assert body["risk_level"] in ("none", "low")
    assert body["evc"]["score"] == 0.0
    # No forcing: the invoice keeps its status and no case was opened (R6).
    assert _invoice_status(client, invoice["id"]) == "received"
    assert client.get("/api/v1/cases").json() == []
    # Nothing here claims genuineness (R2).
    raw = str(body).lower()
    assert "is_genuine" not in raw and "is_fraud" not in raw


# --------------------------- 2. unauthorized bank-account change ------------
def test_case_2_unauthorized_bank_account_change_forces_review(client):
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Cambio Ltd")
    invoice = _make_invoice(
        client,
        invoice_number="INV-C2",
        vendor_id=vendor_id,
        total_amount="600.00",
        remittance_account_raw=OTHER_IBAN,  # NOT the approved account
    )
    body = _assess(client, invoice["id"])
    assert "bank_account_unverified" in _signal_types(body)
    unverified = [
        f for f in body["findings"] if f["signal_type"] == "bank_account_unverified"
    ]
    assert unverified[0]["severity"] == "high"  # §8.5 floor — never downgraded
    assert body["evc"]["result_state"] == "high_risk_discrepancy"
    assert body["risk_level"] == "high"
    assert _invoice_status(client, invoice["id"]) == "needs_review"

    # No account was auto-approved by the invoice (R5): the only approved
    # account remains the originally verified one.
    def _approved(session):
        from app.models import VendorBankAccount

        return [
            (str(a.verified_by), a.status)
            for a in session.query(VendorBankAccount)
            .filter(VendorBankAccount.vendor_id == uuid.UUID(vendor_id))
            .all()
        ]
    rows = db_query(_approved)
    assert len(rows) == 1  # the original account only
    assert rows[0][1] == "approved"
    # A single high discrepancy is NOT critical — no auto-case (R6 needs two).
    assert client.get("/api/v1/cases").json() == []


# ------------------------------------------- 3. duplicate submission --------
def test_case_3_duplicate_submission_is_a_signal_never_an_error(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Duplico GmbH")
    base = dict(
        vendor_id=vendor_id,
        total_amount="500.00",
        invoice_date="2026-06-01",
        remittance_account_raw=APPROVED_IBAN,
    )
    first = _make_invoice(client, invoice_number="INV-DUP-9", **base)
    second = _make_invoice(client, invoice_number="INV-DUP-9", **base)
    assert first["id"] != second["id"]  # intake allowed — signal, not 409

    body = _assess(client, second["id"])
    dup = [f for f in body["findings"] if f["signal_type"] == "duplicate_candidate"]
    assert dup and dup[0]["severity"] == "medium"
    assert dup[0]["evidence_refs"] == [first["id"]]
    assert body["evc"]["result_state"] == "review_required"
    assert _invoice_status(client, second["id"]) == "needs_review"

    def _matches(session):
        from app.models import EvidenceMatch

        return [
            (m.match_kind, m.status, m.source_entity_id, m.target_entity_id)
            for m in session.query(EvidenceMatch)
            .filter(
                EvidenceMatch.organization_id == uuid.UUID(org_id),
                EvidenceMatch.match_kind == "invoice_number",
            )
            .all()
        ]
    matches = db_query(_matches)
    assert any(
        kind == "invoice_number"
        and status == "open"
        and {uuid.UUID(first["id"]), uuid.UUID(second["id"])}
        == {source, target}
        for kind, status, source, target in matches
    )


# ------------------------------------------------- 4. unknown vendor --------
def test_case_4_unknown_vendor_is_capped_medium_never_fraud(client):
    _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-NOVENDOR-4")
    body = _assess(client, invoice["id"])
    unknown = [f for f in body["findings"] if f["signal_type"] == "unknown_vendor"]
    assert unknown and unknown[0]["severity"] == "medium"  # capped
    identity = body["evc"]["features"]["identity_consistency"]
    assert identity["state"] == "insufficient_evidence"
    assert identity["contribution"] == 0.0  # unknown is never scored
    assert body["evc"]["result_state"] == "review_required"
    assert body["risk_level"] == "medium"
    assert _invoice_status(client, invoice["id"]) == "needs_review"
    assert client.get("/api/v1/cases").json() == []  # medium — no auto-case


# ---------------------------------------------------- 5. PO mismatch --------
def test_case_5_po_amount_mismatch_is_high(client):
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Mismatcho AG")
    po_id = _make_po(client, "PO-M5", "1000.00", vendor_id)
    invoice = _make_invoice(
        client,
        invoice_number="INV-M5",
        vendor_id=vendor_id,
        purchase_order_id=po_id,
        total_amount="2500.00",  # 2.5× the PO
        remittance_account_raw=APPROVED_IBAN,
    )
    body = _assess(client, invoice["id"])
    mismatch = [f for f in body["findings"] if f["signal_type"] == "amount_mismatch"]
    assert mismatch and mismatch[0]["severity"] == "high"
    po_feature = body["evc"]["features"]["po_mismatch"]
    assert po_feature["state"] == "confirmed_discrepancy"
    assert po_feature["severity"] == "high"
    assert body["evc"]["result_state"] == "high_risk_discrepancy"
    assert body["risk_level"] == "high"
    assert _invoice_status(client, invoice["id"]) == "needs_review"


# ------------------------- 6. unreadable critical OCR field -----------------
def test_case_6_unreadable_critical_ocr_field_never_becomes_a_mismatch(client):
    """A payment-critical value that exists only through below-gate OCR is
    manual-verification uncertainty (R3). The human-entered column (100.00)
    disagrees wildly with the low-confidence extraction (999.00) — and the
    system must flag MANUAL VERIFICATION, never a mismatch claim."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Blurredo Oy")
    po_id = _make_po(client, "PO-O6", "100.00", vendor_id)
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("blur.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice", "vendor_id": vendor_id},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    def _seed_low_confidence_total(session):
        """A later extraction version whose total is uncertain AND wrong."""
        from app.models import Document, ExtractionField, ExtractionResult

        doc = session.get(Document, uuid.UUID(document_id))
        result = ExtractionResult(
            organization_id=doc.organization_id,
            document_id=doc.id,
            extraction_version="qa-lowconf-v1",
            status="completed",
            # Strictly later than the inline run so get_result() (latest by
            # created_at) picks this one despite SQLite second-resolution.
            created_at=datetime.now(timezone.utc),
        )
        session.add(result)
        session.flush()
        session.add(
            ExtractionField(
                organization_id=doc.organization_id,
                extraction_result_id=result.id,
                field_name="total_amount",
                field_value="999.00",
                confidence=0.3,  # far below the 0.85 gate
            )
        )
        session.commit()

    db_query(_seed_low_confidence_total)

    invoice = _make_invoice(
        client,
        invoice_number="INV-O6",
        vendor_id=vendor_id,
        purchase_order_id=po_id,
        source_document_id=document_id,
        total_amount="100.00",
        remittance_account_raw=APPROVED_IBAN,
    )
    body = _assess(client, invoice["id"])
    types = _signal_types(body)
    # Manual verification demanded — the machine never resolves this itself.
    assert "ocr_uncertain" in types
    assert body["evc"]["manual_verification_required"] is True
    # THE INVARIANT: uncertain OCR never becomes confident fraud evidence.
    assert "amount_mismatch" not in types, types
    assert "bank_account_unverified" not in types
    # The disagreement itself is surfaced for a human, column wins, ≤ medium.
    conflict = [f for f in body["findings"]
                if f["signal_type"] == "field_provenance_conflict"]
    assert conflict and conflict[0]["severity"] == "medium"
    assert body["risk_level"] in ("low", "medium")
    assert _invoice_status(client, invoice["id"]) == "needs_review"
    # The uncertain field stays machine-unverified in the API surface.
    fields = client.get(f"/api/v1/documents/{document_id}/fields").json()
    uncertain = [f for f in fields if f["field_name"] == "total_amount"
                 and f["confidence"] == 0.3]
    assert uncertain and uncertain[0]["verification_status"] == "unverified"


# ------------------------------------------------ 7. multi-org isolation ----
def test_case_7_multi_org_isolation(client):
    org_a_id = _register_org(client, email="orga@acme.example")
    vendor_a = client.post(
        "/api/v1/vendors", json={"display_name": "Org A Vendor"}
    ).json()
    po_a = _make_po(client, "PO-A7", "10.00", vendor_a["id"])
    invoice_a = _make_invoice(
        client,
        invoice_number="INV-A7",
        vendor_id=vendor_a["id"],
        purchase_order_id=po_a,
        total_amount="10.00",
    )
    _assess(client, invoice_a["id"])
    document_a = client.post(
        "/api/v1/documents",
        files={"file": ("a7.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    ).json()

    # Switch to org B and probe org A's resources.
    client.cookies.clear()
    assert register_second_org(client, email="orgb@corp.example").status_code == 201
    foreign_ids = {
        "vendor": vendor_a["id"],
        "po": po_a,
        "invoice": invoice_a["id"],
        "document": document_a["id"],
    }
    assert client.get(f"/api/v1/vendors/{foreign_ids['vendor']}").status_code == 404
    assert client.get(f"/api/v1/purchase-orders/{foreign_ids['po']}").status_code == 404
    assert client.get(f"/api/v1/invoices/{foreign_ids['invoice']}").status_code == 404
    assert client.get(f"/api/v1/documents/{foreign_ids['document']}").status_code == 404
    assert (
        client.get(f"/api/v1/documents/{foreign_ids['document']}/file").status_code
        == 404
    )
    # Mutations against foreign ids are 404 too (no existence leak).
    assert (
        client.post(f"/api/v1/invoices/{foreign_ids['invoice']}/assess").status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/invoices/{foreign_ids['invoice']}/evidence"
        ).status_code
        == 404
    )
    # Org B's lists never contain org A rows.
    assert foreign_ids["invoice"] not in [
        i["id"] for i in client.get("/api/v1/invoices").json()
    ]
    assert foreign_ids["vendor"] not in [
        v["id"] for v in client.get("/api/v1/vendors").json()
    ]
    # Org B works in complete isolation: same names, independent records.
    vendor_b = client.post(
        "/api/v1/vendors", json={"display_name": "Org A Vendor"}  # same name OK
    ).json()
    assert vendor_b["id"] != vendor_a["id"]
    org_b_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    assert org_b_id != org_a_id

    # Back in org A: everything still there, nothing from B visible.
    client.cookies.clear()
    assert login(client, username="orga@acme.example").status_code == 200
    assert client.get(f"/api/v1/invoices/{invoice_a['id']}").status_code == 200
    assert vendor_b["id"] not in [v["id"] for v in client.get("/api/v1/vendors").json()]


# ----------------- 8. unauthorized account-change approval (R5 matrix) ------
def test_case_8_finance_officer_cannot_approve_account_change(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client, "Cambio Dos SA")
    change = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests",
        json={
            "account_holder_name": "New Details",
            "account_number": OTHER_IBAN,
            "bank_country": "GB",
            "reason": "Vendor claims a bank migration.",
        },
    )
    assert change.status_code == 201, change.text
    change_id = change.json()["id"]
    assert change.json()["status"] == "pending"

    # The finance_officer prepares payments but may NEVER decide R5 changes.
    add_user(org_id, "fin8@acme.example", "finance_officer")
    client.cookies.clear()
    assert login_as(client, "fin8@acme.example").status_code == 200
    assert (
        client.post(
            f"/api/v1/vendors/{vendor_id}/change-requests/{change_id}/approve",
            json={"resolution_note": "Self-approved."},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/vendors/{vendor_id}/change-requests/{change_id}/reject",
            json={},
        ).status_code
        == 403
    )
    # The same matrix line: no account verification either.
    account = client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "X", "account_number": "111122223333"},
    ).json()
    assert (
        client.post(
            f"/api/v1/vendors/{vendor_id}/bank-accounts/{account['id']}/verify",
            json={
                "verification_method": "registry_check",
                "verification_reference": "x",
            },
        ).status_code
        == 403
    )
    # The request is untouched by every denied attempt.
    client.cookies.clear()
    assert login(client, username="case-owner@acme.example").status_code == 200
    still = client.get(
        f"/api/v1/vendors/{vendor_id}/change-requests"
    ).json()
    assert [c["status"] for c in still if c["id"] == change_id] == ["pending"]

    # A reviewer (independent human, different from the requester) approves.
    add_user(org_id, "rev8@acme.example", "reviewer")
    client.cookies.clear()
    assert login_as(client, "rev8@acme.example").status_code == 200
    reviewer_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    approved = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{change_id}/approve",
        json={"resolution_note": "Callback confirmed with the known contact."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == reviewer_id

    def _resulting(session):
        from app.models import VendorBankAccount

        # The approval created a NEW account stamped with the deciding human
        # (the originally approved one was verified by the owner).
        rows = (
            session.query(VendorBankAccount)
            .filter(
                VendorBankAccount.vendor_id == uuid.UUID(vendor_id),
                VendorBankAccount.status == "approved",
                VendorBankAccount.verified_by == uuid.UUID(reviewer_id),
            )
            .all()
        )
        return [(r.status, r.verification_method, r.verification_reference) for r in rows]
    resulting = db_query(_resulting)
    assert len(resulting) == 1
    status, method, reference = resulting[0]
    assert status == "approved"
    assert method  # independent verification record mandatory (R5)
    # The R5 provenance pointer cites the change request that decided it.
    assert reference == f"change-request:{change_id}"
    # And the deciding note is on the change request itself (API surface).
    decided = client.get(
        f"/api/v1/vendors/{vendor_id}/change-requests"
    ).json()
    mine = [c for c in decided if c["id"] == change_id]
    assert mine[0]["resolution_note"] == "Callback confirmed with the known contact."


# ----------------- 9. reviewer resolves a case with justification -----------
def test_case_9_reviewer_resolves_case_with_justification(client):
    org_id = _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-CASE-9")
    assessment = _assess(client, invoice["id"])
    finding = assessment["findings"][0]

    add_user(org_id, "rev9@acme.example", "reviewer")
    client.cookies.clear()
    assert login_as(client, "rev9@acme.example").status_code == 200

    case = client.post(
        "/api/v1/cases",
        json={
            "title": "Investigate unknown vendor on INV-CASE-9",
            "severity": "medium",
            "invoice_id": invoice["id"],
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]

    noted = client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "comment",
            "body": "Called the requester; vendor exists but was never onboarded.",
        },
    )
    assert noted.status_code == 201, noted.text

    # Close is refused without the mandatory human outcome + summary.
    incomplete = client.post(
        f"/api/v1/cases/{case_id}/close", json={"outcome": "false_positive"}
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "validation_error"
    assert client.get(f"/api/v1/cases/{case_id}").json()["status"] == "open"

    closed = client.post(
        f"/api/v1/cases/{case_id}/close",
        json={
            "outcome": "false_positive",
            "resolution_summary": "Vendor onboarded retroactively; invoice "
            "checked against the signed contract. No fraud indicators remain.",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["outcome"] == "false_positive"

    # Closing twice is refused; the record is immutable after close.
    again = client.post(
        f"/api/v1/cases/{case_id}/close",
        json={"outcome": "inconclusive", "resolution_summary": "reopen attempt"},
    )
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "business_rule_violation"

    actions = client.get(f"/api/v1/cases/{case_id}/actions").json()
    # The human justifications are all on the record: the investigation note,
    # the close decision, and the resolution summary on the case row itself.
    assert any(
        "never onboarded" in a["body"] for a in actions
    ), [a["body"] for a in actions]
    assert any(
        "Case closed with outcome 'false_positive'" in a["body"] for a in actions
    )

    def _summary(session):
        from app.models import InvestigationCase

        row = session.get(InvestigationCase, uuid.UUID(case_id))
        return row.resolution_summary, str(row.closed_at is not None)
    resolution_summary, has_closed_at = db_query(_summary)
    assert "onboarded retroactively" in resolution_summary
    assert has_closed_at == "True"

    # The finding keeps its own disposition track (annotation, not a rewrite):
    # the automated assessment stays intact and the human reason is recorded.
    dispositioned = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed", "reason": "Resolved inside the case."},
    )
    assert dispositioned.status_code == 200, dispositioned.text
    latest = client.get(f"/api/v1/invoices/{invoice['id']}/assessment").json()
    assert latest["risk_level"] == assessment["risk_level"]  # never rewritten
    stamped = [f for f in latest["findings"] if f["id"] == finding["id"]]
    assert stamped[0]["disposition"] == "dismissed"


# ------------- 10. processing fails and retries without duplicates ----------
def test_case_10_processing_failure_and_retry_leaves_no_duplicates(
    client, monkeypatch, tmp_path
):
    """Provider misconfiguration fails the job loudly; re-upload dedups;
    POST /process retries the SAME job; no duplicate document/job/extraction
    rows are ever created."""
    from app.core.config import get_settings
    from app.modules.extraction import service as extraction_service

    pdf_path = tmp_path / "retry_case.pdf"
    gf._pdf(
        [
            "INVOICE",
            "Vendor: Retry Oy",
            "Invoice Number: INV-RETRY-10",
            "Invoice Date: 2026-10-01",
            "Currency: EUR",
            "Total: 42.00",
        ],
        pdf_path,
    )
    pdf_bytes = pdf_path.read_bytes()

    def _upload():
        return client.post(
            "/api/v1/documents",
            files={"file": ("retry_case.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"kind": "invoice"},
        )

    _register_org(client)

    # Step 1: a misconfigured OCR provider fails the inline job loudly.
    monkeypatch.setenv("VERIPAY_OCR_PROVIDER", "typo-provider")
    get_settings.cache_clear()
    failed = _upload()
    assert failed.status_code == 422, failed.text
    assert failed.json()["error"]["code"] == "business_rule_violation"

    listing = client.get("/api/v1/documents").json()
    assert len(listing) == 1  # the document row WAS persisted
    document_id = listing[0]["id"]
    assert listing[0]["processing_status"] == "failed"

    def _counts(session):
        from sqlalchemy import select

        from app.models import Document, ExtractionResult, ProcessingJob

        doc = session.get(Document, uuid.UUID(document_id))
        jobs = session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.document_id == doc.id,
                ProcessingJob.organization_id == doc.organization_id,
            )
        ).all()
        results = session.scalars(
            select(ExtractionResult).where(
                ExtractionResult.document_id == doc.id,
                ExtractionResult.organization_id == doc.organization_id,
            )
        ).all()
        return len(jobs), [j.status for j in jobs], [j.attempts for j in jobs], len(results)

    jobs, statuses, attempts, results = db_query(_counts)
    assert jobs == 1 and results == 1
    assert statuses == ["failed"] and attempts == [1]

    # Step 2: re-uploading the same bytes dedups — no second document.
    monkeypatch.undo()
    get_settings.cache_clear()
    reupload = _upload()
    assert reupload.status_code == 200, reupload.text
    assert reupload.json()["deduplicated"] is True
    assert reupload.json()["id"] == document_id

    def _doc_count(session):
        from app.models import Document

        doc = session.get(Document, uuid.UUID(document_id))
        return (
            session.query(Document)
            .filter(
                Document.organization_id == doc.organization_id,
                Document.sha256 == doc.sha256,
            )
            .count()
        )
    assert db_query(_doc_count) == 1

    # Step 3: the idempotent retry heals the document — SAME job row.
    retried = client.post(f"/api/v1/documents/{document_id}/process")
    assert retried.status_code == 200, retried.text
    assert retried.json()["job_status"] == "completed"
    assert retried.json()["processing_status"] == "completed"

    jobs_after, statuses_after, attempts_after, results_after = db_query(_counts)
    assert jobs_after == 1  # no duplicate job rows
    assert statuses_after == ["completed"]
    assert attempts_after == [2]  # the retry, on the same row
    assert results_after == 1  # fields-v1 upserted in place, never duplicated
    fields = client.get(f"/api/v1/documents/{document_id}/fields").json()
    assert {f["field_name"] for f in fields} >= {"vendor_name", "total"}
    # The extraction version is the durable single one.
    extraction = client.get(f"/api/v1/documents/{document_id}/extraction").json()
    assert extraction["extraction_version"] == extraction_service.EXTRACTION_VERSION
