"""Prompt-04 EVC — the 9 brief scenarios as executable tests + policy and
override-flow guarantees.

THE LABELED SET IN ``test_synthetic_labeled_set_metrics`` IS SYNTHETIC: every
case is constructed by hand to be separable, so the FP/FN rates below assert
the harness works — they say nothing about real-world performance.

Scenarios (from the brief):
  1. normal/trusted                          → no_material_discrepancies
  2. new unauthorized account                → high_risk_discrepancy (floor high)
  3. duplicate                               → review_required (medium)
  4. near-duplicate (field overlap)          → review_required (medium)
  5. unknown vendor                          → review_required (override)
  6. PO amount mismatch                      → high_risk_discrepancy
  7. OCR failure                             → review_required + manual flag
  8. missing evidence                        → insufficient_evidence, ≤ medium
  9. independently approved account change   → bank verified_agreement

Expected EVC contributions (policy evc-1.0 weights × severity factors):
  bank high 30×1.0=30 · PO high 25×1.0=25 · duplicate medium 15×0.7=10.5
  identity medium 10×0.7=7 · history medium 5×0.7=3.5 · untrusted medium
  15×0.7=10.5 · any low severity uses factor 0.35.
"""

import io
import uuid

import pytest

from helpers import db_query, register
from role_helpers import add_user, login_as

PDF_BYTES = b"%PDF-1.4\nEVC scenario document\n"
APPROVED_IBAN = "DE89370400440532013000"
OTHER_IBAN = "GB29NWBK60161331926819"


# --------------------------------------------------------------- helpers ----
def _register_org(client) -> str:
    assert register(client).status_code == 201
    return client.get("/api/v1/auth/me").json()["user"]["organization_id"]


def _add_reviewer(client, org_id: str) -> str:
    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    assert login_as(client, "rev@acme.example").status_code == 200
    me = client.get("/api/v1/auth/me").json()
    return me["user"]["id"]


def _vendor_with_approved_account(client, name: str = "Trusted Vendor Ltd",
                                  iban: str = APPROVED_IBAN) -> tuple[str, str]:
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": name}
    ).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": name,
            "account_number": iban,
            "bank_country": "DE",
        },
    ).json()
    response = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "written_confirmation",
            "verification_reference": "Signed bank letter on file.",
        },
    )
    assert response.status_code == 200, response.text
    return vendor["id"], account["id"]


def _make_po(client, number: str, amount: str, currency: str = "EUR") -> str:
    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": number, "amount": amount, "currency": currency},
    )
    assert po.status_code == 201, po.text
    return po.json()["id"]


def _make_invoice(client, **overrides) -> dict:
    payload = {"invoice_number": "INV-001", "currency": "EUR"}
    payload.update(overrides)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _assess(client, invoice_id: str) -> dict:
    response = client.post(f"/api/v1/invoices/{invoice_id}/assess")
    assert response.status_code == 200, response.text
    return response.json()


def _invoice_status(client, invoice_id: str) -> str:
    return client.get(f"/api/v1/invoices/{invoice_id}").json()["status"]


def _feature(evc: dict, key: str) -> dict:
    return evc["features"][key]


