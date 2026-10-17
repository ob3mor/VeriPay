"""Extraction evaluation over the SYNTHETIC fixtures (Prompt-02, item 9).

What this measures — read the honesty notes before quoting the numbers:

- The corpus is scripts/generate_fixtures.py output: deterministic,
  machine-generated invoices with a real text layer (plus one blurred PNG
  that no text-layer provider can read). The numbers are therefore
  SYNTHETIC-FIXTURE METRICS for the label extractor + text-layer provider
  pipeline — NOT production accuracy and NOT OCR accuracy (the text layer
  is bit-exact; no pixel OCR runs here).
- Field precision: extracted fields that are WRONG (expected field with a
  mismatched normalized value, or a field listed in the fixture's ``absent``
  ground truth) over all extracted-against-ground-truth comparisons.
- Field recall: expected fields correctly extracted over all expected.
- Processing latency: wall-clock of the full upload→inline-OCR→persisted
  fields round-trip per document, measured over the TestClient (no network).

Ground truth lives beside the content in generate_fixtures.FixtureSpec.
"""

import io
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import generate_fixtures as gf  # noqa: E402

from helpers import register  # noqa: E402

FIXTURES_DIR = gf.FIXTURES_DIR

# A synthetic corpus this clean must stay above these floors; if extraction
# regresses, the printed numbers show exactly how far it fell.
PRECISION_FLOOR = 0.90
RECALL_FLOOR = 0.90
PER_DOCUMENT_LATENCY_FLOOR_SECONDS = 10.0


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures():
    """Regenerate any missing fixture (the committed set normally exists)."""
    missing = [
        spec.file_name for spec in gf.FIXTURES if not (FIXTURES_DIR / spec.file_name).exists()
    ]
    if missing or not (FIXTURES_DIR / "blurry_scan.png").exists():
        gf.generate(FIXTURES_DIR)


def _upload(client, path: Path):
    with open(path, "rb") as fh:
        started = time.perf_counter()
        response = client.post(
            "/api/v1/documents",
            files={"file": (path.name, io.BytesIO(fh.read()), "application/pdf")},
            data={"kind": "invoice"},
        )
        elapsed = time.perf_counter() - started
    return response, elapsed


def _normalized_value(field_json: dict):
    normalized = field_json.get("normalized_value")
    return normalized.get("value") if isinstance(normalized, dict) else None


def _field_matches(field_json: dict, expected) -> bool:
    if field_json["field_name"] == "line_items":
        items = (field_json.get("normalized_value") or {}).get("items") or []
        if len(items) != expected["count"]:
            return False
        return (
            [i["line_total"] for i in items] == expected["line_totals"]
            and [i["description"] for i in items] == expected["descriptions"]
        )
    return _normalized_value(field_json) == expected


def test_field_precision_recall_and_latency_on_fixtures(client):
    assert register(client).status_code == 201

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    misses: list[str] = []
    latencies: dict[str, float] = {}

    for spec in gf.FIXTURES:
        response, elapsed = _upload(client, FIXTURES_DIR / spec.file_name)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["processing_status"] == "completed"
        latencies[spec.file_name] = elapsed

        extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
        assert extraction["ocr_provider"] == "text_layer", spec.file_name

        extracted = {
            f["field_name"]: f
            for f in client.get(f"/api/v1/documents/{body['id']}/fields").json()["items"]
        }

        for name, expected in spec.expected.items():
            field = extracted.get(name)
            if field is not None and _field_matches(field, expected):
                true_positives += 1
            else:
                false_negatives += 1
                if field is not None:
                    false_positives += 1  # extracted, but with a wrong value
                    misses.append(
                        f"{spec.file_name}:{name} wrong value "
                        f"({_normalized_value(field)!r} != {expected!r})"
                    )
                else:
                    misses.append(f"{spec.file_name}:{name} not extracted")

        for name in spec.absent:
            if name in extracted:
                false_positives += 1
                misses.append(f"{spec.file_name}:{name} must be absent")

    total_expected = true_positives + false_negatives
    assert total_expected > 0
    precision = true_positives / (true_positives + false_positives)
    recall = true_positives / total_expected

    slowest = max(latencies.values())
    report = (
        f"synthetic-fixture metrics: precision={precision:.3f} "
        f"({true_positives} TP / {false_positives} FP), "
        f"recall={recall:.3f} ({true_positives}/{total_expected}), "
        f"latency per doc: min={min(latencies.values()) * 1000:.0f}ms "
        f"max={slowest * 1000:.0f}ms; misses: {misses or 'none'}"
    )
    print("\n" + report)

    assert precision >= PRECISION_FLOOR, report
    assert recall >= RECALL_FLOOR, report
    assert slowest <= PER_DOCUMENT_LATENCY_FLOOR_SECONDS, report


def test_blurry_scan_has_no_text_layer_and_yields_no_fields(client):
    """The PNG scan cannot be read by a text-layer provider: the honest
    outcome is zero fields, not an error and not invented content."""
    assert register(client).status_code == 201
    with open(FIXTURES_DIR / "blurry_scan.png", "rb") as fh:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("blurry_scan.png", io.BytesIO(fh.read()), "image/png")},
            data={"kind": "invoice"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    extraction = client.get(f"/api/v1/documents/{body['id']}/extraction").json()
    assert extraction["ocr_provider"] == "text_layer"
    assert "pixel OCR" in extraction["provider_meta"]["note"]
    assert client.get(f"/api/v1/documents/{body['id']}/fields").json()["items"] == []
