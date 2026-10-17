"""Extraction-quality validation (Prompt-02) — NOT fraud signals.

Checks the extracted field set for internal consistency and well-formedness
and produces a human-readable summary that lands on the extraction result
(``extraction_results.validation_summary``). Severity vocabulary here is
*document quality* vocabulary (``info`` | ``warning`` | ``error``) — it is
deliberately NOT the fraud signal severity vocabulary; nothing in this
module scores risk, claims tampering, or auto-dispositions anything
(ARCHITECTURE §8: explainable signals are the fraud module's job).

Business invariants honored here:
- R3: a critical field with ``None``/low confidence is flagged as UNCERTAIN —
  it is never treated as confident evidence of anything.
- R5: a passing IBAN mod-97 checksum proves FORMAT ONLY. The explanation
  says so verbatim: ownership requires independent human verification.
- Missing values are reported as incomplete inputs, never as fraud.
"""

import re
from decimal import Decimal

from app.core.config import get_settings
from app.modules.extraction.fields import (
    CURRENCY,
    DUE_DATE,
    ExtractedFieldData,
    IBAN,
    INVOICE_DATE,
    SUBTOTAL,
    TAX,
    TOTAL,
    CRITICAL_FIELDS,
)

# subtotal + tax vs total tolerance: rounding to cents on both sides.
_ARITHMETIC_TOLERANCE = Decimal("0.02")

# A syntactically plausible IBAN: CC + 2 check digits + 10..30 alphanumerics.
_IBAN_SHAPE_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")

FORMAT_ONLY_NOTE = (
    "A passing mod-97 checksum proves the IBAN FORMAT only. It says nothing "
    "about ownership: an account belongs to the vendor only after "
    "independent human verification (R5)."
)


def _money(field: ExtractedFieldData | None) -> Decimal | None:
    if field is None or not field.normalized_value:
        return None
    raw = field.normalized_value.get("value")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # noqa: BLE001 — malformed numbers are reported, not raised
        return None


def _find(fields: list[ExtractedFieldData], name: str) -> ExtractedFieldData | None:
    return next((f for f in fields if f.field_name == name), None)


class _Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(
        self,
        check: str,
        *,
        passed: bool | None,
        severity: str,
        message: str,
        field_name: str | None = None,
    ) -> None:
        self.checks.append(
            {
                "check": check,
                "field_name": field_name,
                "passed": passed,
                "severity": severity,
                "message": message,
            }
        )


def validate_fields(
    fields: list[ExtractedFieldData], *, confidence_threshold: float | None = None
) -> dict:
    """Run every check over the extracted fields; return the summary dict
    persisted on the extraction result."""
    if confidence_threshold is None:
        confidence_threshold = get_settings().ocr_confidence_threshold
    report = _Report()
    by_name = {f.field_name: f for f in fields}

    _check_arithmetic(report, by_name)
    _check_iban(report, by_name.get(IBAN))
    _check_dates(report, by_name)
    _check_currency(report, by_name.get(CURRENCY))
    _check_uncertain_critical(report, by_name, confidence_threshold)

    errors = sum(1 for c in report.checks if c["severity"] == "error")
    warnings = sum(1 for c in report.checks if c["severity"] == "warning")
    infos = sum(1 for c in report.checks if c["severity"] == "info")
    status = "pass"
    if errors:
        status = "errors"
    elif warnings:
        status = "warnings"
    return {
        "status": status,
        "summary": {
            "checks_total": len(report.checks),
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "confidence_threshold": confidence_threshold,
        },
        "checks": report.checks,
    }


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def _check_arithmetic(report: _Report, by_name: dict[str, ExtractedFieldData]) -> None:
    subtotal = _money(by_name.get(SUBTOTAL))
    tax = _money(by_name.get(TAX))
    total = _money(by_name.get(TOTAL))

    missing = [
        name
        for name, value in (("subtotal", subtotal), ("tax", tax), ("total", total))
        if value is None
    ]
    if missing:
        report.add(
            "arithmetic_consistency",
            passed=None,
            severity="info",
            field_name=",".join(missing),
            message=(
                "Arithmetic not evaluated: "
                + ", ".join(missing)
                + " missing or unparseable. Missing values are an extraction "
                "gap, not evidence of anything."
            ),
        )
        return

    difference = abs((subtotal + tax) - total)
    if difference <= _ARITHMETIC_TOLERANCE:
        report.add(
            "arithmetic_consistency",
            passed=True,
            severity="info",
            message=(
                f"subtotal + tax = total holds ({subtotal} + {tax} = {total}, "
                f"tolerance {_ARITHMETIC_TOLERANCE})."
            ),
        )
    else:
        report.add(
            "arithmetic_consistency",
            passed=False,
            severity="error",
            message=(
                f"subtotal + tax ({subtotal} + {tax}) differs from total "
                f"({total}) by {difference}. The document needs human "
                "review — this can be an OCR misread or a real discrepancy."
            ),
        )