# -------------------------------------------------- 1. normal / trusted -----
def test_scenario_1_normal_trusted_is_no_material_discrepancy(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-1", "1250.00")
    invoice = _make_invoice(
        client,
        vendor_id=vendor_id,
        purchase_order_id=po_id,
        total_amount="1250.00",
        remittance_account_raw=APPROVED_IBAN,
        remittance_bank_name_raw="Deutsche Bank",
    )
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    assert evc is not None
    assert evc["policy_version"] == "evc-1.0"
    assert evc["result_state"] == "no_material_discrepancies"
    assert body["risk_level"] in ("none", "low")
    assert evc["score"] == 0.0
    assert evc["overrides"] == []
    assert _feature(evc, "bank_account_consistency")["state"] == "verified_agreement"
    assert _feature(evc, "po_mismatch")["state"] == "verified_agreement"
    assert _feature(evc, "identity_consistency")["state"] == "insufficient_evidence"
    # Uncertainty is reported, never hidden — and never scored.
    assert "identity_consistency" in evc["uncertainty"]["features_insufficient"]
    # No forcing: the invoice keeps its status (no review demanded).
    assert _invoice_status(client, invoice["id"]) == "received"
    weights = evc["features"]["bank_account_consistency"]["weight"]
    assert weights == 30.0 and sum(evc["weights"].values()) == 100.0


# ------------------------------- 2. new unauthorized (unverified) account ---
def test_scenario_2_new_unauthorized_account_forces_review(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    invoice = _make_invoice(
        client,
        vendor_id=vendor_id,
        total_amount="1250.00",
        remittance_account_raw=OTHER_IBAN,  # NOT the approved account
    )
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    bank = _feature(evc, "bank_account_consistency")
    assert bank["state"] == "confirmed_discrepancy"
    assert bank["severity"] == "high"
    assert bank["contribution"] == 30.0
    types = [f["signal_type"] for f in body["findings"]]
    assert "bank_account_unverified" in types
    floor = [f for f in body["findings"] if f["signal_type"] == "bank_account_unverified"]
    assert floor[0]["severity"] == "high"  # §8.5 floor — never downgraded
    assert evc["result_state"] == "high_risk_discrepancy"
    assert body["risk_level"] == "high"
    overrides = [o["override"] for o in evc["overrides"]]
    assert "unverified_payment_destination" in overrides
    assert _invoice_status(client, invoice["id"]) == "needs_review"
    # A single high discrepancy is NOT critical (no auto-case, R6 needs two).
    cases = client.get("/api/v1/cases").json()["items"]
    assert cases == []
    # A PENDING account with the same fingerprint is recorded as a collision.
    client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "V", "account_number": OTHER_IBAN},
    )
    body2 = _assess(client, invoice["id"])  # re-assessment (append-only)
    bank2 = _feature(body2["evc"], "bank_account_consistency")
    assert bank2["observations"]["non_approved_collisions"]
    def _bank_match(session):
        from app.models import EvidenceMatch

        return [
            m.match_kind
            for m in session.query(EvidenceMatch)
            .filter(
                EvidenceMatch.organization_id == uuid.UUID(org_id),
                EvidenceMatch.match_kind == "bank_account",
            )
            .all()
        ]
    assert "bank_account" in db_query(_bank_match)


