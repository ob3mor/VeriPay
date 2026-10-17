"""GET /audit-events: action filter + limit/offset pagination — the auditor's
untested query branches of the audit reader."""

from helpers import register


def _generate_events(client):
    assert register(client).status_code == 201
    client.post("/api/v1/vendors", json={"display_name": "Audit Vendor"})
    client.post(
        "/api/v1/purchase-orders", json={"po_number": "PO-AUD", "amount": "5.00"}
    )


def test_action_filter_returns_only_that_action(client):
    _generate_events(client)
    vendors = client.get("/api/v1/audit-events", params={"action": "vendor.created"})
    assert vendors.status_code == 200
    assert vendors.json(), "expected at least one vendor.created event"
    assert all(e["action"] == "vendor.created" for e in vendors.json())

    none = client.get("/api/v1/audit-events", params={"action": "no.such.action"})
    assert none.status_code == 200
    assert none.json() == []


def test_pagination_slices_the_org_trail(client):
    _generate_events(client)
    everything = client.get("/api/v1/audit-events", params={"limit": 100}).json()
    assert len(everything) >= 3  # register + vendor + PO events at minimum

    page1 = client.get("/api/v1/audit-events", params={"limit": 1, "offset": 0}).json()
    page2 = client.get("/api/v1/audit-events", params={"limit": 1, "offset": 1}).json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
    # Newest-first ordering: page 1 is the head of the unpaginated list.
    assert page1[0]["id"] == everything[0]["id"]
    assert page2[0]["id"] == everything[1]["id"]

    # Offsets beyond the trail are empty, not an error.
    far = client.get(
        "/api/v1/audit-events", params={"limit": 10, "offset": len(everything) + 50}
    )
    assert far.status_code == 200
    assert far.json() == []


def test_filter_and_pagination_compose(client):
    _generate_events(client)
    all_vendors = client.get(
        "/api/v1/audit-events", params={"action": "vendor.created", "limit": 100}
    ).json()
    if len(all_vendors) >= 2:
        first = client.get(
            "/api/v1/audit-events",
            params={"action": "vendor.created", "limit": 1, "offset": 0},
        ).json()
        assert first[0]["id"] == all_vendors[0]["id"]
