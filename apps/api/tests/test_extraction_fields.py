"""Structured field extraction (app/modules/extraction/fields.py):
normalization primitives, Arabic/English labels, provider hints, provenance
contract. Deterministic unit tests — no OCR engine needed."""

from decimal import Decimal

from app.adapters.ocr.base import OcrBlock, OcrDocument, OcrPage
from app.modules.extraction.fields import (
    BANK_NAME,
    CONTACT_EMAIL,
    CONTACT_PHONE,
    DUE_DATE,
    ExtractedFieldData,
    IBAN,
    INVOICE_DATE,
    INVOICE_NUMBER,
    LINE_ITEMS,
    PO_REFERENCE,
    SUBTOTAL,
    TAX,
    TOTAL,
    VENDOR_NAME,
    VENDOR_TAX_ID,
    extract_fields,
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_digits,
    normalize_iban,
)
from app.modules.extraction.validation import validate_fields


def _doc(lines: list[str], *, provider: str = "text_layer", confidence=None) -> OcrDocument:
    return OcrDocument(
        pages=[
            OcrPage(
                page_number=1,
                blocks=[
                    OcrBlock(text=line, confidence=confidence) for line in lines if line
                ],
            )
        ],
        provider=provider,
        page_count=1,
    )


def _by_name(fields):
    return {f.field_name: f for f in fields}


# --------------------------------------------------------------------------
# Normalization primitives
# --------------------------------------------------------------------------


def test_normalize_digits_arabic_and_persian():
    assert normalize_digits("١٢٣٤") == "1234"
    assert normalize_digits("۰۱۲") == "012"
    assert normalize_digits("فات-2026-١٠٠") == "فات-2026-100"
    assert normalize_digits("1٫٢٠٠") == "1.200"  # Arabic decimal separator


def test_normalize_amount_conventions():
    assert normalize_amount("1,234.56") == Decimal("1234.56")
    assert normalize_amount("1.234,56") == Decimal("1234.56")
    assert normalize_amount("١٢٠٠.٠٠") == Decimal("1200.00")
    assert normalize_amount("€1.190,00") == Decimal("1190.00")
    assert normalize_amount("1190.00 EUR") == Decimal("1190.00")
    assert normalize_amount("2") == Decimal("2")
    assert normalize_amount("kein Betrag") is None


def test_normalize_date_formats():
    assert normalize_date("15.10.2026") == "2026-10-15"
    assert normalize_date("2026-10-02") == "2026-10-02"
    assert normalize_date("01.11.2026") == "2026-11-01"
    assert normalize_date("15/10/2026") == "2026-10-15"
    assert normalize_date("١٥.١٠.٢٠٢٦") == "2026-10-15"
    assert normalize_date("not a date") is None


def test_normalize_iban_and_currency():
    assert normalize_iban("DE89 3704 0044 0532 0130 00") == "DE89370400440532013000"
    assert normalize_iban("iban: sa03 8000 0000 6080 1016 7519") == (
        "SA0380000000608010167519"
    )
    assert normalize_currency("EUR") == "EUR"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("EURO") is None


# --------------------------------------------------------------------------
# Label matching (English + Arabic)
# --------------------------------------------------------------------------


def test_english_labels_extract_with_provenance():
    fields = _by_name(
        extract_fields(
            _doc(
                [
                    "Vendor: Contoso GmbH",
                    "Invoice Number: INV-1",
                    "Invoice Date: 15.10.2026",
                    "Due Date: 14.11.2026",
                    "Currency: EUR",
                    "Subtotal: 1,000.00",
                    "Tax (19%): 190.00",
                    "Total: 1,190.00",
                    "PO Number: PO-7",
                ]
            )
        )
    )
    vendor = fields[VENDOR_NAME]
    assert vendor.normalized_value == {"value": "Contoso GmbH"}
    assert vendor.provider == "text_layer"
    assert vendor.page == 1
    assert vendor.supporting_text == "Vendor: Contoso GmbH"
    assert vendor.human_verified is False  # extraction never self-verifies
    assert vendor.source == "label"
    assert fields[INVOICE_NUMBER].normalized_value == {"value": "INV-1"}
    assert fields[INVOICE_DATE].normalized_value == {"value": "2026-10-15"}
    assert fields[DUE_DATE].normalized_value == {"value": "2026-11-14"}
    assert fields["currency"].normalized_value == {"value": "EUR"}
    assert fields[SUBTOTAL].normalized_value == {"value": "1000.00", "currency": None}
    assert fields[TAX].normalized_value == {"value": "190.00", "currency": None}
    assert fields[TOTAL].normalized_value == {"value": "1190.00", "currency": None}
    assert fields[PO_REFERENCE].normalized_value == {"value": "PO-7"}


def test_arabic_labels_and_digit_normalization():
    fields = _by_name(
        extract_fields(
            _doc(
                [
                    "البائع: شركة النور",
                    "الرقم الضريبي: ٣٠١٢٣٤٥٦٧٨",
                    "رقم الفاتورة: ف-2027-٥",
                    "التاريخ: 15.01.2027",
                    "تاريخ الاستحقاق: 14.02.2027",
                    "العملة: EGP",
                    "المجموع الفرعي: ١٠٠٠.٠٠",
                    "الضريبة: ١٥٠.٠٠",
                    "الإجمالي: ١١٥٠.٠٠",
                    "رقم أمر الشراء: أمر-٩",
                ]
            )
        )
    )
    assert fields[VENDOR_NAME].normalized_value == {"value": "شركة النور"}
    assert fields[VENDOR_TAX_ID].normalized_value == {"value": "3012345678"}
    assert fields[INVOICE_NUMBER].normalized_value == {"value": "ف-2027-5"}
    assert fields[INVOICE_DATE].normalized_value == {"value": "2027-01-15"}
    assert fields[DUE_DATE].normalized_value == {"value": "2027-02-14"}
    assert fields["currency"].normalized_value == {"value": "EGP"}
    assert fields[SUBTOTAL].normalized_value["value"] == "1000.00"
    assert fields[TAX].normalized_value["value"] == "150.00"
    assert fields[TOTAL].normalized_value["value"] == "1150.00"
    assert fields[PO_REFERENCE].normalized_value == {"value": "أمر-9"}


