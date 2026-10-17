"""OcrProvider adapters (Prompt-02): text layer, tesseract (skipped without
the binary), Azure Document Intelligence (SDK mocked via an injected fake
client — the real cloud is never contacted from this machine), and the
honest fallback-to-stub behavior of the factory.
"""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from app.adapters.ocr.base import (  # noqa: E402
    build_ocr_provider,
    build_ocr_provider_with_fallback,
)
from app.adapters.ocr.text_layer import OcrTextLayerProvider  # noqa: E402
from app.modules.extraction.fields import extract_fields  # noqa: E402

FIXTURES = gf.FIXTURES_DIR


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------
# Text layer
# --------------------------------------------------------------------------


def test_text_layer_reads_embedded_text_with_page_numbers():
    ocr = OcrTextLayerProvider().extract(_read("normal_invoice.pdf"), "application/pdf")
    assert ocr.provider == "text_layer"
    assert ocr.page_count == 1
    assert ocr.pages[0].page_number == 1
    assert ocr.pages[0].blocks, "the fixture PDF has a real text layer"
    joined = "\n".join(b.text for b in ocr.pages[0].blocks)
    assert "Invoice Number: INV-2026-0042" in joined
    # Embedded digital text is bit-exact: reading confidence is 1.0.
    assert all(b.confidence == 1.0 for b in ocr.pages[0].blocks)
    assert ocr.provider_meta["extractor"] == "pypdf"


def test_text_layer_arabic_uses_pdfminer_logical_order():
    ocr = OcrTextLayerProvider().extract(_read("arabic_invoice.pdf"), "application/pdf")
    joined = "\n".join(b.text for b in ocr.pages[0].blocks)
    assert ocr.provider_meta["extractor"] == "pdfminer.six"
    assert "البائع: شركة الأفق للقرطاسية" in joined  # logical order, not reversed
    # pdfminer supplies real line bounding boxes.
    assert all(b.bbox is not None for b in ocr.pages[0].blocks)


def test_text_layer_broken_pdf_is_honest_empty():
    ocr = OcrTextLayerProvider().extract(
        b"%PDF-1.4\nthis is not a parseable pdf body", "application/pdf"
    )
    assert ocr.page_count == 0
    assert ocr.pages == []
    assert "note" in ocr.provider_meta  # says what happened, invents nothing


def test_text_layer_image_documents_have_no_text_layer():
    ocr = OcrTextLayerProvider().extract(_read("blurry_scan.png"), "image/png")
    assert ocr.pages == []
    assert "pixel OCR" in ocr.provider_meta["note"]


def test_text_layer_fields_flow_through_extraction():
    ocr = OcrTextLayerProvider().extract(_read("mixed_language.pdf"), "application/pdf")
    fields = {f.field_name: f for f in extract_fields(ocr)}
    assert fields["total"].normalized_value["value"] == "1207.50"
    assert fields["subtotal"].raw_value == "١٠٥٠.٠٠"  # raw preserved as read
    assert fields["subtotal"].normalized_value["value"] == "1050.00"  # digits normalized


# --------------------------------------------------------------------------
# Tesseract (optional; the binary is absent on this machine → skips)
# --------------------------------------------------------------------------

def _tesseract_usable() -> bool:
    from app.adapters.ocr.tesseract import tesseract_available

    return tesseract_available()


@pytest.mark.skipif(not _tesseract_usable(), reason="tesseract binary not installed")
def test_tesseract_reads_the_blurry_scan():
    from app.adapters.ocr.tesseract import OcrTesseractProvider

    ocr = OcrTesseractProvider(lang="ara+eng").extract(
        _read("blurry_scan.png"), "image/png"
    )
    assert ocr.provider == "tesseract"
    assert ocr.page_count == 1
    assert any(b.text for b in ocr.pages[0].blocks)