def _check_iban(report: _Report, iban_field: ExtractedFieldData | None) -> None:
    if iban_field is None:
        report.add(
            "iban_checksum",
            passed=None,
            severity="info",
            field_name="iban",
            message="No IBAN found on the document; bank identifiers are "
            "incomplete for remittance checks.",
        )
        return

    iban = ""
    if iban_field.normalized_value:
        iban = str(iban_field.normalized_value.get("value") or "")
    if not iban:
        report.add(
            "bank_identifier_incomplete",
            passed=False,
            severity="warning",
            field_name="iban",
            message="An IBAN-like value was extracted but could not be "
            "normalized; bank identifiers are incomplete.",
        )
        return

    if not _IBAN_SHAPE_RE.match(iban):
        report.add(
            "bank_identifier_incomplete",
            passed=False,
            severity="error",
            field_name="iban",
            message=(
                f"The bank identifier '{iban}' is incomplete or malformed "
                "(expected CCdd + 10-30 alphanumerics); it cannot be used "
                "for remittance matching."
            ),
        )
        return

    if _mod97_valid(iban):
        report.add(
            "iban_checksum",
            passed=True,
            severity="info",
            field_name="iban",
            message=(
                f"IBAN {iban} passes the mod-97 checksum. {FORMAT_ONLY_NOTE}"
            ),
        )
    else:
        report.add(
            "iban_checksum",
            passed=False,
            severity="error",
            field_name="iban",
            message=(
                f"IBAN {iban} FAILS the mod-97 checksum: the identifier as "
                "read is invalid (OCR misread, typo, or an altered account "
                "number). Do not treat it as a valid payee; route to human "
                "review. Note: even a passing checksum would prove format "
                f"only. {FORMAT_ONLY_NOTE}"
            ),
        )


def _mod97_valid(iban: str) -> bool:
    """ISO 7064 MOD 97-10: rearrange (append country code digits + check
    digits at the end), replace letters (A=10..Z=35), value mod 97 == 1."""
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged
    )
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _check_dates(
    report: _Report, by_name: dict[str, ExtractedFieldData]
) -> None:
    invoice_date = by_name.get(INVOICE_DATE)
    due_date = by_name.get(DUE_DATE)

    for field in (invoice_date, due_date):
        if field is None:
            continue
        parsed = (field.normalized_value or {}).get("value")
        if not parsed:
            report.add(
                "date_format",
                passed=False,
                severity="error",
                field_name=field.field_name,
                message=(
                    f"{field.field_name} value '{field.raw_value}' is not a "
                    "recognizable date format; it cannot be used until a "
                    "human verifies it."
                ),
            )
    if invoice_date and due_date:
        inv = (invoice_date.normalized_value or {}).get("value")
        due = (due_date.normalized_value or {}).get("value")
        if inv and due and due < inv:
            report.add(
                "date_order",
                passed=False,
                severity="warning",
                message=(
                    f"due_date ({due}) precedes invoice_date ({inv}); either "
                    "an extraction error or an unusual document."
                ),
            )


def _check_currency(
    report: _Report, currency_field: ExtractedFieldData | None
) -> None:
    if currency_field is None:
        report.add(
            "currency_format",
            passed=None,
            severity="info",
            field_name=CURRENCY,
            message="No currency field found on the document.",
        )
        return
    code = (currency_field.normalized_value or {}).get("value")
    if not code:
        report.add(
            "currency_format",
            passed=False,
            severity="error",
            field_name=CURRENCY,
            message=(
                f"Currency value '{currency_field.raw_value}' is not a 3-letter "
                "ISO 4217 code."
            ),
        )
    else:
        report.add(
            "currency_format",
            passed=True,
            severity="info",
            field_name=CURRENCY,
            message=f"Currency is a valid ISO 4217 code ({code}).",
        )


def _check_uncertain_critical(
    report: _Report,
    by_name: dict[str, ExtractedFieldData],
    threshold: float,
) -> None:
    for name in CRITICAL_FIELDS:
        field = by_name.get(name)
        if field is None:
            report.add(
                "critical_field_missing",
                passed=None,
                severity="info",
                field_name=name,
                message=(
                    f"Critical field '{name}' was not found on the document; "
                    "its absence is an extraction gap, not fraud."
                ),
            )
            continue
        confidence = field.confidence
        if confidence is None or confidence < threshold:
            report.add(
                "uncertain_critical_field",
                passed=False,
                severity="warning",
                field_name=name,
                message=(
                    f"Critical field '{name}' has confidence "
                    f"{confidence if confidence is not None else 'None'} "
                    f"(threshold {threshold}): it is UNCERTAIN and must not "
                    "become confident evidence (R3) until a human verifies it."
                ),
            )
