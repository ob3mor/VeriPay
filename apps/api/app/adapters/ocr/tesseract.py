"""OcrTesseractProvider — local pixel OCR via pytesseract (optional ``[ocr]``
extra) plus the tesseract BINARY, which is a system dependency and is probed
at build time. Arabic + English are read together via ``lang='ara+eng'``
(settings.tesseract_lang).

Honesty rules baked in:
- The binary/dependency check happens in ``__init__`` so the pipeline can
  fall back to the stub with an explicit reason instead of crashing mid-job.
- Word confidences from tesseract travel as-is (0..1); a line's confidence
  is the mean of its words' confidences. Tesseract's own "no confidence"
  (-1) maps to None — never to a made-up number.
- PDFs are NOT supported here (tesseract rasterizes pixels, it cannot read
  a PDF container without an external renderer): a clear error is raised so
  the caller can route PDFs to the text-layer provider instead.
"""

from io import BytesIO

from app.core.config import get_settings


class TesseractUnavailableError(RuntimeError):
    """Raised when the tesseract engine (binary or wrapper) is missing."""


def tesseract_available() -> bool:
    """True only when BOTH the pytesseract wrapper and the tesseract binary
    are usable in this environment."""
    try:
        import pytesseract
    except ImportError:
        return False
    try:
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 — any failure means "not usable"
        return False
    return True


def _word_confidence(raw_conf: float) -> float | None:
    """Tesseract word confidence is -1 (N/A) or 0..100."""
    if raw_conf is None or raw_conf < 0:
        return None
    return round(raw_conf / 100.0, 4)


class OcrTesseractProvider:
    name = "tesseract"

    def __init__(self, lang: str | None = None) -> None:
        try:
            import pytesseract  # noqa: F401 — availability probe
        except ImportError as exc:
            raise TesseractUnavailableError(
                "pytesseract is not installed (pip install 'veripay-api[ocr]')."
            ) from exc
        if not tesseract_available():
            raise TesseractUnavailableError(
                "The tesseract binary was not found on this system. Install "
                "tesseract (e.g. UB Mannheim build on Windows) with the "
                "'ara' and 'eng' language packs."
            )
        self.lang = lang or get_settings().tesseract_lang

    def extract(self, data: bytes, mime_type: str) -> "object":  # noqa: ANN201 — OcrDocument
        import pytesseract
        from PIL import Image, UnidentifiedImageError

        from app.adapters.ocr.base import OcrBlock, OcrDocument, OcrPage

        if mime_type not in ("image/png", "image/jpeg"):
            raise ValueError(
                "The tesseract provider reads images (PNG/JPEG) only; PDFs "
                "with a text layer belong to the text_layer provider."
            )
        try:
            image = Image.open(BytesIO(data))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError(f"The image could not be decoded: {exc}") from exc

        data_dict = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )

        # Group words into lines: tesseract's page/block/par/line numbers.
        lines: dict[tuple[int, int, int, int, int], list[dict]] = {}
        n = len(data_dict.get("text", []))
        for i in range(n):
            word = (data_dict["text"][i] or "").strip()
            key = (
                int(data_dict["page_num"][i]),
                int(data_dict["block_num"][i]),
                int(data_dict["par_num"][i]),
                int(data_dict["line_num"][i]),
                0,
            )
            lines.setdefault(key, []).append(
                {
                    "word": word,
                    "left": int(data_dict["left"][i]),
                    "top": int(data_dict["top"][i]),
                    "width": int(data_dict["width"][i]),
                    "height": int(data_dict["height"][i]),
                    "conf": _word_confidence(float(data_dict["conf"][i])),
                }
            )

        pages_by_number: dict[int, OcrPage] = {}
        for key in sorted(lines):
            words = lines[key]
            page_number = key[0]
            text_parts = [w["word"] for w in words if w["word"]]
            if not text_parts:
                continue
            confidences = [w["conf"] for w in words if w["conf"] is not None]
            confidence = (
                round(sum(confidences) / len(confidences), 4)
                if confidences
                else None
            )
            bbox = (
                float(min(w["left"] for w in words)),
                float(min(w["top"] for w in words)),
                float(max(w["left"] + w["width"] for w in words)),
                float(max(w["top"] + w["height"] for w in words)),
            )
            block = OcrBlock(
                text=" ".join(text_parts), bbox=bbox, confidence=confidence
            )
            page = pages_by_number.get(page_number)
            if page is None:
                page = OcrPage(page_number=page_number, blocks=[])
                pages_by_number[page_number] = page
            page.blocks.append(block)

        pages = [pages_by_number[k] for k in sorted(pages_by_number)]
        return OcrDocument(
            pages=pages,
            provider=self.name,
            provider_meta={
                "lang": self.lang,
                "input_mime": mime_type,
                "input_bytes": len(data),
            },
            page_count=len(pages),
        )
