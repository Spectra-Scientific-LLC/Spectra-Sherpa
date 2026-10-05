from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_canonical_dataset.py"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_canonical_dataset", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

MANIFEST_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-manifest.json"
QUALIFICATION_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-parser-qualification.json"
PHASE3_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-reproducibility.json"
REPORT_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-canonical-dataset.json"


def _rows_matrix_axis() -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    axis = np.linspace(4000.0, 400.0, 1868, dtype=np.float64)
    rows: list[dict[str, Any]] = []
    spectra: list[np.ndarray] = []
    for block in (1, 2, 3):
        for order, specimen in enumerate("ABCDEFGHIJK", start=1):
            sample_id = f"{specimen}__B{block}"
            spectra.append(np.sin(axis / 300.0) + order * 0.01 + block * 0.001)
            rows.append(
                {
                    "sample_id": sample_id,
                    "specimen_id": specimen,
                    "block": block,
                    "acquisition_order": order,
                    "analysis_role": "oil",
                    "claimed_botanical_group": "author claim",
                    "author_reported_authenticity_status": "supplier_claim",
                    "evidence_status": "pending_exact_citation",
                    "distribution_filename": f"{sample_id}.spa",
                    "curated_sha256": f"{block * 11 + order:064x}",
                    "canonical_omnic_title": f"{block}{specimen}",
                    "label_status": "acquired_label_verified",
                    "acquired_at": f"2026-08-24T0{block}:{order:02d}:00+00:00",
                }
            )
    return rows, np.vstack(spectra), axis


def test_phase4_builds_typed_target_free_dataset_and_round_trips(tmp_path: Path) -> None:
    rows, matrix, axis = _rows_matrix_axis()
    dataset = TOOL.build_canonical_dataset(rows, matrix, axis)
    projection = TOOL.dataset_projection(dataset)

    assert projection["shape"] == [33, 1868]
    assert projection["target_state"] == "absent"
    assert projection["sample_classes_state"] == "absent"
    assert tuple(dataset.sample_axis.sample_table) == TOOL.SAMPLE_TABLE_COLUMNS
    assert all(dataset.sample_axis.include_mask)

    artifact = tmp_path / TOOL.ARTIFACT_FILENAME
    record = TOOL._write_private_artifact(artifact, TOOL._artifact_bytes(dataset))
    assert record["status"] == TOOL.ARTIFACT_STATUS
    assert TOOL.dataset_projection(TOOL.load_private_dataset(artifact)) == projection
    assert TOOL._restart_projection(artifact) == projection


def test_phase4_private_artifact_rejects_symlink_without_overwrite(tmp_path: Path) -> None:
    victim_dir = tmp_path / "victim"
    link_dir = tmp_path / "link"
    victim_dir.mkdir()
    link_dir.mkdir()
    target = victim_dir / TOOL.ARTIFACT_FILENAME
    target.write_text("unchanged")
    artifact = link_dir / TOOL.ARTIFACT_FILENAME
    artifact.symlink_to(target)
    with pytest.raises(TOOL.CorpusError, match="linked or non-regular"):
        TOOL._write_private_artifact(artifact, b"{}\n")
    assert target.read_text() == "unchanged"


def test_phase4_private_artifact_verification_rejects_corruption_without_repair(tmp_path: Path) -> None:
    rows, matrix, axis = _rows_matrix_axis()
    dataset = TOOL.build_canonical_dataset(rows, matrix, axis)
    expected_payload = TOOL._artifact_bytes(dataset)
    artifact = tmp_path / TOOL.ARTIFACT_FILENAME
    TOOL._write_private_artifact(artifact, expected_payload)
    artifact.write_bytes(b"{}\n")
    corrupted_payload = artifact.read_bytes()

    with pytest.raises(TOOL.CorpusError, match="bytes differ from the exact reconstructed dataset"):
        TOOL._verify_private_artifact(artifact, expected_payload)

    assert artifact.read_bytes() == corrupted_payload


def test_checked_phase4_evidence_is_closed_and_cross_bound() -> None:
    report = json.loads(REPORT_PATH.read_text())
    manifest_bytes = MANIFEST_PATH.read_bytes()
    qualification_bytes = QUALIFICATION_PATH.read_bytes()
    phase3_bytes = PHASE3_PATH.read_bytes()
    assert TOOL.validate_checked_phase4_evidence(REPORT_PATH, MANIFEST_PATH, QUALIFICATION_PATH, PHASE3_PATH) == []
    assert TOOL.validate_phase4_evidence_links(report, manifest_bytes, qualification_bytes, phase3_bytes) == []

    mutations = (
        lambda value: value["dataset"].__setitem__("values_sha256", "0" * 64),
        lambda value: value["dataset"].__setitem__("target_state", "present"),
        lambda value: value["sample_table"].__setitem__("sha256", "0" * 64),
        lambda value: value["round_trip"].__setitem__("fresh_process_restart_equal", False),
    )
    for mutate in mutations:
        changed = copy.deepcopy(report)
        mutate(changed)
        assert TOOL.validate_phase4_evidence_links(changed, manifest_bytes, qualification_bytes, phase3_bytes)


def test_checked_phase4_report_digest_rejects_mutation(tmp_path: Path) -> None:
    changed = json.loads(REPORT_PATH.read_text())
    changed["private_artifact"]["sha256"] = "0" * 64
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(changed, indent=2) + "\n")
    assert TOOL.validate_checked_phase4_evidence(changed_path, MANIFEST_PATH, QUALIFICATION_PATH, PHASE3_PATH) == [
        "checked Phase-4 report digest differs from the exact reviewed authority"
    ]