# ------------------------------------------------------- 3. duplicate -------
def test_scenario_3_duplicate_upload_is_review_required(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    base = dict(
        vendor_id=vendor_id,
        total_amount="500.00",
        invoice_date="2026-06-01",
        remittance_account_raw=APPROVED_IBAN,
    )
    first = _make_invoice(client, invoice_number="INV-DUP", **base)
    second = _make_invoice(client, invoice_number="INV-DUP", **base)
    assert first["id"] != second["id"]  # intake allowed 201 — signal, not 409
    body = _assess(client, second["id"])
    evc = body["evc"]
    dup = _feature(evc, "duplicate_indicators")
    assert dup["state"] == "confirmed_discrepancy"
    assert dup["severity"] == "medium"
    assert dup["contribution"] == pytest.approx(10.5)
    assert dup["observations"]["classifications"] == ["duplicate_upload"]
    dupe_findings = [f for f in body["findings"] if f["signal_type"] == "duplicate_candidate"]
    assert dupe_findings and dupe_findings[0]["severity"] == "medium"
    assert dupe_findings[0]["evidence_refs"] == [first["id"]]
    assert evc["result_state"] == "review_required"
    assert body["risk_level"] == "medium"
    assert evc["score"] == pytest.approx(10.5)
    assert _invoice_status(client, second["id"]) == "needs_review"

    def _match(session):
        from app.models import EvidenceMatch

        return [
            (m.match_kind, m.status)
            for m in session.query(EvidenceMatch)
            .filter(
                EvidenceMatch.organization_id == uuid.UUID(org_id),
                EvidenceMatch.match_kind == "invoice_number",
            )
            .all()
        ]
    kinds = db_query(_match)
    assert kinds and all(status == "open" for _k, status in kinds)


def test_duplicate_number_normalization_matches_across_spellings(client):
    """INV-2024/007 ≡ inv 2024 007 ≡ INV2024007 (normalized-number axis)."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    _make_invoice(
        client, invoice_number="INV-2024/007", vendor_id=vendor_id,
        total_amount="10.00",
    )
    second = _make_invoice(
        client, invoice_number="inv 2024 007", vendor_id=vendor_id,
        total_amount="10.00",
    )
    body = _assess(client, second["id"])
    dup = _feature(body["evc"], "duplicate_indicators")
    assert dup["state"] == "confirmed_discrepancy"
    assert dup["observations"]["classifications"] == ["duplicate_upload"]


def test_duplicate_across_vendor_records_needs_entity_match(client):
    """Same number, two DIFFERENT vendor records: the pair only counts when
    the retrieval module's vendor entity match ties them together."""
    _register_org(client)
    vendor_a, _a = _vendor_with_approved_account(client, "Alpha Trading Ltd")
    vendor_b, _b = _vendor_with_approved_account(client, "Alpha Trading Company")
    _make_invoice(
        client, invoice_number="INV-9", vendor_id=vendor_a, total_amount="70.00",
    )
    second = _make_invoice(
        client, invoice_number="INV-9", vendor_id=vendor_b, total_amount="70.00",
    )
    body = _assess(client, second["id"])
    dup = _feature(body["evc"], "duplicate_indicators")
    assert dup["state"] == "confirmed_discrepancy"  # entity-matched pair


def test_same_number_different_unrelated_vendors_is_not_a_duplicate(client):
    """Generic numbers ('001') across unrelated vendors must not fire."""
    _register_org(client)
    vendor_a, _a = _vendor_with_approved_account(client, "Helios Manufacturing SA")
    vendor_b, _b = _vendor_with_approved_account(client, "Nordwind Logistik GmbH")
    _make_invoice(
        client, invoice_number="001", vendor_id=vendor_a, total_amount="70.00",
    )
    second = _make_invoice(
        client, invoice_number="001", vendor_id=vendor_b, total_amount="70.00",
    )
    body = _assess(client, second["id"])
    dup = _feature(body["evc"], "duplicate_indicators")
    assert dup["state"] == "verified_agreement"


def test_corrected_version_is_low_not_medium(client):
    """Same normalized number, amount differs, strictly newer date → a
    corrected-version candidate (low): human-confirmed, not scored like a
    duplicate upload."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    _make_invoice(
        client, invoice_number="INV-COR", vendor_id=vendor_id,
        total_amount="100.00", invoice_date="2026-01-10",
    )
    corrected = _make_invoice(
        client, invoice_number="INV-COR", vendor_id=vendor_id,
        total_amount="150.00", invoice_date="2026-02-20",
    )
    body = _assess(client, corrected["id"])
    dup = _feature(body["evc"], "duplicate_indicators")
    assert dup["observations"]["classifications"] == ["corrected_version_candidate"]
    corrected_findings = [
        f for f in body["findings"] if f["signal_type"] == "duplicate_candidate"
    ]
    assert corrected_findings[0]["severity"] == "low"
    assert dup["severity"] == "low"
    assert dup["contribution"] == pytest.approx(15.0 * 0.35)


# -------------------------------------------------- 4. near-duplicate -------
def test_scenario_4_near_duplicate_field_overlap(client):
    """Distinct numbers, same vendor/amount/currency/date/pay-to →
    near_duplicate (medium): appearance similarity is a duplicate INDICATOR,
    never authenticity."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    base = dict(
        vendor_id=vendor_id, total_amount="300.00", invoice_date="2026-06-02",
        remittance_account_raw=APPROVED_IBAN,
    )
    first = _make_invoice(client, invoice_number="INV-ND-1", **base)
    _ = first  # the earlier member of the pair
    second = _make_invoice(client, invoice_number="INV-ND-2", **base)
    body = _assess(client, second["id"])
    evc = body["evc"]
    dup = _feature(evc, "duplicate_indicators")
    assert dup["state"] == "confirmed_discrepancy"
    assert dup["observations"]["classifications"] == ["near_duplicate"]
    assert dup["contribution"] == pytest.approx(10.5)

    def _near_match(session):
        from app.models import EvidenceMatch

        rows = (
            session.query(EvidenceMatch)
            .filter(EvidenceMatch.match_kind == "near_duplicate")
            .all()
        )
        return [
            (m.matched_fields.get("axis"), m.similarity_score) for m in rows
        ]
    axes = db_query(_near_match)
    assert any(axis and "field overlap" in axis and score >= 0.75
               for axis, score in axes)
    assert evc["result_state"] == "review_required"
    assert _invoice_status(client, second["id"]) == "needs_review"