@pytest.mark.skipif(_tesseract_usable(), reason="tesseract binary IS installed")
def test_tesseract_unavailable_raises_runtime_error():
    """On machines without the binary this test RUNS: the provider must
    refuse to build with a RuntimeError (subclass), which is what the
    pipeline's honest stub fallback keys on."""
    from app.adapters.ocr.tesseract import OcrTesseractProvider, TesseractUnavailableError

    with pytest.raises(TesseractUnavailableError):
        OcrTesseractProvider()


def test_tesseract_build_failure_falls_back_to_stub_honestly():
    """With the binary absent, configuring tesseract degrades to the stub
    with an explicit recorded reason (never silent, never fabricated text)."""
    provider, reason = build_ocr_provider_with_fallback("tesseract")
    if _tesseract_usable():
        assert reason is None
        return
    assert provider.name == "stub"
    assert reason is not None and "tesseract" in reason


# --------------------------------------------------------------------------
# Azure Document Intelligence (SDK mocked — never executed against the cloud)
# --------------------------------------------------------------------------


class _FakeHttpError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _fake_azure_result():
    region = SimpleNamespace(page_number=1, polygon=(10, 10, 200, 30))
    line = SimpleNamespace(content="Vendor: Contoso", polygon=(10, 10, 200, 30))
    fields = {
        "VendorName": SimpleNamespace(
            value="Contoso GmbH",
            content=None,
            confidence=0.95,
            bounding_regions=[region],
        ),
        "InvoiceId": SimpleNamespace(
            value="INV-9001",
            content=None,
            confidence=0.93,
            bounding_regions=[region],
        ),
        "InvoiceDate": SimpleNamespace(
            value=date(2026, 10, 15),
            content="15/10/2026",
            confidence=0.91,
            bounding_regions=[region],
        ),
        "Total": SimpleNamespace(
            value=1416.10,
            content="1416.10",
            confidence=0.97,
            bounding_regions=[region],
        ),
        "CustomTag": SimpleNamespace(  # unmapped name → snake_case fallback
            value="x", content=None, confidence=0.5, bounding_regions=[region]
        ),
    }
    return SimpleNamespace(
        pages=[SimpleNamespace(page_number=1, lines=[line])], fields=fields
    )


class FakeAzureClient:
    """Mimics azure.ai.formrecognizer.DocumentAnalysisClient (LRO surface:
    begin_analyze_document → poller with wait/done/result)."""

    def __init__(self, *, result=None, errors=None):
        self.result = result
        self.errors = list(errors or [])
        self.calls: list[dict] = []

    def begin_analyze_document(self, model_id, document=None, **kwargs):
        self.calls.append({"model_id": model_id, "bytes": len(document), **kwargs})
        errors = self.errors
        result = self.result

        class _Poller:
            def wait(self, timeout=None):
                self.waited_timeout = timeout
                if errors:
                    raise errors.pop(0)

            def done(self):
                return not errors

            def result(self):
                return result

        return _Poller()


