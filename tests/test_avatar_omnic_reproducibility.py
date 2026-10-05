from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_reproducibility.py"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_reproducibility", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

MANIFEST_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-manifest.json"
QUALIFICATION_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-parser-qualification.json"
REPORT_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-reproducibility.json"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _fake_sources(tmp_path: Path) -> tuple[Path, Path, list[dict[str, Any]], np.ndarray, np.ndarray]:
    specimens = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K")
    axis = np.linspace(4000.0, 400.0, 1868, dtype=np.float64)
    base = 0.08 + 0.04 * np.sin(np.linspace(0.0, 12.0, 1868)) + 0.01 * np.cos(np.linspace(0.0, 41.0, 1868))
    rows: list[dict[str, Any]] = []
    values: list[np.ndarray] = []
    for block in (1, 2, 3):
        for order, specimen in enumerate(specimens, start=1):
            sample_id = f"{specimen}__B{block}"
            spectrum = base + order * 0.001 + block * 0.0002 * np.sin(np.linspace(0.0, 8.0, 1868))
            values.append(spectrum)
            rows.append(
                {
                    "sample_id": sample_id,
                    "specimen_id": specimen,
                    "block": block,
                    "acquisition_order": order,
                    "acquired_at": f"2026-08-24T0{block}:{order:02d}:00+00:00",
                    "distribution_filename": f"{sample_id}.spa",
                    "curated_sha256": _sha(f"source:{sample_id}"),
                    "values_sha256": TOOL._array_sha256(spectrum),
                    "axis_sha256": TOOL._array_sha256(axis),
                }
            )
    matrix = np.vstack(values)
    manifest = {
        "dataset_id": TOOL.DATASET_ID,
        "dataset_version": "1",
        "files": rows,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    qualification = {
        "dataset_id": TOOL.DATASET_ID,
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "structural_ingestion_passed": True,
        "external_converter_parity_verified": True,
        "files": [
            {
                "sample_id": row["sample_id"],
                "values_sha256": row["values_sha256"],
                "axis_sha256": row["axis_sha256"],
                "external_converter_full_array_equal": True,
            }
            for row in rows
        ],
    }
    qualification_path = tmp_path / "qualification.json"
    qualification_path.write_text(json.dumps(qualification))
    return manifest_path, qualification_path, rows, matrix, axis


def _fake_figures(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    return [
        {
            "filename": name,
            "sha256": _sha(name),
            "size_bytes": 100 + index,
            "status": "generated_private_not_redistributed_pending_phase9_permission",
        }
        for index, name in enumerate(TOOL.PRIVATE_FIGURE_NAMES)
    ]


def test_phase3_builds_exact_block_aware_reproducibility_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, qualification, rows, matrix, axis = _fake_sources(tmp_path)
    monkeypatch.setattr(TOOL, "_load_exact_sources", lambda *_args: (rows, matrix, axis))
    monkeypatch.setattr(TOOL, "_render_private_figures", _fake_figures)
    report = TOOL.build_phase3_report(manifest, qualification, tmp_path, tmp_path / "figures")

    assert report["matrix"]["shape"] == [33, 1868]
    assert len(report["spectra"]) == 33
    assert len(report["pairwise_repeatability"]) == 33
    assert len(report["specimens"]) == 11
    assert len(report["blocks"]) == 3
    assert report["summary"]["correlation_investigation_trigger_count"] == 0
    assert report["summary"]["rms_investigation_trigger_count"] == 0
    assert report["inclusion_decision"]["excluded_sample_ids"] == []
    assert TOOL.validate_phase3_evidence_links(report, manifest.read_bytes(), qualification.read_bytes()) == []


def test_phase3_evidence_rejects_metric_trigger_and_identity_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, qualification, rows, matrix, axis = _fake_sources(tmp_path)
    monkeypatch.setattr(TOOL, "_load_exact_sources", lambda *_args: (rows, matrix, axis))
    monkeypatch.setattr(TOOL, "_render_private_figures", _fake_figures)
    report = TOOL.build_phase3_report(manifest, qualification, tmp_path, tmp_path / "figures")

    changed = copy.deepcopy(report)
    changed["pairwise_repeatability"][0]["pearson_correlation"] = 0.5
    assert any(
        "correlation trigger disagrees" in failure
        for failure in TOOL.validate_phase3_evidence_links(changed, manifest.read_bytes(), qualification.read_bytes())
    )

    changed = copy.deepcopy(report)
    changed["spectra"][0]["values_sha256"] = "0" * 64
    assert any(
        "values binding differs" in failure
        for failure in TOOL.validate_phase3_evidence_links(changed, manifest.read_bytes(), qualification.read_bytes())
    )

    changed = copy.deepcopy(report)
    changed["inclusion_decision"]["excluded_sample_ids"] = [changed["spectra"][0]["sample_id"]]
    assert any(
        "silently excludes" in failure
        for failure in TOOL.validate_phase3_evidence_links(changed, manifest.read_bytes(), qualification.read_bytes())
    )


def test_phase3_evidence_rejects_summary_threshold_and_projection_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, qualification, rows, matrix, axis = _fake_sources(tmp_path)
    monkeypatch.setattr(TOOL, "_load_exact_sources", lambda *_args: (rows, matrix, axis))
    monkeypatch.setattr(TOOL, "_render_private_figures", _fake_figures)
    report = TOOL.build_phase3_report(manifest, qualification, tmp_path, tmp_path / "figures")

    mutations = (
        ("thresholds", lambda value: value["thresholds"].__setitem__("pearson_correlation_below", 0.5)),
        ("summary", lambda value: value["summary"].__setitem__("rms_investigation_trigger_count", 1)),
        ("specimen", lambda value: value["specimens"][0]["sample_ids"].reverse()),
        ("block", lambda value: value["blocks"][0].__setitem__("difference_to_grand_mean_rms", float("nan"))),
        ("pair", lambda value: value["pairwise_repeatability"][0].__setitem__("sample_id_a", "K__B1")),
        ("PCA", lambda value: value.__setitem__("pca_block_drift", "complete")),
    )
    for label, mutate in mutations:
        changed = copy.deepcopy(report)
        mutate(changed)
        assert TOOL.validate_phase3_evidence_links(
            changed, manifest.read_bytes(), qualification.read_bytes()
        ), f"{label} mutation was accepted"


def test_phase3_requires_exact_manifest_qualification_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, qualification, rows, matrix, axis = _fake_sources(tmp_path)
    payload = json.loads(qualification.read_text())
    payload["source_manifest_sha256"] = "0" * 64
    qualification.write_text(json.dumps(payload))
    monkeypatch.setattr(TOOL, "_load_exact_sources", lambda *_args: (rows, matrix, axis))
    monkeypatch.setattr(TOOL, "_render_private_figures", _fake_figures)
    with pytest.raises(TOOL.CorpusError, match="not bound to the exact manifest"):
        TOOL.build_phase3_report(manifest, qualification, tmp_path, tmp_path / "figures")


def test_phase3_rejects_wrong_source_size_before_read_or_native_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, qualification, rows, _matrix, _axis = _fake_sources(tmp_path)
    first = rows[0]
    first["size_bytes"] = 1
    manifest_payload = json.loads(manifest.read_text())
    manifest_payload["files"] = rows
    qualification_payload = json.loads(qualification.read_text())
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / first["distribution_filename"]).write_bytes(b"oversized")
    native_reached = False

    def forbidden_read_bytes(_path: Path) -> bytes:
        raise AssertionError("unbounded Path.read_bytes was reached")

    def forbidden_native(_path: Path) -> tuple[np.ndarray, np.ndarray, object]:
        nonlocal native_reached
        native_reached = True
        raise AssertionError("native ingestion was reached")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    monkeypatch.setattr(TOOL, "_native_arrays", forbidden_native)
    with pytest.raises(TOOL.CorpusError, match="size differs"):
        TOOL._load_exact_sources(manifest_payload, qualification_payload, curated)
    assert native_reached is False


def test_phase3_private_figure_path_enforces_private_root() -> None:
    with pytest.raises(TOOL.CorpusError, match="must be outside"):
        TOOL._render_private_figures(
            REPO_ROOT / "docs" / "evidence" / "avatar-plots",
            [],
            np.empty((0, 0)),
            np.empty(0),
            [],
        )


def test_phase3_private_figure_renderer_rejects_symlink_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    public_target = tmp_path / "public-evidence.txt"
    public_target.write_text("unchanged")
    (private_dir / TOOL.PRIVATE_FIGURE_NAMES[0]).symlink_to(public_target)
    monkeypatch.setattr(TOOL, "_require_private_worktree_path", lambda path: path)

    with pytest.raises(TOOL.CorpusError, match="unexpected file"):
        TOOL._render_private_figures(private_dir, [], np.empty((0, 0)), np.empty(0), [])
    assert public_target.read_text() == "unchanged"


def test_checked_phase3_evidence_is_closed_and_cross_bound() -> None:
    report = json.loads(REPORT_PATH.read_text())
    manifest_bytes = MANIFEST_PATH.read_bytes()
    qualification_bytes = QUALIFICATION_PATH.read_bytes()
    assert TOOL.validate_checked_phase3_evidence(REPORT_PATH, MANIFEST_PATH, QUALIFICATION_PATH) == []
    assert TOOL.validate_phase3_evidence_links(report, manifest_bytes, qualification_bytes) == []

    changed = copy.deepcopy(report)
    changed["private_figures"][0]["status"] = "public"
    assert any(
        "publication boundary is overstated" in failure
        for failure in TOOL.validate_phase3_evidence_links(changed, manifest_bytes, qualification_bytes)
    )


def test_checked_phase3_evidence_digest_rejects_scientific_mutation(tmp_path: Path) -> None:
    changed = json.loads(REPORT_PATH.read_text())
    changed["spectra"][0]["mean_absorbance"] = 123.0
    changed_path = tmp_path / "changed-report.json"
    changed_path.write_text(json.dumps(changed, indent=2) + "\n")
    assert TOOL.validate_checked_phase3_evidence(changed_path, MANIFEST_PATH, QUALIFICATION_PATH) == [
        "checked Phase-3 report digest differs from the exact reviewed authority"
    ]
