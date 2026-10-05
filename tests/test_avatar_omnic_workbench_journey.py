from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_workbench_journey.py"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_workbench_journey", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

EVIDENCE = REPO_ROOT / "docs" / "evidence"
REPORT = EVIDENCE / "avatar-essential-oils-v1-workbench-journey.json"
MANIFEST = EVIDENCE / "avatar-essential-oils-v1-manifest.json"
QUALIFICATION = EVIDENCE / "avatar-essential-oils-v1-parser-qualification.json"
CANONICAL_REPORT = EVIDENCE / "avatar-essential-oils-v1-canonical-dataset.json"
DEFINITION = EVIDENCE / "avatar-essential-oils-v1-collection-definition.json"


def _validate(path: Path = REPORT) -> list[str]:
    return TOOL.validate_checked_journey(path, MANIFEST, QUALIFICATION, CANONICAL_REPORT, DEFINITION)


def test_checked_avatar_workbench_journey_is_exact_and_cross_bound() -> None:
    assert _validate() == []


def test_checked_avatar_workbench_journey_rejects_every_observation_mutation(tmp_path: Path) -> None:
    report = json.loads(REPORT.read_text())
    mutations = (
        lambda value: value["upload_and_inventory"].__setitem__("persisted_file_count", 32),
        lambda value: value["definition_receipt"].__setitem__("scientific_collection_sha256", "0" * 64),
        lambda value: value["collection_inspection"].__setitem__("raw_spectrum_trace_count", 32),
        lambda value: value["stale_source_test"].__setitem__("definition_fallback_observed", True),
        lambda value: value["privacy_boundary"].__setitem__("screenshots_published", True),
        lambda value: value["nonclaims"].remove("non_author_physical_action_2"),
    )
    for index, mutate in enumerate(mutations):
        changed = copy.deepcopy(report)
        mutate(changed)
        path = tmp_path / f"changed-{index}.json"
        path.write_text(json.dumps(changed, indent=2) + "\n")
        failures = _validate(path)
        assert "checked Workbench journey digest differs from the reviewed authority" in failures
        assert "checked Workbench journey differs from its closed reviewed projection" in failures


def test_workbench_journey_contains_no_private_payload_or_location_fields() -> None:
    text = REPORT.read_text()
    forbidden = ("private-input", "/Users/", "experiment_id", "project_id", "user_id", "screenshot_path")
    assert all(marker not in text for marker in forbidden)