# ---------------------------------------------------- 5. unknown vendor -----
def test_scenario_5_unknown_vendor_requires_review(client):
    _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-NOVENDOR")
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    identity = _feature(evc, "identity_consistency")
    assert identity["state"] == "insufficient_evidence"
    assert identity["contribution"] == 0.0  # unknown is never scored
    types = [f["signal_type"] for f in body["findings"]]
    assert "unknown_vendor" in types
    unknown = [f for f in body["findings"] if f["signal_type"] == "unknown_vendor"]
    assert unknown[0]["severity"] == "medium"  # capped — not a fraud claim
    overrides = [o["override"] for o in evc["overrides"]]
    assert "unknown_vendor" in overrides
    assert evc["result_state"] == "review_required"
    assert body["risk_level"] == "medium"
    assert _invoice_status(client, invoice["id"]) == "needs_review"


# ------------------------------------------------- 6. PO amount mismatch ----
def test_scenario_6_po_amount_mismatch_is_high_risk(client):
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-2", "1000.00")
    invoice = _make_invoice(
        client, vendor_id=vendor_id, purchase_order_id=po_id,
        total_amount="2500.00", remittance_account_raw=APPROVED_IBAN,
    )
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    po = _feature(evc, "po_mismatch")
    assert po["state"] == "confirmed_discrepancy"
    assert po["severity"] == "high"
    assert po["contribution"] == 25.0
    mismatch = [f for f in body["findings"] if f["signal_type"] == "amount_mismatch"]
    assert mismatch and mismatch[0]["severity"] == "high"
    assert evc["result_state"] == "high_risk_discrepancy"
    assert body["risk_level"] == "high"
    assert _invoice_status(client, invoice["id"]) == "needs_review"


