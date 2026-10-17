"""Information retrieval & evidence search (Prompt-03).

Public surface (import from here, not submodules, where possible):

- ``search`` / ``get_invoice_evidence`` / ``suggest_vendor_resolutions``
  (``service``) — the read-only retrieval API used by ``api/v1``.
- ``build_search_index`` (``indexing``) — the org-scoped searchable projection.
- IR evaluation metrics (``metrics``) used by the evaluation tests.

Hard rules encoded across this module:

- **Org filtering happens BEFORE candidate generation.** Every SQL pull that
  feeds candidates or the index carries ``WHERE organization_id = :org``; the
  PostgreSQL technique branches apply the same predicate inside every UNION
  arm. No code path sees a row from another tenant.
- **Trust-aware ranking.** An unverified upload is never promoted into the
  trusted vendor master: trust tiers are an explicit multiplier on the fused
  score (``trust.py``), and entity resolution only ever *suggests* candidates —
  merging is a human confirm flow (existing ``POST /invoices/{id}/resolve-vendor``).
- **Uncertain OCR never becomes confident evidence** (R3): unverified
  extraction fields keep the ``unverified_upload`` tier regardless of score.
- Missing relationships surface as ``missing_evidence``-style gaps with
  severity capped at ``medium`` and language stating the record may simply not
  exist in VeriPay (R4). Nothing here claims genuineness (R2) or moves money.
"""
