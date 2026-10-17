"""GET /api/v1/health â€” public liveness (docs/API.md Â§4)."""


def test_health_returns_ok_with_version(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "veripay-api"
    assert body["version"]
