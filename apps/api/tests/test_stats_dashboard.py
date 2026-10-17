"""GET /stats/dashboard — org-scoped aggregates (the auditor's missing
stats endpoint). Counts are work-queue sizes, never verdicts (R2)."""

import time
import uuid

from helpers import db_query, register
from role_helpers import add_user, login_as, register_second_org


def _seed_org_a(client):
    """One org with: 2 invoices (1 needs_review via a high assessment),
    1 open case, 1 failed job."""
    assert register(client).status_code == 201
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]

    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": "PO-STATS", "amount": "1000.00", "currency": "EUR"},
    ).json()
    # Invoice #1: total differs from the PO → amount_mismatch (high) → the
    # assessment forces needs_review.
    reviewed = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-HIGH",
            "purchase_order_id": po["id"],
            "total_amount": "2500.00",
            "currency": "EUR",
        },
    ).json()
    assessment = client.post(f"/api/v1/invoices/{reviewed['id']}/assess").json()
    assert assessment["risk_level"] == "high"

    # Invoice #2: plain received, never assessed.
    plain = client.post("/api/v1/invoices", json={"invoice_number": "INV-PLAIN"}).json()

    # One open case on invoice #2.
    case = client.post(
        "/api/v1/cases",
        json={
            "title": "Check this",
            "severity": "medium",
            "invoice_id": plain["id"],
        },
    )
    assert case.status_code == 201, case.text

    # One failed processing job.
    def _seed_failed_job(session):
        from app.models import Organization, ProcessingJob

        org = session.get(Organization, uuid.UUID(org_id))
        job = ProcessingJob(
            organization_id=org.id,
            job_type="ocr_extraction",
            idempotency_key="stats-failed-job",
            status="failed",
            last_error="synthetic failure",
        )
        session.add(job)
        session.commit()

    db_query(_seed_failed_job)
    return org_id


def test_dashboard_counts_match_seeded_state(client):
    _org_id = _seed_org_a(client)
    stats = client.get("/api/v1/stats/dashboard")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_invoices"] == 2
    assert body["needs_review_invoices"] == 1
    assert body["open_cases"] == 1
    assert body["high_risk_invoices"] == 1
    assert body["processing_failures"] == 1


def test_dashboard_is_org_scoped(client):
    _org_id = _seed_org_a(client)
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    stats = client.get("/api/v1/stats/dashboard").json()
    assert stats["total_invoices"] == 0
    assert stats["needs_review_invoices"] == 0
    assert stats["open_cases"] == 0
    assert stats["high_risk_invoices"] == 0
    assert stats["processing_failures"] == 0


def test_dashboard_counts_latest_assessment_per_invoice(client):
    """Assessment history is append-only: the dashboard counts each invoice's
    LATEST assessment. The real lowering path is R5 itself — a human verifies
    the remittance account, a re-assessment finds it approved, and the high
    signal is gone (nothing was downgraded; the rules simply no longer fire)."""
    assert register(client).status_code == 201
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    vendor = client.post("/api/v1/vendors", json={"display_name": "V"}).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={"account_holder_name": "V", "account_number": "DE89370400440532013000"},
    ).json()
    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": "PO-1", "amount": "10.00", "currency": "EUR"},
    ).json()
    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_number": "INV-1",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "total_amount": "10.00",
            "currency": "EUR",
            "remittance_account_raw": "DE89370400440532013000",
        },
    ).json()

    first = client.post(f"/api/v1/invoices/{invoice['id']}/assess").json()
    assert first["risk_level"] == "high"  # remittance matches a PENDING account
    assert client.get("/api/v1/stats/dashboard").json()["high_risk_invoices"] == 1

    # Human verification (R5) — reviewer approves the matching account.
    add_user(org_id, "rev@acme.example", "reviewer")
    client.cookies.clear()
    assert login_as(client, "rev@acme.example").status_code == 200
    approved = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "Confirmed with known contact.",
        },
    )
    assert approved.status_code == 200

    # SQLite stamps created_at with second resolution; sleep so the re-run's
    # assessment is unambiguously the latest (the append-only "latest row per
    # invoice" rule, docs/DATABASE.md §13).
    time.sleep(1.1)

    # Re-assessment (reviewer is a contributor): the newest assessment is low.
    second = client.post(f"/api/v1/invoices/{invoice['id']}/assess").json()
    assert second["risk_level"] in ("none", "low")
    stats = client.get("/api/v1/stats/dashboard").json()
    assert stats["high_risk_invoices"] == 0
    # The older forcing is NOT undone by a disposition-style trick: the
    # invoice stays needs_review until the human workflow closes it.
    assert client.get(f"/api/v1/invoices/{invoice['id']}").json()["status"] == "needs_review"


def test_dashboard_readable_by_every_role(client):
    org_id = _seed_org_a(client)
    # auditor (read-only role) can view the dashboard.
    add_user(org_id, "aud@acme.example", "auditor")
    client.cookies.clear()
    assert login_as(client, "aud@acme.example").status_code == 200
    assert client.get("/api/v1/stats/dashboard").status_code == 200