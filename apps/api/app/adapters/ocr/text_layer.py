"""OcrTextLayerProvider — reads the embedded digital text layer of PDFs.

Documents whose pages carry a real text layer ( digitally generated
invoices) never need pixel OCR: the text is read exactly as stored, with
per-block page numbers.

Honesty rules baked in:
- The provider reads only embedded text; it invents nothing. A PDF without
  a text layer (a scan) yields zero blocks with an explicit ``note`` in
  ``provider_meta`` — pixel OCR (tesseract/azure) is a separate provider.
- A PDF that cannot be parsed yields an honest empty document with the
  parse error recorded — the pipeline does not crash and does not guess.
- Confidence: embedded digital text is bit-exact, so blocks carry
  ``TEXT_LAYER_CONFIDENCE`` (1.0). This is reading certainty, not a claim
  about the document's truth — field-level label matching quality is
  measured separately (tests/test_extraction_evaluation.py).
- pypdf is the primary extractor. pypdf renders Arabic in *visual* order
  (RTL runs reversed), which would corrupt label matching, so a document
  whose extracted text contains Arabic letters is re-read with
  pdfminer.six, which preserves logical order (and supplies real
  per-line bounding boxes). pdfminer is also the fallback when pypdf
  cannot parse the PDF at all. Without pdfminer installed, Arabic
  documents stay on pypdf with an explicit meta note about the ordering
  limitation — the text is never silently mangled into a wrong field.
"""

from io import BytesIO

from app.adapters.ocr.base import OcrBlock, OcrDocument, OcrPage

# Bit-exact digital text: the reading itself is certain. (Field-level
# confidence propagates from this; humans can still correct any field.)
TEXT_LAYER_CONFIDENCE = 1.0

_MIN_CHARS_FOR_TEXT_LAYER = 20

# Arabic block ranges (base + presentation forms + supplements).
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _contains_arabic(text: str) -> bool:
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in _ARABIC_RANGES) for ch in text
    )


def _clean_lines(text: str) -> list[str]:
    """Split page text into non-empty single-line blocks."""
    lines = []
    for raw in text.splitlines():
        line = raw.replace("\x00", "").rstrip()
        if line.strip():
            lines.append(line.strip())
    return lines


class OcrTextLayerProvider:
    name = "text_layer"

    def extract(self, data: bytes, mime_type: str) -> OcrDocument:
        if mime_type != "application/pdf":
            return OcrDocument(
                pages=[],
                provider=self.name,
                provider_meta={
                    "note": (
                        f"{mime_type} has no PDF text layer; pixel OCR "
                        "(tesseract or azure) is required for image documents."
                    ),
                    "input_bytes": len(data),
                    "input_mime": mime_type,
                },
                page_count=0,
            )

        try:
            return self._extract_with_pypdf(data)
        except Exception as exc:  # noqa: BLE001 — a broken PDF must not 500
            fallback = self._extract_with_pdfminer(data, error=exc)
            if fallback is not None:
                return fallback
            return OcrDocument(
                pages=[],
                provider=self.name,
                provider_meta={
                    "note": (
                        "The PDF text layer could not be read (parse error); "
                        "no text was extracted and nothing was guessed."
                    ),
                    "parse_error": f"{type(exc).__name__}: {exc}"[:500],
                },
                page_count=0,
            )

    # -- pypdf (primary) ---------------------------------------------------

    def _extract_with_pypdf(self, data: bytes) -> OcrDocument:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            return OcrDocument(
                pages=[],
                provider=self.name,
                provider_meta={
                    "note": "The PDF is encrypted; no text was extracted."
                },
                page_count=0,
            )

        pages: list[OcrPage] = []
        total_chars = 0
        contains_arabic = False
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 — one broken page must not sink all
                text = ""
            if _contains_arabic(text):
                contains_arabic = True
            blocks = [
                OcrBlock(text=line, confidence=TEXT_LAYER_CONFIDENCE)
                for line in _clean_lines(text)
            ]
            total_chars += sum(len(b.text) for b in blocks)
            pages.append(OcrPage(page_number=index, blocks=blocks))

        meta: dict = {"extractor": "pypdf"}
        if total_chars < _MIN_CHARS_FOR_TEXT_LAYER:
            meta["note"] = (
                "The PDF carries no usable text layer (likely a scan); "
                "pixel OCR (tesseract or azure) is required for its content."
            )
        if contains_arabic:
            # pypdf outputs RTL runs in visual order (reversed), which would
            # corrupt Arabic label/value matching. Re-read with pdfminer.six,
            # which preserves logical order.
            re_read = self._extract_with_pdfminer(data, reason="arabic_order")
            if re_read is not None:
                re_read.provider_meta["extractor"] = "pdfminer.six"
                re_read.provider_meta["note"] = (
                    "Arabic text detected: read with pdfminer.six to preserve "
                    "logical (reading) order; pypdf yields visual order."
                )
                return re_read
            meta["arabic_ordering_note"] = (
                "Arabic text was read with pypdf, which outputs visual order; "
                "install pdfminer.six for logical-order Arabic extraction."
            )
        return OcrDocument(
            pages=pages,
            provider=self.name,
            provider_meta=meta,
            page_count=len(pages),
        )

    # -- pdfminer.six (fallback; also gives real bounding boxes) -----------

    _PDFMINER_NOTES = {
        "parse_error": (
            "pypdf could not parse this PDF ({error}); the pdfminer.six "
            "fallback was used."
        ),
        "arabic_order": (
            "Arabic text detected: read with pdfminer.six to preserve "
            "logical (reading) order; pypdf yields visual order."
        ),
    }

    def _extract_with_pdfminer(self, data: bytes, *, reason: str = "parse_error", error: Exception | None = None) -> OcrDocument | None:
        """Used when pypdf cannot parse the PDF, or when Arabic text needs
        logical-order extraction. Returns None when the pdfminer.six
        dependency is not installed."""
        try:
            from pdfminer.high_level import extract_pages
            from pdfminer.layout import LTTextContainer, LTTextLine
        except ImportError:
            return None

        pages: list[OcrPage] = []
        total_chars = 0
        try:
            for index, page_layout in enumerate(
                extract_pages(BytesIO(data)), start=1
            ):
                blocks: list[OcrBlock] = []
                for element in page_layout:
                    if not isinstance(element, LTTextContainer):
                        continue
                    for line in element:
                        if not isinstance(line, LTTextLine):
                            continue
                        text = line.get_text().strip()
                        if not text:
                            continue
                        bbox = (line.x0, line.y0, line.x1, line.y1)
                        blocks.append(
                            OcrBlock(
                                text=text,
                                bbox=bbox,
                                confidence=TEXT_LAYER_CONFIDENCE,
                            )
                        )
                        total_chars += len(text)
                pages.append(OcrPage(page_number=index, blocks=blocks))
        except Exception:  # noqa: BLE001 — fallback failed; report honestly
            return None

        meta: dict = {"extractor": "pdfminer.six"}
        if reason == "parse_error":
            meta["note"] = self._PDFMINER_NOTES["parse_error"].format(
                error=f"{type(error).__name__}: {error}" if error else "unknown"
            )
        else:
            meta["note"] = self._PDFMINER_NOTES.get(reason, "")
        if total_chars < _MIN_CHARS_FOR_TEXT_LAYER:
            meta["note"] = (
                "The PDF carries no usable text layer (likely a scan); "
                "pixel OCR (tesseract or azure) is required for its content."
            )
        return OcrDocument(
            pages=pages, provider=self.name, provider_meta=meta, page_count=len(pages)
        )
