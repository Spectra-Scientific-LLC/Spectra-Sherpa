from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_phase53c_portability.py"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_phase53c_portability", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

REPORT = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-portability.json"


def test_checked_phase53c_portability_report_is_exact() -> None:
    assert TOOL.validate_checked_report(REPORT) == []


def test_checked_phase53c_portability_report_rejects_scientific_and_process_mutations(tmp_path: Path) -> None:
    report = json.loads(REPORT.read_text())
    mutations = (
        lambda value: value["process_and_workspace_boundary"].__setitem__("old_dataset_handle_used", True),
        lambda value: value["save_export_import"].__setitem__("restored_source_count", 32),
        lambda value: value["scientific_projection"].__setitem__("values_sha256", "0" * 64),
        lambda value: value["identity_preservation"].__setitem__("sample_labels_and_table_exact", False),
        lambda value: value["legacy_sidecar_retirement"].__setitem__("exact_source_binding", False),
        lambda value: value["privacy_boundary"].__setitem__("project_archive_published", True),
        lambda value: value["nonclaims"].remove("non_author_physical_action_2"),
    )
    for index, mutate in enumerate(mutations):
        changed = copy.deepcopy(report)
        mutate(changed)
        path = tmp_path / f"changed-{index}.json"
        path.write_text(json.dumps(changed, sort_keys=True, indent=2) + "\n")
        failures = TOOL.validate_checked_report(path)
        assert "checked portability report digest differs from the reviewed authority" in failures
        assert "checked portability report differs from its closed reviewed projection" in failures


def test_checked_phase53c_report_contains_no_private_location_or_database_identity() -> None:
    text = REPORT.read_text()
    forbidden = (
        "private-input",
        "/Users/",
        '"project_id":',
        '"experiment_id":',
        '"user_id":',
        '"database_id":',
    )
    assert all(marker not in text for marker in forbidden)


def _retirement_fixture(tmp_path: Path, *, retired: bool = False):
    workspace = tmp_path / "workspace"
    raw = workspace / "experiments" / "exp_002" / "raw"
    raw.mkdir(parents=True)
    sidecar_root = workspace / ("retired-phase5-legacy-sample-sidecars" if retired else ".metadata_overrides")
    sidecar_root.mkdir()
    os.chmod(sidecar_root, 0o700)
    rows = []
    entries = []
    for index, name in enumerate(("A", "B"), start=1):
        source_bytes = f"source-{name}".encode()
        source = raw / f"{name}.spa"
        source.write_bytes(source_bytes)
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        sample_id = f"{name}__B1"
        annotations = {"sample_id": sample_id, "specimen_id": name, "block": 1, "acquisition_order": index}
        file_name = f"raw/{name}.spa"
        rows.append(
            {
                "file_name": file_name,
                "sha256": source_sha,
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": sample_id,
                "annotations": annotations,
            }
        )
        entries.append(
            {
                "file_name": file_name,
                "size_bytes": len(source_bytes),
                "sha256": source_sha,
                "prepared_data_sha256": TOOL.EMPTY_PREPARED_DATA_SHA256,
            }
        )
        sidecar = {
            "sample_labels": [sample_id],
            "sample_table": {key: [value] for key, value in annotations.items()},
        }
        filename = TOOL._sidecar_filename_for_source(experiment_id=2, file_name=file_name)
        (sidecar_root / filename).write_text(json.dumps(sidecar))
    definition_bytes = json.dumps({"rows": rows}, sort_keys=True, separators=(",", ":")).encode()
    definition_path = workspace / "definition.json"
    definition_path.write_bytes(definition_bytes)
    definition_sha = hashlib.sha256(definition_bytes).hexdigest()
    source_sha = TOOL._source_manifest(entries)["manifest_digest"]
    if retired:
        (sidecar_root / "retirement.json").write_text("{}\n")
    return workspace, sidecar_root, definition_path, definition_bytes, definition_sha, source_sha


def test_retirement_rejects_correct_values_under_unrelated_sidecar_names(tmp_path: Path) -> None:
    workspace, root, _, definition, definition_sha, source_sha = _retirement_fixture(tmp_path)
    original = sorted(root.iterdir())[0]
    original.rename(root / f"file__{'f' * 64}.json")
    with pytest.raises(ValueError, match="source-derived names"):
        TOOL._admit_legacy_sidecar_inventory(
            workspace=workspace,
            experiment_id=2,
            definition_payload=definition,
            sidecar_root=root,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )


def test_retirement_rejects_linked_overrides_root(tmp_path: Path) -> None:
    workspace, root, _, definition, definition_sha, source_sha = _retirement_fixture(tmp_path)
    real = workspace / "real-overrides"
    root.rename(real)
    os.symlink(real, root)
    with pytest.raises(ValueError, match="linked or non-directory"):
        TOOL._admit_legacy_sidecar_inventory(
            workspace=workspace,
            experiment_id=2,
            definition_payload=definition,
            sidecar_root=root,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )


def test_retirement_rejects_non_equivalent_row(tmp_path: Path) -> None:
    workspace, root, _, definition, definition_sha, source_sha = _retirement_fixture(tmp_path)
    sidecar = sorted(root.iterdir())[0]
    value = json.loads(sidecar.read_text())
    value["sample_table"]["block"] = [2]
    sidecar.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="differs from the attached collection definition"):
        TOOL._admit_legacy_sidecar_inventory(
            workspace=workspace,
            experiment_id=2,
            definition_payload=definition,
            sidecar_root=root,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )


def test_run_requires_exact_re_admitted_retirement_receipt(tmp_path: Path) -> None:
    workspace, root, definition_path, definition, definition_sha, source_sha = _retirement_fixture(
        tmp_path, retired=True
    )
    observed = TOOL._admit_legacy_sidecar_inventory(
        workspace=workspace,
        experiment_id=2,
        definition_payload=definition,
        sidecar_root=root,
        expected_definition_sha256=definition_sha,
        expected_source_sha256=source_sha,
        control_names=frozenset({"retirement.json"}),
    )
    TOOL._require_live_duplicate_authority_absent(workspace=workspace, receipt=observed)
    observed["live_duplicate_authority_absent"] = True
    missing = workspace / "missing-receipt.json"
    with pytest.raises(ValueError, match="absent, linked, or unreadable"):
        TOOL._require_retirement_receipt(
            workspace=workspace,
            experiment_id=2,
            definition_path=definition_path,
            receipt_path=missing,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )
    receipt = workspace / "receipt.json"
    receipt.write_text(json.dumps({**observed, "sidecar_count": 1}, sort_keys=True, indent=2) + "\n")
    os.chmod(receipt, 0o600)
    with pytest.raises(ValueError, match="differs from the re-admitted"):
        TOOL._require_retirement_receipt(
            workspace=workspace,
            experiment_id=2,
            definition_path=definition_path,
            receipt_path=receipt,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )
    receipt.unlink()
    target = workspace / "linked-target.json"
    target.write_text(json.dumps(observed))
    os.chmod(target, 0o600)
    os.symlink(target, receipt)
    with pytest.raises(ValueError, match="linked, non-regular, or not private"):
        TOOL._require_retirement_receipt(
            workspace=workspace,
            experiment_id=2,
            definition_path=definition_path,
            receipt_path=receipt,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )


def test_run_refuses_live_duplicate_or_linked_live_root(tmp_path: Path) -> None:
    workspace, retired, definition_path, definition, definition_sha, source_sha = _retirement_fixture(
        tmp_path, retired=True
    )
    observed = TOOL._admit_legacy_sidecar_inventory(
        workspace=workspace,
        experiment_id=2,
        definition_payload=definition,
        sidecar_root=retired,
        expected_definition_sha256=definition_sha,
        expected_source_sha256=source_sha,
        control_names=frozenset({"retirement.json"}),
    )
    observed["live_duplicate_authority_absent"] = True
    receipt = workspace / "receipt.json"
    receipt.write_text(json.dumps(observed, sort_keys=True, indent=2) + "\n")
    os.chmod(receipt, 0o600)

    live = workspace / ".metadata_overrides"
    live.mkdir(mode=0o700)
    name = observed["sidecars"][0]["sidecar_filename"]
    (live / name).write_bytes((retired / name).read_bytes())
    with pytest.raises(ValueError, match="exact retired sidecar remains"):
        TOOL._require_retirement_receipt(
            workspace=workspace,
            experiment_id=2,
            definition_path=definition_path,
            receipt_path=receipt,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )

    (live / name).unlink()
    live.rmdir()
    linked_target = workspace / "linked-live-target"
    linked_target.mkdir(mode=0o700)
    os.symlink(linked_target, live)
    with pytest.raises(ValueError, match="linked, non-directory, or not private"):
        TOOL._require_retirement_receipt(
            workspace=workspace,
            experiment_id=2,
            definition_path=definition_path,
            receipt_path=receipt,
            expected_definition_sha256=definition_sha,
            expected_source_sha256=source_sha,
        )