def test_two_high_discrepancies_are_critical_and_open_a_case(client):
    """Unverified destination + PO mismatch → risk critical → R6 auto-case."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-3", "1000.00")
    invoice = _make_invoice(
        client, vendor_id=vendor_id, purchase_order_id=po_id,
        total_amount="2500.00", remittance_account_raw=OTHER_IBAN,
    )
    body = _assess(client, invoice["id"])
    assert body["risk_level"] == "critical"
    cases = client.get("/api/v1/cases").json()["items"]
    assert len(cases) == 1
    assert cases[0]["triggering_assessment_id"] == body["id"]
    assert cases[0]["severity"] == "critical"


# ----------------------------------------------------- 7. OCR failure -------
def test_scenario_7_ocr_failure_requires_manual_verification(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("broken.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    def _fail_document(session):
        from app.models import Document

        doc = session.get(Document, uuid.UUID(document_id))
        doc.processing_status = "failed"
        doc.processing_error = "synthetic OCR failure (test)"
        session.commit()
    db_query(_fail_document)

    invoice = _make_invoice(
        client, vendor_id=vendor_id, source_document_id=document_id,
        total_amount="100.00",
    )
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    types = [f["signal_type"] for f in body["findings"]]
    assert "ocr_uncertain" in types
    assert evc["manual_verification_required"] is True
    assert "ocr_uncertain" in [o["override"] for o in evc["overrides"]]
    assert evc["result_state"] == "review_required"
    assert body["risk_level"] == "medium"
    assert _invoice_status(client, invoice["id"]) == "needs_review"
    assert any("Manual verification" in line for line in body["explanation"])


def test_below_gate_critical_fields_flag_manual_verification(client):
    """Payment-critical values that exist only through below-gate OCR are
    critical OCR uncertainty (R3) — manual verification flag + review."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("blur.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )
    document_id = upload.json()["id"]

    def _seed_uncertain_total(session):
        from datetime import datetime, timezone

        from app.models import Document, ExtractionField, ExtractionResult

        doc = session.get(Document, uuid.UUID(document_id))
        result = ExtractionResult(
            organization_id=doc.organization_id,
            document_id=doc.id,
            extraction_version="provider-v9",
            status="completed",
            # Explicit timestamp strictly later than the inline run, so
            # get_result() (latest by created_at) picks this one despite
            # SQLite's second-resolution CURRENT_TIMESTAMP.
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
    db_query(_seed_uncertain_total)

    invoice = _make_invoice(
        client, vendor_id=vendor_id, source_document_id=document_id,
        total_amount="100.00",  # human-entered column wins; provenance disagrees
    )
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    assert evc["manual_verification_required"] is True
    types = [f["signal_type"] for f in body["findings"]]
    assert "ocr_uncertain" in types           # critical value read below gate
    assert "field_provenance_conflict" in types  # column vs provenance
    untrusted = _feature(evc, "untrusted_source_indicators")
    assert untrusted["state"] in ("confirmed_discrepancy", "insufficient_evidence")
    assert untrusted["observations"]["critical_below_gate"] == ["total_amount"]


# ------------------------------------------------- 8. missing evidence ------
def test_scenario_8_missing_evidence_is_insufficient_and_capped(client):
    org_id = _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    invoice = _make_invoice(client, vendor_id=vendor_id)  # no PO, no remittance
    body = _assess(client, invoice["id"])
    evc = body["evc"]
    missing = [f for f in body["findings"] if f["signal_type"] == "missing_evidence"]
    assert missing
    assert all(f["severity"] in ("low", "medium") for f in missing)  # R4 cap
    for key in ("po_mismatch", "bank_account_consistency", "historical_anomalies"):
        assert _feature(evc, key)["state"] == "insufficient_evidence"
        assert _feature(evc, key)["contribution"] == 0.0
    assert evc["score"] == 0.0
    # Unknown is never scored as safe: risk is low (uncertainty), and the
    # explanation carries the uncertainty note.
    assert body["risk_level"] == "low"
    assert evc["result_state"] == "no_material_discrepancies"
    assert any("neither evidence of fraud nor of correctness" in line
               for line in body["explanation"])
    assert _invoice_status(client, invoice["id"]) == "received"  # no forcing


# ------------------------- 9. independently approved account change ---------
def test_scenario_9_independently_approved_account_change_verifies(client):
    org_id = _register_org(client)
    requester_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    vendor_id, _account_id = _vendor_with_approved_account(client)
    # Invoice #1 pays the originally-approved account: verified.
    first = _make_invoice(
        client, vendor_id=vendor_id, total_amount="80.00",
        remittance_account_raw=APPROVED_IBAN,
    )
    body1 = _assess(client, first["id"])
    assert _feature(body1["evc"], "bank_account_consistency")["state"] == (
        "verified_agreement"
    )

    # A change request is filed, then approved by a DIFFERENT human
    # (reviewer role) — the machine can never approve it.
    client.post(
        f"/api/v1/vendors/{vendor_id}/bank-accounts",
        json={"account_holder_name": "New Bank Details", "account_number": OTHER_IBAN},
    )
    change = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests",
        json={
            "account_holder_name": "New Bank Details",
            "account_number": OTHER_IBAN,
            "bank_country": "GB",
            "reason": "Vendor migrated banks; letter attached.",
        },
    )
    assert change.status_code == 201, change.text
    change_id = change.json()["id"]
    # finance_officer cannot approve (R5 matrix).
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    assert client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{change_id}/approve",
        json={},
    ).status_code == 403

    reviewer_id = _add_reviewer(client, org_id)
    approved = client.post(
        f"/api/v1/vendors/{vendor_id}/change-requests/{change_id}/approve",
        json={"resolution_note": "Callback confirmed with known contact."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] not in (None, requester_id)

    def _new_account(session):
        from app.models import VendorBankAccount

        rows = (
            session.query(VendorBankAccount)
            .filter(
                VendorBankAccount.vendor_id == uuid.UUID(vendor_id),
                VendorBankAccount.status == "approved",
                VendorBankAccount.verified_by.isnot(None),
            )
            .all()
        )
        return sorted(
            (str(r.verified_by), r.verification_method, r.verification_reference)
            for r in rows
        )
    verification_records = db_query(_new_account)
    assert any(v_by == reviewer_id for v_by, _m, _r in verification_records)

    # Invoice #2 pays the newly-approved account: verified_agreement again —
    # because a human approved it, never because an invoice said so.
    second = _make_invoice(
        client, vendor_id=vendor_id, total_amount="120.00",
        remittance_account_raw=OTHER_IBAN,
    )
    body2 = _assess(client, second["id"])
    bank2 = _feature(body2["evc"], "bank_account_consistency")
    assert bank2["state"] == "verified_agreement"
    types = [f["signal_type"] for f in body2["findings"]]
    assert "bank_account_unverified" not in types


# --------------------------------- policy engine & override-flow guarantees --
def test_policy_loader_refuses_weakened_invariant_floors():
    """A policy edit cannot weaken the machine-enforced floors (R4/R5)."""
    from app.core.errors import AppError
    from app.modules.fraud import policy as policy_module

    tampered = {
        "policy_version": "evc-1.0",
        "weights": {k: 100.0 / 6 for k in policy_module.FEATURE_KEYS},
        "thresholds": {"review_required": 30, "high_risk": 60},
        "severity_factors": {"low": 0.35, "medium": 0.7, "high": 1.0},
        "critical_rule": {"min_high_signals": 2},
        "signals": {
            "default_severities": {},
            "severity_floors": {},  # ← weakened: floor removed
            "severity_caps": {"missing_evidence": "medium"},
            "override_minimum_result": policy_module.INVARIANT_OVERRIDE_MINIMUM_RESULT,
        },
    }
    with pytest.raises(AppError):
        policy_module._validate(tampered)
    tampered["signals"]["severity_floors"] = dict(policy_module.INVARIANT_SEVERITY_FLOORS)
    tampered["signals"]["severity_caps"] = {"missing_evidence": "high"}  # ← cap raised
    with pytest.raises(AppError):
        policy_module._validate(tampered)


def test_severity_floor_is_machine_enforced():
    from app.modules.fraud.evc import SignalType, _clamp_severity
    from app.modules.fraud.policy import load_policy

    policy = load_policy()
    clamped = _clamp_severity(SignalType.BANK_ACCOUNT_UNVERIFIED, "low", policy)
    assert clamped == "high"
    capped = _clamp_severity(SignalType.MISSING_EVIDENCE, "high", policy)
    assert capped == "medium"


def test_disposition_requires_a_reason_and_writes_review_action(client):
    org_id = _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-OVR")
    body = _assess(client, invoice["id"])
    finding = body["findings"][0]

    missing_reason = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed"},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["error"]["code"] == "validation_error"

    blank_note = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed", "note": "   "},
    )
    assert blank_note.status_code == 422

    ok = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed", "reason": "Vendor confirmed on callback."},
    )
    assert ok.status_code == 200, ok.text

    def _action(session):
        from app.models import ReviewAction

        row = (
            session.query(ReviewAction)
            .filter(ReviewAction.organization_id == uuid.UUID(org_id))
            .order_by(ReviewAction.created_at.desc())
            .first()
        )
        return (
            row.case_id,
            row.action_type,
            row.body,
            row.payload.get("finding_id"),
            row.payload.get("to"),
        )
    case_id, action_type, body_text, finding_ref, to_state = db_query(_action)
    assert case_id is None  # no case context — recorded case-less
    assert action_type == "decision"
    assert body_text == "Vendor confirmed on callback."
    assert finding_ref == finding["id"] and to_state == "dismissed"


