"""Seed a reproducible, fully SYNTHETIC demo dataset into the VeriPay database.

Everything in here is fictional: vendors, people, tax ids, banks and account
numbers (``XX00DEMO...`` patterns are not valid IBANs), ticket references, and
amounts. No real financial data exists anywhere in this file.

Honesty notes (docs/ARCHITECTURE.md §8 invariants):
- Bank-account approvals go through the REAL human service path
  (vendors.service.approve_bank_account) with the demo reviewer as the actor
  and clearly fictional verification references — the seed never flips an
  account's status directly, and pending accounts stay pending.
- Assessments are computed by the REAL deterministic engine
  (fraud.service.assess_invoice, rules-v0.1) — nothing here fabricates
  signals, scores, or explanations, and ``evc`` stays NULL.
- The investigation case is opened by the REAL cases.service.open_case with
  the demo reviewer as the human actor (rules-v0.1 never emits ``critical``,
  so R6 auto-open cannot fire — a human opens this one, which is the R6
  workflow anyway).
- Invoices are created through procurement.service.create_invoice, so the
  duplicate-number scenario produces a REAL intake-time evidence match and
  ``needs_review`` (docs/API.md §2 — duplicates are signals, never 409s).

Usage (from the repo root, against the no-Docker default SQLite):
    apps\\api\\.venv\\Scripts\\python.exe scripts\\seed_demo.py

Against PROFILE A PostgreSQL (compose up first):
    set VERIPAY_DATABASE_URL=postgresql+psycopg://veripay:veripay_dev@localhost:5432/veripay
    apps\\api\\.venv\\Scripts\\python.exe scripts\\seed_demo.py

Idempotent: if the demo organization (slug ``demo-co``) already exists the
script prints a note and exits 0 without touching anything. Every row uses a
fixed UUID, so a fresh database always seeds identically. If a previous run
failed halfway through, the org exists and the script will refuse to continue —
delete the database file (or drop the schema) and re-run.

Seeded scenarios (5 vendors, 8 POs, 12 invoices, 5 bank accounts, 1 case).
Per-signal severities follow docs/ARCHITECTURE.md §8; the aggregate
``risk_level`` of rules-v0.1 maps one notch below the worst individual signal
(observed run, 2026-10-17: a lone ``high`` signal aggregates to ``medium``,
``low``/``medium`` signals to ``low``/...). Invoice-level ``needs_review`` is
forced by the high-severity signals themselves, not by the aggregate level.

    #  invoice        scenario                                   signals (severity)                        aggregate risk
    1  INV-NW-1001    clean                                      —                                         none
    2  INV-NW-1002    clean                                      —                                         none
    3  INV-NW-1003    no printed pay-to details                  missing_evidence (medium, R4)             low
    4  INV-BT-2001    clean                                      —                                         none
    5  INV-BT-2001    DUPLICATE number, altered total            duplicate_candidate (medium) +            medium
                                                                 amount_mismatch (high); intake already
                                                                 recorded the match + needs_review
    6  INV-BT-2002    missing purchase order                     missing_evidence (medium, R4 —            low
                                                                 not fraud by itself)
    7  INV-BT-2003    MODIFIED pay-to account (≠ approved)       bank_account_unverified (high, R5)        medium → needs_review
    8  INV-HD-3001    remits to a PENDING account                bank_account_unverified (high, R5)        medium → needs_review
    9  INV-HD-3002    tampered amount + unverified account       amount_mismatch (high) +                  medium → needs_review
                                                                 bank_account_unverified (high)
    10 INV-KF-4001    vendor has NO accounts on file             bank_account_unverified (high)            medium → needs_review
    11 INV-SL-5001    extracted value below the confidence gate  unverified_input (low, R3)                none
    12 INV-SL-5002    extracted provenance disagrees with        field_provenance_conflict (medium,        low
                      the column                                 R3 — column wins)
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

# Make the API package importable when the script is run from the repo root
# (or anywhere else) with the venv interpreter.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: F401,E402 — registers every model on Base.metadata
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.enums import (  # noqa: E402
    BankAccountVerificationMethod,
    CaseSeverity,
    ReviewActionType,
    UserRole,
)
from app.core.security import hash_password  # noqa: E402
from app.modules.cases import service as cases_service  # noqa: E402
from app.modules.fraud import service as fraud_service  # noqa: E402
from app.modules.procurement import service as procurement_service  # noqa: E402
from app.models import (  # noqa: E402
    Invoice,
    Organization,
    User,
)
from app.modules.vendors import service as vendors_service  # noqa: E402

ORG_SLUG = "demo-co"
DEMO_PASSWORD = "VeriPay-Demo-2026!"

# Fixed UUIDs — every run on a fresh database produces identical ids.
def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


ORG_ID = _uid(1)
ADMIN_ID = _uid(11)     # org_admin
FINANCE_ID = _uid(12)   # finance_officer
REVIEWER_ID = _uid(13)  # reviewer
AUDITOR_ID = _uid(14)   # auditor

# Fictional pay-to account numbers. fingerprint_account() normalizes to DIGITS
# ONLY, so every distinct account below has a distinct digit string.
ACC_NW = "XX00DEMO00001001"        # Nordwind, approved
ACC_BT = "XX00DEMO00002002"        # Baltic, approved
ACC_SUB = "XX00DEMO99999999"       # the "modified" account printed on INV-BT-2003
ACC_HD = "XX00DEMO00003003"        # Helios, PENDING only
ACC_SL = "XX00DEMO00005005"        # Solaris, approved
ACC_KF_PRINTED = "XX00DEMO77777004"  # printed on INV-KF-4001; Kavanagh has no accounts on file


def _user(db_user_id: int, email: str, full_name: str, role: UserRole) -> User:
    return User(
        id=UUID(f"00000000-0000-4000-8000-{db_user_id:012d}"),
        organization_id=ORG_ID,
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=full_name,
        role=role.value,
    )


def _invoice(
    db, *, actor: User, vendor_id, po_id, number: str, issued: date, due: date,
    total: str, subtotal: str, bank: str | None, account: str | None,
) -> Invoice:
    return procurement_service.create_invoice(
        db,
        org_id=ORG_ID,
        actor=actor,
        invoice_number=number,
        vendor_id=vendor_id,
        purchase_order_id=po_id,
        invoice_date=issued,
        due_date=due,
        currency="EUR",
        subtotal_amount=Decimal(subtotal),
        tax_amount=Decimal(total) - Decimal(subtotal),
        total_amount=Decimal(total),
        remittance_bank_name_raw="Demo Bank (fictional)" if bank else None,
        remittance_account_raw=account,
        source_document_id=None,
    )


def seed() -> None:
    # Schema: on a fresh no-Docker SQLite this creates the full schema from the
    # models; on a database alembic already migrated it is a no-op (checkfirst).
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        existing = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
        if existing is not None:
            print(f"Demo data already present (organization slug {ORG_SLUG!r}) — nothing to do.")
            return

        org = Organization(id=ORG_ID, name="Demo Company AG (synthetic demo data)", slug=ORG_SLUG)
        db.add(org)
        users = {
            "admin": _user(11, "admin@demo.example", "Dana Reyes (demo)", UserRole.ORG_ADMIN),
            "finance": _user(12, "finance@demo.example", "Milo Brandt (demo)", UserRole.FINANCE_OFFICER),
            "reviewer": _user(13, "reviewer@demo.example", "Petra Kovacs (demo)", UserRole.REVIEWER),
            "auditor": _user(14, "auditor@demo.example", "Sam Okafor (demo)", UserRole.AUDITOR),
        }
        db.add_all(users.values())
        db.commit()
        admin, finance, reviewer = users["admin"], users["finance"], users["reviewer"]

        # --- 5 fictional vendors -------------------------------------------
        v_nw = vendors_service.create_vendor(
            db, org_id=ORG_ID, actor=admin, display_name="Nordwind Bürobedarf GmbH",
            legal_name="Nordwind Bürobedarf GmbH (fictional)", tax_id="DE00DEMO001",
            notes="Synthetic demo vendor — office supplies.",
        )
        v_bt = vendors_service.create_vendor(
            db, org_id=ORG_ID, actor=admin, display_name="Baltic IT Services OÜ",
            legal_name="Baltic IT Services OÜ (fictional)", tax_id="EE00DEMO002",
            notes="Synthetic demo vendor — carries the duplicate-number and modified-account scenarios.",
        )
        v_hd = vendors_service.create_vendor(
            db, org_id=ORG_ID, actor=admin, display_name="Helios Druck & Medien GmbH",
            legal_name="Helios Druck & Medien GmbH (fictional)", tax_id="DE00DEMO003",
            notes="Synthetic demo vendor — bank account still pending verification.",
        )
        v_kf = vendors_service.create_vendor(
            db, org_id=ORG_ID, actor=admin, display_name="Kavanagh Facilities Ltd",
            legal_name="Kavanagh Facilities Ltd (fictional)", tax_id="IE00DEMO004",
            notes="Synthetic demo vendor — deliberately has NO bank accounts on file.",
        )
        v_sl = vendors_service.create_vendor(
            db, org_id=ORG_ID, actor=admin, display_name="Solaris Consulting Sàrl",
            legal_name="Solaris Consulting Sàrl (fictional)", tax_id="CH00DEMO005",
            notes="Synthetic demo vendor — carries the R3 provenance scenarios.",
        )

        # --- Bank accounts: approved (with the human verification record) + pending
        acc_nw = vendors_service.create_bank_account(
            db, org_id=ORG_ID, vendor_id=v_nw.id, actor=finance, holder="Nordwind Bürobedarf GmbH",
            account_number=ACC_NW, bank_name="Demo Bank Hamburg (fictional)", bank_country="DE",
            make_current=True,
        )
        acc_bt = vendors_service.create_bank_account(
            db, org_id=ORG_ID, vendor_id=v_bt.id, actor=finance, holder="Baltic IT Services OÜ",
            account_number=ACC_BT, bank_name="Demo Bank Tallinn (fictional)", bank_country="EE",
            make_current=True,
        )
        acc_hd = vendors_service.create_bank_account(
            db, org_id=ORG_ID, vendor_id=v_hd.id, actor=finance, holder="Helios Druck & Medien GmbH",
            account_number=ACC_HD, bank_name="Demo Bank Leipzig (fictional)", bank_country="DE",
            make_current=True,
        )
        acc_sl = vendors_service.create_bank_account(
            db, org_id=ORG_ID, vendor_id=v_sl.id, actor=finance, holder="Solaris Consulting Sàrl",
            account_number=ACC_SL, bank_name="Demo Bank Geneva (fictional)", bank_country="CH",
            make_current=True,
        )
        # Historical pending account (exercises the is_current partial index:
        # one current + one non-current account coexist, DATABASE.md §7).
        acc_sl_old = vendors_service.create_bank_account(
            db, org_id=ORG_ID, vendor_id=v_sl.id, actor=finance, holder="Solaris Consulting Sàrl",
            account_number="XX00DEMO00005004", bank_name="Demo Bank Geneva (fictional)",
            bank_country="CH", make_current=False,
        )
        # R5: approval happens through the human service path, reviewer as the
        # deciding human, fictional references. Helios + the historical Solaris
        # account stay PENDING.
        for acc, method, ref in (
            (acc_nw, BankAccountVerificationMethod.CALLBACK_TO_KNOWN_CONTACT,
             "DEMO-CB-2026-001 (fictional callback log)"),
            (acc_bt, BankAccountVerificationMethod.WRITTEN_CONFIRMATION,
             "DEMO-WC-2026-014 (fictional signed confirmation)"),
            (acc_sl, BankAccountVerificationMethod.REGISTRY_CHECK,
             "DEMO-REG-2026-007 (fictional registry excerpt)"),
        ):
            vendors_service.approve_bank_account(
                db, org_id=ORG_ID, vendor_id=acc.vendor_id, account_id=acc.id,
                actor=reviewer, method=method.value, reference=ref,
                verification_document_id=None,
            )

        # --- Purchase orders -------------------------------------------------
        def po(number: str, vendor_id, amount: str, issued: date, what: str):
            return procurement_service.create_purchase_order(
                db, org_id=ORG_ID, actor=finance, po_number=number, vendor_id=vendor_id,
                amount=Decimal(amount), currency="EUR", issued_at=issued,
                description=f"{what} (synthetic demo data)",
            )

        po_nw1 = po("PO-2026-1001", v_nw.id, "1240.50", date(2026, 8, 3), "Office supplies Q3")
        po_nw2 = po("PO-2026-1002", v_nw.id, "2210.00", date(2026, 8, 12), "Office supplies Q3")
        po_nw3 = po("PO-2026-1003", v_nw.id, "640.00", date(2026, 8, 27), "Printer consumables")
        po_bt1 = po("PO-2026-2001", v_bt.id, "1850.00", date(2026, 8, 5), "Workstation rollout support")
        po_hd1 = po("PO-2026-3001", v_hd.id, "2200.00", date(2026, 8, 18), "Print run — product brochures")
        po_kf1 = po("PO-2026-4001", v_kf.id, "3480.00", date(2026, 8, 21), "Facilities maintenance September")
        po_sl1 = po("PO-2026-5001", v_sl.id, "1180.00", date(2026, 8, 25), "Process consulting, fixed fee")
        po_sl2 = po("PO-2026-5002", v_sl.id, "2410.00", date(2026, 9, 1), "Process consulting, phase 2")

        # --- Invoices (duplicate arrives last so intake records the match) ----
        inv_nw1 = _invoice(db, actor=finance, vendor_id=v_nw.id, po_id=po_nw1.id,
                           number="INV-NW-1001", issued=date(2026, 9, 2), due=date(2026, 10, 2),
                           total="1240.50", subtotal="1042.44", bank="Demo Bank Hamburg (fictional)", account=ACC_NW)
        inv_nw2 = _invoice(db, actor=finance, vendor_id=v_nw.id, po_id=po_nw2.id,
                           number="INV-NW-1002", issued=date(2026, 9, 9), due=date(2026, 10, 9),
                           total="2210.00", subtotal="1857.14", bank="Demo Bank Hamburg (fictional)", account=ACC_NW)
        inv_nw3 = _invoice(db, actor=finance, vendor_id=v_nw.id, po_id=po_nw3.id,
                           number="INV-NW-1003", issued=date(2026, 9, 15), due=date(2026, 10, 15),
                           total="640.00", subtotal="537.82", bank=None, account=None)  # no printed pay-to
        inv_bt1 = _invoice(db, actor=finance, vendor_id=v_bt.id, po_id=po_bt1.id,
                           number="INV-BT-2001", issued=date(2026, 9, 4), due=date(2026, 10, 4),
                           total="1850.00", subtotal="1554.62", bank="Demo Bank Tallinn (fictional)", account=ACC_BT)
        inv_bt2 = _invoice(db, actor=finance, vendor_id=v_bt.id, po_id=None,
                           number="INV-BT-2002", issued=date(2026, 9, 10), due=date(2026, 10, 10),
                           total="990.00", subtotal="831.93", bank="Demo Bank Tallinn (fictional)", account=ACC_BT)
        inv_bt3 = _invoice(db, actor=finance, vendor_id=v_bt.id, po_id=po_bt1.id,
                           number="INV-BT-2003", issued=date(2026, 9, 16), due=date(2026, 10, 16),
                           total="1850.00", subtotal="1554.62", bank="Unknown Bank (fictional)", account=ACC_SUB)
        inv_hd1 = _invoice(db, actor=finance, vendor_id=v_hd.id, po_id=po_hd1.id,
                           number="INV-HD-3001", issued=date(2026, 9, 8), due=date(2026, 10, 8),
                           total="2200.00", subtotal="1848.74", bank="Demo Bank Leipzig (fictional)", account=ACC_HD)
        inv_hd2 = _invoice(db, actor=finance, vendor_id=v_hd.id, po_id=po_hd1.id,
                           number="INV-HD-3002", issued=date(2026, 9, 20), due=date(2026, 10, 20),
                           total="3100.00", subtotal="2605.04", bank="Demo Bank Leipzig (fictional)", account=ACC_HD)
        inv_kf1 = _invoice(db, actor=finance, vendor_id=v_kf.id, po_id=po_kf1.id,
                           number="INV-KF-4001", issued=date(2026, 9, 12), due=date(2026, 10, 12),
                           total="3480.00", subtotal="2924.37", bank="Unknown Bank (fictional)", account=ACC_KF_PRINTED)
        inv_sl1 = _invoice(db, actor=finance, vendor_id=v_sl.id, po_id=po_sl1.id,
                           number="INV-SL-5001", issued=date(2026, 9, 14), due=date(2026, 10, 14),
                           total="1180.00", subtotal="991.60", bank="Demo Bank Geneva (fictional)", account=ACC_SL)
        inv_sl2 = _invoice(db, actor=finance, vendor_id=v_sl.id, po_id=po_sl2.id,
                           number="INV-SL-5002", issued=date(2026, 9, 22), due=date(2026, 10, 22),
                           total="2410.00", subtotal="2025.21", bank="Demo Bank Geneva (fictional)", account=ACC_SL)
        # The duplicate: same vendor + number as INV-BT-2001, total altered.
        # create_invoice records the intake-time evidence match and sets
        # needs_review (docs/API.md §2) — real intake behavior, not hand-made.
        inv_bt1_dup = _invoice(db, actor=finance, vendor_id=v_bt.id, po_id=po_bt1.id,
                               number="INV-BT-2001", issued=date(2026, 9, 24), due=date(2026, 10, 24),
                               total="4999.00", subtotal="4111.76", bank="Unknown Bank (fictional)", account=ACC_SUB)

        # R3 demo data: provenance metadata on two Solaris invoices. The invoice
        # COLUMNS stay the source of truth (docs/ARCHITECTURE.md §8.3); the
        # provenance records demonstrate the two gate outcomes.
        inv_sl1.field_sources = {
            "total_amount": {  # below the 0.85 gate → unverified_input, never a mismatch claim
                "origin": "extracted", "confidence": 0.42, "extracted_value": "1180.00",
            }
        }
        inv_sl2.field_sources = {
            "total_amount": {  # confident extraction that disagrees with the column → conflict; column wins
                "origin": "extracted", "confidence": 0.97, "extracted_value": "2104.00",
            }
        }
        db.commit()

        # --- Assessments: computed by the REAL engine (rules-v0.1) -----------
        print("Running the deterministic fraud engine (rules-v0.1) on all invoices:")
        assessments: dict[str, object] = {}
        for label, inv in (
            ("INV-NW-1001 clean", inv_nw1), ("INV-NW-1002 clean", inv_nw2),
            ("INV-NW-1003 no printed pay-to", inv_nw3), ("INV-BT-2001 clean", inv_bt1),
            ("INV-BT-2002 missing PO", inv_bt2), ("INV-BT-2003 modified account", inv_bt3),
            ("INV-HD-3001 pending account", inv_hd1), ("INV-HD-3002 tampered amount", inv_hd2),
            ("INV-KF-4001 no accounts on file", inv_kf1), ("INV-SL-5001 low-confidence provenance", inv_sl1),
            ("INV-SL-5002 provenance conflict", inv_sl2),
            ("INV-BT-2001 DUPLICATE (altered total)", inv_bt1_dup),
        ):
            assessment = fraud_service.assess_invoice(
                db, org_id=ORG_ID, invoice_id=inv.id, actor=finance, context=None
            )
            assessments[inv.id] = assessment
            print(f"  {label:40s} -> risk={assessment.risk_level:8s} score={assessment.risk_score:g}")

        # --- The one investigation case (human-opened, R6 workflow) ----------
        case = cases_service.open_case(
            db,
            org_id=ORG_ID,
            actor=reviewer,
            title="Duplicate invoice number INV-BT-2001 with altered total",
            severity=CaseSeverity.HIGH.value,
            invoice_id=inv_bt1_dup.id,
            triggering_assessment_id=assessments[inv_bt1_dup.id].id,
            description=(
                "Demo scenario: a second invoice arrived with the same vendor and "
                "number as INV-BT-2001 but a higher total, remitting to an account "
                "that matches no approved account on file. Confirm with the vendor "
                "via a known contact which invoice is valid before any payment "
                "decision is made outside VeriPay (synthetic demo data)."
            ),
        )
        cases_service.add_review_action(
            db, org_id=ORG_ID, case_id=case.id, actor=reviewer,
            action_type=ReviewActionType.COMMENT.value,
            body="Opened from the demo seed: check the duplicate evidence match, the "
                 "amount difference vs PO-2026-2001, and verify the printed pay-to "
                 "account independently before dispositioning.",
            payload={"invoice_id": str(inv_bt1_dup.id)},
        )

        print()
        print(f"Seeded demo data into: {engine.url.render_as_string(hide_password=True)}")
        print("Login (all demo users, fictional people):")
        print("  admin@demo.example / finance@demo.example / reviewer@demo.example /")
        print("  auditor@demo.example — password: VeriPay-Demo-2026!")
        print(f"Investigation case: {case.case_number} ({case.title})")
        print("All data is synthetic; account numbers use XX00DEMO... patterns and are not valid IBANs.")


if __name__ == "__main__":
    seed()
