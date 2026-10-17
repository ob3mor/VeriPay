"""Generate deterministic synthetic invoice fixtures for extraction tests.

Output (default): apps/api/tests/fixtures/

  normal_invoice.pdf      English invoice with embedded text (valid IBAN)
  arabic_invoice.pdf      Arabic labels + Arabic-Indic digits
  mixed_language.pdf      English labels with Arabic values/digits
  modified_account.pdf    like normal_invoice but with an altered IBAN digit
                          (fails the mod-97 checksum)
  duplicate_invoice.pdf   same invoice number as normal_invoice, other amounts
  missing_po_invoice.pdf  no PO reference line
  blurry_scan.png         Pillow-rendered, deliberately blurred "scan"
                          (no text layer — pixel-OCR territory)

Honesty notes:
- Content is deterministic (fixed text, reportlab invariant=1) so evaluation
  numbers are reproducible.
- Arabic is drawn in LOGICAL order without a shaping engine: the rendered
  glyphs look disconnected — these fixtures exist for TEXT-extraction
  testing, not visual fidelity.
- The PDFs have a real text layer (that is the point of the default
  text_layer provider); blurry_scan.png is the counter-example.

Run:  apps\\api\\.venv\\Scripts\\python.exe scripts\\generate_fixtures.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

FIXTURES_DIR = REPO_ROOT / "apps" / "api" / "tests" / "fixtures"

# Candidate Arabic+Latin-capable fonts (Windows first — this dev machine).
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)

# A handful of well-known, publicly documented VALID example IBANs (they
# pass mod-97; the modified fixture flips one digit to break that).
IBAN_DE_VALID = "DE89 3704 0044 0532 0130 00"
IBAN_DE_MODIFIED = "DE89 3704 0044 0532 0130 01"  # last digit altered
IBAN_EG_VALID = "EG38 0019 0005 0000 0000 2631 8000 2"
IBAN_SA_VALID = "SA03 8000 0000 6080 1016 7519"


@dataclass
class FixtureSpec:
    """One fixture: its drawn lines and the extraction ground truth.

    ``expected`` maps field_name → expected normalized value (what
    app.modules.extraction.fields should produce); ``absent`` lists fields
    that must NOT be extracted from this fixture.
    """

    file_name: str
    lines: list[str]
    expected: dict[str, str] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    expect_arithmetic_ok: bool = True


NORMAL_LINES = [
    "INVOICE",
    "Vendor: Contoso Office Supplies GmbH",
    "VAT No: DE812345678",
    "Tel: +49 30 1234567",
    "Email: billing@contoso.example",
    "Bank: Stadtbank Berlin",
    f"IBAN: {IBAN_DE_VALID}",
    "Invoice Number: INV-2026-0042",
    "Invoice Date: 15.10.2026",
    "Due Date: 14.11.2026",
    "Currency: EUR",
    "PO Number: PO-2026-0007",
    "",
    "Description            Qty   Unit Price   Total",
    "Consulting services    2     400.00       800.00",
    "Office chairs          3     130.00       390.00",
    "",
    "Subtotal: 1190.00",
    "Tax (19%): 226.10",
    "Total: 1416.10",
]

ARABIC_LINES = [
    "فاتورة",
    "البائع: شركة الأفق للقرطاسية",
    "الرقم الضريبي: ٣٠١٢٣٤٥٦٧٨",
    "هاتف: ٠٢٢٣٤٥٦٧٨٩٠",
    "البريد الإلكتروني: billing@alofok.example",
    "البنك: بنك النيل",
    f"IBAN: {IBAN_EG_VALID}",
    "رقم الفاتورة: فات-2026-١٠٠",
    "التاريخ: 15.10.2026",
    "تاريخ الاستحقاق: 14.11.2026",
    "العملة: EGP",
    "رقم أمر الشراء: أمر-2026-55",
    "",
    "المجموع الفرعي: ١٢٠٠.٠٠",
    "الضريبة: ١٨٠.٠٠",
    "الإجمالي: ١٣٨٠.٠٠",
]

MIXED_LINES = [
    "INVOICE / فاتورة",
    "Vendor: شركة الأفق للقرطاسية",
    "Invoice Number: INV-2026-0077",
    "التاريخ: 2026-10-02",
    "Due Date: 01.11.2026",
    "Currency: EUR",
    "PO Number: PO-2026-0099",
    "Bank: بنك النيل",
    f"IBAN: {IBAN_SA_VALID}",
    "",
    "Paper supply A4   5   210.00   1050.00",
    "",
    "Subtotal: ١٠٥٠.٠٠",
    "Tax (VAT): 157.50",
    "Total: 1207.50",
]

MODIFIED_ACCOUNT_LINES = [
    "INVOICE",
    "Vendor: Contoso Office Supplies GmbH",
    "VAT No: DE812345678",
    "Tel: +49 30 1234567",
    "Email: billing@contoso.example",
    "Bank: Stadtbank Berlin",
    f"IBAN: {IBAN_DE_MODIFIED}",
    "Invoice Number: INV-2026-0044",
    "Invoice Date: 15.10.2026",
    "Due Date: 14.11.2026",
    "Currency: EUR",
    "PO Number: PO-2026-0007",
    "",
    "Subtotal: 1190.00",
    "Tax (19%): 226.10",
    "Total: 1416.10",
]

DUPLICATE_LINES = [
    "INVOICE",
    "Vendor: Contoso Office Supplies GmbH",
    "Invoice Number: INV-2026-0042",
    "Invoice Date: 16.10.2026",
    "Due Date: 15.11.2026",
    "Currency: EUR",
    "PO Number: PO-2026-0007",
    "",
    "Subtotal: 500.00",
    "Tax (19%): 95.00",
    "Total: 595.00",
]

MISSING_PO_LINES = [
    "INVOICE",
    "Vendor: Contoso Office Supplies GmbH",
    "VAT No: DE812345678",
    "Tel: +49 30 1234567",
    "Email: billing@contoso.example",
    "Bank: Stadtbank Berlin",
    f"IBAN: {IBAN_DE_VALID}",
    "Invoice Number: INV-2026-0043",
    "Invoice Date: 15.10.2026",
    "Due Date: 14.11.2026",
    "Currency: EUR",
    "",
    "Subtotal: 1190.00",
    "Tax (19%): 226.10",
    "Total: 1416.10",
]

FIXTURES: list[FixtureSpec] = [
    FixtureSpec(
        file_name="normal_invoice.pdf",
        lines=NORMAL_LINES,
        expected={
            "vendor_name": "Contoso Office Supplies GmbH",
            "vendor_tax_id": "DE812345678",
            "contact_phone": "+49 30 1234567",
            "contact_email": "billing@contoso.example",
            "bank_name": "Stadtbank Berlin",
            "iban": "DE89370400440532013000",
            "invoice_number": "INV-2026-0042",
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-14",
            "currency": "EUR",
            "po_reference": "PO-2026-0007",
            "subtotal": "1190.00",
            "tax": "226.10",
            "total": "1416.10",
            "line_items": {
                "count": 2,
                "line_totals": ["800.00", "390.00"],
                "descriptions": ["Consulting services", "Office chairs"],
            },
        },
    ),
    FixtureSpec(
        file_name="arabic_invoice.pdf",
        lines=ARABIC_LINES,
        expected={
            "vendor_name": "شركة الأفق للقرطاسية",
            "vendor_tax_id": "3012345678",
            "contact_phone": "02234567890",
            "contact_email": "billing@alofok.example",
            "bank_name": "بنك النيل",
            "iban": "EG380019000500000000263180002",
            "invoice_number": "فات-2026-100",
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-14",
            "currency": "EGP",
            "po_reference": "أمر-2026-55",
            "subtotal": "1200.00",
            "tax": "180.00",
            "total": "1380.00",
        },
    ),
    FixtureSpec(
        file_name="mixed_language.pdf",
        lines=MIXED_LINES,
        expected={
            "vendor_name": "شركة الأفق للقرطاسية",
            "invoice_number": "INV-2026-0077",
            "invoice_date": "2026-10-02",
            "due_date": "2026-11-01",
            "currency": "EUR",
            "po_reference": "PO-2026-0099",
            "bank_name": "بنك النيل",
            "iban": "SA0380000000608010167519",
            "subtotal": "1050.00",
            "tax": "157.50",
            "total": "1207.50",
            "line_items": {
                "count": 1,
                "line_totals": ["1050.00"],
                "descriptions": ["Paper supply A4"],
            },
        },
    ),
    FixtureSpec(
        file_name="modified_account.pdf",
        lines=MODIFIED_ACCOUNT_LINES,
        expected={
            "vendor_name": "Contoso Office Supplies GmbH",
            "vendor_tax_id": "DE812345678",
            "contact_phone": "+49 30 1234567",
            "contact_email": "billing@contoso.example",
            "bank_name": "Stadtbank Berlin",
            "iban": "DE89370400440532013001",
            "invoice_number": "INV-2026-0044",
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-14",
            "currency": "EUR",
            "po_reference": "PO-2026-0007",
            "subtotal": "1190.00",
            "tax": "226.10",
            "total": "1416.10",
        },
        expect_arithmetic_ok=True,
    ),
    FixtureSpec(
        file_name="duplicate_invoice.pdf",
        lines=DUPLICATE_LINES,
        expected={
            "vendor_name": "Contoso Office Supplies GmbH",
            "invoice_number": "INV-2026-0042",
            "invoice_date": "2026-10-16",
            "due_date": "2026-11-15",
            "currency": "EUR",
            "po_reference": "PO-2026-0007",
            "subtotal": "500.00",
            "tax": "95.00",
            "total": "595.00",
        },
        absent=["iban", "contact_email", "contact_phone", "vendor_tax_id", "bank_name"],
    ),
    FixtureSpec(
        file_name="missing_po_invoice.pdf",
        lines=MISSING_PO_LINES,
        expected={
            "vendor_name": "Contoso Office Supplies GmbH",
            "vendor_tax_id": "DE812345678",
            "contact_phone": "+49 30 1234567",
            "contact_email": "billing@contoso.example",
            "bank_name": "Stadtbank Berlin",
            "iban": "DE89370400440532013000",
            "invoice_number": "INV-2026-0043",
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-14",
            "currency": "EUR",
            "subtotal": "1190.00",
            "tax": "226.10",
            "total": "1416.10",
        },
        absent=["po_reference"],
    ),
]


def _find_arabic_font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _pdf(lines: list[str], out_path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as canvas_module

    font_path = _find_arabic_font()
    font_name = "Helvetica"
    if font_path is not None:
        pdfmetrics.registerFont(TTFont("FixtureFont", font_path))
        font_name = "FixtureFont"

    c = canvas_module.Canvas(str(out_path), pagesize=A4, invariant=1)
    width, height = A4
    y = height - 60
    for line in lines:
        if line:
            c.setFont(font_name, 11)
            c.drawString(60, y, line)
        y -= 20
    c.showPage()
    c.save()


def _png(lines: list[str], out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("RGB", (900, 1100), "white")
    draw = ImageDraw.Draw(image)
    y = 40
    for line in lines:
        if line:
            draw.text((60, y), line, fill="black")
        y += 28
    # Deterministic degradation: a fixed blur, no random noise anywhere.
    image = image.filter(ImageFilter.GaussianBlur(radius=3))
    image.save(out_path, format="PNG")


def generate(out_dir: Path = FIXTURES_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in FIXTURES:
        path = out_dir / spec.file_name
        _pdf(spec.lines, path)
        written.append(path)
    scan_path = out_dir / "blurry_scan.png"
    _png(NORMAL_LINES, scan_path)
    written.append(scan_path)
    return written


def main() -> int:
    written = generate()
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