def _azure_settings(**overrides):
    base = dict(
        azure_di_model="prebuilt-invoice",
        azure_di_page_cap=2,
        azure_di_timeout_seconds=5.0,
        azure_di_max_retries=2,
        azure_di_endpoint=None,
        azure_di_key=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_azure_maps_fields_and_confidences():
    from app.adapters.ocr.azure_di import OcrAzureDocumentProvider

    client = FakeAzureClient(result=_fake_azure_result())
    provider = OcrAzureDocumentProvider(client=client, settings=_azure_settings())
    ocr = provider.extract(b"%PDF-fake", "application/pdf")

    assert ocr.provider == "azure"
    assert client.calls[0]["model_id"] == "prebuilt-invoice"
    assert client.calls[0]["pages"] == ["1-2"]  # F0 page cap honored
    assert ocr.provider_meta["retries_used"] == 0

    hinted = [b for b in ocr.pages[0].blocks if b.field_hint]
    hints = {b.field_hint: b for b in hinted}
    assert hints["vendor_name"].confidence == 0.95
    assert hints["vendor_name"].text == "Contoso GmbH"
    assert hints["invoice_number"].text == "INV-9001"
    assert hints["total"].text == "1416.10"
    assert hints["custom_tag"].field_hint == "custom_tag"
    # The mapped hints drive the structured field extraction with the
    # provider confidence intact (R3: travels as-is).
    fields = {f.field_name: f for f in extract_fields(ocr)}
    assert fields["vendor_name"].confidence == 0.95
    assert fields["invoice_date"].normalized_value["value"] == "2026-10-15"


def test_azure_quota_exceeded_is_explicit_and_not_retried():
    from app.adapters.ocr.azure_di import (
        AzureDiQuotaExceededError,
        OcrAzureDocumentProvider,
    )

    client = FakeAzureClient(errors=[_FakeHttpError(429)])
    provider = OcrAzureDocumentProvider(client=client, settings=_azure_settings())
    with pytest.raises(AzureDiQuotaExceededError) as excinfo:
        provider.extract(b"%PDF-fake", "application/pdf")
    assert "quota" in str(excinfo.value).lower()
    assert len(client.calls) == 1  # never retried a spent quota


def test_azure_transient_errors_retry_with_backoff(monkeypatch):
    from app.adapters.ocr.azure_di import OcrAzureDocumentProvider

    monkeypatch.setattr(
        "app.adapters.ocr.azure_di.time.sleep", lambda _s: None
    )
    client = FakeAzureClient(
        errors=[_FakeHttpError(503), _FakeHttpError(502)],
        result=_fake_azure_result(),
    )
    provider = OcrAzureDocumentProvider(client=client, settings=_azure_settings())
    ocr = provider.extract(b"%PDF-fake", "application/pdf")
    assert ocr.provider_meta["retries_used"] == 2
    assert len(client.calls) == 3


def test_azure_transient_exhaustion_raises_after_budget(monkeypatch):
    from app.adapters.ocr.azure_di import (
        AzureDiTransientExhaustedError,
        OcrAzureDocumentProvider,
    )

    monkeypatch.setattr("app.adapters.ocr.azure_di.time.sleep", lambda _s: None)
    client = FakeAzureClient(
        errors=[_FakeHttpError(503), _FakeHttpError(503), _FakeHttpError(503)]
    )
    provider = OcrAzureDocumentProvider(client=client, settings=_azure_settings())
    with pytest.raises(AzureDiTransientExhaustedError):
        provider.extract(b"%PDF-fake", "application/pdf")


def test_azure_timeout_is_explicit():
    from app.adapters.ocr.azure_di import AzureDiTimeoutError, OcrAzureDocumentProvider

    class NeverDonePoller:
        def wait(self, timeout=None):
            self.seen_timeout = timeout

        def done(self):
            return False

        def result(self):  # pragma: no cover — never reached
            raise AssertionError("result() must not be called on timeout")

    client = FakeAzureClient()
    client.begin_analyze_document = lambda *a, **k: NeverDonePoller()
    provider = OcrAzureDocumentProvider(client=client, settings=_azure_settings())
    with pytest.raises(AzureDiTimeoutError):
        provider.extract(b"%PDF-fake", "application/pdf")


def test_azure_requires_configuration_without_injected_client():
    from app.adapters.ocr.azure_di import AzureDiConfigurationError

    with pytest.raises(AzureDiConfigurationError):
        build_ocr_provider("azure")


def test_azure_configuration_failure_falls_back_to_stub():
    provider, reason = build_ocr_provider_with_fallback("azure")
    assert provider.name == "stub"
    assert reason is not None and "azure" in reason


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def test_unknown_provider_name_is_a_hard_error():
    with pytest.raises(ValueError):
        build_ocr_provider("does-not-exist")
    with pytest.raises(ValueError):
        build_ocr_provider_with_fallback("does-not-exist")


def test_default_text_layer_builds_without_fallback():
    provider, reason = build_ocr_provider_with_fallback("text_layer")
    assert provider.name == "text_layer"
    assert reason is None
