"""Structured field extraction from OCR blocks (Prompt-02).

Turns ``OcrDocument`` blocks into named invoice fields. Every produced field
carries the full provenance contract (R3): raw value, typed normalized value,
page, bbox, provider, provider confidence (``None`` when the provider gives
none — never invented), the supporting text, and a human-correction flag that
is always ``False`` at extraction time (humans correct fields through the
review endpoint afterwards).

Two sources, in priority order:
1. ``field_hint`` blocks — providers that recognize field identity themselves
   (Azure prebuilt-invoice) are trusted for the field NAME only; the value
   still goes through the same normalization.
2. Label-based matching over block lines — Arabic + English label variants
   (فاتورة/Invoice, التاريخ/Date, …), same-line values with next-line
   fallback.

Normalization is deliberately conservative: values that cannot be parsed
(dates, amounts) keep ``normalized_value=None`` so the validation module
flags them instead of this module guessing.

Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩ and the Persian extension ۰-۹) are
normalized to ASCII before any parse; amounts accept both ``1,234.56`` and
``1.234,56`` conventions.

First occurrence wins (document order) — deterministic; alternates are not
guessed at.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.adapters.ocr.base import OcrBlock, OcrDocument

# --------------------------------------------------------------------------
# Data contract
# --------------------------------------------------------------------------


@dataclass
class ExtractedFieldData:
    """One extracted field with its full provenance (R3)."""

    field_name: str
    raw_value: str | None
    normalized_value: dict | None
    page: int | None
    bbox: tuple[float, float, float, float] | None
    provider: str
    confidence: float | None  # None = provider gave none — never invented
    supporting_text: str | None
    # Always False at extraction time; flips via human review only.
    human_verified: bool = False
    # True when the field identity came from a provider field hint
    # (Azure) rather than label matching — provenance for the evaluation.
    source: str = "label"  # "label" | "provider_field"


# Field vocabulary (extraction_fields.field_name; DATABASE.md §12 lists the
# canonical examples; these are the ones this extractor produces).
VENDOR_NAME = "vendor_name"
VENDOR_TAX_ID = "vendor_tax_id"
INVOICE_NUMBER = "invoice_number"
INVOICE_DATE = "invoice_date"
DUE_DATE = "due_date"
CURRENCY = "currency"
SUBTOTAL = "subtotal"
TAX = "tax"
TOTAL = "total"
IBAN = "iban"
BANK_NAME = "bank_name"
PO_REFERENCE = "po_reference"
CONTACT_EMAIL = "contact_email"
CONTACT_PHONE = "contact_phone"
LINE_ITEMS = "line_items"

# Fields whose loss or uncertainty matters most downstream (validation
# flags them; the R3 gate still governs their use as evidence).
CRITICAL_FIELDS = (TOTAL, INVOICE_NUMBER, VENDOR_NAME, IBAN)

# --------------------------------------------------------------------------
# Normalization primitives
# --------------------------------------------------------------------------

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_PERSIAN_INDIC = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DECIMAL_SEP = "\u066b"  # ٫
_ARABIC_THOUSANDS_SEP = "\u066c"  # ٬

_CURRENCY_SYMBOLS = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "₹": "INR",
    "ج.م": "EGP",
    "ر.س": "SAR",
    "د.إ": "AED",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%dT%H:%M",
)


def normalize_digits(text: str) -> str:
    """Arabic-Indic / Persian-Indic digits → ASCII; Arabic decimal and
    thousands separators → ``.`` and removed."""
    text = text.translate(_ARABIC_INDIC).translate(_PERSIAN_INDIC)
    text = text.replace(_ARABIC_DECIMAL_SEP, ".").replace(_ARABIC_THOUSANDS_SEP, "")
    return text


def normalize_amount(raw: str) -> Decimal | None:
    """Parse a printed money/quantity string into a Decimal.

    Handles currency symbols/codes, thousands separators in both the
    ``1,234.56`` and ``1.234,56`` conventions, and Arabic-Indic digits.
    Returns None when the text is not a number (callers keep
    normalized_value None rather than guessing).
    """
    if raw is None:
        return None
    text = normalize_digits(raw).strip()
    text = text.replace(_ARABIC_THOUSANDS_SEP, "")
    for symbol in sorted(_CURRENCY_SYMBOLS, key=len, reverse=True):
        text = text.replace(symbol, "")
    text = re.sub(r"(?i)\b[A-Z]{3}\b", "", text)  # ISO codes: EUR, USD …
    text = re.sub(r"[\s\u00a0]", "", text)
    text = re.sub(r"[^0-9.,\-]", "", text)
    if not text or not re.search(r"\d", text):
        return None

    if "." in text and "," in text:
        # The LAST separator is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if len(tail) == 2 and head:
            text = text.replace(",", ".")  # decimal comma: 1234,56
        else:
            text = text.replace(",", "")  # thousands: 1,234 / 1,234,567
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_date(raw: str) -> str | None:
    """Parse a printed date into ISO ``YYYY-MM-DD``; None when unparseable."""
    if not raw:
        return None
    text = normalize_digits(raw).strip().strip(".,;")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_currency(raw: str) -> str | None:
    text = normalize_digits(raw).strip().upper().rstrip(".")
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    match = re.fullmatch(r"[A-Z]{3}", text)
    return text if match else None


def infer_currency(text: str) -> str | None:
    """Currency from a symbol or ISO code found inside an amount string."""
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    match = re.search(r"(?<![A-Z])(EUR|USD|GBP|EGP|SAR|AED|CHF|JPY)(?![A-Z])", text.upper())
    return match.group(1) if match else None


_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def normalize_iban(raw: str) -> str | None:
    """Extract + normalize an IBAN from free text (spaces removed, upper)."""
    if not raw:
        return None
    text = normalize_digits(raw).upper().replace(" ", "").replace("-", "")
    match = _IBAN_RE.search(text)
    return match.group(0) if match else None


def _money_normalized(raw: str) -> dict | None:
    amount = normalize_amount(raw)
    if amount is None:
        return None
    return {"value": f"{amount:f}", "currency": infer_currency(raw)}


# --------------------------------------------------------------------------
# Label vocabulary (Arabic + English)
# --------------------------------------------------------------------------

# Order matters: more specific labels first (vendor_tax_id before tax,
# subtotal before total, due_date before bare date fallbacks). Matching is
# anchored at the start of a line.
_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        VENDOR_TAX_ID,
        (
            r"tax\s*(?:id|number|no\.?)",
            r"vat\s*(?:id|number|no\.?|reg(?:ister)?\.?)",
            r"steuer[- ]?nr\.?",
            r"الرقم\s*الضريبي",
            r"الرقم\s*الجبائي",
        ),
    ),
    (
        INVOICE_NUMBER,
        (
            r"invoice\s*(?:number|no\.?|#|id)?",
            r"رقم\s*الفاتورة",
        ),
    ),
    (
        DUE_DATE,
        (
            r"due\s*date",
            r"payment\s*due(?:\s*date)?",
            r"date\s*due",
            r"تاريخ\s*الاستحقاق",
        ),
    ),
    (
        INVOICE_DATE,
        (
            r"invoice\s*date",
            r"date(?:\s*of\s*issue)?",
            r"تاريخ\s*الفاتورة",
            r"التاريخ",
        ),
    ),
    (
        PO_REFERENCE,
        (
            r"p\.?\s*o\.?\s*(?:number|no\.?|#)?",
            r"purchase\s*order(?:\s*(?:number|no\.?|#))?",
            r"رقم\s*أمر\s*الشراء",
            r"أمر\s*الشراء",
        ),
    ),
    (CURRENCY, (r"currency", r"العملة")),
    (
        VENDOR_NAME,
        (
            r"vendor(?:\s*name)?",
            r"supplier",
            r"seller",
            r"biller",
            r"from",
            r"البائع",
            r"المورد",
        ),
    ),
    (BANK_NAME, (r"bank(?:\s*name)?", r"اسم\s*البنك", r"البنك")),
    (SUBTOTAL, (r"sub[\s\-]*total", r"net\s*amount", r"المجموع\s*الفرعي")),
    (
        TAX,
        (r"sales\s*tax", r"value\s*added\s*tax", r"vat\b", r"tax", r"mwst", r"الضريبة", r"ضريبة"),
    ),
    (
        TOTAL,
        (r"grand\s*total", r"total\s*(?:amount)?", r"amount\s*due", r"balance\s*due", r"الإجمالي", r"المجموع"),
    ),
)

# "Tax (19%): 226.10" — the parenthetical rate must not break the label.
# Value grammar: either "label: value" (separator REQUIRED before an inline
# value — a bare "Invoice" prefix must never swallow the rest of a line) or
# a label-only line (value lives on the next block; _field_from_label falls
# back to it).
_LABEL_LINE_RE = {
    field_name: re.compile(
        r"^\s*(?:" + r"|".join(variants) + r")\s*(?:\([^)]*\))?\s*(?:[:\-–]\s*(.*)|\s*)$",
        re.IGNORECASE | re.UNICODE,
    )
    for field_name, variants in _LABELS
}

# Line-item row: description followed by qty, unit price, line total.
_LINE_ITEM_RE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<qty>\d[\d.,]*)\s+(?P<unit>\d[\d.,]*)\s+(?P<total>\d[\d.,]*)\s*$"
)

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extract_fields(ocr: OcrDocument) -> list[ExtractedFieldData]:
    """Extract the structured field set from OCR blocks, in document order."""
    extracted: list[ExtractedFieldData] = []
    seen: set[str] = set()

    # Pass 1 — provider-recognized fields (field_hint blocks).
    for page in ocr.pages:
        for block in page.blocks:
            if not block.field_hint or block.field_hint in seen:
                continue
            field_data = _field_from_hint(block, page.page_number, ocr.provider)
            if field_data is not None:
                extracted.append(field_data)
                seen.add(field_data.field_name)

    # Pass 2 — label matching, line by line (with next-line value fallback).
    for page in ocr.pages:
        blocks = [b for b in page.blocks if b.field_hint is None]
        for index, block in enumerate(blocks):
            for line in block.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = _match_labeled_line(line)
                if match is None:
                    continue
                field_name, raw_value = match
                if field_name in seen:
                    continue
                next_block = (
                    blocks[index + 1] if not raw_value and index + 1 < len(blocks) else None
                )
                field_data = _field_from_label(
                    field_name,
                    raw_value,
                    label_block=block,
                    value_block=next_block,
                    page_number=page.page_number,
                    provider=ocr.provider,
                )
                if field_data is not None:
                    extracted.append(field_data)
                    seen.add(field_data.field_name)

    # Pass 3 — label-less patterns: IBAN, email anywhere in the text.
    for page in ocr.pages:
        for block in page.blocks:
            if IBAN not in seen:
                iban = normalize_iban(block.text)
                if iban and _looks_like_iban_context(block.text):
                    extracted.append(
                        ExtractedFieldData(
                            field_name=IBAN,
                            raw_value=iban,
                            normalized_value={"value": iban},
                            page=page.page_number,
                            bbox=block.bbox,
                            provider=ocr.provider,
                            confidence=block.confidence,
                            supporting_text=block.text,
                        )
                    )
                    seen.add(IBAN)
            if CONTACT_EMAIL not in seen:
                match = _EMAIL_RE.search(block.text)
                if match:
                    email = match.group(0).strip(".,;")
                    extracted.append(
                        ExtractedFieldData(
                            field_name=CONTACT_EMAIL,
                            raw_value=email,
                            normalized_value={"value": email.lower()},
                            page=page.page_number,
                            bbox=block.bbox,
                            provider=ocr.provider,
                            confidence=block.confidence,
                            supporting_text=block.text,
                        )
                    )
                    seen.add(CONTACT_EMAIL)

    # Pass 4 — phone (label-based only: bare digit runs would match amounts)
    # and line items, both from unlabeled lines.
    for page in ocr.pages:
        blocks = [b for b in page.blocks if b.field_hint is None]
        for index, block in enumerate(blocks):
            if CONTACT_PHONE not in seen:
                phone = _match_phone_line(block.text)
                if phone:
                    extracted.append(
                        ExtractedFieldData(
                            field_name=CONTACT_PHONE,
                            raw_value=phone,
                            normalized_value={"value": phone},
                            page=page.page_number,
                            bbox=block.bbox,
                            provider=ocr.provider,
                            confidence=block.confidence,
                            supporting_text=block.text,
                        )
                    )
                    seen.add(CONTACT_PHONE)
            item = _match_line_item(block.text)
            if item is not None:
                existing = next(
                    (f for f in extracted if f.field_name == LINE_ITEMS), None
                )
                if existing is None:
                    extracted.append(
                        ExtractedFieldData(
                            field_name=LINE_ITEMS,
                            raw_value=block.text,
                            normalized_value={"items": [item]},
                            page=page.page_number,
                            bbox=block.bbox,
                            provider=ocr.provider,
                            confidence=block.confidence,
                            supporting_text=block.text,
                        )
                    )
                else:
                    existing.normalized_value["items"].append(item)
                    existing.raw_value = (existing.raw_value or "") + "\n" + block.text

    return extracted


# --------------------------------------------------------------------------
# Per-source helpers
# --------------------------------------------------------------------------


def _field_from_hint(
    block: OcrBlock, page_number: int, provider: str
) -> ExtractedFieldData | None:
    """Normalize a provider-recognized field (Azure prebuilt-invoice)."""
    name = block.field_hint
    raw = (block.text or "").strip()
    normalized: dict | None
    if name in (INVOICE_DATE, DUE_DATE):
        iso = normalize_date(raw)
        normalized = {"value": iso} if iso else None
    elif name in (SUBTOTAL, TAX, TOTAL):
        normalized = _money_normalized(raw)
    elif name == CURRENCY:
        code = normalize_currency(raw)
        normalized = {"value": code} if code else None
    elif name == IBAN:
        iban = normalize_iban(raw)
        normalized = {"value": iban} if iban else None
    elif name == LINE_ITEMS:
        return None  # Azure item lists need richer mapping — not claimed here
    else:
        normalized = {"value": raw} if raw else None
    if not raw:
        return None
    return ExtractedFieldData(
        field_name=name,
        raw_value=raw,
        normalized_value=normalized,
        page=page_number,
        bbox=block.bbox,
        provider=provider,
        confidence=block.confidence,
        supporting_text=raw,
        source="provider_field",
    )


def _match_labeled_line(line: str) -> tuple[str, str] | None:
    """(field_name, raw value) when a line starts with a known label."""
    for field_name, label_re in _LABEL_LINE_RE.items():
        match = label_re.match(line)
        if match:
            return field_name, (match.group(1) or "").strip()
    return None


def _field_from_label(
    field_name: str,
    raw_value: str,
    *,
    label_block: OcrBlock,
    value_block: OcrBlock | None,
    page_number: int,
    provider: str,
) -> ExtractedFieldData | None:
    value_block_conf = (
        value_block.confidence if value_block is not None else None
    )
    confidences = [c for c in (label_block.confidence, value_block_conf) if c is not None]
    confidence = min(confidences) if confidences else None
    bbox = label_block.bbox or (value_block.bbox if value_block else None)
    if not raw_value and value_block is not None:
        # Next-line fallback ONLY when the next line is not itself a labeled
        # line (a bare "INVOICE" title must not swallow the following
        # "Vendor: …" line as its value).
        next_first_line = value_block.text.strip().splitlines()[0].strip()
        if _match_labeled_line(next_first_line) is None:
            raw_value = value_block.text.strip()
            supporting = f"{label_block.text} / {value_block.text}"
        else:
            supporting = label_block.text
            value_block = None
    else:
        supporting = label_block.text
    if not raw_value:
        return None

    cleaned = raw_value.strip().strip("\"'").strip()
    normalized: dict | None
    if field_name in (INVOICE_DATE, DUE_DATE):
        iso = normalize_date(raw_value)
        normalized = {"value": iso} if iso else None
    elif field_name in (SUBTOTAL, TAX, TOTAL):
        normalized = _money_normalized(raw_value)
    elif field_name == CURRENCY:
        code = normalize_currency(raw_value)
        normalized = {"value": code} if code else None
    elif field_name in (INVOICE_NUMBER, PO_REFERENCE, VENDOR_TAX_ID):
        # Identifier fields: Arabic-Indic digits normalize; case kept.
        value = normalize_digits(cleaned)
        normalized = {"value": value} if value else None
    else:
        normalized = {"value": cleaned} if cleaned else None
    return ExtractedFieldData(
        field_name=field_name,
        raw_value=raw_value,
        normalized_value=normalized,
        page=page_number,
        bbox=bbox,
        provider=provider,
        confidence=confidence,
        supporting_text=supporting,
    )


def _looks_like_iban_context(text: str) -> bool:
    """The IBAN regex alone would match order numbers like 'GB00X...';
    require an IBAN/bank-context hint unless the text is essentially the
    IBAN itself."""
    if _IBAN_RE.fullmatch(text.replace(" ", "")):
        return True
    return bool(
        re.search(r"(?i)\biban\b|\baccount\b|\bhesab\b|الحساب|آيبان|ايبان", text)
    )


def _match_phone_line(line: str) -> str | None:
    match = re.match(
        r"^\s*(?:tel(?:ephone)?|phone|mobile|fax|telefon|هاتف|جوال|فاكس)\s*[:\-–]\s*(.+)$",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None
    phone = normalize_digits(match.group(1)).strip()
    if not re.fullmatch(r"\+?[\d][\d\s\-()]{5,}", phone):
        return None
    return phone


def _match_line_item(line: str) -> dict | None:
    """A line-item row: description, qty, unit price, line total.

    Labeled amount lines (Subtotal/Tax/Total) never match because they
    carry labels, not 3 trailing numbers — and any description containing
    a colon is treated as a label anyway (an IBAN line is not a line item).
    """
    line = line.strip()
    match = _LINE_ITEM_RE.match(line)
    if not match:
        return None
    if ":" in match.group("desc"):
        return None
    quantity = normalize_amount(match.group("qty"))
    unit_price = normalize_amount(match.group("unit"))
    line_total = normalize_amount(match.group("total"))
    if None in (quantity, unit_price, line_total):
        return None
    description = normalize_digits(match.group("desc")).strip()
    return {
        "description": description,
        "quantity": str(quantity),
        "unit_price": f"{unit_price:f}",
        "line_total": f"{line_total:f}",
    }
