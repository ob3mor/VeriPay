"""StubOcrProvider — deterministic placeholder output (docs/ARCHITECTURE §7.2).

Honesty rules baked in:
- It reads NO text: pages are empty, so no field can ever be extracted from
  it (real engines replace it via the same protocol).
- Every block it emits would carry ``confidence = None``; the extraction
  gate treats None as below-threshold, so stub output can NEVER become
  confident fraud evidence (R3).
"""

from app.adapters.ocr.base import OcrDocument, OcrProvider


class StubOcrProvider:
    name = "stub"

    def extract(self, data: bytes, mime_type: str) -> OcrDocument:
        return OcrDocument(
            pages=[],
            provider=self.name,
            provider_meta={
                "note": (
                    "Synthetic stub output: no text was read. Configure a real "
                    "VERIPAY_OCR_PROVIDER to extract fields."
                ),
                "input_bytes": len(data),
                "input_mime": mime_type,
            },
            page_count=0,
        )
