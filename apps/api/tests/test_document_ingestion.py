"""Document ingestion: validation, tenant isolation, protected downloads."""

import io

from role_helpers import login_as, register_second_org
from helpers import register

PDF_BYTES = b"%PDF-1.4\nfake invoice content for validation tests\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(client, *, name="invoice.pdf", data=PDF_BYTES, mime="application/pdf", kind="invoice"):
    return client.post(
        "/api/v1/documents",
        files={"file": (name, io.BytesIO(data), mime)},
        data={"kind": kind},
    )


def test_valid_pdf_uploads_and_processes_inline(client):
    assert register(client).status_code == 201
    response = _upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["processing_status"] == "completed"
    assert body["job_status"] == "completed"
    assert body["deduplicated"] is False
    # The stub OCR reads nothing â€” honest empty extraction.
    fields = client.get(f"/api/v1/documents/{body['id']}/fields").json()["items"]
    assert fields == []


def test_signature_check_rejects_renamed_files(client):
    assert register(client).status_code == 201
    # A text file pretending to be a PDF fails the magic-byte check.
    fake = _upload(client, name="invoice.pdf", data=b"not a pdf at all", mime="application/pdf")
    assert fake.status_code == 422
    # A PDF with a PNG content type fails the declared-vs-actual check.
    mismatch = _upload(client, name="x.pdf", data=PDF_BYTES, mime="image/png")
    assert mismatch.status_code == 422
    # Unsupported type (text/plain) fails the allowlist.
    txt = _upload(client, name="x.txt", data=b"hello", mime="text/plain")
    assert txt.status_code == 422


def test_per_org_dedup_returns_existing_document(client):
    assert register(client).status_code == 201
    first = _upload(client)
    second = _upload(client, name="same-again.pdf")
    assert first.status_code == 201
    assert second.status_code == 200 or second.json()["deduplicated"] is True
    assert second.json()["id"] == first.json()["id"]


def test_download_is_protected_and_tenant_scoped(client):
    assert register(client).status_code == 201
    document_id = _upload(client).json()["id"]

    # Same org: bytes come back.
    ok = client.get(f"/api/v1/documents/{document_id}/file")
    assert ok.status_code == 200
    assert ok.content == PDF_BYTES

    # Other org: the id is indistinguishable from nonexistent (404, no leak).
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    cross = client.get(f"/api/v1/documents/{document_id}/file")
    assert cross.status_code == 404
    listing = client.get("/api/v1/documents").json()["items"]
    assert document_id not in [d["id"] for d in listing]


def test_upload_requires_contributor_role(client):
    assert register(client).status_code == 201
    from helpers import db_query

    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    from role_helpers import add_user

    add_user(org_id, "aud@acme.example", "auditor")
    client.cookies.clear()
    login_as(client, "aud@acme.example")
    forbidden = _upload(client)
    assert forbidden.status_code == 403