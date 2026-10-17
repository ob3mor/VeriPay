"""Extraction → invoice binding: the R3 provenance path through the API.

Before this the ``origin: "extracted"`` stamp and the
field_provenance_conflict signal were unreachable — nothing ever wrote them
(the auditor's finding). Seeded extraction fields stand in for a real OCR
provider's output (the stub/text-layer fixtures cannot produce named fields
deterministically); the service path is the same one the text_layer provider
exercises.
"""

import io
import uuid
from datetime import datetime, timezone

from helpers import db_query, register
from role_helpers import register_second_org

PDF_BYTES = b"%PDF-1.4\nbinding test\n"


def _upload_document(client) -> str:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("bind.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        data={"kind": "invoice"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_extraction_fields(client, document_id: str):
    """Persist two named fields exactly as a real provider's run would:
    a confident total and a below-gate currency (confidence travels as-is)."""

    def _seed(session):
        from app.models import Document, ExtractionField, ExtractionResult

        doc = session.get(Document, uuid.UUID(document_id))
        result = ExtractionResult(
            organization_id=doc.organization_id,
            document_id=doc.id,
            extraction_version="provider-v9",  # newer than the inline run
            status="completed",
            # Explicit timestamp: strictly later than the inline stub-v1
            # result so get_result() (latest by created_at) picks this one
            # even with SQLite's second-resolution CURRENT_TIMESTAMP.
            created_at=datetime.now(timezone.utc),
        )
        session.add(result)
        session.flush()
        confident_total = ExtractionField(
            organization_id=doc.organization_id,
            extraction_result_id=result.id,
            field_name="total_amount",
            field_value="1250.00",
            confidence=0.9,
        )
        below_gate_currency = ExtractionField(
            organization_id=doc.organization_id,
            extraction_result_id=result.id,
            field_name="currency",
            field_value="EUR",
            confidence=0.4,  # below the 0.85 gate
        )
        session.add_all([confident_total, below_gate_currency])
        session.commit()
        return str(confident_total.id), str(below_gate_currency.id)

    return db_query(_seed)


def test_invoice_binds_extracted_provenance_and_signals_fire(client):
    assert register(client).status_code == 201
    document_id = _upload_document(client)
    _total_field_id, _currency_field_id = _seed_extraction_fields(client, document_id)

    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-EXT",
            "total_amount": "2500.00",  # human-entered — the column WINS
            "source_document_id": document_id,
        },
    )
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["id"]

    def _field_sources(session):
        from app.models import Invoice

        row = session.get(Invoice, uuid.UUID(invoice_id))
        return dict(row.field_sources or {})

    sources = db_query(_field_sources)

    # total_amount: human-entered (manual origin, the column is authoritative)
    # BUT the extracted provenance is retained → the disagreement (2500 vs
    # 1250) must surface as field_provenance_conflict.
    assert sources["total_amount"]["origin"] == "manual"
    assert sources["total_amount"]["extracted_value"] == "1250.00"
    assert sources["total_amount"]["confidence_at_ingest"] == 0.9

    # currency: never human-entered → extracted origin with below-gate
    # confidence → unverified_input, never a confident claim (R3).
    assert sources["currency"]["origin"] == "extracted"
    assert sources["currency"]["confidence_at_ingest"] == 0.4

    # The extraction fields are linked to the invoice row.
    def _linked_field_ids(session):
        from app.models import ExtractionField

        return sorted(
            str(f.id)
            for f in session.query(ExtractionField).filter(
                ExtractionField.invoice_id == uuid.UUID(invoice_id)
            )
        )

    linked = db_query(_linked_field_ids)
    assert linked == sorted([_total_field_id, _currency_field_id])

    # The column itself was never overwritten by extraction.
    fetched = client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert fetched["total_amount"] == "2500.00"

    # Assess: both R3 signals fire with the §8 severities.
    assessment = client.post(f"/api/v1/invoices/{invoice_id}/assess").json()
    by_type = {f["signal_type"]: f["severity"] for f in assessment["findings"]}
    assert by_type.get("field_provenance_conflict") == "medium"
    assert by_type.get("unverified_input") == "low"


def test_invoice_cannot_reference_another_orgs_document(client):
    assert register(client).status_code == 201
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    foreign_document = _upload_document(client)

    client.cookies.clear()
    assert register(client, email="back@acme.example",
                    organization_name="Back Corp").status_code == 201
    response = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-STEAL",
            "source_document_id": foreign_document,
        },
    )
    assert response.status_code == 404
