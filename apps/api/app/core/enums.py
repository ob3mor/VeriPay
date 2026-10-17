"""Status vocabularies (Python ``StrEnum`` per docs/DATABASE.md §1).

Status columns are plain ``String(32)`` in the database (no DB-native enums);
these enums + Pydantic v2 validate values at the API boundary.
"""

from enum import StrEnum


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(StrEnum):
    """The four canonical roles (owner's Phase 2 contract).

    - ``org_admin``: full administrative control of the organization.
    - ``finance_officer``: prepares the payment decision (outside VeriPay);
      may upload, register vendors/accounts/POs/invoices, work cases.
    - ``reviewer``: verifies bank accounts, dispositions findings, closes cases.
    - ``auditor``: read-only over the audit trail.
    """

    ORG_ADMIN = "org_admin"
    FINANCE_OFFICER = "finance_officer"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class VendorStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class BankAccountStatus(StrEnum):
    """R5: a new account starts ``pending``; ONLY a human approves, and only
    with an independent verification record. No code path auto-approves."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class BankAccountVerificationMethod(StrEnum):
    CALLBACK_TO_KNOWN_CONTACT = "callback_to_known_contact"
    WRITTEN_CONFIRMATION = "written_confirmation"
    REGISTRY_CHECK = "registry_check"


class ChangeRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    # R1/R2: no "approved"/"genuine" state exists.
    RECEIVED = "received"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    CLOSED = "closed"


class DocumentKind(StrEnum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    BANK_LETTER = "bank_letter"
    STATEMENT = "statement"
    OTHER = "other"


class ProcessingStatus(StrEnum):
    """Durable processing state machine (documents, extraction results,
    processing jobs). Transitions are guarded in the service layer; retries
    are idempotent via processing_jobs.idempotency_key."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_MANUAL_INPUT = "requires_manual_input"


class JobType(StrEnum):
    OCR_EXTRACTION = "ocr_extraction"
    DUPLICATE_SCAN = "duplicate_scan"
    ASSESSMENT = "assessment"


class ExtractionFieldVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"


class MatchKind(StrEnum):
    """evidence_matches kinds. The three duplicate kinds come from the
    duplicate-detection design; bank_account/vendor/purchase_order record
    matches against trusted registries with their evidence."""

    BANK_ACCOUNT = "bank_account"
    VENDOR = "vendor"
    PURCHASE_ORDER = "purchase_order"
    INVOICE_NUMBER = "invoice_number"
    NEAR_DUPLICATE = "near_duplicate"
    FIELD_OVERLAP = "field_overlap"


class MatchStatus(StrEnum):
    OPEN = "open"
    DISMISSED = "dismissed"
    CONFIRMED = "confirmed"


class SignalType(StrEnum):
    """The fraud signal vocabulary — single source of truth is
    docs/ARCHITECTURE.md §8. Default severities live in
    core/fraud_rules.py; bank_account_unverified has severity floor high."""

    MISSING_EVIDENCE = "missing_evidence"
    UNVERIFIED_INPUT = "unverified_input"
    FIELD_PROVENANCE_CONFLICT = "field_provenance_conflict"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    AMOUNT_MISMATCH = "amount_mismatch"
    BANK_ACCOUNT_UNVERIFIED = "bank_account_unverified"


class FindingDisposition(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AssessmentStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    WAITING_VENDOR = "waiting_vendor"
    CLOSED = "closed"


class CaseSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CaseOutcome(StrEnum):
    # Even no_critical_findings is a disposition, not a genuineness claim (R2).
    FRAUD_CONFIRMED = "fraud_confirmed"
    POLICY_VIOLATION = "policy_violation"
    FALSE_POSITIVE = "false_positive"
    NO_CRITICAL_FINDINGS = "no_critical_findings"
    INCONCLUSIVE = "inconclusive"


class ReviewActionType(StrEnum):
    COMMENT = "comment"
    DECISION = "decision"
    ASSIGNMENT = "assignment"
    STATUS_CHANGE = "status_change"
    FIELD_VERIFIED = "field_verified"
    ACCOUNT_VERIFIED = "account_verified"
    ACCOUNT_CHANGE_APPROVED = "account_change_approved"
    ACCOUNT_CHANGE_REJECTED = "account_change_rejected"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
