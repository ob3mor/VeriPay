"""Unit tests for retrieval normalization (Prompt-03 §2): Arabic-Indic digits,
diacritics-insensitive matching, Arabic/English label variants, legal-form
equivalents, and the portable trigram similarity."""

from app.modules.retrieval.normalize import (
    expand_label_variants,
    names_equivalent,
    normalize_identifier,
    normalize_text,
    tokenize,
    trigram_set,
    trigram_similarity,
)


# ------------------------------------------------------------------ digits ---
def test_arabic_indic_digits_fold_to_ascii():
    assert normalize_text("فاتورة ١٢٣٤") == "فاتوره 1234"
    assert normalize_text("۱۲۳۴") == "1234"  # Persian extension


def test_identifier_keeps_digits_through_arabic_numerals():
    assert normalize_identifier("INV-٢٠٢٦/٠٠٧") == "inv2026007"
    assert normalize_identifier("INV-2026-007") == "inv2026007"
    assert normalize_identifier("INV 2026 007") == normalize_identifier(
        "inv2026007"
    )


# -------------------------------------------------------------- diacritics ---
def test_diacritics_are_insensitive():
    with_marks = "مُحَمَّد لُقْمَان"
    assert normalize_text(with_marks) == normalize_text("محمد لقمان")


def test_tatweel_removed():
    assert normalize_text("شــركة") == normalize_text("شركة")


def test_alef_and_teh_marbuta_unify():
    assert normalize_text("أحمد") == normalize_text("احمد")
    assert normalize_text("شركة") == normalize_text("شركه")
    assert normalize_text("مجموعة") == normalize_text("مجموعه")
    assert normalize_text("ى") == normalize_text("ي")


def test_latin_case_and_punctuation_collapse():
    assert normalize_text("Acme-Co, GmbH.") == "acme co gmbh"
    assert normalize_text("  multiple   spaces ") == "multiple spaces"


# ------------------------------------------------------------ identifiers ----
def test_normalize_identifier_forms_agree():
    assert normalize_identifier("PO 2026/001") == normalize_identifier("po-2026-001")
    assert normalize_identifier(None) == ""
    assert normalize_identifier("") == ""


# ------------------------------------------------------------- legal forms ---
def test_legal_form_equivalence_english():
    assert names_equivalent("Acme Co.", "Acme Company")
    assert names_equivalent("Acme Industrial GmbH", "Acme Industrial")
    assert not names_equivalent("Acme Co.", "Zahra Foods Ltd")


def test_legal_form_equivalence_arabic():
    assert names_equivalent("شركة النور للتجارة", "النور للتجارة")
    assert names_equivalent("مؤسسة البركة", "البركة")


def test_strip_legal_forms_never_empties_the_name():
    from app.modules.retrieval.normalize import strip_legal_forms

    assert strip_legal_forms("شركة") != ""  # nothing left → keep original tokens
    # "Trading"/"Co." are legal-form words on BOTH sides: "Nour Trading Co."
    # and "شركة النور للتجارة" both reduce to their content token(s).
    assert strip_legal_forms("Nour Trading Co.") == "nour"
    assert strip_legal_forms("شركة النور للتجارة") == "النور"


# ----------------------------------------------------------- label variants --
def test_label_expansion_english_to_arabic():
    assert expand_label_variants(["invoice"]) == ["invoice", "فاتوره"]
    expanded = expand_label_variants(["bank", "account"])
    assert set(expanded) == {
        "bank",
        "account",
        "بنك",
        "البنك",
        "حساب",
        "الحساب",
    }
    assert expanded[:2] == ["bank", "account"]  # originals keep their order


def test_label_expansion_arabic_to_english():
    assert expand_label_variants(["فاتوره"]) == ["فاتوره", "invoice"]
    assert expand_label_variants(["رقم"]) == ["رقم", "number"]


def test_label_expansion_is_deduplicated_and_stable():
    assert expand_label_variants(["invoice", "فاتوره"]) == ["invoice", "فاتوره"]


# ---------------------------------------------------------------- trigram ----
def test_trigram_identical_strings_score_one():
    assert trigram_similarity("Nour Trading Co", "Nour Trading Co") == 1.0


def test_trigram_disjoint_strings_score_zero():
    assert trigram_similarity("abc", "xyz") == 0.0


def test_trigram_ocr_typo_scores_high():
    # Misread 'o' as '0' — the OCR-error-tolerance case.
    score = trigram_similarity("Acme Gr0up Ltd", "Acme Group Ltd")
    assert score > 0.7


def test_trigram_arabic_diacritics_insensitive():
    assert trigram_similarity("مُحَمَّد", "محمد") == 1.0


def test_trigram_set_padding_for_short_strings():
    assert trigram_set("ab") == frozenset({"ab"})
    assert trigram_set("") == frozenset()
    assert len(trigram_set("abcd")) >= 4


def test_tokenize_uses_normalized_space():
    assert tokenize("INV-٢٠٢٦-٠٠٧ EUR") == ["inv", "2026", "007", "eur"]