def test_next_line_value_fallback_and_label_guard():
    fields = _by_name(
        extract_fields(
            _doc(["Invoice Number:", "INV-2026-9", "Vendor: Contoso GmbH"])
        )
    )
    assert fields[INVOICE_NUMBER].normalized_value == {"value": "INV-2026-9"}
    assert "/ " in fields[INVOICE_NUMBER].supporting_text  # label + value spans


def test_bare_title_does_not_swallow_the_next_label_line():
    """'INVOICE' alone (no value) must not consume 'Vendor: …' as its value."""
    fields = _by_name(extract_fields(_doc(["INVOICE", "Vendor: Contoso GmbH"])))
    assert INVOICE_NUMBER not in fields
    assert fields[VENDOR_NAME].normalized_value == {"value": "Contoso GmbH"}


def test_total_vs_subtotal_disambiguation():
    fields = _by_name(extract_fields(_doc(["Subtotal: 100.00", "Total: 119.00"])))
    assert fields[SUBTOTAL].normalized_value["value"] == "100.00"
    assert fields[TOTAL].normalized_value["value"] == "119.00"


# --------------------------------------------------------------------------
# Label-less patterns
# --------------------------------------------------------------------------


def test_iban_email_phone_extraction():
    fields = _by_name(
        extract_fields(
            _doc(
                [
                    "Bank: Stadtbank Berlin",
                    "IBAN: DE89 3704 0044 0532 0130 00",
                    "Email: Billing@Contoso.Example",
                    "Tel: +49 30 1234567",
                ]
            )
        )
    )
    assert fields[BANK_NAME].normalized_value == {"value": "Stadtbank Berlin"}
    assert fields[IBAN].normalized_value == {"value": "DE89370400440532013000"}
    assert fields[CONTACT_EMAIL].normalized_value == {"value": "billing@contoso.example"}
    assert fields[CONTACT_PHONE].normalized_value == {"value": "+49 30 1234567"}


def test_line_items_extract_and_iban_is_not_one():
    fields = _by_name(
        extract_fields(
            _doc(
                [
                    "Description  Qty  Price  Total",
                    "Consulting  2  400.00  800.00",
                    "Chairs  3  130.00  390.00",
                    "IBAN: DE89 3704 0044 0532 0130 00",
                ]
            )
        )
    )
    items = fields[LINE_ITEMS].normalized_value["items"]
    assert [i["description"] for i in items] == ["Consulting", "Chairs"]
    assert [i["line_total"] for i in items] == ["800.00", "390.00"]


def test_confidence_travels_as_is_and_none_stays_none():
    fields = _by_name(extract_fields(_doc(["Total: 10.00"], confidence=None)))
    assert fields[TOTAL].confidence is None  # never invented
    fields = _by_name(extract_fields(_doc(["Total: 10.00"], confidence=0.42)))
    assert fields[TOTAL].confidence == 0.42


def test_provider_field_hints_win_and_normalize():
    ocr = OcrDocument(
        pages=[
            OcrPage(
                page_number=2,
                blocks=[
                    OcrBlock(
                        text="Contoso",
                        confidence=0.91,
                        field_hint=VENDOR_NAME,
                    ),
                    OcrBlock(
                        text="15.10.2026",
                        confidence=0.9,
                        field_hint=INVOICE_DATE,
                    ),
                ],
            )
        ],
        provider="azure",
        page_count=2,
    )
    fields = _by_name(extract_fields(ocr))
    assert fields[VENDOR_NAME].source == "provider_field"
    assert fields[VENDOR_NAME].page == 2
    assert fields[VENDOR_NAME].provider == "azure"
    assert fields[INVOICE_DATE].normalized_value == {"value": "2026-10-15"}


def test_first_occurrence_wins_document_order():
    fields = _by_name(extract_fields(_doc(["Total: 1.00", "Total: 2.00"])))
    assert fields[TOTAL].raw_value == "1.00"


# --------------------------------------------------------------------------
# Validation glue (quick integration of fields → validation)
# --------------------------------------------------------------------------


def test_valid_invoice_set_validates_clean():
    fields = extract_fields(
        _doc(
            [
                "Vendor: Contoso GmbH",
                "Invoice Number: INV-1",
                "Currency: EUR",
                "Subtotal: 1000.00",
                "Tax: 190.00",
                "Total: 1190.00",
                "IBAN: DE89 3704 0044 0532 0130 00",
            ],
            confidence=1.0,
        )
    )
    summary = validate_fields(fields)
    assert summary["status"] == "pass"
    arithmetic = next(c for c in summary["checks"] if c["check"] == "arithmetic_consistency")
    assert arithmetic["passed"] is True


def test_fields_without_confidence_are_flagged_uncertain():
    fields = extract_fields(_doc(["Total: 1190.00"], confidence=None))
    summary = validate_fields(fields)
    uncertain = [c for c in summary["checks"] if c["check"] == "uncertain_critical_field"]
    assert any(c["field_name"] == TOTAL for c in uncertain)
