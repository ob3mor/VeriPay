"""GET /audit-events: action filter + limit/offset pagination — the auditor's
query branches of the audit reader, over the docs/API.md §3 envelope
(``{"items": [...], "pagination": {limit, offset, total}}``)."""

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
    body = vendors.json()
    assert body["items"], "expected at least one vendor.created event"
    assert all(e["action"] == "vendor.created" for e in body["items"])
    # §3 envelope: total counts the SAME filtered set the items came from.
    assert body["pagination"]["total"] == len(body["items"])
    assert body["pagination"]["limit"] == 50 and body["pagination"]["offset"] == 0

    none = client.get("/api/v1/audit-events", params={"action": "no.such.action"})
    assert none.status_code == 200
    assert none.json()["items"] == []
    assert none.json()["pagination"]["total"] == 0


def test_pagination_slices_the_org_trail(client):
    _generate_events(client)
    everything = client.get("/api/v1/audit-events", params={"limit": 100}).json()
    assert len(everything["items"]) >= 3  # register + vendor + PO events at minimum
    assert everything["pagination"]["total"] == len(everything["items"])
    assert everything["pagination"]["limit"] == 100

    page1 = client.get("/api/v1/audit-events", params={"limit": 1, "offset": 0}).json()
    page2 = client.get("/api/v1/audit-events", params={"limit": 1, "offset": 1}).json()
    assert len(page1["items"]) == 1 and len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]
    # Newest-first ordering: page 1 is the head of the unpaginated list.
    assert page1["items"][0]["id"] == everything["items"][0]["id"]
    assert page2["items"][0]["id"] == everything["items"][1]["id"]
    # total is over the whole trail, independent of the page size.
    assert page1["pagination"]["total"] == everything["pagination"]["total"]

    # Offsets beyond the trail are empty, not an error.
    far = client.get(
        "/api/v1/audit-events",
        params={"limit": 10, "offset": everything["pagination"]["total"] + 50},
    )
    assert far.status_code == 200
    assert far.json()["items"] == []


def test_filter_and_pagination_compose(client):
    _generate_events(client)
    all_vendors = client.get(
        "/api/v1/audit-events", params={"action": "vendor.created", "limit": 100}
    ).json()
    if len(all_vendors["items"]) >= 2:
        first = client.get(
            "/api/v1/audit-events",
            params={"action": "vendor.created", "limit": 1, "offset": 0},
        ).json()
        assert first["items"][0]["id"] == all_vendors["items"][0]["id"]
        # The filtered total (not the whole-trail total) rides along.
        assert first["pagination"]["total"] == len(all_vendors["items"])
