"""Contract tests pinning the backend serialized shape of each node.

These tests guard against silent drift in what ``serialize_result``
emits for nodes that frontend consumers (Sherpa Advisor, NodeDetailView,
DataTableModal, PlotNode) rely on.  Each fixture is captured by
``tests/fixtures/node_serialization/generate.py`` and committed to git;
the test here re-runs the node at test time, re-serializes, re-normalizes
the same way, and asserts it matches the committed fixture.

When the backend intentionally changes a node's serialized shape, the
fix is to regenerate the fixtures::

    python -m tests.fixtures.node_serialization.generate
    git add tests/fixtures/node_serialization
    git commit

and, in the same PR, update any frontend consumers that depend on the
old shape.  The backend test failure message below tells you exactly
which fields drifted so you know what needs updating on the consumer
side.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.node_serialization._contract import (
    FIXTURE_SPECS,
    FixtureSpec,
    capture_fixture,
    fixture_path,
    load_fixture,
)

pytest.importorskip("spectrochempy")


def _diff_summary(actual: object, expected: object, path: str = "") -> list[str]:
    """Return a list of human-readable diff lines between two JSON trees."""
    diffs: list[str] = []
    if type(actual) is not type(expected):
        diffs.append(f"  {path or '<root>'}: type mismatch ({type(actual).__name__} vs {type(expected).__name__})")
        return diffs
    if isinstance(actual, dict) and isinstance(expected, dict):
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        for key in missing:
            diffs.append(f"  {path}.{key}: missing in actual (expected has it)")
        for key in added:
            diffs.append(f"  {path}.{key}: added in actual (expected does not)")
        for key in sorted(set(actual) & set(expected)):
            diffs.extend(_diff_summary(actual[key], expected[key], f"{path}.{key}"))
        return diffs
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            diffs.append(f"  {path}: length mismatch ({len(actual)} vs {len(expected)})")
        for i, (a, e) in enumerate(zip(actual, expected)):
            diffs.extend(_diff_summary(a, e, f"{path}[{i}]"))
        return diffs
    if actual != expected:
        diffs.append(f"  {path}: value mismatch ({actual!r} vs {expected!r})")
    return diffs


@pytest.mark.parametrize("spec", FIXTURE_SPECS, ids=[s.name for s in FIXTURE_SPECS])
def test_node_serialization_matches_fixture(spec: FixtureSpec) -> None:
    """Re-run the node, serialize, normalize, and compare to the fixture.

    Failure modes and what they mean:

    - **"missing in actual"** — a field that used to be present in the
      serialized output has been removed.  Any frontend consumer that
      read it is now seeing ``undefined`` silently.  Decide whether
      the field should come back, or update the consumers.

    - **"added in actual"** — a new field has appeared.  Usually fine,
      but regenerate the fixture so it's pinned going forward.

    - **"type mismatch"** / **"value mismatch"** — the shape of a nested
      value changed (e.g. a list became a dict, or ``null`` became
      ``"<missing>"``).  This is the class of bug that bit PR #16.
    """
    try:
        fixture = load_fixture(spec)
    except FileNotFoundError:
        pytest.fail(
            f"Fixture file missing for spec {spec.name!r}. "
            f"Generate with: python -m tests.fixtures.node_serialization.generate"
        )

    try:
        actual = capture_fixture(spec)
    except Exception as exc:  # noqa: BLE001 — any builder failure is a test failure
        pytest.fail(
            f"Builder for {spec.name!r} raised {type(exc).__name__}: {exc}. "
            f"If this is expected (e.g. missing test data), mark the spec "
            f"as skippable."
        )

    if actual == fixture:
        return

    diffs = _diff_summary(actual["serialized"], fixture["serialized"], "serialized")
    diff_text = "\n".join(diffs) if diffs else "  (no structural diff; metadata only)"

    pytest.fail(
        f"Backend serialized shape for {spec.name!r} drifted from the "
        f"committed fixture at {fixture_path(spec).relative_to(fixture_path(spec).parents[3])}.\n"
        f"\nField-level differences:\n{diff_text}\n"
        f"\nIf this drift is intentional, regenerate the fixture and update "
        f"any frontend consumer that depends on the old shape:\n"
        f"  python -m tests.fixtures.node_serialization.generate\n"
        f"  git add tests/fixtures/node_serialization"
    )


def test_fixtures_are_valid_json() -> None:
    """Smoke check: every fixture on disk parses as valid JSON."""
    for spec in FIXTURE_SPECS:
        path = fixture_path(spec)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            # Round-trip: parse then re-serialize.
            parsed = json.load(fh)
            json.dumps(parsed)
        assert "_spec" in parsed, f"{path.name} missing '_spec' key"
        assert parsed["_spec"] == spec.name, f"{path.name} has _spec={parsed['_spec']!r} but expected {spec.name!r}"


def test_normalize_strips_uuids_and_timestamps() -> None:
    """Spot-check the normalization helper behaviour in isolation."""
    from tests.fixtures.node_serialization._contract import normalize_for_fixture

    payload = {
        "dataset_id": "7f07df8d-1879-411c-a7fc-b6b53f1360d4",
        "nested": {
            "timestamp": "2026-04-11T05:31:46.265510+00:00",
            "clean": "stable value",
            "inner_uuid": "00000000-0000-0000-0000-000000000000",
        },
        "preserved_number": 42,
        "preserved_list": [1, 2, 3],
    }
    result = normalize_for_fixture(payload)
    assert result["dataset_id"] == "<dataset_id>"
    assert result["nested"]["timestamp"] == "<timestamp>"
    assert result["nested"]["clean"] == "stable value"
    assert result["nested"]["inner_uuid"] == "<uuid>"
    assert result["preserved_number"] == 42
    assert result["preserved_list"] == [1, 2, 3]


def test_normalize_summarizes_large_arrays() -> None:
    """Large numeric arrays in known 'bulk data' keys get shape-summarized."""
    from tests.fixtures.node_serialization._contract import normalize_for_fixture

    payload = {
        "data": [[float(i + j) for j in range(13)] for i in range(200)],
        "target": list(range(200)),
        "metadata": {"n_samples": 200, "n_features": 13},
        # A short "data" list inside an unrelated context — still gets
        # summarized because we key off the field name, which is the
        # right heuristic for bulk-data fields but means authors of
        # new fixture specs should use unique field names for
        # small-but-important payloads (done in practice by using
        # key names like ``metrics`` or ``per_target``, not ``data``).
    }
    result = normalize_for_fixture(payload)
    assert result["data"] == {
        "__array_summary__": True,
        "shape": [200, 13],
        "element_type": "list",
    }
    assert result["target"] == {
        "__array_summary__": True,
        "shape": [200],
        "element_type": "int",
    }
    # Small metadata dict passes through unchanged.
    assert result["metadata"] == {"n_samples": 200, "n_features": 13}


def test_normalize_preserves_row_dict_lists() -> None:
    """List-of-dicts (metrics rows) must NOT be summarized into shape descriptors.

    Metrics payloads from HoldoutEvaluation have ``data: [row_dict,
    row_dict, ...]`` — the whole point of the fixture is to pin the
    exact row structure, so summarizing would destroy the signal.
    """
    from tests.fixtures.node_serialization._contract import normalize_for_fixture

    payload = {
        "data": [
            {"target": "Moisture", "RMSEP": 0.1, "R2": 0.98},
            {"target": "Oil", "RMSEP": 0.2, "R2": 0.90},
        ],
    }
    result = normalize_for_fixture(payload)
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 2
    assert result["data"][0]["target"] == "Moisture"