def test_disposition_anchors_to_case_when_given(client):
    org_id = _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-CASED")
    body = _assess(client, invoice["id"])
    case = client.post(
        "/api/v1/cases",
        json={"title": "Investigate", "severity": "medium", "invoice_id": invoice["id"]},
    ).json()
    finding = body["findings"][0]
    ok = client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "acknowledged", "reason": "Tracing the payment.", "case_id": case["id"]},
    )
    assert ok.status_code == 200

    def _actions(session):
        from app.models import ReviewAction

        return [
            (str(r.case_id), r.body)
            for r in session.query(ReviewAction)
            .filter(ReviewAction.organization_id == uuid.UUID(org_id))
            .all()
        ]
    actions = db_query(_actions)
    assert any(case_id == case["id"] and "Tracing the payment." in body_text
               for case_id, body_text in actions)
    # The case actions feed exposes it too.
    feed = client.get(f"/api/v1/cases/{case['id']}/actions").json()["items"]
    assert any("Tracing the payment." in a["body"] for a in feed)


def test_original_assessment_and_evidence_preserved_immutably(client):
    """The override flow is additive: the original automated assessment + the
    evidence it cited are byte-identical after human dispositions."""
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    base = dict(vendor_id=vendor_id, total_amount="500.00",
                invoice_date="2026-06-01", remittance_account_raw=APPROVED_IBAN)
    _make_invoice(client, invoice_number="INV-IMM", **base)
    second = _make_invoice(client, invoice_number="INV-IMM", **base)
    before = _assess(client, second["id"])
    snapshot = {k: before[k] for k in ("evc", "signals", "explanation", "risk_level",
                                       "risk_score", "model_version")}
    finding = next(
        f for f in before["findings"] if f["signal_type"] == "duplicate_candidate"
    )
    assert client.post(
        f"/api/v1/findings/{finding['id']}/disposition",
        json={"disposition": "dismissed", "reason": "Corrected re-issue, confirmed."},
    ).status_code == 200

    after = client.get(f"/api/v1/invoices/{second['id']}/assessment").json()
    for key, value in snapshot.items():
        assert after[key] == value  # unchanged — dispositions never rewrite
    # The disposition is visible on the finding, not on the assessment.
    stamped = [f for f in after["findings"] if f["id"] == finding["id"]]
    assert stamped[0]["disposition"] == "dismissed"
    # Match review also leaves detection evidence intact.
    def _match_id(session):
        from app.models import EvidenceMatch

        row = (
            session.query(EvidenceMatch)
            .filter(EvidenceMatch.match_kind == "invoice_number")
            .first()
        )
        return str(row.id), row.matched_fields
    match_id, matched_fields = db_query(_match_id)
    assert client.post(
        f"/api/v1/matches/{match_id}/review",
        json={"status": "confirmed", "reason": "Second billing confirmed."},
    ).status_code == 200
    fetched = client.get(f"/api/v1/matches/{match_id}").json()
    assert fetched["matched_fields"] == matched_fields  # evidence intact
    assert fetched["status"] == "confirmed"


