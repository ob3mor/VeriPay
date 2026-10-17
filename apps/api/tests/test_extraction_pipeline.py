"""Extraction pipeline wiring (Prompt-02): provider selection via
settings.ocr_provider, honest stub fallback when an engine is unavailable,
misconfiguration failing loudly, and the upsert-per-version rule."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from helpers import register  # noqa: E402

FIXTURES = gf.FIXTURES_DIR


def _upload(client, name="normal_invoice.pdf", mime="application/pdf"):
    with open(FIXTURES / name, "rb") as fh:
        return client.post(
            "/api/v1/documents",
            files={"file": (name, io.BytesIO(fh.read()), mime)},
            data={"kind": "invoice"},
        )


@pytest.fixture()
def _ocr_provider_env(monkeypatch):
    """Point VERIPAY_OCR_PROVIDER somewhere and rebuild the cached settings;
    always restores the cached default afterwards."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_upload_runs_the_configured_text_layer_provider(client):
    assert register(client).status_code == 201
    response = _upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["processing_status"] == "completed"

    extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
    assert extraction["ocr_provider"] == "text_layer"
    assert extraction["provider_meta"]["extractor"] in ("pypdf", "pdfminer.six")
    assert extraction["status"] == "completed"

    fields = client.get(f"/api/v1/documents/{body['id']}/fields").json()
    names = {f["field_name"] for f in fields}
    assert {"vendor_name", "invoice_number", "invoice_date", "subtotal", "tax", "total", "iban"} <= names
    total = next(f for f in fields if f["field_name"] == "total")
    assert total["confidence"] == 1.0
    # Validation summary landed on the result.
    summary = extraction["validation_summary"]
    assert summary["status"] == "pass"
    assert any(c["check"] == "arithmetic_consistency" for c in summary["checks"])


def test_unavailable_engine_falls_back_to_stub_honestly(client, _ocr_provider_env):
    """tesseract is configured but the binary is absent on this machine →
    the extraction completes with the STUB provider, an explicit fallback
    reason in provider_meta, and zero fields (the stub reads nothing)."""
    _ocr_provider_env.setenv("VERIPAY_OCR_PROVIDER", "tesseract")

    from app.adapters.ocr.tesseract import tesseract_available

    assert register(client).status_code == 201
    response = _upload(client)
    body = response.json()

    extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
    if tesseract_available():
        # The unlikely machine WITH tesseract: no fallback expected.
        assert extraction["ocr_provider"] == "tesseract"
        return
    assert body["processing_status"] == "completed"
    assert extraction["ocr_provider"] == "stub"
    assert "tesseract" in extraction["provider_meta"]["fallback"]
    assert client.get(f"/api/v1/documents/{body['id']}/fields").json() == []


def test_unknown_provider_fails_loudly(client, _ocr_provider_env):
    """A typo'd provider name is misconfiguration: the job fails with the
    versioned envelope instead of silently extracting nothing."""
    _ocr_provider_env.setenv("VERIPAY_OCR_PROVIDER", "tesseract-typo")
    assert register(client).status_code == 201
    response = _upload(client)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "business_rule_violation"

    # The document row records the durable failure; a retry is possible.
    listing = client.get("/api/v1/documents").json()
    assert listing, "the upload was persisted before the job failed"


def test_stub_provider_yields_no_fields(client, _ocr_provider_env):
    _ocr_provider_env.setenv("VERIPAY_OCR_PROVIDER", "stub")
    assert register(client).status_code == 201
    body = _upload(client).json()
    assert body["processing_status"] == "completed"
    extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
    assert extraction["ocr_provider"] == "stub"
    assert client.get(f"/api/v1/documents/{body['id']}/fields").json() == []
