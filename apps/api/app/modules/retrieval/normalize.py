"""Text normalization for bilingual (Arabic/English) invoice retrieval.

Deterministic, dependency-free normalization applied identically to indexed
text and to queries, so both sides meet in the same space:

- Arabic-Indic digits (U+0660–U+0669) and the Persian extension (U+06F0–U+06F9)
  fold to ASCII — ``١٢٣٤`` and ``۱۲۳۴`` match ``1234``.
- Arabic diacritics (tashkeel U+064B–U+065F, superscript alef U+0670) and
  tatweel (U+0640) are removed — matching is diacritics-insensitive.
- Alef variants (أ إ آ ٱ), teh marbuta (ة) and alef maqsura (ى) unify — the
  standard aggressive Arabic folding that survives OCR glyph variation.
- Casefolding + punctuation collapse for Latin text (``Acme-Co`` ≡ ``acme co``).
- Legal-form tokens (``Co.``, ``GmbH``, ``شركة``, ``مؤسسة`` …) are an
  equivalence class: stripped from BOTH sides of a comparison when something
  else remains, so ``Acme Co.`` ≡ ``Acme Company`` ≡ ``شركة Acme``.
- Arabic/English *label* variants (فاتورة/invoice, بنك/bank …) expand queries
  so a label written in either language reaches the same tokens.

Also provides the portable trigram similarity (Dice coefficient over character
3-grams) that the fallback backend uses — the same 0..1 scale pg_trgm's
``similarity()`` uses on PostgreSQL.
"""

import re
import unicodedata

# ------------------------------------------------------------------ digits ---
_ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"  # U+0660..U+0669
_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"  # U+06F0..U+06F9
_DIGIT_MAP = str.maketrans(
    {ord(a): str(i) for i, a in enumerate(_ARABIC_INDIC)}
    | {ord(p): str(i) for i, p in enumerate(_PERSIAN)}
)


def normalize_digits(text: str) -> str:
    """Arabic-Indic/Persian digits → ASCII (extraction/fields.py convention)."""
    return text.translate(_DIGIT_MAP)


# --------------------------------------------------------------- arabic ------
# Tashkeel (fathatan..sukun), superscript alef, small high letters, tatweel.
_ARABIC_MARKS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
# Alef variants → ا; teh marbuta ة → ه; alef maqsura ى → ي.
_ARABIC_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
    }
)


def _fold_arabic(text: str) -> str:
    text = _ARABIC_MARKS.sub("", text)
    return text.translate(_ARABIC_FOLD)


# ------------------------------------------------- punctuation / casing ------
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """The canonical comparison form: fold digits, marks, case, punctuation."""
    if not text:
        return ""
    text = normalize_digits(text)
    text = unicodedata.normalize("NFKC", text)
    text = _fold_arabic(text)
    text = text.casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalize_identifier(text: str | None) -> str:
    """Identifier form for exact matching: digits folded, alphanumerics kept,
    everything else dropped, casefolded — ``INV-2024/007`` ≡ ``inv 2024 007``
    ≡ ``INV2024007``."""
    if not text:
        return ""
    text = normalize_digits(text).casefold()
    return re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", text)


def tokenize(text: str | None) -> list[str]:
    """Whitespace tokens of the normalized form (order preserved)."""
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


# ------------------------------------------------------------ legal forms ----
# Equivalence class of company-legal-form tokens. Stored as the *normalized*
# spelling (they pass through normalize_text first at comparison time).
LEGAL_FORM_TOKENS = frozenset(
    {
        # English (incl. dotted abbreviations after punctuation collapse).
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "llp",
        "plc",
        "gmbh",
        "ag",
        "bv",
        "nv",
        "sa",
        "sarl",
        "sas",
        "sal",
        "wll",
        "est",
        "establishment",
        "trading",
        "group",
        "holding",
        "holdings",
        # Arabic (normalized: diacritics folded, ة→ه …).
        "شركه",  # شركة (company)
        "مؤسسه",  # مؤسسة (establishment)
        "مجموعه",  # مجموعة (group)
        "للتجاره",  # للتجارة (for trading)
        "تجاريه",  # تجارية (commercial)
        "محدوده",  # محدودة (limited)
        "مسؤوليه",  # مسؤولية (liability)
        "ذات",  # ذات (… own …) — only in legal-form phrases
    }
)


