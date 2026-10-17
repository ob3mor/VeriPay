"""Extraction module: OCR output → structured fields → validation → rows.

- ``service``: the ocr_extraction job (provider selection with honest
  fallback, field persistence, upsert-per-version) + human field review.
- ``fields``: label-based + provider-hint field extraction with
  normalization (Arabic-Indic digits, Arabic/English labels).
- ``validation``: extraction-quality checks (arithmetic, IBAN mod-97,
  date/currency formats, uncertain critical fields) — quality QA, not
  fraud signals.
"""
