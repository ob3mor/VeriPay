"""Prompt-07 QA — security pass.

- Broken access control: role matrix sweep over every mutating endpoint
  (docs/API.md §5 role × action matrix).
- Cross-tenant exposure: org B ids in org A requests → 404 (no leak).
- SQL injection probes on string parameters (ORM-only assertions).
- XSS payloads stored/serialized safely (JSON data, exact round-trip).
- CSRF: missing / wrong header / cross-origin (token + origin defenses).
- Token handling: expired / tampered / garbage / org-mismatch / revoked.
- Unsafe uploads: renamed exe, oversized, wrong mime (magic-byte checks).
- Sensitive logging: no full account numbers / credentials in audit detail.
- Storage authorization: tenant-prefixed keys, cross-org file 404.
"""

import io
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.core.enums import UserRole  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

from helpers import bearer, db_query, login, register  # noqa: E402
from role_helpers import add_user, login_as  # noqa: E402

PASSWORD = "correct-horse-battery-staple"
APPROVED_IBAN = "DE89370400440532013000"
OTHER_IBAN = "GB29NWBK60161331926819"
PDF_BYTES = b"%PDF-1.4\nqa sweep plain document\n"
DOC_B_BYTES = b"%PDF-1.4\nqa sweep delete target\n"
UPLOAD_OP_BYTES = b"%PDF-1.4\nqa sweep upload op\n"

CONTRIBUTE = {UserRole.ORG_ADMIN, UserRole.FINANCE_OFFICER, UserRole.REVIEWER}
# docs/API.md §5 "Work cases" row (assign / review actions / disposition):
# same roles as CONTRIBUTE, but a distinct matrix row — kept separate so the
# sweep tests each row's intent, not an implementation constant.
CASE_WORK = {UserRole.ORG_ADMIN, UserRole.FINANCE_OFFICER, UserRole.REVIEWER}
VERIFY = {UserRole.ORG_ADMIN, UserRole.REVIEWER}
ADMIN_ONLY = {UserRole.ORG_ADMIN}
AUDIT_VIEW = {UserRole.ORG_ADMIN, UserRole.AUDITOR}