def test_assessment_vocabulary_never_claims_genuineness(client):
    """R2: no is_fraud/is_genuine anywhere in the EVC surface."""
    _register_org(client)
    invoice = _make_invoice(client, invoice_number="INV-R2")
    body = _assess(client, invoice["id"])
    raw = str(body).lower()
    assert "is_genuine" not in raw and "is_fraud" not in raw
    assert body["explanation"][-1].endswith(
        "never certifies an invoice as genuine."
    )


# ------------------------------------------------- synthetic labeled set ----
def test_synthetic_labeled_set_metrics(client):
    """FP rate / FN rate / manual-review rate on a LABELED SYNTHETIC set.

    HONESTY LABEL: this set is hand-constructed to be separable — the rates
    assert the EVC harness wires features → states → forcing correctly. They
    are NOT real-world performance estimates.
    Labels: normals must NOT be flagged (result_state stays
    no_material_discrepancies); fraud patterns MUST be flagged (review_required
    or high_risk_discrepancy). The OCR-failure case is review-needed-by-design
    — counted in the manual-review rate, excluded from FP/FN denominators.
    """
    _register_org(client)
    vendor_id, _account_id = _vendor_with_approved_account(client)
    po_id = _make_po(client, "PO-M1", "100.00")

    labeled = {"normal": [], "fraud": [], "review_by_design": []}

    def _assess_and_label(label, invoice):
        body = _assess(client, invoice["id"])
        labeled[label].append((invoice["invoice_number"], body))
        return body

    # --- normals ------------------------------------------------------------
    # N1: trusted full pipeline.
    n1 = _make_invoice(
        client, invoice_number="M-N1", vendor_id=vendor_id,
        purchase_order_id=po_id, total_amount="100.00",
        invoice_date="2026-01-01", remittance_account_raw=APPROVED_IBAN,
    )
    _assess_and_label("normal", n1)
    # N2: no PO linked (evidence gap, not fraud).
    n2 = _make_invoice(
        client, invoice_number="M-N2", vendor_id=vendor_id, total_amount="100.00",
        invoice_date="2026-02-15", remittance_account_raw=APPROVED_IBAN,
    )
    _assess_and_label("normal", n2)
    # N3 series: consistent history (amounts equal, dates 45+ days apart so
    # the near-duplicate window never fires).
    for i, day in enumerate(("2026-03-30", "2026-05-15", "2026-07-01", "2026-08-20"), 1):
        inv = _make_invoice(
            client, invoice_number=f"M-N3-{i}", vendor_id=vendor_id,
            purchase_order_id=po_id, total_amount="100.00", invoice_date=day,
            remittance_account_raw=APPROVED_IBAN,
        )
        _assess_and_label("normal", inv)
    # N4: no remittance printed, no PO — pure insufficient evidence.
    n4 = _make_invoice(
        client, invoice_number="M-N4", vendor_id=vendor_id, total_amount="100.00",
    )
    _assess_and_label("normal", n4)

    # --- fraud patterns -----------------------------------------------------
    # F1: new unauthorized account.
    f1 = _make_invoice(
        client, invoice_number="M-F1", vendor_id=vendor_id, total_amount="100.00",
        remittance_account_raw=OTHER_IBAN,
    )
    _assess_and_label("fraud", f1)
    # F2: duplicate upload (the second member is the fraud pattern). The pair
    # lives on its OWN vendor so the history feature's median reflects the
    # pair's amounts; dates stay > 7 days from every other amount-differing
    # pair so the field-overlap axis (same payee + close date) never fires.
    vendor_dup, _dup_account = _vendor_with_approved_account(client, "Metric Dup Vendor")
    f2a = _make_invoice(
        client, invoice_number="M-F2", vendor_id=vendor_dup, total_amount="500.00",
        invoice_date="2026-09-01",
    )
    _assess_and_label("normal", f2a)
    f2b = _make_invoice(
        client, invoice_number="M-F2", vendor_id=vendor_dup, total_amount="500.00",
        invoice_date="2026-09-01",
    )
    _assess_and_label("fraud", f2b)
    # F3: near-duplicate pair under distinct numbers, own vendor + pay-to.
    vendor_nd, _nd_account = _vendor_with_approved_account(client, "Metric Near Vendor")
    f3a = _make_invoice(
        client, invoice_number="M-F3-A", vendor_id=vendor_nd, total_amount="300.00",
        invoice_date="2026-10-01", remittance_account_raw=APPROVED_IBAN,
    )
    _assess_and_label("normal", f3a)
    f3b = _make_invoice(
        client, invoice_number="M-F3-B", vendor_id=vendor_nd, total_amount="300.00",
        invoice_date="2026-10-01", remittance_account_raw=APPROVED_IBAN,
    )
    _assess_and_label("fraud", f3b)
    # F4: PO amount mismatch.
    po2 = _make_po(client, "PO-M2", "1000.00")
    f4 = _make_invoice(
        client, invoice_number="M-F4", vendor_id=vendor_id, purchase_order_id=po2,
        total_amount="2500.00", remittance_account_raw=APPROVED_IBAN,
    )
    _assess_and_label("fraud", f4)
    # F5: unknown vendor.
    f5 = _make_invoice(client, invoice_number="M-F5")
    _assess_and_label("fraud", f5)

    # --- review-needed-by-design (neither fraud nor clean) ------------------
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("broken-m.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )
    document_id = upload.json()["id"]

    def _fail(session):
        from app.models import Document

        doc = session.get(Document, uuid.UUID(document_id))
        doc.processing_status = "failed"
        session.commit()
    db_query(_fail)
    o1 = _make_invoice(
        client, invoice_number="M-O1", vendor_id=vendor_id,
        source_document_id=document_id, total_amount="100.00",
    )
    _assess_and_label("review_by_design", o1)

    def flagged(body) -> bool:
        return body["evc"]["result_state"] != "no_material_discrepancies"

    false_positives = [name for name, body in labeled["normal"] if flagged(body)]
    missed = [name for name, body in labeled["fraud"] if not flagged(body)]
    total = sum(len(v) for v in labeled.values())
    flagged_count = sum(
        1 for items in labeled.values() for _n, body in items if flagged(body)
    )
    fp_rate = len(false_positives) / len(labeled["normal"])
    fn_rate = len(missed) / len(labeled["fraud"])
    manual_review_rate = flagged_count / total

    # SYNTHETIC-set expectations (separable by construction).
    assert false_positives == [], f"FPs: {false_positives}"
    assert missed == [], f"FNs: {missed}"
    assert fp_rate == 0.0
    assert fn_rate == 0.0
    assert manual_review_rate == pytest.approx(6 / 15)