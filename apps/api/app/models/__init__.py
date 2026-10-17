"""SQLAlchemy 2 models for the VeriPay tables (docs/DATABASE.md, v2 vocabulary).

All tables use portable types and the conventions from DATABASE.md §1:
UUID PKs generated client-side, ``organization_id`` + index on every tenant
table (except ``organizations`` itself), timestamps, Numeric money, sa.JSON,
explicitly-named constraints, partial indexes declared for BOTH dialects.

``audit_events`` is the one table with a *nullable* organization_id (the
intentional exception: pre-auth events have no tenant).
"""

from app.models.audit import AuditEvent
from app.models.cases import InvestigationCase, ReviewAction
from app.models.documents import Document, ExtractionField, ExtractionResult
from app.models.fraud import EvidenceMatch, FraudAssessment, FraudFinding
from app.models.identity import Organization, Session, User
from app.models.processing import ProcessingJob
from app.models.procurement import Invoice, InvoiceLineItem, PurchaseOrder
from app.models.vendors import (
    BankAccountChangeRequest,
    Vendor,
    VendorAuthorizedContact,
    VendorBankAccount,
)

__all__ = [
    "AuditEvent",
    "BankAccountChangeRequest",
    "Document",
    "EvidenceMatch",
    "ExtractionField",
    "ExtractionResult",
    "FraudAssessment",
    "FraudFinding",
    "Invoice",
    "InvoiceLineItem",
    "InvestigationCase",
    "Organization",
    "ProcessingJob",
    "PurchaseOrder",
    "ReviewAction",
    "Session",
    "User",
    "Vendor",
    "VendorAuthorizedContact",
    "VendorBankAccount",
]
