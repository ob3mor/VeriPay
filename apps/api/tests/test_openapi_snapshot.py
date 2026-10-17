"""OpenAPI snapshot drift test (docs/API.md Â§1): the committed
apps/api/openapi.json snapshot must match the live FastAPI schema, so
frontend type generation and static builds never need a running backend."""

import json
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def test_openapi_snapshot_matches_live_schema(client):
    live = client.app.openapi()

    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(
            json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot == live
