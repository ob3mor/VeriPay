"""Token org scoping: each organization's principal sees only its own org
(docs/API.md Â§5 â€” the tenant comes from the token, only)."""

from helpers import bearer, register


def test_two_organizations_each_me_reports_its_own_org(client):
    org_a = register(client, email="a@alpha.example", organization_name="Alpha Analytics LLC")
    org_b = register(client, email="b@beta.example", organization_name="Beta Trading GmbH")

    assert org_a.status_code == 201, org_a.text
    assert org_b.status_code == 201, org_b.text
    body_a, body_b = org_a.json(), org_b.json()
    assert body_a["organization"]["id"] != body_b["organization"]["id"]

    me_a = client.get("/api/v1/auth/me", headers=bearer(body_a["access_token"]))
    me_b = client.get("/api/v1/auth/me", headers=bearer(body_b["access_token"]))

    assert me_a.status_code == 200
    assert me_b.status_code == 200
    assert me_a.json()["organization"]["id"] == body_a["organization"]["id"]
    assert me_a.json()["organization"]["slug"] == "alpha-analytics-llc"
    assert me_b.json()["organization"]["id"] == body_b["organization"]["id"]
    assert me_b.json()["organization"]["slug"] == "beta-trading-gmbh"

    # The JWT claims themselves carry distinct, org-scoped identities.
    from app.core.security import decode_access_token

    claim_a = decode_access_token(body_a["access_token"])
    claim_b = decode_access_token(body_b["access_token"])
    assert claim_a["org_id"] != claim_b["org_id"]
    assert claim_a["sub"] == body_a["user"]["id"]
    assert claim_b["sub"] == body_b["user"]["id"]