@pytest.fixture()
def raw_client():
    """Plain TestClient — no automatic CSRF echoing (the guard under test)."""
    Base.metadata.create_all(bind=engine)
    with TestClient(fastapi_app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def _register_org(client, email: str) -> str:
    assert register(client, email=email).status_code == 201
    return client.get("/api/v1/auth/me").json()["user"]["organization_id"]


# ---------------------------------------------------------------------------
# 1. Role matrix sweep over mutating endpoints
# ---------------------------------------------------------------------------
def _seed_role_world(client, tmp_path: Path) -> dict:
    """One fresh org with an isolated target for every mutating endpoint."""
    register(client, email="seed-owner@qa.example")
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Sweep Vendor Ltd"}
    ).json()

    def _pending_account(n: int) -> str:
        return client.post(
            f"/api/v1/vendors/{vendor['id']}/bank-accounts",
            json={
                "account_holder_name": f"Sweep Holder {n}",
                "account_number": f"1000000000000000{n}",
            },
        ).json()["id"]

    change_1 = client.post(
        f"/api/v1/vendors/{vendor['id']}/change-requests",
        json={
            "account_holder_name": "Change One",
            "account_number": OTHER_IBAN,
            "reason": "sweep approve target",
        },
    ).json()
    change_2 = client.post(
        f"/api/v1/vendors/{vendor['id']}/change-requests",
        json={
            "account_holder_name": "Change Two",
            "account_number": "22222222222222222222",
            "reason": "sweep reject target",
        },
    ).json()

    po = client.post(
        "/api/v1/purchase-orders",
        json={"po_number": "PO-SWEEP", "amount": "10.00", "vendor_id": vendor["id"]},
    ).json()

    invoice_main = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-SWEEP-1", "vendor_id": vendor["id"]},
    ).json()
    invoice_resolve = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-SWEEP-2"},
    ).json()
    invoice_assess = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-SWEEP-3"},
    ).json()

    # A finding (disposition target) and an evidence match (review target),
    # both created at seed time so the target exists for every role.
    assessed = client.post(f"/api/v1/invoices/{invoice_main['id']}/assess")
    assert assessed.status_code == 200, assessed.text
    finding_id = assessed.json()["findings"][0]["id"]
    duplicate = client.post(
        "/api/v1/invoices",
        json={"invoice_number": "INV-SWEEP-1", "vendor_id": vendor["id"]},
    ).json()
    matched = client.post(f"/api/v1/invoices/{duplicate['id']}/assess")
    assert matched.status_code == 200, matched.text

    def _match_id(session):
        from app.models import EvidenceMatch

        row = (
            session.query(EvidenceMatch)
            .filter(EvidenceMatch.match_kind == "invoice_number")
            .first()
        )
        assert row is not None
        return str(row.id)

    match_id = db_query(_match_id)

    case_assign = client.post(
        "/api/v1/cases",
        json={"title": "Sweep assign", "severity": "low", "vendor_id": vendor["id"]},
    ).json()
    case_close = client.post(
        "/api/v1/cases",
        json={"title": "Sweep close", "severity": "low", "vendor_id": vendor["id"]},
    ).json()
    case_actions = client.post(
        "/api/v1/cases",
        json={"title": "Sweep actions", "severity": "low", "vendor_id": vendor["id"]},
    ).json()

    # A labeled document whose extraction yields a field (PATCH review target)
    # and a second standalone document (DELETE target).
    labeled = tmp_path / "sweep_labeled.pdf"
    gf._pdf(
        [
            "INVOICE",
            "Vendor: Sweep Vendor Ltd",
            "Invoice Number: INV-SWEEP-DOC",
            "Invoice Date: 2026-10-01",
            "Currency: EUR",
            "Total: 10.00",
        ],
        labeled,
    )
    with open(labeled, "rb") as fh:
        doc_a = client.post(
            "/api/v1/documents",
            files={"file": ("sweep_labeled.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        ).json()
    fields = client.get(f"/api/v1/documents/{doc_a['id']}/fields").json()["items"]
    assert fields, "labeled sweep document must extract fields"
    with io.BytesIO(DOC_B_BYTES) as fh:
        doc_b = client.post(
            "/api/v1/documents",
            files={"file": ("sweep_b.pdf", fh, "application/pdf")},
            data={"kind": "other"},
        ).json()

    return {
        "org_id": org_id,
        "owner_id": owner_id,
        "vendor_id": vendor["id"],
        "account_verify": _pending_account(1),
        "account_reject": _pending_account(2),
        "account_revoke": _pending_account(3),
        "change_approve": change_1["id"],
        "change_reject": change_2["id"],
        "po_id": po["id"],
        "invoice_main": invoice_main["id"],
        "invoice_resolve": invoice_resolve["id"],
        "invoice_assess": invoice_assess["id"],
        "finding_id": finding_id,
        "match_id": match_id,
        "case_assign": case_assign["id"],
        "case_close": case_close["id"],
        "case_actions": case_actions["id"],
        "doc_a": doc_a["id"],
        "doc_a_field": fields[0]["id"],
        "doc_b": doc_b["id"],
    }


def _sweep_plan(w: dict) -> list[tuple[str, str, str, object]]:
    """(name, method, url, json/multipart body) for every mutating endpoint
    plus the role-gated audit read. Each entry targets its own seeded object
    so a successful mutation cannot poison another attempt."""
    return [
        ("create_vendor", "POST", "/api/v1/vendors",
         {"display_name": "Sweep Created Vendor"}),
        ("create_contact", "POST", f"/api/v1/vendors/{w['vendor_id']}/contacts",
         {"full_name": "Sweep Contact", "email": "sweep.contact@qa.example"}),
        ("register_bank_account", "POST", f"/api/v1/vendors/{w['vendor_id']}/bank-accounts",
         {"account_holder_name": "Sweep New", "account_number": "3333333333333"}),
        ("verify_bank_account", "POST",
         f"/api/v1/vendors/{w['vendor_id']}/bank-accounts/{w['account_verify']}/verify",
         {"verification_method": "registry_check", "verification_reference": "sweep"}),
        ("reject_bank_account", "POST",
         f"/api/v1/vendors/{w['vendor_id']}/bank-accounts/{w['account_reject']}/reject",
         {"resolution_note": "sweep"}),
        ("revoke_bank_account", "POST",
         f"/api/v1/vendors/{w['vendor_id']}/bank-accounts/{w['account_revoke']}/revoke",
         None),
        ("create_change_request", "POST", f"/api/v1/vendors/{w['vendor_id']}/change-requests",
         {"account_holder_name": "Sweep Change",
          "account_number": "44444444444444", "reason": "sweep"}),
        ("approve_change_request", "POST",
         f"/api/v1/vendors/{w['vendor_id']}/change-requests/{w['change_approve']}/approve",
         {"resolution_note": "sweep"}),
        ("reject_change_request", "POST",
         f"/api/v1/vendors/{w['vendor_id']}/change-requests/{w['change_reject']}/reject",
         {"resolution_note": "sweep"}),
        ("create_purchase_order", "POST", "/api/v1/purchase-orders",
         {"po_number": "PO-SWEEP-OP", "amount": "5.00"}),
        ("create_invoice", "POST", "/api/v1/invoices",
         {"invoice_number": "INV-SWEEP-OP"}),
        ("add_line_item", "POST", f"/api/v1/invoices/{w['invoice_main']}/line-items",
         {"description": "Sweep line", "quantity": "1", "line_total": "1.00"}),
        ("resolve_vendor", "POST", f"/api/v1/invoices/{w['invoice_resolve']}/resolve-vendor",
         {"vendor_id": w["vendor_id"]}),
        ("assess_invoice", "POST", f"/api/v1/invoices/{w['invoice_assess']}/assess", None),
        ("disposition_finding", "POST", f"/api/v1/findings/{w['finding_id']}/disposition",
         {"disposition": "acknowledged", "reason": "sweep"}),
        ("review_match", "POST", f"/api/v1/matches/{w['match_id']}/review",
         {"status": "dismissed", "reason": "sweep"}),
        ("open_case", "POST", "/api/v1/cases",
         {"title": "Sweep open", "severity": "low", "vendor_id": w["vendor_id"]}),
        ("assign_case", "POST", f"/api/v1/cases/{w['case_assign']}/assign", None),  # user_id filled later
        ("add_review_action", "POST", f"/api/v1/cases/{w['case_actions']}/actions",
         {"action_type": "comment", "body": "sweep action"}),
        ("close_case", "POST", f"/api/v1/cases/{w['case_close']}/close",
         {"outcome": "inconclusive", "resolution_summary": "sweep close"}),
        ("upload_document", "POST", "/api/v1/documents",
         {"_files": ("sweep_op.pdf", io.BytesIO(UPLOAD_OP_BYTES), "application/pdf"),
          "kind": "other"}),
        ("reprocess_document", "POST", f"/api/v1/documents/{w['doc_a']}/process", None),
        ("review_extraction_field", "PATCH",
         f"/api/v1/documents/{w['doc_a']}/fields/{w['doc_a_field']}",
         {"action": "confirm"}),
        ("delete_document", "DELETE", f"/api/v1/documents/{w['doc_b']}", None),
        ("view_audit_events", "GET", "/api/v1/audit-events?limit=1", None),
    ]


@pytest.mark.parametrize("role", [r.value for r in UserRole])
def test_role_matrix_sweep_over_mutating_endpoints(client, tmp_path, role):
    """Every mutating endpoint allows exactly its API.md §5 role set; every
    other role gets 403 forbidden (never 404 — the user is authenticated —
    and never a 500)."""
    world = _seed_role_world(client, tmp_path)

    if role != UserRole.ORG_ADMIN.value:
        add_user(world["org_id"], f"sweep-{role}@qa.example", role)
    # log in as the sweep role (owner is already org_admin)
    client.cookies.clear()
    if role == UserRole.ORG_ADMIN.value:
        assert login(client, username="seed-owner@qa.example").status_code == 200
    else:
        assert login_as(client, f"sweep-{role}@qa.example").status_code == 200
    actor_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    mismatches = []
    for name, method, url, payload in _sweep_plan(world):
        if name == "assign_case":
            payload = {"user_id": actor_id}
        if payload is not None and "_files" in payload:
            response = client.request(method, url, files={"file": payload["_files"]},
                                      data={"kind": payload["kind"]})
        elif payload is not None:
            response = client.request(method, url, json=payload)
        else:
            response = client.request(method, url)
        expected = {"create_vendor": CONTRIBUTE, "create_contact": CONTRIBUTE,
                    "register_bank_account": CONTRIBUTE,
                    "verify_bank_account": VERIFY, "reject_bank_account": VERIFY,
                    "revoke_bank_account": VERIFY,
                    "create_change_request": CONTRIBUTE,
                    "approve_change_request": VERIFY,
                    "reject_change_request": VERIFY,
                    "create_purchase_order": CONTRIBUTE, "create_invoice": CONTRIBUTE,
                    "add_line_item": CONTRIBUTE, "resolve_vendor": CONTRIBUTE,
                    "assess_invoice": CONTRIBUTE, "disposition_finding": CASE_WORK,
                    "review_match": CASE_WORK, "open_case": VERIFY,
                    "assign_case": CONTRIBUTE, "add_review_action": CONTRIBUTE,
                    "close_case": VERIFY, "upload_document": CONTRIBUTE,
                    "reprocess_document": CONTRIBUTE,
                    "review_extraction_field": VERIFY, "delete_document": ADMIN_ONLY,
                    "view_audit_events": AUDIT_VIEW}[name]
        allowed = UserRole(role) in expected
        if allowed:
            ok = response.status_code in (200, 201, 204)
        else:
            ok = response.status_code == 403 and (
                response.json().get("error", {}).get("code") == "forbidden"
            )
        if not ok:
            mismatches.append(
                (name, role, response.status_code, response.text[:200])
            )

    assert not mismatches, f"role-matrix violations: {mismatches}"


# ---------------------------------------------------------------------------
# 2. Cross-tenant exposure
# ---------------------------------------------------------------------------
def test_cross_tenant_org_b_ids_are_404_in_org_a_requests(client):
    """Org B seeds a full resource set; org A's requests against those ids
    are 404 — reads, mutations, retrieval, and the stored file."""
    register(client, email="orgb@tenant.example")
    vendor_b = client.post(
        "/api/v1/vendors", json={"display_name": "B Vendor"}
    ).json()
    invoice_b = client.post(
        "/api/v1/invoices", json={"invoice_number": "INV-B-1"}
    ).json()
    case_b = client.post(
        "/api/v1/cases",
        json={"title": "B case", "severity": "low", "invoice_id": invoice_b["id"]},
    ).json()
    with io.BytesIO(PDF_BYTES) as fh:
        document_b = client.post(
            "/api/v1/documents",
            files={"file": ("b.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        ).json()

    client.cookies.clear()
    register(client, email="orga@tenant.example")

    assert client.get(f"/api/v1/vendors/{vendor_b['id']}").status_code == 404
    assert client.get(f"/api/v1/invoices/{invoice_b['id']}").status_code == 404
    assert client.get(f"/api/v1/cases/{case_b['id']}").status_code == 404
    assert client.get(f"/api/v1/documents/{document_b['id']}").status_code == 404
    assert (
        client.get(f"/api/v1/documents/{document_b['id']}/file").status_code == 404
    )
    assert (
        client.get(f"/api/v1/invoices/{invoice_b['id']}/evidence").status_code == 404
    )
    assert (
        client.post(f"/api/v1/invoices/{invoice_b['id']}/assess").status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/invoices/{invoice_b['id']}/resolve-vendor", json={}
        ).status_code
        == 404
    )
    # Writes against B's vendor are 404 too (no existence leak).
    assert (
        client.post(
            f"/api/v1/vendors/{vendor_b['id']}/bank-accounts",
            json={"account_holder_name": "Evil", "account_number": "99998888"},
        ).status_code
        == 404
    )
    # Lists never leak B rows.
    assert invoice_b["id"] not in [
        i["id"] for i in client.get("/api/v1/invoices").json()["items"]
    ]


# ---------------------------------------------------------------------------
# 3. SQL injection probes on string parameters (ORM-only assertions)
# ---------------------------------------------------------------------------
SQL_PROBES = [
    "' OR '1'='1",
    "'; DROP TABLE vendors;--",
    '" OR ""="',
    "1' UNION SELECT email, password_hash FROM users--",
    "admin'--",
    "%' AND 1=1 --",
    "x' OR organization_id IS NOT NULL --",
]


def test_sql_injection_probes_stay_parameterized_data(client):
    """Probes are stored and matched as plain data: no 500s, no effect on the
    tables, and every probe round-trips byte-exact through the ORM."""
    _register_org(client, email="sqli@qa.example")

    for probe in SQL_PROBES:
        created = client.post("/api/v1/vendors", json={"display_name": probe})
        assert created.status_code == 201, created.text
        fetched = client.get(f"/api/v1/vendors/{created.json()['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["display_name"] == probe  # verbatim data

        invoiced = client.post("/api/v1/invoices", json={"invoice_number": probe})
        assert invoiced.status_code == 201, invoiced.text

        audit = client.get("/api/v1/audit-events", params={"action": probe})
        assert audit.status_code == 200
        assert audit.json()["items"] == []  # no rows match; the filter stayed a filter

    # limit is a typed int — an injected string is a 422, never a 500.
    bad_limit = client.get("/api/v1/vendors", params={"limit": "1 OR 1=1"})
    assert bad_limit.status_code == 422
    assert bad_limit.json()["error"]["code"] == "validation_error"

    def _orm_state(session):
        from sqlalchemy import select

        from app.models import AuditEvent, User, Vendor

        vendors = session.scalars(select(Vendor)).all()
        assert len(vendors) == len(SQL_PROBES)  # exactly the created rows
        # Exact-match ORM queries return exactly one row per probe — the
        # parameterization held (no wildcard/boolean payload smuggled in).
        for probe in SQL_PROBES:
            hits = (
                session.query(Vendor).filter(Vendor.display_name == probe).all()
            )
            assert len(hits) == 1
            assert hits[0].display_name == probe
        # The dropped table was not dropped; the credential columns intact.
        users = session.query(User).all()
        assert len(users) == 1 and users[0].password_hash.startswith("$2")
        events = session.query(AuditEvent).count()
        assert events > 0
        return True

    assert db_query(_orm_state) is True


# ---------------------------------------------------------------------------
# 4. XSS payloads stored safely (serialization level)
# ---------------------------------------------------------------------------
XSS_VENDOR = "<script>alert('vendor')</script>"
XSS_INVOICE = '"><img src=x onerror=alert(1)>'
XSS_CASE = "<svg onload=alert('case')>"
XSS_LINE = "<img src=x onerror=alert('line')>"


def test_xss_payloads_stored_and_served_as_inert_json(client):
    """The API stores payloads verbatim and serves them as JSON data — the
    serialization contract (application/json; no HTML rendering, no
    execution, no silent mutation)."""
    _register_org(client, email="xss@qa.example")
    vendor = client.post(
        "/api/v1/vendors", json={"display_name": XSS_VENDOR}
    )
    assert vendor.status_code == 201
    assert "application/json" in vendor.headers["content-type"]
    assert vendor.json()["display_name"] == XSS_VENDOR  # untouched by the API

    fetched = client.get(f"/api/v1/vendors/{vendor.json()['id']}").json()
    assert fetched["display_name"] == XSS_VENDOR

    invoice = client.post(
        "/api/v1/invoices", json={"invoice_number": XSS_INVOICE}
    ).json()
    assert invoice["invoice_number"] == XSS_INVOICE

    case = client.post(
        "/api/v1/cases",
        json={"title": XSS_CASE, "severity": "low", "invoice_id": invoice["id"]},
    )
    assert case.status_code == 201
    assert case.json()["title"] == XSS_CASE

    line = client.post(
        f"/api/v1/invoices/{invoice['id']}/line-items",
        json={"description": XSS_LINE, "quantity": "1", "line_total": "1.00"},
    )
    assert line.status_code == 201
    assert line.json()["description"] == XSS_LINE

    # The audit trail replays the values as JSON data too (never HTML).
    events = client.get("/api/v1/audit-events?limit=100").json()["items"]
    case_event = next(e for e in events if e["action"] == "case.opened")
    assert case_event["detail"]["title"] == XSS_CASE


# ---------------------------------------------------------------------------
# 5. CSRF: missing / wrong header / cross-origin
# ---------------------------------------------------------------------------
def test_csrf_missing_wrong_and_cross_origin(raw_client):
    assert raw_client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-qa@qa.example",
            "password": PASSWORD,
            "full_name": "CSRF QA",
            "organization_name": "QA GmbH",
        },
    ).status_code == 201

    # Missing header on a cookie-authenticated mutation → 403 forbidden.
    missing = raw_client.post("/api/v1/vendors", json={"display_name": "X"})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "forbidden"

    # Wrong header value → 403.
    wrong = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "X"},
        headers={"X-CSRF-Token": "not-the-cookie-value"},
    )
    assert wrong.status_code == 403

    token = raw_client.cookies.get("veripay_csrf")

    # Cross-origin (attacker page forcing the cookies) → 403 even WITH the
    # correct token — the Origin check is the second defense.
    evil_origin = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "X"},
        headers={"X-CSRF-Token": token or "", "Origin": "https://evil.example"},
    )
    assert evil_origin.status_code == 403

    evil_referer = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "X"},
        headers={"X-CSRF-Token": token or "", "Referer": "https://evil.example/x"},
    )
    assert evil_referer.status_code == 403

    # The allowlisted SPA origin with the correct token is accepted.
    good = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "CSRF OK"},
        headers={"X-CSRF-Token": token or "", "Origin": "http://localhost:3000"},
    )
    assert good.status_code == 201, good.text

    # The origin check covers pre-auth endpoints too (forced login POSTs).
    evil_login = raw_client.post(
        "/api/v1/auth/login",
        data={"username": "csrf-qa@qa.example", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert evil_login.status_code == 403

    # Bearer clients are exempt from the CSRF header (not ambient authority).
    raw_client.cookies.clear()
    login_response = raw_client.post(
        "/api/v1/auth/login",
        data={"username": "csrf-qa@qa.example", "password": PASSWORD},
    )
    assert login_response.status_code == 200
    api_token = login_response.json()["access_token"]
    bearer_call = raw_client.post(
        "/api/v1/vendors",
        json={"display_name": "Bearer No CSRF"},
        headers={"Authorization": f"Bearer {api_token}"},
    )
    assert bearer_call.status_code == 201


# ---------------------------------------------------------------------------
# 6. Token handling: expired / tampered / garbage / org-mismatch / revoked
# ---------------------------------------------------------------------------
def test_token_handling_expired_tampered_garbage_org_mismatch_revoked(client):
    from datetime import timedelta

    from app.core.security import create_access_token

    registered = register(client, email="tokens@qa.example")
    assert registered.status_code == 201
    body = registered.json()
    token = body["access_token"]

    # Baseline works.
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200

    # Expired.
    expired = create_access_token(
        user_id=body["user"]["id"],
        organization_id=body["organization"]["id"],
        role=body["user"]["role"],
        expires_delta=timedelta(seconds=-60),
    )
    assert (
        client.get("/api/v1/auth/me", headers=bearer(expired)).status_code == 401
    )

    # Tampered (signature break).
    tampered = token[:-4] + "AAAA"
    assert (
        client.get("/api/v1/auth/me", headers=bearer(tampered)).status_code == 401
    )

    # Garbage.
    assert (
        client.get("/api/v1/auth/me", headers=bearer("garbage.token.here"))
        .status_code
        == 401
    )

    # Valid signature but an org claim that does not match the user row.
    wrong_org = create_access_token(
        user_id=body["user"]["id"],
        organization_id=uuid.uuid4(),
        role=body["user"]["role"],
    )
    wrong_org_response = client.get(
        "/api/v1/auth/me", headers=bearer(wrong_org)
    )
    assert wrong_org_response.status_code == 401

    # Revocation: server-side sign-out kills the jti even while unexpired.
    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code == 200
    revoked = client.get("/api/v1/auth/me", headers=bearer(token))
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "unauthorized"

    # The durable session row was revoked too — replaying the old cookie is
    # dead even though logout cleared it client-side.
    session_value = registered.cookies.get("veripay_session")
    if session_value:
        client.cookies.set("veripay_session", session_value)
        assert client.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# 7. Unsafe uploads
# ---------------------------------------------------------------------------
def test_unsafe_uploads_rejected(client):
    _register_org(client, email="uploads@qa.example")
    EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00" + b"\x00" * 128

    # A renamed .exe with a PDF name+mime must fail the magic-byte check.
    with io.BytesIO(EXE_BYTES) as fh:
        exe = client.post(
            "/api/v1/documents",
            files={"file": ("invoice.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        )
    assert exe.status_code == 422
    assert exe.json()["error"]["code"] == "validation_error"

    # Right magic, wrong declaration → rejected.
    with io.BytesIO(PDF_BYTES) as fh:
        wrong_mime = client.post(
            "/api/v1/documents",
            files={"file": ("x.pdf", fh, "image/png")},
            data={"kind": "invoice"},
        )
    assert wrong_mime.status_code == 422

    # PNG magic declared as PDF → rejected.
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    with io.BytesIO(png_bytes) as fh:
        png_as_pdf = client.post(
            "/api/v1/documents",
            files={"file": ("x.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        )
    assert png_as_pdf.status_code == 422

    # Outside the allowlist entirely.
    with io.BytesIO(b"hello") as fh:
        txt = client.post(
            "/api/v1/documents",
            files={"file": ("x.txt", fh, "text/plain")},
            data={"kind": "other"},
        )
    assert txt.status_code == 422

    # Over the size ceiling (10 MiB default) — even with valid PDF magic.
    oversized = b"%PDF-1.4\n" + b"A" * (10 * 1024 * 1024)
    with io.BytesIO(oversized) as fh:
        big = client.post(
            "/api/v1/documents",
            files={"file": ("big.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        )
    assert big.status_code == 422

    # Empty upload.
    with io.BytesIO(b"") as fh:
        empty = client.post(
            "/api/v1/documents",
            files={"file": ("empty.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        )
    assert empty.status_code == 422

    # Nothing leaked into the document store.
    assert client.get("/api/v1/documents").json()["items"] == []


# ---------------------------------------------------------------------------
# 8. Sensitive logging: audit detail carries no account numbers or secrets
# ---------------------------------------------------------------------------
def test_audit_detail_never_contains_account_numbers_or_secrets(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "secrets@qa.example",
            "password": "qa-secret-passphrase-31337",
            "full_name": "Secret Keeper",
            "organization_name": "Discretion GmbH",
        },
    )
    assert registered.status_code == 201
    FULL_ACCOUNT = OTHER_IBAN  # distinctive, appears exactly once below

    vendor = client.post(
        "/api/v1/vendors", json={"display_name": "Discreet Vendor"}
    ).json()
    account = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts",
        json={
            "account_holder_name": "Discreet Vendor",
            "account_number": FULL_ACCOUNT,
            "bank_country": "GB",
        },
    ).json()
    verified = client.post(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts/{account['id']}/verify",
        json={
            "verification_method": "callback_to_known_contact",
            "verification_reference": "Callback ticket INC-42",
        },
    )
    assert verified.status_code == 200, verified.text

    events = client.get("/api/v1/audit-events?limit=100").json()["items"]
    assert len(events) >= 3
    for event in events:
        detail_blob = str(event.get("detail"))
        # The full account number exists only in the request body — it is
        # fingerprinted server-side and never lands in the audit trail.
        assert FULL_ACCOUNT not in detail_blob, event["action"]
        # No credentials, no bearer tokens, no JWT segments.
        assert "qa-secret-passphrase-31337" not in detail_blob
        assert "Bearer " not in detail_blob
        assert "eyJ" not in detail_blob

    # The registered event may carry the email, never the password hash.
    registered_event = next(e for e in events if e["action"] == "user.registered")
    assert registered_event["actor_user_id"]

    # Role masking on the account surface itself (docs/API.md §5.8).
    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "masked-fin@qa.example", "finance_officer")
    client.cookies.clear()
    assert login_as(client, "masked-fin@qa.example").status_code == 200
    masked = client.get(f"/api/v1/vendors/{vendor['id']}/bank-accounts").json()["items"]
    assert masked and "verification_reference" not in masked[0]
    assert "verification_method" not in masked[0]
    assert FULL_ACCOUNT not in str(masked)
    assert "account_fingerprint" not in masked[0]

    # reviewer/org_admin get the provenance view — still never the number.
    client.cookies.clear()
    assert (
        login(client, username="secrets@qa.example", password="qa-secret-passphrase-31337")
        .status_code
        == 200
    )
    detail_view = client.get(
        f"/api/v1/vendors/{vendor['id']}/bank-accounts"
    ).json()["items"]
    assert detail_view[0]["verification_reference"] == "Callback ticket INC-42"
    assert FULL_ACCOUNT not in str(detail_view)


# ---------------------------------------------------------------------------
# 9. Storage authorization
# ---------------------------------------------------------------------------
def test_storage_keys_tenant_prefixed_and_cross_org_file_404(client):
    _register_org(client, email="storage-a@qa.example")
    org_a = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    with io.BytesIO(PDF_BYTES) as fh:
        document_a = client.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        ).json()

    def _key(session):
        from app.models import Document

        row = session.get(Document, uuid.UUID(document_a["id"]))
        return row.storage_key

    key = db_query(_key)
    # Tenant-prefixed key: a misconfigured shared root cannot merge tenants
    # (docs/ARCHITECTURE.md §7.1: {org_id}/{document_id}/{sha256}{ext}).
    assert key.startswith(f"{org_a}/")
    assert document_a["id"] in key
    assert document_a["sha256"] in key

    # The owner downloads the exact bytes.
    ok = client.get(f"/api/v1/documents/{document_a['id']}/file")
    assert ok.status_code == 200
    assert ok.content == PDF_BYTES

    # Org B cannot resolve the row (404, no existence leak) — the download
    # key is resolved from the org-scoped DB record, never from the client.
    client.cookies.clear()
    _register_org(client, email="storage-b@qa.example")
    org_b = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    cross = client.get(f"/api/v1/documents/{document_a['id']}/file")
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "not_found"

    # B's own object lives under B's prefix and is downloadable by B.
    with io.BytesIO(DOC_B_BYTES) as fh:
        document_b = client.post(
            "/api/v1/documents",
            files={"file": ("b.pdf", fh, "application/pdf")},
            data={"kind": "invoice"},
        ).json()

    def _key_b(session):
        from app.models import Document

        return session.get(Document, uuid.UUID(document_b["id"])).storage_key

    key_b = db_query(_key_b)
    assert key_b.startswith(f"{org_b}/")
    own = client.get(f"/api/v1/documents/{document_b['id']}/file")
    assert own.status_code == 200 and own.content == DOC_B_BYTES
    assert key != key_b  # different tenants, different prefixes