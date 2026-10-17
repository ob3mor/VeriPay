# VeriPay — Database Design

Status: design v1 · 2026-10-17. Implementation contract for the SQLAlchemy 2 models and Alembic migrations.

## 1. Conventions (apply to every table)

- **Primary keys:** `id` as `sa.Uuid` (SQLAlchemy 2 portable type; native UUID on PostgreSQL, CHAR(32) on SQLite), generated client-side (`default=uuid4`).
- **Tenancy:** every table **except `organizations`** (the tenant root itself) carries `organization_id: sa.Uuid, ForeignKey("organizations.id"), nullable=False` **with an index on it** — the first column of the table's primary access indexes.
- **Timestamps:** `created_at` and `updated_at` as `DateTime(timezone=True)` with `server_default=func.now()`; `updated_at` also `onupdate=func.now()`. Kept on all tables, including `audit_logs`, for uniformity (rows there are never updated in practice — see §audit_logs).
- **Money:** `Numeric(14, 2)`; quantities/unit prices `Numeric(14, 4)`. Never float.
- **Status fields:** `String(32)` validated by Python `enum.StrEnum` + Pydantic v2 at the API boundary. **No DB-native enums** (portability, ADR 0002). CHECK constraints are used only where both PostgreSQL and SQLite support them.
- **Semi-structured data:** `sa.JSON` (JSONB on PostgreSQL, TEXT on SQLite). JSON is written and read whole — no JSON-path operators in queries (they would break SQLite parity).
- **Partial indexes:** any partial unique index **must** declare **both** `postgresql_where=` and `sqlite_where=`. With `postgresql_where` alone, SQLAlchemy emits a plain `CREATE UNIQUE INDEX` on SQLite — the predicate silently disappears (§7 documents the verified failure).
- **Naming:** snake_case plural tables; constraint/index names `uq_<table>_<cols>` / `ck_<table>_<rule>` / `ix_<table>_<cols>`.
- **Soft delete:** not used; deletions are hard and audited via `audit_logs`.

## 2. Entity-relationship overview

```
organizations ──< users
      │
      ├──< vendors ──< vendor_trusted_accounts
      │        │              ▲
      │        │              │  remittance account matched to invoice
      │        ├──< purchase_orders ──< invoices ────────┘
      │        │   (source_document_id)  │
      │        │                        ├──< invoice_line_items
      │        │                        ├──< fraud_assessments
      │        │                        ├──< duplicate_matches (pair with another invoices row)
      │        │                        └──< cases ──< case_notes >── users (author)
      │        └──< cases (vendor-scoped: invoice_id NULL)
      ├──< documents ──< extracted_fields
      │       ▲ invoices.source_document_id, purchase_orders.source_document_id
      └──< audit_logs  (polymorphic entity ref, no FK; actor_user_id → users; org nullable)
```

## 3. Phase 1 migration scope

Migration **`0001_core_identity`** (Alembic, authored against PostgreSQL — ADR 0002) creates exactly:

- `organizations`
- `users`

