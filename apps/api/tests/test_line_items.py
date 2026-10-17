"""Invoice line items: create/list, positions, decimal parsing, isolation —
the auditor's model-without-endpoints gap (InvoiceLineItem)."""

from helpers import register
from role_helpers import register_second_org


def _invoice(client):
    assert register(client).status_code == 201
    invoice = client.post("/api/v1/invoices", json={"invoice_number": "INV-LI"})
    assert invoice.status_code == 201, invoice.text
    return invoice.json()["id"]


def test_line_items_create_and_list_in_position_order(client):
    invoice_id = _invoice(client)
    first = client.post(
        f"/api/v1/invoices/{invoice_id}/line-items",
        json={"description": "Widget", "quantity": "2", "unit_price": "19.99",
              "line_total": "39.98"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["position"] == 1
    assert first.json()["quantity"] == "2"  # Decimal → string, never float

    second = client.post(
        f"/api/v1/invoices/{invoice_id}/line-items",
        json={"description": "Gadget", "quantity": "1"},
    )
    assert second.status_code == 201
    assert second.json()["position"] == 2

    rows = client.get(f"/api/v1/invoices/{invoice_id}/line-items").json()
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[0]["description"] == "Widget"


def test_line_item_invalid_decimal_is_422(client):
    invoice_id = _invoice(client)
    response = client.post(
        f"/api/v1/invoices/{invoice_id}/line-items",
        json={"description": "Bad", "quantity": "not-a-number"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_line_items_require_contributor_role(client):
    invoice_id = _invoice(client)
    from helpers import db_query
    from role_helpers import add_user

    org_id = client.get("/api/v1/auth/me").json()["user"]["organization_id"]
    add_user(org_id, "aud@acme.example", "auditor")
    client.cookies.clear()
    from role_helpers import login_as

    login_as(client, "aud@acme.example")
    forbidden = client.post(
        f"/api/v1/invoices/{invoice_id}/line-items", json={"description": "x"}
    )
    assert forbidden.status_code == 403
    # Reads stay open to every member (read-only role included).
    assert client.get(f"/api/v1/invoices/{invoice_id}/line-items").status_code == 200


def test_line_items_are_tenant_scoped(client):
    invoice_id = _invoice(client)
    client.cookies.clear()
    assert register_second_org(client).status_code == 201
    assert (
        client.post(
            f"/api/v1/invoices/{invoice_id}/line-items", json={"description": "x"}
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/invoices/{invoice_id}/line-items").status_code == 404
    )
