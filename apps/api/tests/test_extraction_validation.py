"""Extraction-quality validation (app/modules/extraction/validation.py).

The severities here are DOCUMENT-QUALITY severities (info/warning/error) for
humans — never fraud signals, never risk scores. The IBAN checks state
explicitly that a passing checksum proves FORMAT only (R5)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from app.modules.extraction.fields import (  # noqa: E402
    ExtractedFieldData,
    INVOICE_DATE,
    INVOICE_NUMBER,
    SUBTOTAL,
    TAX,
    TOTAL,
    VENDOR_NAME,
)
from app.modules.extraction.validation import (  # noqa: E402
    FORMAT_ONLY_NOTE,
    validate_fields,
)

VALID_IBAN = "DE89370400440532013000"  # generator's known-valid example
MODIFIED_IBAN = "DE89370400440532013001"  # one digit altered → checksum fails


def _field(
    name: str,
    raw: str,
    value=None,
    *,
    confidence: float | None = 1.0,
) -> ExtractedFieldData:
    normalized = None if value is None else value
    return ExtractedFieldData(
        field_name=name,
        raw_value=raw,
        normalized_value=normalized,
        page=1,
        bbox=None,
        provider="text_layer",
        confidence=confidence,
        supporting_text=raw,
    )


def _amount_field(name: str, raw: str, amount: str, *, confidence=1.0):
    return _field(name, raw, {"value": amount, "currency": "EUR"}, confidence=confidence)


def _money_set(*, subtotal="1190.00", tax="226.10", total="1416.10", confidence=1.0):
    return [
        _amount_field(SUBTOTAL, subtotal, subtotal, confidence=confidence),
        _amount_field(TAX, tax, tax, confidence=confidence),
        _amount_field(TOTAL, total, total, confidence=confidence),
    ]


def _check(summary, check_name, field_name=None):
    for c in summary["checks"]:
        if c["check"] == check_name and (field_name is None or c["field_name"] == field_name):
            return c
    return None


# --------------------------------------------------------------------------
# Arithmetic
# --------------------------------------------------------------------------


def test_arithmetic_pass():
    summary = validate_fields(_money_set())
    check = _check(summary, "arithmetic_consistency")
    assert check["passed"] is True
    assert summary["status"] == "pass"


def test_arithmetic_mismatch_is_an_error_for_humans():
    summary = validate_fields(_money_set(total="1500.00"))
    check = _check(summary, "arithmetic_consistency")
    assert check["passed"] is False
    assert check["severity"] == "error"
    assert summary["status"] == "errors"


def test_arithmetic_with_missing_operands_is_info_not_fraud():
    fields = [_amount_field(TOTAL, "1416.10", "1416.10")]
    summary = validate_fields(fields)
    check = _check(summary, "arithmetic_consistency")
    assert check["passed"] is None
    assert check["severity"] == "info"
    assert "not evidence of anything" in check["message"]


def test_arithmetic_tolerance_accepts_cent_rounding():
    summary = validate_fields(
        _money_set(subtotal="1190.005", tax="226.10", total="1416.10")
    )
    # 1190.005 parses to Decimal('1190.005'); +226.10 = 1416.105 vs 1416.10 → 0.005 diff
    assert _check(summary, "arithmetic_consistency")["passed"] is True


# --------------------------------------------------------------------------
# IBAN mod-97
# --------------------------------------------------------------------------


def test_valid_iban_passes_with_format_only_note():
    fields = _money_set() + [_field("iban", VALID_IBAN, {"value": VALID_IBAN})]
    summary = validate_fields(fields)
    check = _check(summary, "iban_checksum", field_name="iban")
    assert check["passed"] is True
    assert "FORMAT only" in check["message"]
    assert FORMAT_ONLY_NOTE in check["message"]


def test_modified_account_iban_fails_checksum():
    fields = _money_set() + [_field("iban", MODIFIED_IBAN, {"value": MODIFIED_IBAN})]
    summary = validate_fields(fields)
    check = _check(summary, "iban_checksum", field_name="iban")
    assert check["passed"] is False
    assert check["severity"] == "error"
    assert "mod-97" in check["message"]
    # The failure explanation itself repeats the format-only caveat.
    assert "format" in check["message"].lower()


def test_malformed_bank_identifier_is_incomplete():
    fields = _money_set() + [_field("iban", "DE89", {"value": "DE89"})]
    summary = validate_fields(fields)
    check = _check(summary, "bank_identifier_incomplete", field_name="iban")
    assert check is not None and check["passed"] is False


def test_missing_iban_is_reported_informatively():
    summary = validate_fields(_money_set())
    check = _check(summary, "iban_checksum", field_name="iban")
    assert check is not None and check["passed"] is None
    assert "incomplete" in check["message"]


# --------------------------------------------------------------------------
# Dates / currency
# --------------------------------------------------------------------------


def test_unparseable_date_is_flagged():
    fields = [
        _field(INVOICE_DATE, "Sometime 2026", None),
    ]
    summary = validate_fields(fields)
    check = _check(summary, "date_format", field_name=INVOICE_DATE)
    assert check is not None and check["severity"] == "error"


def test_due_date_before_invoice_date_is_a_warning():
    fields = [
        _field(INVOICE_DATE, "2026-11-01", {"value": "2026-11-01"}),
        _field("due_date", "2026-10-01", {"value": "2026-10-01"}),
    ]
    summary = validate_fields(fields)
    check = _check(summary, "date_order")
    assert check is not None and check["severity"] == "warning"


def test_bad_currency_code_is_flagged():
    summary = validate_fields([_field("currency", "EURO", {"value": None})])
    check = _check(summary, "currency_format", field_name="currency")
    assert check is not None and check["severity"] == "error"


# --------------------------------------------------------------------------
# Uncertain critical fields (R3)
# --------------------------------------------------------------------------


def test_none_confidence_on_critical_field_is_flagged():
    summary = validate_fields(_money_set(confidence=None))
    for name in (SUBTOTAL, TOTAL):
        check = _check(summary, "uncertain_critical_field", field_name=name)
        if check is not None:  # subtotal/tax are not critical; total is
            assert check["severity"] == "warning"
    assert _check(summary, "uncertain_critical_field", field_name=TOTAL) is not None


def test_low_confidence_on_critical_field_is_flagged():
    summary = validate_fields(_money_set(confidence=0.5))
    assert _check(summary, "uncertain_critical_field", field_name=TOTAL) is not None


def test_missing_critical_field_is_info_about_a_gap_not_fraud():
    summary = validate_fields(
        [
            _field(INVOICE_NUMBER, "INV-1", {"value": "INV-1"}),
        ]
    )
    check = _check(summary, "critical_field_missing", field_name=VENDOR_NAME)
    assert check is not None and check["severity"] == "info"
    assert "not fraud" in check["message"]


def test_summary_shape_is_stable():
    summary = validate_fields(_money_set())
    assert set(summary) == {"status", "summary", "checks"}
    assert set(summary["summary"]) == {
        "checks_total", "errors", "warnings", "infos", "confidence_threshold",
    }


def test_fixture_ibans_really_differ_in_checksum_validity():
    """Ground-truth sanity: the generator's valid/modified pair must actually
    differ under mod-97 (guards against a silently wrong fixture)."""
    from app.modules.extraction.validation import _mod97_valid

    assert _mod97_valid(gf.IBAN_DE_VALID.replace(" ", ""))
    assert not _mod97_valid(gf.IBAN_DE_MODIFIED.replace(" ", ""))
    assert _mod97_valid(gf.IBAN_EG_VALID.replace(" ", ""))
    assert _mod97_valid(gf.IBAN_SA_VALID.replace(" ", ""))