(plus Alembic's own `alembic_version`.) All other tables arrive in later migrations per §14. Tests never run Alembic: they create the whole schema from `Base.metadata.create_all` on SQLite.

## 4. organizations — tenant root

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `name` | String(200) | display name |
| `slug` | String(100) | URL-safe, immutable; used in future external references |
| `status` | String(32) | `active` \| `suspended`; default `active` |
| `created_at` / `updated_at` | timestamptz | |

Constraints: `uq_organizations_slug (slug)`.
Exception note: no `organization_id` column — this table **is** the tenant.

## 5. users

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK → organizations, NOT NULL | indexed |
| `email` | String(320) | **globally unique** — the login key (Phase 1 decision; see §16) |
| `password_hash` | String(255) | argon2/bcrypt via `core.security`; never plaintext, never serialized to API responses |
| `full_name` | String(200) | |
| `role` | String(32) | `owner` \| `admin` \| `analyst` \| `reviewer`; org creator gets `owner` |
| `status` | String(32) | `active` \| `disabled` |
| `last_login_at` | timestamptz, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `uq_users_email (email)`; `ix_users_organization_id (organization_id)`.
Relationships: organization; audit_logs (actor); case_notes (author); vendors/vendor_trusted_accounts (created_by / verified_by).

## 6. vendors

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `display_name` | String(200) | as shown in UI |
| `legal_name` | String(200), nullable | |
| `normalized_name` | String(200) | lowercased, punctuation-collapsed; the matching key for vendor resolution |
| `tax_id` | String(64), nullable | masked in API responses; matching-only access |
| `status` | String(32) | `active` \| `inactive` \| `blocked` |
| `notes` | Text, nullable | free-text context added by analysts |
| `created_by` | Uuid FK → users, nullable | NULL if ingested |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `uq_vendors_org_normalized_name (organization_id, normalized_name)`; `ix_vendors_org_status (organization_id, status)`.

## 7. vendor_trusted_accounts — trusted bank accounts (R5)

A "trusted account" is bank details the organization has on file from a verified source (contract, W-9/form, prior verified payment). Fraud analysis compares the remittance details printed on an invoice against these.

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `vendor_id` | Uuid FK → vendors, NOT NULL | indexed |
| `account_holder_name` | String(200) | |
| `bank_name` | String(200), nullable | |
| `bank_country` | String(2), nullable | ISO 3166-1 alpha-2 |
| `account_number_last4` | String(4), nullable | display only |
| `account_fingerprint` | String(64) | SHA-256 of the normalized full account identifier — used for exact matching; **full account numbers/IBANs are not stored** (data minimization; revisit only with dedicated encryption-at-rest) |
| `verification_status` | String(32) | `pending` \| `verified` \| `failed` \| `revoked`; **default `pending`** (R5) |
| `verification_method` | String(32), nullable | `callback_to_known_contact` \| `written_confirmation` \| `registry_check`; **required when status becomes `verified`** |
| `verification_reference` | String(200), nullable | who/when/what in free text (e.g. ticket id); required together with method |
| `verification_document_id` | Uuid FK → documents, nullable | **structured link** to the supporting document (bank letter/statement uploaded in the vendor's context via `documents.vendor_id`) — this is how the R5 verification workflow cites its own evidence |
| `verified_at` | timestamptz, nullable | |
| `verified_by` | Uuid FK → users, nullable | must be set by the human who verified |
| `is_current` | Boolean | marks the vendor's current on-file account |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes:
- **Partial unique index**: `uq_vta_one_current (organization_id, vendor_id) WHERE is_current` — one current trusted account per vendor per org. It must be declared with **both** dialect kwargs:
  `Index("uq_vta_one_current", "organization_id", "vendor_id", unique=True, postgresql_where=text("is_current"), sqlite_where=text("is_current"))`
  **Pitfall (design-reviewer-verified on SQLAlchemy 2.1.5 / Python 3.12.0 / SQLite 3.42.0; not re-run in this session):** an `Index` carrying only `postgresql_where` renders `CREATE UNIQUE INDEX uq_vta_one_current ON vendor_trusted_accounts (organization_id, vendor_id)` with **no WHERE clause** on SQLite, so inserting a second non-current (historical) account raises `IntegrityError` — the is_current history flow breaks on the dev/test dialect. Adding `sqlite_where=text("is_current")` fixes it. Phase 3 ships a contract test asserting one current + one historical account coexist (IMPLEMENTATION_PLAN.md §Phase 3).
- `ix_vta_org_vendor (organization_id, vendor_id)`; `ix_vta_org_fingerprint (organization_id, account_fingerprint)`.

Business rules encoded here: the `vendors` service refuses to set `verification_status = 'verified'` without `verification_method` + `verification_reference` + `verified_by`; there is no code path that flips status automatically (ARCHITECTURE §8.5).

## 8. purchase_orders

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `po_number` | String(100) | |
| `vendor_id` | Uuid FK → vendors, nullable | POs may be ingested before vendor resolution |
| `amount` | Numeric(14,2), nullable | NULL until extraction/manual entry completes |
| `currency` | String(3), nullable | ISO 4217 |
| `issued_at` | Date, nullable | |
| `description` | Text, nullable | |
| `status` | String(32) | `draft` \| `active` \| `closed` \| `cancelled` |
| `source_document_id` | Uuid FK → documents, nullable | set when the PO was ingested by upload |
| `created_by` | Uuid FK → users, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `uq_po_org_number (organization_id, po_number)`; `ix_po_org_vendor (organization_id, vendor_id)`.

## 9. invoices

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `vendor_id` | Uuid FK → vendors, nullable | NULL until vendor resolution (workflow step 3) — NULL is a state, not an error |
| `purchase_order_id` | Uuid FK → purchase_orders, nullable | linked PO; NULL → `missing_evidence` signal (R4), never fraud by itself |
| `invoice_number` | String(100) | |
| `invoice_date` | Date, nullable | |
| `due_date` | Date, nullable | |
| `currency` | String(3), nullable | |
| `subtotal_amount` / `tax_amount` / `total_amount` | Numeric(14,2), nullable | filled by extraction or manual entry |
| `remittance_bank_name_raw` | String(200), nullable | pay-to bank name **as printed on the invoice** |
| `remittance_account_raw` | String(120), nullable | pay-to account/IBAN as printed |
| `remittance_account_fingerprint` | String(64), nullable, indexed | normalized fingerprint of the printed details |
| `payment_account_id` | Uuid FK → vendor_trusted_accounts, nullable | the trusted account matched to the remittance details; **NULL (no match) → `bank_account_unverified`, severity `high`, forces `needs_review`** (ARCHITECTURE §8.5); a match against a `pending`/`failed`/`revoked` account yields the same signal |
| `status` | String(32) | `received` \| `processing` \| `needs_review` \| `closed`; no "approved"/"genuine" state exists (R1/R2) |
| `field_sources` | JSON, nullable | **per-column provenance**: `{column_name: {origin: "manual" \| "extracted", extracted_field_id, confidence_at_ingest}}`. The API stamps `origin: "manual"` for human-entered values; the extraction service stamps `origin: "extracted"` with a link to the `extracted_fields` row. **Invoice columns are the source of truth for computation; `extracted_fields` are provenance; fraud features consult `field_sources` to apply the R3 gate** (ARCHITECTURE §8.3): `manual` is gate-passed, `extracted` is gated on the provenance field's confidence/verification |
| `source_document_id` | Uuid FK → documents, nullable | |
| `created_by` | Uuid FK → users, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes:
- **There is deliberately NO unique constraint on `(organization_id, vendor_id, invoice_number)`.** The classic fraud pattern — a vendor re-billing the same invoice number, possibly with altered amounts — must reach duplicate detection and human review, not die in a 409. Re-submission is **allowed** at intake; the intake service records a `duplicate_matches` row (`match_type = invoice_number_match`) and sets `invoices.status = needs_review`. Duplicate numbers are a **signal**, never a rejection (API.md §2).
- `ix_invoice_org_vendor_number (organization_id, vendor_id, invoice_number)` — non-unique lookup index backing that check.
- `ix_invoice_org_status (organization_id, status)`; `ix_invoice_org_number (organization_id, invoice_number)`; `ix_invoice_org_remittance_fp (organization_id, remittance_account_fingerprint)`.
- **Unresolved-vendor duplicates:** the same check re-runs when `vendor_id` is filled by resolution (workflow step 3), creating `duplicate_matches` rows and setting `needs_review` for any hit — behavior is identical at intake and at resolution.

## 10. invoice_line_items

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `invoice_id` | Uuid FK → invoices, NOT NULL | |
| `position` | Integer | parse/display order |
| `description` | Text, nullable | |
| `quantity` | Numeric(14,4), nullable | |
| `unit_price` | Numeric(14,4), nullable | fractional unit prices are legitimate |
| `line_total` | Numeric(14,2), nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `ix_ili_org_invoice (organization_id, invoice_id)` (line items are almost always fetched with their invoice).

## 11. documents

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `kind` | String(32) | `invoice` \| `purchase_order` \| `bank_letter` \| `statement` \| `other` |
| `vendor_id` | Uuid FK → vendors, nullable, indexed | vendor context for non-invoice documents (bank letters, statements) — the seam that lets a trusted account's supporting document and the vendor's document history be found; **column added by migration `0003`** (the `vendors` table does not exist yet in `0002`) |
| `file_name` | String(255) | original file name |
| `mime_type` | String(120) | validated against an allowlist at upload |
| `size_bytes` | BigInteger | |
| `sha256` | String(64) | content hash |
| `storage_provider` | String(32) | `local` \| `minio` \| `azure_blob` — which adapter wrote the bytes |
| `storage_key` | String(500) | tenant-prefixed object key `{org_id}/{document_id}/{sha256}{ext}` (ARCHITECTURE §7.1) |
| `ocr_status` | String(32) | `pending` \| `processing` \| `done` \| `failed`; default `pending` |
| `ocr_provider` | String(64), nullable | provider id used |
| `ocr_completed_at` | timestamptz, nullable | |
| `page_count` | Integer, nullable | |
| `uploaded_by` | Uuid FK → users | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `uq_document_org_sha256 (organization_id, sha256)` — per-org content dedup; `ix_document_org_kind (organization_id, kind)`; `ix_document_org_vendor (organization_id, vendor_id)`; `ix_document_org_ocr_status (organization_id, ocr_status)`.
Bytes are never stored in the database — only via the `StorageProvider` seam.
Dedup consequence (deliberate): identical bytes re-uploaded within an org return the **same** document row, so two distinct documents with identical bytes cannot exist per org — which is why `duplicate_matches` has no content-hash match type (§14).

## 12. extracted_fields — OCR output with evidence spans + confidence (R3)

One row per extracted field per document extraction.

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `document_id` | Uuid FK → documents, NOT NULL | indexed |
| `invoice_id` | Uuid FK → invoices, nullable | set when an invoice record is created/bound from this document |
| `field_name` | String(100) | `invoice_number`, `invoice_date`, `vendor_name`, `vendor_tax_id`, `total_amount`, `currency`, `po_number`, `remittance_bank_name`, `remittance_account`, … |
| `field_value` | Text, nullable | value as extracted |
| `normalized_value` | JSON, nullable | typed normal form, e.g. `{"value": "1250.00", "currency": "EUR"}` |
| `confidence` | Float, nullable | 0..1; **NULL when the provider gives none (e.g. stub) — NULL behaves like "below gate"** |
| `evidence_spans` | JSON | array of `{page, block, text, bbox: [x0, y0, x1, y1], confidence}` — provenance humans inspect in step 7 |
| `extraction_version` | String(32) | extractor + model version |
| `verification_status` | String(32) | `unverified` \| `confirmed` \| `corrected` — human verification state |
| `verified_value` | Text, nullable | the human's value when corrected |
| `verified_by` | Uuid FK → users, nullable | |
| `verified_at` | timestamptz, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `uq_ef_org_doc_field_version (organization_id, document_id, field_name, extraction_version)`; `ix_ef_org_document (organization_id, document_id)`; `ix_ef_org_field (organization_id, field_name)`.
Re-extraction rule: re-running the **same** `extraction_version` on the same document **upserts** (replaces that version's rows in place — no 409); different versions coexist side by side.

Fraud gate (ARCHITECTURE §8.3): a field is usable as fraud evidence only when `verification_status <> 'unverified'` **or** `confidence >= OCR_CONFIDENCE_THRESHOLD` (default 0.85). Otherwise features emit `unverified_input`, never a mismatch.

## 13. fraud_assessments (EVC placeholder for Phase 4)

Append-only history; the latest row per invoice is the current assessment.

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `invoice_id` | Uuid FK → invoices, NOT NULL | indexed |
| `risk_level` | String(32) | `none` \| `low` \| `medium` \| `high` \| `critical` |
| `risk_score` | Float, nullable | 0..100, meaningful only within `model_version`; NULL when not computable |
| `model_version` | String(64) | feature + scoring version that produced this row |
| `feature_snapshot` | JSON | every computed feature with its inputs and evidence references at assessment time |
| `signals` | JSON | array of `{type, severity, field_refs, evidence_refs, message}`; typed vocabulary with default severities — single source of truth is ARCHITECTURE §8: `missing_evidence` (≤ `medium`), `unverified_input` (`low`), `field_provenance_conflict` (`medium`), `duplicate_candidate` (`medium`), `amount_mismatch` (`high`), `bank_account_unverified` (`high`, floor — may not be downgraded) |
| `explanation` | JSON | ordered human-readable reasons — the "explainable" deliverable |
| `evc` | JSON, nullable | **Phase 4 placeholder.** Reserved for the Phase 4 EVC construct; must remain NULL until Phase 4 defines it. No code may read or write it before then |
| `status` | String(32) | `complete` \| `partial` \| `failed` |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `ix_fa_org_invoice (organization_id, invoice_id)`; `ix_fa_org_risk (organization_id, risk_level)`.
There is **no** `is_fraud`/`is_genuine` column (R2). Between Phases 4 and 5 the mandatory-case obligation for `critical` assessments is **derived on read, not stored**: a `critical` assessment without an associated `cases` row is by definition an unmet obligation (no transient marker that a restart could lose); Phase 5 backfills cases for exactly that set.

## 14. duplicate_matches

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `source_invoice_id` | Uuid FK → invoices, NOT NULL | |
| `matched_invoice_id` | Uuid FK → invoices, NOT NULL | |
| `match_type` | String(32) | `invoice_number_match` (same org + vendor + number, at intake or resolution) \| `near_duplicate` (fuzzy content similarity across distinct documents) \| `field_overlap` (key fields match, values differ). **No `exact_content_hash`**: per-org document sha256 dedup collapses identical bytes to one row, so two distinct documents with identical bytes cannot exist within an org (§11) |
| `similarity_score` | Float | 0..1 |
| `matched_fields` | JSON | which fields matched and with which values |
| `status` | String(32) | `open` \| `dismissed` \| `confirmed` — **human** disposition |
| `reviewed_by` | Uuid FK → users, nullable | |
| `reviewed_at` | timestamptz, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `ck_dm_not_self CHECK (source_invoice_id <> matched_invoice_id)`; `ix_dm_org_source (organization_id, source_invoice_id)`; `ix_dm_org_matched (organization_id, matched_invoice_id)`.
Both invoices necessarily share `organization_id` (rows are created from org-scoped queries), so cross-org pairing cannot occur.

## 15. cases, case_notes, audit_logs

### cases (Phase 5)

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `case_number` | String(32) | human-friendly, per-org sequence, e.g. `CASE-2026-0001` |
| `invoice_id` | Uuid FK → invoices, nullable | vendor-scoped cases have NULL here |
| `vendor_id` | Uuid FK → vendors, nullable | at least one of invoice/vendor required (CHECK) |
| `triggering_assessment_id` | Uuid FK → fraud_assessments, nullable | the assessment that opened the case (R6 provenance) — with append-only assessment history the *latest* assessment can differ from the triggering one, so the composed view anchors on this column, falling back to the latest |
| `title` | String(200) | |
| `description` | Text, nullable | |
| `severity` | String(32) | `low` \| `medium` \| `high` \| `critical` — mirrored from the triggering assessment |
| `status` | String(32) | `open` \| `in_review` \| `waiting_vendor` \| `closed` |
| `outcome` | String(32), nullable | `fraud_confirmed` \| `policy_violation` \| `false_positive` \| `no_critical_findings` \| `inconclusive` — set **only by a human** at close; even `no_critical_findings` is a case disposition, not a claim the invoice is genuine (R2) |
| `assigned_to` | Uuid FK → users, nullable | |
| `opened_by` | Uuid FK → users, nullable | NULL when auto-opened by the fraud module (system actor) |
| `sla_due_at` | timestamptz, nullable | |
| `resolution_summary` | Text, nullable | **required when closing** |
| `closed_at` | timestamptz, nullable | |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `ck_case_target CHECK (invoice_id IS NOT NULL OR vendor_id IS NOT NULL)`; `ck_case_close CHECK (status <> 'closed' OR (outcome IS NOT NULL AND resolution_summary IS NOT NULL))`; `uq_case_org_number (organization_id, case_number)`; `ix_case_org_status (organization_id, status)`; `ix_case_org_assignee (organization_id, assigned_to)`.
`case_number` allocation is race-safe via the constraint as arbiter: `INSERT … SELECT MAX(case_number) + 1` for the org, retrying on uniqueness violation — never a bare `MAX+1` read-then-write (which races under concurrent case creation).
R6 enforcement: only `fraud` (system actor) auto-creates cases; the `cases` service rejects close without outcome + summary; no endpoint auto-closes.

### case_notes (Phase 5)

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK, NOT NULL | indexed |
| `case_id` | Uuid FK → cases, NOT NULL | |
| `author_id` | Uuid FK → users, nullable | NULL = system-generated note (e.g. auto-open reason) |
| `kind` | String(32) | `comment` \| `decision` \| `evidence_reference` \| `system` |
| `body` | Text | |
| `references` | JSON, nullable | linked entities `[{entity_type, entity_id}]` |
| `created_at` / `updated_at` | timestamptz | |

Constraints/indexes: `ix_cn_org_case (organization_id, case_id)`.

### audit_logs (Phase 6) — append-only

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `organization_id` | Uuid FK → organizations, **nullable**, indexed | **the one intentional exception to mandatory org scoping**: pre-auth events (e.g. failed login for an unknown email) have no tenant. Every row that has tenant context MUST carry it |
| `actor_user_id` | Uuid FK → users, nullable | NULL for system actors |
| `actor_type` | String(32) | `user` \| `system` |
| `action` | String(100) | dotted names: `user.registered`, `user.login_succeeded`, `user.login_failed`, `document.uploaded`, `assessment.created`, `case.opened`, `case.closed`, `vendor.account.verified`, … |
| `entity_type` | String(100), nullable | polymorphic |
| `entity_id` | Uuid, nullable | **no FK** — the log survives entity deletion |
| `detail` | JSON, nullable | ip, user_agent, request_id, before/after (secrets and credentials redacted) |
| `request_id` | String(64), nullable | correlates with the API error envelope |
| `occurred_at` | timestamptz, NOT NULL | event time — the source of truth |
| `created_at` / `updated_at` | timestamptz | kept for table-convention uniformity; rows are never updated (append-only enforced in the service layer; no update/delete endpoints) |

Constraints/indexes: `ix_al_org (organization_id)`; `ix_al_action (action)`; `ix_al_occurred (occurred_at)`; `ix_al_entity (entity_type, entity_id)`.

## 16. Migration plan

| Migration | Phase | Tables created |
|---|---|---|
| `0001_core_identity` | 1 | organizations, users |
| `0002_documents` | 2 | documents, extracted_fields |
| `0003_vendor_procurement` | 3 | vendors, vendor_trusted_accounts, purchase_orders, invoices, invoice_line_items (+ `ALTER documents ADD vendor_id`) |
| `0004_fraud` | 4 | fraud_assessments, duplicate_matches |
| `0005_cases` | 5 | cases (incl. `triggering_assessment_id`), case_notes |
| `0006_audit` | 6 | audit_logs |

Alembic targets PostgreSQL. On the development machine migrations can only be validated **offline** (`alembic upgrade head --sql`); the first live `upgrade head` against PostgreSQL happens under PROFILE A / CI (not runnable locally — no Docker).

## 17. SQLite fallback notes (ADR 0002)

- Tests create the schema via `Base.metadata.create_all` on SQLite. Alembic also runs against a **scratch SQLite file as an executability smoke test** (`alembic upgrade head` on a throwaway DB) — this catches model/migration drift that offline `--sql` (which emits SQL without validating against models) cannot. It validates migration *executability* only and is **not** a PostgreSQL substitute; the live-PG migration run remains a CI gate before any release.
- `sa.Uuid` → CHAR(32), `sa.JSON` → TEXT, `DateTime(timezone=True)` → ISO strings; code must not rely on server-side date arithmetic or PG-only functions. (Design-reviewer-verified on SQLAlchemy 2.1.5 / Python 3.12.0 / SQLite 3.42.0; not re-run in this session: `sa.Uuid` renders CHAR(32) as claimed, and `Numeric(14,2)` round-trips exactly as `Decimal('1250.10')` with no warnings. Fraud feature code must still compare money as `Decimal`, never float.)
- **Partial indexes need both `postgresql_where` and `sqlite_where`** (§1, §7): with only `postgresql_where`, SQLite builds a **full** unique index and the `is_current` history flow breaks. ALTERs touching them need Alembic batch mode.
- Concurrency: the no-Docker dev profile must set `PRAGMA busy_timeout` (≥ 5000 ms) + WAL and serialize OCR background-task writes (single-writer queue or per-org lock) — the Phase 1 sync engine plus SQLite on Windows will otherwise throw `database is locked` when background extraction writes race API requests.
- CHECK constraints work on both dialects; native enums, array columns, and JSON-path operators are banned by §1 conventions.
- Transaction/isolation semantics differ between dialects; tenant-isolation tests must run on both, and the suite must run on PostgreSQL under PROFILE A/CI before any release.
