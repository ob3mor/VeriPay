# ADR 0007: Canonical model vocabulary v2 (Phase 2) and the migration squash

Date: 2026-10-17 · Status: accepted (Phase 2)

## Context

The owner's Phase 2 brief fixes a canonical model list that supersedes the
Phase 1 design names: VendorAuthorizedContact, VendorBankAccount (with the
pending/approved/rejected/revoked workflow), BankAccountChangeRequest,
ExtractionResult, EvidenceMatch, FraudFinding, InvestigationCase,
ReviewAction, AuditEvent. The repository was unpushed and no database existed
in the wild when Phase 2 started.

## Decision

- Rename/rebuild to the owner's vocabulary (mapping in docs/DATABASE.md
  §"v2 vocabulary"): `vendor_trusted_accounts` → `vendor_bank_accounts`
  (verification_status → status; verified/failed → approved/rejected),
  `extracted_fields` → `extraction_results` + `extraction_fields`,
  `duplicate_matches` → `evidence_matches` (generalized match kinds),
  `cases` → `investigation_cases`, `case_notes` → `review_actions`,
  `audit_logs` → `audit_events`. New tables: `vendor_authorized_contacts`,
  `bank_account_change_requests`, `fraud_findings`, `processing_jobs`,
  `sessions`.
- **Squash the migration chain** to a single `0001_full_schema` (validated
  upgrade/downgrade/`alembic check` on scratch SQLite). The staged Phase 1
  chain 0001–0006 was deleted with the schema it described; nothing had ever
  run against it outside scratch files.
- Roles: `org_admin | finance_officer | reviewer | auditor` (replaces
  owner/admin/analyst/reviewer and the never-implemented `viewer`).

## Consequences

- The model layer, API surface, contracts, and docs speak one vocabulary.
- Fresh clones get the complete schema in one step (and the compose API
  container applies it automatically before serving).
- Any future rename now costs a real migration — the vocabulary is canonical.