def strip_legal_forms(text: str) -> str:
    """Drop legal-form tokens from the normalized text (both scripts).

    Tokens are removed only while at least one content token remains, so
    ``شركة`` alone does not vanish into the empty string.
    """
    tokens = [t for t in normalize_text(text).split() if t]
    content = [t for t in tokens if t not in LEGAL_FORM_TOKENS]
    return " ".join(content if content else tokens)


def names_equivalent(a: str, b: str) -> bool:
    """Legal-form-insensitive name equality (``Acme Co.`` ≡ ``Acme Company``)."""
    return strip_legal_forms(a) == strip_legal_forms(b)


# ------------------------------------------------- AR/EN label variants ------
# Field-label vocabulary shared by both languages. A query token expands to
# its counterparts so a label in either script reaches the same matches (the
# extractor's label matching, extraction/fields.py, uses the same vocabulary).
# Keys AND values are in the NORMALIZED space (normalize_text folds ة→ه, أ→ا,
# ى→ي and strips diacritics) — expansion runs on normalized query tokens only.
LABEL_SYNONYMS: dict[str, frozenset[str]] = {
    "invoice": frozenset({"فاتوره"}),
    "فاتوره": frozenset({"invoice"}),
    "date": frozenset({"تاريخ", "التاريخ"}),
    "تاريخ": frozenset({"date"}),
    "total": frozenset({"اجمالي", "الاجمالي", "المجموع", "مجموع"}),
    "اجمالي": frozenset({"total"}),
    "الاجمالي": frozenset({"total"}),
    "المجموع": frozenset({"total"}),
    "subtotal": frozenset({"مجموع جزئي"}),
    "tax": frozenset({"ضريبه", "الضريبه"}),
    "ضريبه": frozenset({"tax"}),
    "bank": frozenset({"بنك", "البنك"}),
    "بنك": frozenset({"bank"}),
    "account": frozenset({"حساب", "الحساب"}),
    "حساب": frozenset({"account"}),
    "number": frozenset({"رقم", "الرقم"}),
    "رقم": frozenset({"number"}),
    "vendor": frozenset({"مورد", "المورد"}),
    "مورد": frozenset({"vendor"}),
    "currency": frozenset({"عمله", "العمله"}),
    "عمله": frozenset({"currency"}),
    "po": frozenset({"طلب شراء"}),
    "purchase": frozenset({"شراء"}),
    "order": frozenset({"طلب"}),
    "amount": frozenset({"مبلغ", "المبلغ"}),
    "مبلغ": frozenset({"amount"}),
    "payment": frozenset({"دفع"}),
    "دفع": frozenset({"payment"}),
}


def expand_label_variants(tokens: list[str]) -> list[str]:
    """Query-side expansion: add the other-language variants of label tokens.

    Returns the original tokens plus their synonyms (deduplicated, order
    stable). Compound phrases (e.g. "طلب شراء") are joined with a space and
    kept as phrase substrings for containment matching.
    """
    out: list[str] = list(tokens)
    for token in tokens:
        for synonym in LABEL_SYNONYMS.get(token, ()):  # exact token match
            if synonym not in out:
                out.append(synonym)
    return out


# ----------------------------------------------------------- trigrams --------
def trigram_set(text: str) -> frozenset[str]:
    """Character 3-grams of the normalized text (padded for short strings)."""
    normalized = normalize_text(text)
    if not normalized:
        return frozenset()
    if len(normalized) < 3:
        return frozenset({normalized})
    padded = f"  {normalized}  "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def trigram_similarity(a: str, b: str) -> float:
    """Dice coefficient over character trigrams, 0..1 — the portable twin of
    pg_trgm's ``similarity()`` (same scale, not bit-identical values)."""
    ta, tb = trigram_set(a), trigram_set(b)
    if not ta or not tb:
        return 0.0
    return 2.0 * len(ta & tb) / (len(ta) + len(tb))
