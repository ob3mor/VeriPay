"""OcrProvider seam — text extraction engines plug in here (Phase 2 contract).

Real engines (Tesseract locally, Azure Document Intelligence F0 in the
cloud demo) implement ``extract`` and are selected via
``VERIPAY_OCR_PROVIDER``. Modules never import a concrete provider.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class OcrBlock:
    text: str
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None  # None = the provider gives no confidence


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
    if name == "stub":
        from app.adapters.ocr.stub import StubOcrProvider

        return StubOcrProvider()
    raise ValueError(
        f"Unknown OCR provider: {name!r}. Real engines arrive in a later phase."
    )
