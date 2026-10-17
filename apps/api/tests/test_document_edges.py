"""Document upload edges (size) + hard delete — the auditor's untested
branches in app/modules/documents/service.py."""

import io
import os
import uuid

from helpers import db_query, register
from role_helpers import add_user, login_as, register_second_org

PDF_BYTES = b"%PDF-1.4\nupload edge test payload\n"


def _upload(client, data=PDF_BYTES, name="edge.pdf"):
    return client.post(
        "/api/v1/documents",
        files={"file": (name, io.BytesIO(data), "application/pdf")},
        data={"kind": "invoice"},
    )


def test_oversize_upload_is_rejected(client, monkeypatch):
    assert register(client).status_code == 201
    from app.core.config import get_settings

    # 128 bytes is above the small fixture below but far below the default.
    monkeypatch.setattr(get_settings(), "upload_max_bytes", 128)
    big = b"%PDF-1.4\n" + b"x" * 256
    response = _upload(client, data=big)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    # Nothing was persisted.
    assert client.get("/api/v1/documents").json() == []


def test_empty_upload_is_rejected(client):
    assert register(client).status_code == 201
    response = _upload(client, data=b"")
    assert response.status_code == 422
    assert b"empty" in response.json()["error"]["message"].lower().encode()


def test_org_admin_can_delete_an_unused_document(client):
    assert register(client).status_code == 201
    document = _upload(client).json()

    def _storage_key(session):
        from app.models import Document

        return session.get(Document, uuid.UUID(document["id"])).storage_key

    storage_key = db_query(_storage_key)

    deleted = client.delete(f"/api/v1/documents/{document['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/documents/{document['id']}").status_code == 404
    assert client.get(f"/api/v1/documents/{document['id']}/file").status_code == 404

    # The stored object is gone from document storage too (seam delete).
    from app.core.config import get_settings
    from app.modules.documents.service import _build_storage

    provider = _build_storage(get_settings())
    assert provider.exists(storage_key) is False


def test_deleting_a_referenced_document_is_409(client):
    """An invoice references the document — deletion must not dangle it."""
    assert register(client).status_code == 201
    document = _upload(client).json()
    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-REF",
            "source_document_id": document["id"],
        },
    )
    assert invoice.status_code == 201, invoice.text
    deleted = client.delete(f"/api/v1/documents/{document['id']}")
    assert deleted.status_code == 409
    assert deleted.json()["error"]["code"] == "conflict"
    assert client.get(f"/api/v1/documents/{document['id']}").status_code == 200


def test_r5_verification_document_blocks_deletion(client):
    """A bank account cites the document as its verification record (R5) —
    the audit-proof provenance must not be deletable."""
    assert register(client).status_code == 201
    document = _upload(client).json()
    vendor = client.post("/api/v1/vendors", json={"display_name": "V"}).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "DE89370400440532013000"},
    ).json()
    verified = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "written_confirmation",
            "verification_reference": "Signed bank letter.",
            "verification_document_id": document["id"],
        },
    )
    assert verified.status_code == 200, verified.text
    deleted = client.delete(f"/api/v1/documents/{document['id']}")
    assert deleted.status_code == 409


def test_delete_is_org_admin_only_and_tenant_scoped(client):
    assert register(client).status_code == 201
    document = _upload(client).json()
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]

    # finance_officer (contributor) cannot delete.
    add_user(org_id, "fin@acme.example", "finance_officer")
    client.cookies.clear()
    login_as(client, "fin@acme.example")
    assert client.delete(f"/api/v1/documents/{document['id']}").status_code == 403

    # Another org's delete is a 404 (no existence leak).
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    assert client.delete(f"/api/v1/documents/{document['id']}").status_code == 404
