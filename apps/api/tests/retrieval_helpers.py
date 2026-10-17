"""Seeding helpers for the retrieval (Prompt-03) test suite.

Synthetic, honestly labeled data built through the real API where the API is
the write path (vendors, accounts, POs, invoices, cases, documents) and
directly through the org-scoped models where only the DB can express it
(extraction fields with spans/confidence — the R3 evidence units).

Every org is seeded the same way, so tenant-isolation tests can create org B
with IDENTICAL names/numbers and prove no leakage.
"""

import io
import uuid

from helpers import db_query, register

PDF_BYTES = b"%PDF-1.4\nretrieval test document\n"

NOUR_DISPLAY = "Nour Trading Co."
NOUR_LEGAL_AR = "شركة النور للتجارة"
NOUR_TAX = "TAX-9911"
NOUR_IBAN = "DE89370400440532013000"
ACME_DISPLAY = "Acme Industrial GmbH"
ZAHRA_DISPLAY = "Zahra Foods Ltd"
DELTA_DISPLAY = "Delta Logistics"

PO_NOUR = "PO-2026-001"
PO_ACME = "PO-2026-002"
INV_NOUR = "INV-2026-0007"
INV_ACME = "INV-2026-0008"
INV_ZAHRA = "INV-2026-0009"
INV_DELTA = "INV-2025-0301"


def register_org(client, email: str = "dana@acme.example") -> dict:
    response = register(client, email=email)
    assert response.status_code == 201, response.text
    me = client.get("/api/v1/auth/me").json()
    return {
        "org_id": me["user"]["organization_id"],
        "user_id": me["user"]["id"],
        "email": email,
    }


def _add_extraction_fields(
    org_id: str, document_id: str, invoice_id: str | None
) -> dict:
    """Insert one extraction result + its fields directly (R3 evidence units
    with spans, confidence, and human-verification state)."""

    def _create(session):
        from app.models import ExtractionField, ExtractionResult

        result = ExtractionResult(
            organization_id=uuid.UUID(org_id),
            document_id=uuid.UUID(document_id),
            extraction_version="retrieval-test-v1",
            status="completed",
        )
        session.add(result)
        session.flush()

        specs = [
            # (field_name, value, confidence, verification_status, spans)
            (
                "vendor_name",
                "Nour Trading Co",
                0.62,
                "unverified",
                [{"page": 1, "block": 0, "text": "Nour Trading Co", "bbox": [10.0, 20.0, 210.0, 40.0]}],
            ),
            (
                "invoice_number",
                INV_NOUR,
                0.97,
                "unverified",
                [{"page": 1, "block": 1, "text": INV_NOUR, "bbox": [300.0, 20.0, 420.0, 40.0]}],
            ),
            (
                "po_reference",
                PO_NOUR,
                0.9,
                "unverified",
                [{"page": 1, "block": 2, "text": PO_NOUR, "bbox": [300.0, 45.0, 400.0, 60.0]}],
            ),
            (
                "total",
                "1250.00",
                0.88,
                "unverified",
                [{"page": 1, "block": 3, "text": "1250.00", "bbox": [320.0, 400.0, 420.0, 415.0]}],
            ),
            (
                "currency",
                "EUR",
                None,  # NULL confidence: below the gate by definition (R3)
                "confirmed",  # a human confirmed it
                [{"page": 1, "block": 4, "text": "EUR", "bbox": [300.0, 416.0, 330.0, 428.0]}],
            ),
        ]
        field_ids = {}
        for name, value, confidence, status, spans in specs:
            field_row = ExtractionField(
                organization_id=uuid.UUID(org_id),
                extraction_result_id=result.id,
                invoice_id=uuid.UUID(invoice_id) if invoice_id else None,
                field_name=name,
                field_value=value,
                confidence=confidence,
                evidence_spans=spans,
                verification_status=status,
            )
            session.add(field_row)
            session.flush()
            field_ids[name] = str(field_row.id)
        # Commit: db_query's session closes (and would roll back) on exit.
        session.commit()
        return {"result_id": str(result.id), "field_ids": field_ids}

    return db_query(_create)


