#!/usr/bin/env python3
"""Build and verify the private canonical Avatar SherpaDataset artifact."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from avatar_omnic_corpus import (  # noqa: E402
    DATASET_ID,
    PRIVATE_WORKTREE_ROOT,
    REPOSITORY_ROOT,
    CorpusError,
    _array_sha256,
    _sha256_bytes,
)
from avatar_omnic_reproducibility import (  # noqa: E402
    CHECKED_REPORT_SHA256 as PHASE3_REPORT_SHA256,
)
from avatar_omnic_reproducibility import (
    _json_sha256,
    _load_exact_sources,
    validate_checked_phase3_evidence,
)

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis  # noqa: E402
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset  # noqa: E402

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-canonical-dataset/1"
STATUS = "phase4_canonical_dataset_complete_private_artifact_not_distributed"
ARTIFACT_STATUS = "private_not_redistributed_pending_phase9_permission"
ARTIFACT_FILENAME = "avatar-essential-oils-v1-canonical.sherpa.json"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
EXPECTED_SHAPE = (33, 1868)
DATASET_IDENTITY = "avatar-essential-oils/1:canonical-phase4"
CLAIM_BOUNDARY = (
    "Exact native dataset construction and restart round-trip for this 33-spectrum corpus only; no botanical, "
    "authenticity, supplier, population, PCA, or classification conclusion is made."
)
CHECKED_REPORT_SHA256 = "1386ac7facdc742c1b5f9e1992fc2a1c81c57ad79596de07840a0bbcabcccf70"
SAMPLE_TABLE_COLUMNS = (
    "sample_id",
    "specimen_id",
    "block",
    "acquisition_order",
    "analysis_role",
    "claimed_botanical_group",
    "author_reported_authenticity_status",
    "evidence_status",
    "evidence_citation_id",
    "curated_filename",
    "curated_sha256",
    "canonical_omnic_title",
    "label_status",
    "acquired_at",
)
_ROOT_FIELDS = {
    "schema_version",
    "dataset_id",
    "dataset_version",
    "status",
    "source_manifest_sha256",
    "source_parser_qualification_sha256",
    "source_reproducibility_report_sha256",
    "claim_boundary",
    "dataset",
    "sample_table",
    "private_artifact",
    "round_trip",
}


def _sample_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Any]]:
    table = {
        "sample_id": [row["sample_id"] for row in rows],
        "specimen_id": [row["specimen_id"] for row in rows],
        "block": [row["block"] for row in rows],
        "acquisition_order": [row["acquisition_order"] for row in rows],
        "analysis_role": [row["analysis_role"] for row in rows],
        "claimed_botanical_group": [row["claimed_botanical_group"] for row in rows],
        "author_reported_authenticity_status": [row["author_reported_authenticity_status"] for row in rows],
        "evidence_status": [row["evidence_status"] for row in rows],
        "evidence_citation_id": [None for _row in rows],
        "curated_filename": [row["distribution_filename"] for row in rows],
        "curated_sha256": [row["curated_sha256"] for row in rows],
        "canonical_omnic_title": [row["canonical_omnic_title"] for row in rows],
        "label_status": [row["label_status"] for row in rows],
        "acquired_at": [row["acquired_at"] for row in rows],
    }
    if tuple(table) != SAMPLE_TABLE_COLUMNS or any(len(values) != 33 for values in table.values()):
        raise CorpusError("canonical sample table is incomplete or reordered")
    return table


def build_canonical_dataset(rows: Sequence[Mapping[str, Any]], matrix: np.ndarray, axis: np.ndarray) -> SherpaDataset:
    if tuple(matrix.shape) != EXPECTED_SHAPE or tuple(axis.shape) != (EXPECTED_SHAPE[1],):
        raise CorpusError("canonical dataset source shape is not exact")
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(axis)) or not np.all(np.diff(axis) < 0):
        raise CorpusError("canonical dataset contains non-finite values or a non-descending feature axis")
    labels = [str(row["sample_id"]) for row in rows]
    if len(labels) != 33 or len(set(labels)) != 33:
        raise CorpusError("canonical sample identities are missing or duplicated")
    sample_axis = SampleAxis(
        labels=labels,
        title="Acquisition",
        include_mask=np.ones(33, dtype=bool),
        sample_table=_sample_table(rows),
    )
    return SherpaDataset(
        X=np.asarray(matrix, dtype=np.float64),
        feature_axis=SpectralAxis(values=np.asarray(axis, dtype=np.float64), units="cm-1", title="Wavenumber"),
        sample_axis=sample_axis,
        domain=DomainContext(
            technique="IR",
            sample_type="essential oil",
            measurement_mode="ATR absorbance",
            expected_units="absorbance",
            data_quantity="absorbance",
            instrument="Thermo Nicolet Avatar 370",
        ),
        title="Avatar essential-oil three-block corpus",
        units="absorbance",
        dataset_id=DATASET_IDENTITY,
        data_role="X_spectra",
    )


def dataset_projection(dataset: SherpaDataset) -> dict[str, Any]:
    feature_axis = dataset.get_feature_axis()
    sample_axis = dataset.sample_axis
    if feature_axis is None or feature_axis.values is None or sample_axis is None or sample_axis.sample_table is None:
        raise CorpusError("canonical dataset lacks its typed axes or sample table")
    table = sample_axis.sample_table
    projection = {
        "type": "SherpaDataset",
        "wire_version": dataset.to_dict(include_extra=True)["version"],
        "dataset_id": dataset.dataset_id,
        "shape": list(dataset.shape),
        "dtype": str(dataset.X.dtype),
        "values_sha256": _array_sha256(dataset.X),
        "feature_axis_sha256": _array_sha256(feature_axis.values),
        "feature_axis_title": feature_axis.title,
        "feature_axis_units": feature_axis.units,
        "feature_axis_order": "strictly_descending" if np.all(np.diff(feature_axis.values) < 0) else "invalid",
        "sample_labels_sha256": _json_sha256(sample_axis.labels),
        "sample_table_sha256": _json_sha256(table),
        "include_mask_sha256": _json_sha256(
            sample_axis.include_mask.tolist() if sample_axis.include_mask is not None else None
        ),
        "title": dataset.title,
        "units": dataset.units,
        "data_role": dataset.data_role,
        "domain": dataset.domain.model_dump(mode="json", exclude_none=True),
        "target_state": "absent" if dataset.target is None else "present",
        "sample_classes_state": "absent" if sample_axis.classes is None else "present",
    }
    if projection["shape"] != [33, 1868] or projection["feature_axis_order"] != "strictly_descending":
        raise CorpusError("canonical dataset projection is invalid")
    if set(table) != set(SAMPLE_TABLE_COLUMNS) or sample_axis.labels != table["sample_id"]:
        raise CorpusError("canonical sample table or labels differ from the identity authority")
    if projection["target_state"] != "absent" or projection["sample_classes_state"] != "absent":
        raise CorpusError("Phase 4 must not install a modeling target or class authority")
    return projection


def _artifact_bytes(dataset: SherpaDataset) -> bytes:
    return (json.dumps(dataset.to_dict(include_extra=True), sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_private_artifact(path: Path, payload: bytes) -> dict[str, Any]:
    lexical = Path(os.path.abspath(path.expanduser()))
    resolved_parent = lexical.parent.resolve()
    path = resolved_parent / lexical.name
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        try:
            path.relative_to(PRIVATE_WORKTREE_ROOT)
        except ValueError as exc:
            raise CorpusError(
                f"private artifact {path} must be outside the repository or under {PRIVATE_WORKTREE_ROOT}"
            ) from exc
    if path.name != ARTIFACT_FILENAME or len(payload) > MAX_ARTIFACT_BYTES:
        raise CorpusError("canonical private artifact name or size is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise CorpusError("canonical private artifact target is linked or non-regular")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", prefix=f".{path.stem}.", dir=path.parent, delete=False) as temp:
            temporary_path = Path(temp.name)
            temp.write(payload)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
        os.chmod(path, 0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return _private_artifact_record(payload)


def _private_artifact_record(payload: bytes) -> dict[str, Any]:
    return {
        "filename": ARTIFACT_FILENAME,
        "size_bytes": len(payload),
        "sha256": _sha256_bytes(payload),
        "status": ARTIFACT_STATUS,
    }


def _read_private_artifact(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CorpusError("canonical private artifact is absent, linked, or unreadable") from exc
    with os.fdopen(descriptor, "rb") as source:
        source_stat = os.fstat(source.fileno())
        if not stat.S_ISREG(source_stat.st_mode) or not 0 < source_stat.st_size <= MAX_ARTIFACT_BYTES:
            raise CorpusError("canonical private artifact is non-regular, empty, or oversized")
        payload = source.read(MAX_ARTIFACT_BYTES + 1)
    if len(payload) != source_stat.st_size:
        raise CorpusError("canonical private artifact changed while being read")
    return payload


def _verify_private_artifact(path: Path, expected_payload: bytes) -> dict[str, Any]:
    """Read and verify an existing artifact without repairing or replacing it."""

    observed_payload = _read_private_artifact(path)
    if observed_payload != expected_payload:
        raise CorpusError("canonical private artifact bytes differ from the exact reconstructed dataset")
    return _private_artifact_record(observed_payload)


def load_private_dataset(path: Path) -> SherpaDataset:
    try:
        wire = json.loads(_read_private_artifact(path))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CorpusError("canonical private artifact JSON is invalid") from exc
    return SherpaDataset.from_dict(wire)


def _restart_projection(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "restart-project", "--artifact", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise CorpusError("fresh-process canonical dataset restart failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CorpusError("fresh-process canonical dataset projection is unreadable") from exc


def build_phase4_report(
    manifest_path: Path,
    qualification_path: Path,
    phase3_report_path: Path,
    curated_dir: Path,
    private_artifact_path: Path,
    *,
    publish_artifact: bool = True,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    qualification_bytes = qualification_path.read_bytes()
    phase3_bytes = phase3_report_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    qualification = json.loads(qualification_bytes)
    if validate_checked_phase3_evidence(phase3_report_path, manifest_path, qualification_path):
        raise CorpusError("Phase 4 requires the exact checked Phase-3 evidence")
    rows, matrix, axis = _load_exact_sources(manifest, qualification, curated_dir)
    dataset = build_canonical_dataset(rows, matrix, axis)
    projection = dataset_projection(dataset)
    artifact_payload = _artifact_bytes(dataset)
    artifact = (
        _write_private_artifact(private_artifact_path, artifact_payload)
        if publish_artifact
        else _verify_private_artifact(private_artifact_path, artifact_payload)
    )
    in_process = dataset_projection(load_private_dataset(private_artifact_path))
    restarted = _restart_projection(private_artifact_path)
    if projection != in_process or projection != restarted:
        raise CorpusError("canonical dataset differs after in-process or fresh-process restart")
    table = dataset.sample_axis.sample_table
    assert table is not None
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "dataset_version": manifest["dataset_version"],
        "status": STATUS,
        "source_manifest_sha256": _sha256_bytes(manifest_bytes),
        "source_parser_qualification_sha256": _sha256_bytes(qualification_bytes),
        "source_reproducibility_report_sha256": _sha256_bytes(phase3_bytes),
        "claim_boundary": CLAIM_BOUNDARY,
        "dataset": projection,
        "sample_table": {
            "columns": list(SAMPLE_TABLE_COLUMNS),
            "sha256": _json_sha256(table),
            "column_sha256": {column: _json_sha256(table[column]) for column in SAMPLE_TABLE_COLUMNS},
            "row_count": 33,
            "supplier_columns_present": False,
            "target_eligible_authenticity_field": None,
        },
        "private_artifact": artifact,
        "round_trip": {
            "in_process_reload_equal": True,
            "fresh_process_restart_equal": True,
            "projection_sha256": _json_sha256(projection),
            "reloaded_projection_sha256": _json_sha256(in_process),
            "restarted_projection_sha256": _json_sha256(restarted),
        },
    }
    failures = validate_phase4_evidence_links(report, manifest_bytes, qualification_bytes, phase3_bytes)
    if failures:
        raise CorpusError("Phase-4 evidence-link validation failed: " + "; ".join(failures))
    return report


def validate_phase4_evidence_links(
    report: Mapping[str, Any], manifest_bytes: bytes, qualification_bytes: bytes, phase3_bytes: bytes
) -> list[str]:
    failures: list[str] = []
    try:
        manifest = json.loads(manifest_bytes)
        phase3 = json.loads(phase3_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Phase-4 source manifest is unreadable: {type(exc).__name__}"]
    if set(report) != _ROOT_FIELDS or report.get("schema_version") != SCHEMA_VERSION:
        failures.append("Phase-4 root schema or version is invalid")
    if report.get("dataset_id") != DATASET_ID or report.get("dataset_version") != manifest.get("dataset_version"):
        failures.append("Phase-4 corpus identity is invalid")
    if report.get("status") != STATUS or report.get("claim_boundary") != CLAIM_BOUNDARY:
        failures.append("Phase-4 status or claim boundary is invalid")
    bindings = (
        ("source_manifest_sha256", manifest_bytes),
        ("source_parser_qualification_sha256", qualification_bytes),
        ("source_reproducibility_report_sha256", phase3_bytes),
    )
    for field, payload in bindings:
        if report.get(field) != _sha256_bytes(payload):
            failures.append(f"Phase-4 {field} binding differs")
    if report.get("source_reproducibility_report_sha256") != PHASE3_REPORT_SHA256:
        failures.append("Phase-4 source reproducibility report is not the reviewed authority")
    dataset = report.get("dataset")
    required_dataset_fields = {
        "type",
        "wire_version",
        "dataset_id",
        "shape",
        "dtype",
        "values_sha256",
        "feature_axis_sha256",
        "feature_axis_title",
        "feature_axis_units",
        "feature_axis_order",
        "sample_labels_sha256",
        "sample_table_sha256",
        "include_mask_sha256",
        "title",
        "units",
        "data_role",
        "domain",
        "target_state",
        "sample_classes_state",
    }
    if not isinstance(dataset, Mapping) or set(dataset) != required_dataset_fields:
        failures.append("Phase-4 dataset projection schema is invalid")
    elif (
        dataset.get("type") != "SherpaDataset"
        or dataset.get("wire_version") != "1.0"
        or dataset.get("dataset_id") != DATASET_IDENTITY
        or dataset.get("shape") != [33, 1868]
        or dataset.get("dtype") != "float64"
        or dataset.get("values_sha256") != phase3.get("matrix", {}).get("values_sha256")
        or dataset.get("feature_axis_sha256") != manifest["files"][0]["axis_sha256"]
        or dataset.get("feature_axis_title") != "Wavenumber"
        or dataset.get("feature_axis_units") != "cm-1"
        or dataset.get("feature_axis_order") != "strictly_descending"
        or dataset.get("title") != "Avatar essential-oil three-block corpus"
        or dataset.get("units") != "absorbance"
        or dataset.get("data_role") != "X_spectra"
        or dataset.get("domain")
        != {
            "technique": "IR",
            "sample_type": "essential oil",
            "measurement_mode": "ATR absorbance",
            "expected_units": "absorbance",
            "data_quantity": "absorbance",
            "instrument": "Thermo Nicolet Avatar 370",
        }
        or dataset.get("target_state") != "absent"
        or dataset.get("sample_classes_state") != "absent"
    ):
        failures.append("Phase-4 dataset projection differs from the canonical authority")
    sample_table = report.get("sample_table")
    if not isinstance(sample_table, Mapping) or set(sample_table) != {
        "columns",
        "sha256",
        "column_sha256",
        "row_count",
        "supplier_columns_present",
        "target_eligible_authenticity_field",
    }:
        failures.append("Phase-4 sample-table projection schema is invalid")
    else:
        ordered_rows = sorted(manifest["files"], key=lambda row: (int(row["block"]), int(row["acquisition_order"])))
        expected_table = _sample_table(ordered_rows)
        expected_column_hashes = {column: _json_sha256(expected_table[column]) for column in SAMPLE_TABLE_COLUMNS}
        table_invalid = (
            sample_table.get("columns") != list(SAMPLE_TABLE_COLUMNS)
            or sample_table.get("sha256") != _json_sha256(expected_table)
            or sample_table.get("column_sha256") != expected_column_hashes
            or dataset.get("sample_table_sha256") != _json_sha256(expected_table)
            or dataset.get("sample_labels_sha256") != _json_sha256(expected_table["sample_id"])
            or dataset.get("include_mask_sha256") != _json_sha256([True] * 33)
        )
        if (
            table_invalid
            or sample_table.get("row_count") != 33
            or sample_table.get("supplier_columns_present") is not False
            or sample_table.get("target_eligible_authenticity_field") is not None
            or set(sample_table.get("column_sha256", {})) != set(SAMPLE_TABLE_COLUMNS)
        ):
            failures.append("Phase-4 sample-table authority is incomplete or overstated")
    artifact = report.get("private_artifact")
    if not isinstance(artifact, Mapping) or set(artifact) != {"filename", "size_bytes", "sha256", "status"}:
        failures.append("Phase-4 private artifact record schema is invalid")
    elif (
        artifact.get("filename") != ARTIFACT_FILENAME
        or artifact.get("status") != ARTIFACT_STATUS
        or not isinstance(artifact.get("size_bytes"), int)
        or not 0 < artifact.get("size_bytes") <= MAX_ARTIFACT_BYTES
        or not isinstance(artifact.get("sha256"), str)
        or len(artifact.get("sha256")) != 64
    ):
        failures.append("Phase-4 private artifact record is invalid or overstated")
    round_trip = report.get("round_trip")
    if not isinstance(round_trip, Mapping) or set(round_trip) != {
        "in_process_reload_equal",
        "fresh_process_restart_equal",
        "projection_sha256",
        "reloaded_projection_sha256",
        "restarted_projection_sha256",
    }:
        failures.append("Phase-4 round-trip schema is invalid")
    elif (
        round_trip.get("in_process_reload_equal") is not True
        or round_trip.get("fresh_process_restart_equal") is not True
        or len(
            {
                round_trip.get("projection_sha256"),
                round_trip.get("reloaded_projection_sha256"),
                round_trip.get("restarted_projection_sha256"),
            }
        )
        != 1
    ):
        failures.append("Phase-4 round-trip equality is not exact")
    serialized = json.dumps(report, sort_keys=True, ensure_ascii=False)
    if (
        "/Users/" in serialized
        or "private-input" in serialized
        or "EO_Lavender_" in serialized
        or "supplier_name" in serialized
    ):
        failures.append("Phase-4 public evidence contains a private path or supplier field")
    return failures


def validate_checked_phase4_evidence(
    report_path: Path, manifest_path: Path, qualification_path: Path, phase3_report_path: Path
) -> list[str]:
    """Validate the immutable public Phase-4 report without the private artifact."""

    try:
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        manifest_bytes = manifest_path.read_bytes()
        qualification_bytes = qualification_path.read_bytes()
        phase3_bytes = phase3_report_path.read_bytes()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"checked Phase-4 evidence is unreadable: {type(exc).__name__}"]
    if _sha256_bytes(report_bytes) != CHECKED_REPORT_SHA256:
        return ["checked Phase-4 report digest differs from the exact reviewed authority"]
    return validate_phase4_evidence_links(report, manifest_bytes, qualification_bytes, phase3_bytes)


def validate_phase4_report(
    report: Mapping[str, Any],
    manifest_path: Path,
    qualification_path: Path,
    phase3_report_path: Path,
    curated_dir: Path,
    private_artifact_path: Path,
) -> list[str]:
    try:
        expected = build_phase4_report(
            manifest_path,
            qualification_path,
            phase3_report_path,
            curated_dir,
            private_artifact_path,
            publish_artifact=False,
        )
    except (CorpusError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        return [f"Phase-4 source re-admission failed: {type(exc).__name__}: {exc}"]
    return [] if dict(report) == expected else ["Phase-4 report differs from the exact restarted canonical dataset"]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--manifest", type=Path, required=True)
        subparser.add_argument("--qualification", type=Path, required=True)
        subparser.add_argument("--phase3-report", type=Path, required=True)
        subparser.add_argument("--curated-dir", type=Path, required=True)
        subparser.add_argument("--private-artifact", type=Path, required=True)
        if command == "build":
            subparser.add_argument("--output", type=Path, required=True)
        else:
            subparser.add_argument("--report", type=Path, required=True)
    restart = subparsers.add_parser("restart-project")
    restart.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "restart-project":
        print(json.dumps(dataset_projection(load_private_dataset(arguments.artifact)), sort_keys=True))
        return 0
    if arguments.command == "build":
        report = build_phase4_report(
            arguments.manifest,
            arguments.qualification,
            arguments.phase3_report,
            arguments.curated_dir,
            arguments.private_artifact,
        )
        _write_json(arguments.output, report)
    else:
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        failures = validate_phase4_report(
            report,
            arguments.manifest,
            arguments.qualification,
            arguments.phase3_report,
            arguments.curated_dir,
            arguments.private_artifact,
        )
        if failures:
            raise CorpusError("; ".join(failures))
        print("Avatar OMNIC Phase 4 canonical SherpaDataset: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
