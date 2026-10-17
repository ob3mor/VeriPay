"""Manual field review (Prompt-02): PATCH /api/v1/documents/{id}/fields/{field_id}.

R3: only a human flips verification (reviewer/org_admin); the original
extraction is preserved; corrections carry verified_by/at and an audit event.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from helpers import db_query, register  # noqa: E402
from role_helpers import add_user, login_as, register_second_org  # noqa: E402

import generate_fixtures as gf  # noqa: E402

FIXTURES = gf.FIXTURES_DIR


def _upload_invoice(client, name="normal_invoice.pdf"):
    with open(FIXTURES / name, "rb") as fh:
        return client.post(
            "/api/v1/documents",
            files={"file": (name, io.BytesIO(fh.read()), "application/pdf")},
            data={"kind": "invoice"},
        )


def _total_field(client, document_id):
    fields = client.get(f"/api/v1/documents/{document_id}/fields").json()["items"]
    return next(f for f in fields if f["field_name"] == "total")


def _review(client, document_id, field_id, payload):
    return client.patch(
        f"/api/v1/documents/{document_id}/fields/{field_id}", json=payload
    )


def _audit_events(action: str) -> list[dict]:
    def run(session):
        from sqlalchemy import select

        from app.models import AuditEvent

        return [
            {"action": e.action, "detail": e.detail}
            for e in session.scalars(
                select(AuditEvent).where(AuditEvent.action == action)
            ).all()
        ]

    return db_query(run)


def test_extracted_fields_carry_normalized_values_and_spans(client):
    assert register(client).status_code == 201
    body = _upload_invoice(client).json()
    assert body["processing_status"] == "completed"

    extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
    assert extraction["ocr_provider"] == "text_layer"
    assert extraction["validation_summary"]["status"] == "pass"

    fields = client.get(f"/api/v1/documents/{body['id']}/fields").json()["items"]
    total = next(f for f in fields if f["field_name"] == "total")
    assert total["normalized_value"]["value"] == "1416.10"
    assert total["evidence_spans"][0]["page"] == 1
    assert "Total" in total["evidence_spans"][0]["text"]
    assert total["verification_status"] == "unverified"


def test_reviewer_can_confirm_and_correct(client):
    assert register(client).status_code == 201
    document_id = _upload_invoice(client).json()["id"]
    total = _total_field(client, document_id)

    # org creator is org_admin — allowed.
    confirmed = _review(client, document_id, total["id"], {"action": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["verification_status"] == "confirmed"
    assert confirmed.json()["verified_at"] is not None
    assert confirmed.json()["verified_value"] is None

    corrected = _review(
        client,
        document_id,
        total["id"],
        {"action": "correct", "verified_value": "1416.11"},
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["verification_status"] == "corrected"
    assert body["verified_value"] == "1416.11"
    # The original extraction is preserved untouched.
    assert body["field_value"] == total["field_value"]
    assert body["verified_by"] is not None

    events = _audit_events("document.field_corrected")
    assert any(
        e["detail"]["field_name"] == "total" and e["detail"]["document_id"] == document_id
        for e in events
    )
    assert _audit_events("document.field_confirmed"), "confirmations are audited too"


def test_correction_requires_a_value(client):
    assert register(client).status_code == 201
    document_id = _upload_invoice(client).json()["id"]
    total = _total_field(client, document_id)
    missing = _review(client, document_id, total["id"], {"action": "correct"})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "validation_error"
    blank = _review(
        client, document_id, total["id"], {"action": "correct", "verified_value": "  "}
    )
    assert blank.status_code == 422


def test_only_reviewer_and_org_admin_review_fields(client):
    assert register(client).status_code == 201
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    document_id = _upload_invoice(client).json()["id"]
    total = _total_field(client, document_id)

    for role in ("finance_officer", "auditor"):
        add_user(org_id, f"{role}@acme.example", role)
        client.cookies.clear()
        login_as(client, f"{role}@acme.example")
        response = _review(
            client, document_id, total["id"], {"action": "confirm"}
        )
        assert response.status_code == 403, role

    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    login_as(client, "rev@acme.example")
    ok = _review(client, document_id, total["id"], {"action": "confirm"})
    assert ok.status_code == 200


def test_review_is_org_scoped_and_404_safe(client):
    assert register(client).status_code == 201
    document_id = _upload_invoice(client).json()["id"]
    total = _total_field(client, document_id)

    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    cross = _review(client, document_id, total["id"], {"action": "confirm"})
    assert cross.status_code == 404

    unknown = _review(client, document_id, total["id"][:-1] + "0", {"action": "confirm"})
    assert unknown.status_code == 404


def test_re_extraction_upserts_fields_per_version(client):
    assert register(client).status_code == 201
    body = _upload_invoice(client).json()
    document_id = body["id"]
    first = client.get(f"/api/v1/documents/{document_id}/fields").json()["items"]

    retry = client.post(f"/api/v1/documents/{document_id}/process")
    assert retry.status_code == 200

    second = client.get(f"/api/v1/documents/{document_id}/fields").json()["items"]
    # Same version → rows replaced in place: same field count, same values,
    # no duplicate field rows (uq per result+field_name holds).
    assert len(second) == len(first)
    assert {f["field_name"] for f in second} == {f["field_name"] for f in first}
    first_total = next(f for f in first if f["field_name"] == "total")
    second_total = next(f for f in second if f["field_name"] == "total")
    assert second_total["normalized_value"] == first_total["normalized_value"]