def seed_retrieval_org(
    client,
    *,
    email: str = "dana@acme.example",
    with_cases: bool = True,
) -> dict:
    """One org with the full retrieval corpus. Returns all ids + org_id."""
    org = register_org(client, email=email)
    org_id = org["org_id"]

    vendor = client.post(
        "/api/v1/vendors",
        json={
            "display_name": NOUR_DISPLAY,
            "legal_name": NOUR_LEGAL_AR,
            "tax_id": NOUR_TAX,
        },
    ).json()
    approved_account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": NOUR_DISPLAY,
            "account_number": NOUR_IBAN,
            "bank_name": "Nordbank",
            "bank_country": "DE",
        },
    ).json()
    verify = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{approved_account['id']}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "ticket-77",
        },
    )
    assert verify.status_code == 200, verify.text
    # A PENDING account: never searchable as a trusted destination (R5).
    pending_account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": "Nour Pending Account",
            "account_number": "DE11100400440532013099",
            "bank_name": "Shadowbank",
        },
    ).json()

    acme_vendor = client.post(
        "/api/v1/vendors", json={"display_name": ACME_DISPLAY}
    ).json()
    acme_account = client.post(
        f"/api/v1/vendors/{acme_vendor['id']}/bank-accounts",
        json={
            "account_holder_name": ACME_DISPLAY,
            "account_number": "FR1420041010050500013M02606",
            "bank_name": "Banque Nord",
        },
    ).json()
    assert (
        client.post(
            f"/api/v1/vendors/{acme_vendor['id']}/bank-accounts/{acme_account['id']}/verify",
            json={
                "verification_method": "written_confirmation",
                "verification_reference": "letter-2026-05",
            },
        ).status_code
        == 200
    )
    zahra_vendor = client.post(
        "/api/v1/vendors", json={"display_name": ZAHRA_DISPLAY}
    ).json()
    delta_vendor = client.post(
        "/api/v1/vendors", json={"display_name": DELTA_DISPLAY}
    ).json()

    po_nour = client.post(
        "/api/v1/purchase-orders",
        json={
            "po_number": PO_NOUR,
            "vendor_id": vendor["id"],
            "amount": "1250.00",
            "currency": "EUR",
            "description": "5 industrial widgets",
        },
    ).json()
    po_acme = client.post(
        "/api/v1/purchase-orders",
        json={
            "po_number": PO_ACME,
            "vendor_id": acme_vendor["id"],
            "amount": "830.50",
            "currency": "EUR",
        },
    ).json()

    document = client.post(
        "/api/v1/documents",
        files={"file": ("nour-inv.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice", "vendor_id": vendor["id"]},
    ).json()

    invoice_nour = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": INV_NOUR,
            "vendor_id": vendor["id"],
            "purchase_order_id": po_nour["id"],
            "total_amount": "1250.00",
            "currency": "EUR",
            "remittance_bank_name_raw": "Nordbank",
            "remittance_account_raw": NOUR_IBAN,
            "source_document_id": document["id"],
        },
    ).json()
    invoice_acme = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": INV_ACME,
            "vendor_id": acme_vendor["id"],
            "purchase_order_id": po_acme["id"],
            "total_amount": "999.00",  # disagrees with the PO amount
            "currency": "EUR",
        },
    ).json()
    invoice_zahra = client.post(
        "/api/v1/invoices",
        json={"invoice_number": INV_ZAHRA, "vendor_id": zahra_vendor["id"]},
    ).json()
    invoice_delta = client.post(
        "/api/v1/invoices",
        json={"invoice_number": INV_DELTA, "vendor_id": delta_vendor["id"]},
    ).json()
    # Duplicate number (same vendor): the fraud signal path, not a 409.
    duplicate = client.post(
        "/api/v1/invoices",
        json={"invoice_number": INV_NOUR, "vendor_id": vendor["id"]},
    ).json()
    # Remittance printed = the PENDING account: a contradiction for the graph.
    invoice_shadow = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-2026-0777",
            "vendor_id": vendor["id"],
            "remittance_account_raw": "DE11100400440532013099",
        },
    ).json()

    extraction = _add_extraction_fields(
        org_id, document_id=document["id"], invoice_id=invoice_nour["id"]
    )

    case_id = None
    review_action_id = None
    if with_cases:
        case = client.post(
            "/api/v1/cases",
            json={
                "title": "Review duplicate INV-2026-0007",
                "severity": "medium",
                "invoice_id": invoice_nour["id"],
            },
        )
        assert case.status_code == 201, case.text
        case_json = case.json()
        case_id = case_json["id"]
        action = client.post(
            f"/api/v1/cases/{case_id}/actions",
            json={
                "action_type": "comment",
                "body": "Checked the PO and the bank letter; reference ticket-77",
            },
        )
        assert action.status_code == 201, action.text
        review_action_id = action.json()["id"]

    return {
        **org,
        "vendor_id": vendor["id"],
        "acme_vendor_id": acme_vendor["id"],
        "zahra_vendor_id": zahra_vendor["id"],
        "delta_vendor_id": delta_vendor["id"],
        "approved_account_id": approved_account["id"],
        "pending_account_id": pending_account["id"],
        "acme_account_id": acme_account["id"],
        "po_nour_id": po_nour["id"],
        "po_acme_id": po_acme["id"],
        "document_id": document["id"],
        "invoice_nour_id": invoice_nour["id"],
        "invoice_acme_id": invoice_acme["id"],
        "invoice_zahra_id": invoice_zahra["id"],
        "invoice_delta_id": invoice_delta["id"],
        "duplicate_invoice_id": duplicate["id"],
        "invoice_shadow_id": invoice_shadow["id"],
        "extraction_result_id": extraction["result_id"],
        "extraction_field_ids": extraction["field_ids"],
        "case_id": case_id,
        "review_action_id": review_action_id,
    }


def ref(entity_type: str, entity_id: str) -> str:
    """The ref-string format used by search_refs / evaluation labels."""
    return f"{entity_type}:{entity_id}"
