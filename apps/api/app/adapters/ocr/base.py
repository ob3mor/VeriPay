"""OcrProvider seam — text extraction engines plug in here (Phase 2 contract).

Real engines (Tesseract locally, Azure Document Intelligence F0 in the
cloud demo) implement ``extract`` and are selected via
``VERIPAY_OCR_PROVIDER``. Modules never import a concrete provider.

Configured providers (settings.ocr_provider):
- ``text_layer`` (default): reads the embedded digital text of PDFs —
  documents with a real text layer never need pixel OCR.
- ``tesseract``: local pixel OCR for scans/images (optional ``[ocr]`` extra;
  the tesseract binary is a system dependency and is probed at build time).
- ``azure``: Azure Document Intelligence (optional ``[azure-ocr]`` extra;
  F0 free-tier limits are honored — page cap from settings, never an
  automatic tier upgrade).
- ``stub``: deterministic placeholder that reads nothing (Phase 2 contract).

Unavailable engines (missing binary/SDK/credentials) fall back to the stub
with an explicit reason carried in ``provider_meta`` — the stub output is
marked synthetic and yields no fields, so the fallback is honest. An UNKNOWN
provider name stays a hard error (misconfiguration must be visible).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class OcrBlock:
    text: str
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None  # None = the provider gives no confidence
    # Set only by providers that recognize the field identity themselves
    # (Azure prebuilt-invoice): the provider-side field name, e.g.
    # "vendor_name". Label-based providers leave it None.
    field_hint: str | None = None


@dataclass(frozen=True)
class OcrPage:
    page_number: int
    blocks: list[OcrBlock] = field(default_factory=list)


@dataclass(frozen=True)
class OcrDocument:
    pages: list[OcrPage] = field(default_factory=list)
    provider: str = "stub"
    provider_meta: dict[str, Any] = field(default_factory=dict)
    page_count: int = 0


class OcrProvider(Protocol):
    name: str

    def extract(self, data: bytes, mime_type: str) -> OcrDocument: ...


def build_ocr_provider(name: str) -> OcrProvider:
    """Strict factory: builds the named provider or raises ValueError."""
    if name == "stub":
        from app.adapters.ocr.stub import StubOcrProvider

        return StubOcrProvider()
    if name == "text_layer":
        from app.adapters.ocr.text_layer import OcrTextLayerProvider

        return OcrTextLayerProvider()
    if name == "tesseract":
        from app.adapters.ocr.tesseract import OcrTesseractProvider

        return OcrTesseractProvider()
    if name == "azure":
        from app.adapters.ocr.azure_di import OcrAzureDocumentProvider

        return OcrAzureDocumentProvider()
    raise ValueError(
        f"Unknown OCR provider: {name!r}. "
        "Configured providers: text_layer | tesseract | azure | stub."
    )


# Errors that mean "this engine is not available in this environment" —
# missing optional dependency, missing system binary, missing credentials.
# The pipeline falls back to the stub for these; everything else propagates.
ENGINE_UNAVAILABLE_ERRORS = (ImportError, RuntimeError)


def build_ocr_provider_with_fallback(name: str) -> tuple[OcrProvider, str | None]:
    """Build the configured provider, falling back to the stub when the
    engine itself is unavailable (missing dependency / binary / credentials).

    Returns (provider, fallback_reason). fallback_reason is None when the
    configured provider was built; otherwise a human-readable reason that the
    extraction service persists in ``provider_meta`` so the degradation is
    visible, never silent.
    """
    try:
        return build_ocr_provider(name), None
    except ValueError:
        # Unknown provider name: misconfiguration, never silently stubbed.
        raise
    except ENGINE_UNAVAILABLE_ERRORS as exc:
        reason = (
            f"Configured OCR provider {name!r} is unavailable in this "
            f"environment ({type(exc).__name__}: {exc}); fell back to the "
            "stub provider (no text was read — synthetic output)."
        )
        return build_ocr_provider("stub"), reason
