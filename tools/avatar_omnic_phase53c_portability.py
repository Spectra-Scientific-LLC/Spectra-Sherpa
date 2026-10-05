#!/usr/bin/env python3
"""Execute and validate the private Avatar save/restart/import qualification.

The ``run`` command orchestrates two fresh application processes.  Workspace A
must already contain the attached 33-source collection.  Workspace B must not
exist; it is created as a genuinely new application-data root.  Raw sources,
the project archive, and the detailed execution transcript remain private.
Only a bounded path-free summary is suitable for ``docs/evidence``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from spectra_sherpa.core.file_io import open_regular_readonly

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-portability/1"
RETIREMENT_SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-legacy-sidecar-retirement/1"
RUNTIME_IMPLEMENTATION_COMMIT = "9af2ebb7353a2f38a14c57ad06c1840c084dd682"
EXPECTED_SHAPE = [33, 1868]
EXPECTED_VALUES_SHA256 = "66f6f64a08cb0a875ba654f7e9e66949a698c435292cf3fb8cd4c7ae784e2b76"
EXPECTED_AXIS_SHA256 = "f0fb31d4690ff770f518574e19353ee4b2bb6d46f43abdbd90a18aef6293ed6b"
EXPECTED_TABLE_SHA256 = "1b13a7b34c0d9034bc06f397d9fb1bce1b3aa00491f7a50446a8769c483a5d38"
EXPECTED_DEFINITION_SHA256 = "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"
EXPECTED_SOURCE_SHA256 = "199a9b04f7abacdc0ab73eef70fec44133abcd041f87c7e1855af3b753e8fcd8"
EXPECTED_DATASET_ID = "avatar-essential-oils/1:canonical-phase4"
EXPECTED_TITLE = "Avatar essential-oil three-block corpus"
EXPECTED_COLUMNS = 14
EMPTY_PREPARED_DATA_SHA256 = hashlib.sha256(b"{}").hexdigest()
MAX_PRIVATE_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 200 * 1024 * 1024
CHECKED_REPORT_SHA256 = "49d827216609b7fa8ce4840b92cc34549b901fceea30b1d250affcf74fc04f66"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_sha256(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _array_sha256(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype="<f8"))
    return _sha256_bytes(array.tobytes(order="C"))


def _wire_projection(wire: dict[str, Any]) -> dict[str, Any]:
    x_axis = wire.get("x_axis")
    y_axis = wire.get("y_axis")
    metadata = wire.get("metadata")
    if not isinstance(x_axis, dict) or not isinstance(y_axis, dict) or not isinstance(metadata, dict):
        raise ValueError("Builder response lacks its typed axes or metadata")
    labels = y_axis.get("labels")
    table = y_axis.get("sample_table")
    include_mask = y_axis.get("include_mask")
    source = metadata.get("source_collection")
    if not isinstance(labels, list) or not isinstance(table, dict) or not isinstance(source, dict):
        raise ValueError("Builder response lacks its sample or collection authority")
    projection = {
        "shape": list(np.asarray(wire.get("data"), dtype=np.float64).shape),
        "values_sha256": _array_sha256(wire.get("data")),
        "feature_axis_sha256": _array_sha256(x_axis.get("data")),
        "sample_labels_sha256": _json_sha256(labels),
        "sample_table_sha256": _json_sha256(table),
        "include_mask_sha256": _json_sha256(include_mask),
        "sample_count": len(labels),
        "sample_table_column_count": len(table),
        "dataset_id": wire.get("dataset_id"),
        "title": wire.get("title"),
        "units": wire.get("units"),
        "data_role": wire.get("data_role"),
        "domain": wire.get("domain"),
        "target_state": "absent" if wire.get("target") is None else "present",
        "source_manifest_sha256": source.get("source_manifest_sha256"),
        "collection_definition_sha256": source.get("collection_definition_sha256"),
        "scientific_dataset_projection_sha256": source.get("scientific_dataset_projection_sha256"),
        "scientific_collection_sha256": source.get("scientific_collection_sha256"),
    }
    expected = {
        "shape": EXPECTED_SHAPE,
        "values_sha256": EXPECTED_VALUES_SHA256,
        "feature_axis_sha256": EXPECTED_AXIS_SHA256,
        "sample_table_sha256": EXPECTED_TABLE_SHA256,
        "sample_count": EXPECTED_SHAPE[0],
        "sample_table_column_count": EXPECTED_COLUMNS,
        "dataset_id": EXPECTED_DATASET_ID,
        "title": EXPECTED_TITLE,
        "target_state": "absent",
        "source_manifest_sha256": EXPECTED_SOURCE_SHA256,
        "collection_definition_sha256": EXPECTED_DEFINITION_SHA256,
    }
    mismatches = [name for name, value in expected.items() if projection.get(name) != value]
    if mismatches:
        raise ValueError(f"Builder projection differs in: {', '.join(mismatches)}")
    return projection


def _expected_checked_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase5_save_restart_new_workspace_portability_complete_author_operated",
        "observed_at": "2026-08-24",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "observation_authority": "author_operated_two_fresh_local_oss_application_processes",
        "process_and_workspace_boundary": {
            "workspace_a_fresh_restart": True,
            "workspace_b_was_absent_before_run": True,
            "workspace_b_new_database": True,
            "old_dataset_handle_used": False,
        },
        "save_export_import": {
            "saved_snapshot_archive_version": "0.4",
            "saved_version_number": 1,
            "private_archive_size_bytes": 291003,
            "private_archive_sha256": "6f781e0d44bcdc76a364e012dec5342a0c48d686b4307e8d10cc7d8e1406089f",
            "restored_source_count": 33,
            "imported_version_count": 1,
            "new_workspace_reexport_succeeded": True,
            "private_reexport_size_bytes": 291003,
            "private_reexport_sha256": "14b0f2dc3f4a5bc32648c69cdb43871b517634762fde4e5e49bdcec107362906",
        },
        "scientific_projection": {
            "shape": EXPECTED_SHAPE,
            "values_sha256": EXPECTED_VALUES_SHA256,
            "feature_axis_sha256": EXPECTED_AXIS_SHA256,
            "sample_labels_sha256": "46a8bf29309c9756b6852a1391d3ab7a76e0c5ac94a87179a90a5090cd9f1573",
            "sample_table_sha256": EXPECTED_TABLE_SHA256,
            "include_mask_sha256": "3e7d58c9396df0f0d6ae8b8d5fb80647e3bd74ca9217c9bf981070ff56deafac",
            "sample_count": 33,
            "sample_table_column_count": EXPECTED_COLUMNS,
            "dataset_id": EXPECTED_DATASET_ID,
            "title": EXPECTED_TITLE,
            "units": "absorbance",
            "data_role": "X_spectra",
            "domain": {
                "technique": "IR",
                "sample_type": "essential oil",
                "measurement_mode": "ATR absorbance",
                "expected_units": "absorbance",
                "data_quantity": "absorbance",
                "instrument": "Thermo Nicolet Avatar 370",
            },
            "target_state": "absent",
            "source_manifest_sha256": EXPECTED_SOURCE_SHA256,
            "collection_definition_sha256": EXPECTED_DEFINITION_SHA256,
            "scientific_dataset_projection_sha256": (
                "c37334d8227184daa8644453ce1b046679ad5d0f7367d650cdded4dcb86f4cce"
            ),
            "scientific_collection_sha256": "144889847a230ed56ee28e532f790e7dc15883a19328c2cfcc3eb84e1b08e243",
        },
        "identity_preservation": {
            "workspace_a_equals_workspace_b": True,
            "matrix_exact": True,
            "feature_axis_exact": True,
            "sample_labels_and_table_exact": True,
            "source_definition_and_combined_identity_exact": True,
            "target_absent": True,
        },
        "legacy_sidecar_retirement": {
            "status": "exact_duplicate_authority_retired_private",
            "receipt_sha256": "3a73deabcc9c55a509abaca8739d17501bb8c008f10e2885a959a37d5b757bff",
            "sidecar_count": 33,
            "definition_sha256": EXPECTED_DEFINITION_SHA256,
            "source_manifest_sha256": EXPECTED_SOURCE_SHA256,
            "exact_definition_equivalence": True,
            "exact_source_binding": True,
            "raw_source_bytes_changed": False,
            "live_duplicate_authority_absent": True,
        },
        "privacy_boundary": {
            "raw_source_bytes_published": False,
            "project_archive_published": False,
            "private_transcript_published": False,
            "private_paths_or_database_ids_recorded": False,
            "credentials_or_user_identifiers_recorded": False,
        },
        "claim_boundary": (
            "Author-operated exact save, fresh-process restart, private project export, new-workspace import, "
            "dataset rerun, and re-export for this 33-spectrum corpus only."
        ),
        "nonclaims": [
            "non_author_physical_action_2",
            "pca_or_plsda_result",
            "botanical_authenticity_or_population_result",
            "redistribution_permission",
            "public_corpus_or_project_package",
        ],
    }


def validate_checked_report(report_path: Path) -> list[str]:
    failures: list[str] = []
    payload = report_path.read_bytes()
    if _sha256_bytes(payload) != CHECKED_REPORT_SHA256:
        failures.append("checked portability report digest differs from the reviewed authority")
    try:
        report = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        failures.append("checked portability report is not valid JSON")
        return failures
    if report != _expected_checked_report():
        failures.append("checked portability report differs from its closed reviewed projection")
    text = payload.decode("utf-8", errors="replace")
    forbidden = (
        "private-input",
        "/Users/",
        '"project_id":',
        '"experiment_id":',
        '"user_id":',
        '"database_id":',
    )
    if any(marker in text for marker in forbidden):
        failures.append("checked portability report contains a private path or database identity field")
    return failures


def _check_public(args: argparse.Namespace) -> int:
    failures = validate_checked_report(args.report)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Avatar OMNIC Phase 5.3c checked portability report: PASS")
    return 0


def _require_response(response, expected_status: int, label: str) -> Any:
    if response.status_code != expected_status:
        raise RuntimeError(f"{label} failed with HTTP {response.status_code}: {response.text[:500]}")
    return response


def _require_saved_snapshot(snapshot: dict[str, Any], projection: dict[str, Any]) -> None:
    stored_experiments = [
        value for value in snapshot.get("experiments", []) if value.get("file_count") == EXPECTED_SHAPE[0]
    ]
    if len(stored_experiments) != 1:
        raise RuntimeError("saved snapshot does not contain one exact 33-source experiment")
    stored = stored_experiments[0]
    if (
        stored.get("storage_snapshot_schema_version") != "spectrasherpa-project-storage-snapshot/1"
        or stored.get("collection_definition_sha256") != projection["collection_definition_sha256"]
        or stored.get("collection_source_manifest_sha256") != projection["source_manifest_sha256"]
        or stored.get("scientific_dataset_projection_sha256") != projection["scientific_dataset_projection_sha256"]
        or stored.get("scientific_collection_sha256") != projection["scientific_collection_sha256"]
    ):
        raise RuntimeError("saved snapshot is not cross-bound to the exact scientific collection")


def _write_private_bytes(path: Path, payload: bytes, *, max_bytes: int) -> dict[str, Any]:
    if not 0 < len(payload) <= max_bytes:
        raise ValueError("private output is empty or exceeds its bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"size_bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _write_private_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_private_bytes(path, payload, max_bytes=2 * 1024 * 1024)


def _read_private_bytes(path: Path, *, max_bytes: int) -> bytes:
    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise ValueError("private input is absent, linked, or unreadable") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or not 0 < observed.st_size <= max_bytes:
            raise ValueError("private input is non-regular, empty, or oversized")
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("private input changed while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("private input changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _regular_file_identity(path: Path, *, max_bytes: int) -> dict[str, Any]:
    """Return a bounded no-follow size/digest identity without materializing bytes."""

    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise ValueError("source is absent, linked, or unreadable") from exc
    digest = hashlib.sha256()
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or not 0 < observed.st_size <= max_bytes:
            raise ValueError("source is non-regular, empty, or oversized")
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("source changed while being hashed")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("source changed while being hashed")
        return {"size_bytes": observed.st_size, "sha256": digest.hexdigest()}
    finally:
        os.close(descriptor)


def _require_exact_private_directory(path: Path, *, parent: Path) -> None:
    """Require one exact lexical child directory without following its leaf."""

    if path.parent != parent:
        raise ValueError("private directory is outside its exact authority root")
    try:
        observed = path.lstat()
    except OSError as exc:
        raise ValueError("private directory is absent or unreadable") from exc
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISDIR(observed.st_mode)
        or (os.name != "nt" and stat.S_IMODE(observed.st_mode) & 0o077)
    ):
        raise ValueError("private directory is linked or non-directory")


def _canonical_definition_file_name(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("collection definition contains an invalid source file name")
    portable = PurePosixPath(value)
    if (
        portable.is_absolute()
        or portable.as_posix() != value
        or any(part in {"", ".", ".."} for part in portable.parts)
    ):
        raise ValueError("collection definition contains a non-canonical source file name")
    if len(portable.parts) != 2 or portable.parts[0] != "raw":
        raise ValueError("collection definition source is outside the exact raw collection")
    return value


def _source_manifest(entries: list[dict[str, Any]]) -> dict[str, Any]:
    identity = {"schema_version": "spectrasherpa-source-collection/1", "files": entries}
    return {
        **identity,
        "file_count": len(entries),
        "manifest_digest": _sha256_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")),
    }


def _sidecar_filename_for_source(*, experiment_id: int, file_name: str) -> str:
    relative_source = f"experiments/exp_{experiment_id:03d}/{file_name}"
    digest = hashlib.sha256(f"file\x1f{relative_source}".encode("utf-8")).hexdigest()
    return f"file__{digest}.json"


def _admit_legacy_sidecar_inventory(
    *,
    workspace: Path,
    experiment_id: int,
    definition_payload: bytes,
    sidecar_root: Path,
    expected_definition_sha256: str,
    expected_source_sha256: str,
    control_names: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Cross-bind exact source rows, canonical sidecar names, and duplicate values."""

    definition_sha256 = _sha256_bytes(definition_payload)
    if definition_sha256 != expected_definition_sha256:
        raise ValueError("collection definition differs from its exact authority")
    try:
        definition = json.loads(definition_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("collection definition is not valid JSON") from exc
    rows = definition.get("rows") if isinstance(definition, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("collection definition contains no source rows")

    workspace = workspace.resolve()
    _require_exact_private_directory(sidecar_root, parent=workspace)
    all_names = {child.name for child in sidecar_root.iterdir()}
    if not control_names.issubset(all_names):
        raise ValueError("legacy sidecar inventory lacks its exact control record")
    actual_names = all_names - control_names
    source_entries: list[dict[str, Any]] = []
    expected_sidecars: dict[str, dict[str, Any]] = {}
    sample_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("annotations"), dict):
            raise ValueError("collection definition row is invalid")
        file_name = _canonical_definition_file_name(row.get("file_name"))
        source_sha256 = row.get("sha256")
        sample_id = row.get("sample_id")
        annotations = row["annotations"]
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
            or row.get("asset_id") != "spectrum"
            or not isinstance(row.get("source_row_index"), int)
            or isinstance(row.get("source_row_index"), bool)
            or row.get("source_row_index") != 0
            or not isinstance(sample_id, str)
            or not sample_id
            or sample_id in sample_ids
            or annotations.get("sample_id") != sample_id
        ):
            raise ValueError("collection definition source identity is invalid")
        sample_ids.add(sample_id)
        source_path = workspace / "experiments" / f"exp_{experiment_id:03d}" / file_name
        identity = _regular_file_identity(source_path, max_bytes=MAX_SOURCE_BYTES)
        if identity["sha256"] != source_sha256:
            raise ValueError("stored source differs from the collection definition")
        source_entries.append(
            {
                "file_name": file_name,
                "size_bytes": identity["size_bytes"],
                "sha256": source_sha256,
                "prepared_data_sha256": EMPTY_PREPARED_DATA_SHA256,
            }
        )
        sidecar_name = _sidecar_filename_for_source(experiment_id=experiment_id, file_name=file_name)
        if sidecar_name in expected_sidecars:
            raise ValueError("collection definition maps more than one row to a sidecar")
        expected_sidecars[sidecar_name] = {
            "file_name": file_name,
            "source_sha256": source_sha256,
            "asset_id": "spectrum",
            "source_row_index": 0,
            "sample_id": sample_id,
            "annotations": annotations,
        }

    manifest = _source_manifest(source_entries)
    if manifest["manifest_digest"] != expected_source_sha256:
        raise ValueError("stored source inventory differs from its exact manifest authority")
    if actual_names != set(expected_sidecars):
        raise ValueError("legacy sidecar inventory does not match the exact source-derived names")

    records: list[dict[str, Any]] = []
    for sidecar_name in sorted(expected_sidecars):
        authority = expected_sidecars[sidecar_name]
        source = sidecar_root / sidecar_name
        payload = _read_private_bytes(source, max_bytes=64 * 1024)
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("legacy sidecar is not valid JSON") from exc
        if not isinstance(value, dict) or set(value) != {"sample_labels", "sample_table"}:
            raise ValueError("legacy sidecar contains state beyond the duplicate sample authority")
        if value["sample_labels"] != [authority["sample_id"]] or not isinstance(value["sample_table"], dict):
            raise ValueError("legacy sidecar sample identity is invalid")
        annotations = authority["annotations"]
        if set(value["sample_table"]) != set(annotations) or any(
            value["sample_table"][name] != [cell] for name, cell in annotations.items()
        ):
            raise ValueError("legacy sidecar differs from the attached collection definition")
        records.append(
            {
                "sidecar_filename": sidecar_name,
                "sidecar_sha256": _sha256_bytes(payload),
                "file_name": authority["file_name"],
                "source_sha256": authority["source_sha256"],
                "asset_id": authority["asset_id"],
                "source_row_index": authority["source_row_index"],
                "sample_id": authority["sample_id"],
            }
        )
    return {
        "schema_version": RETIREMENT_SCHEMA_VERSION,
        "status": "retired_duplicate_sample_authority_after_exact_source_and_definition_equivalence",
        "definition_sha256": definition_sha256,
        "source_manifest_sha256": manifest["manifest_digest"],
        "source_count": len(source_entries),
        "sidecar_count": len(records),
        "exact_source_binding": True,
        "exact_definition_equivalence": True,
        "raw_source_bytes_changed": False,
        "sidecars": records,
    }


def _require_live_duplicate_authority_absent(*, workspace: Path, receipt: dict[str, Any]) -> None:
    """Prove the exact retired sidecar identities are absent from the live root."""

    live_root = workspace / ".metadata_overrides"
    try:
        observed = live_root.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError("live prepared-data root is unreadable") from exc
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISDIR(observed.st_mode)
        or (os.name != "nt" and stat.S_IMODE(observed.st_mode) & 0o077)
    ):
        raise ValueError("live prepared-data root is linked, non-directory, or not private")
    records = receipt.get("sidecars")
    if not isinstance(records, list) or not records:
        raise ValueError("retirement receipt lacks its exact sidecar inventory")
    for record in records:
        name = record.get("sidecar_filename") if isinstance(record, dict) else None
        if not isinstance(name, str) or not name.startswith("file__") or "/" in name or "\\" in name:
            raise ValueError("retirement receipt contains an invalid sidecar filename")
        try:
            (live_root / name).lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("live prepared-data authority is unreadable") from exc
        raise ValueError("an exact retired sidecar remains in the live prepared-data authority")


def _client():
    from starlette.testclient import TestClient

    from spectra_sherpa.app.main import app

    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53053))


def _require_empty_handle_registry() -> None:
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    if dataset_registry.retained_bytes != 0:
        raise RuntimeError("fresh application process unexpectedly retained a dataset handle")


def _stage_a(args: argparse.Namespace) -> int:
    archive_path = args.archive.resolve()
    change_description = "Phase 5.3c exact restart and portability qualification"
    with _client() as client:
        _require_empty_handle_registry()
        receipt = _require_response(
            client.get(f"/api/v1/experiments/{args.experiment_id}/collection-definition"),
            200,
            "collection-definition receipt",
        ).json()
        if receipt.get("status") != "attached" or receipt.get("definition_sha256") != EXPECTED_DEFINITION_SHA256:
            raise RuntimeError("workspace A collection definition is not attached and exact")
        wire = _require_response(
            client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": args.experiment_id, "asset_id": "spectrum"},
            ),
            200,
            "workspace A dataset reload",
        ).json()
        projection = _wire_projection(wire)
        if (
            receipt.get("source_manifest_sha256") != projection["source_manifest_sha256"]
            or receipt.get("scientific_collection_sha256") != projection["scientific_collection_sha256"]
        ):
            raise RuntimeError("workspace A definition receipt is not cross-bound to the rerun dataset")
        versions = _require_response(
            client.get(f"/api/v1/projects/{args.project_id}/versions"), 200, "workspace A version list"
        ).json()
        exact_versions = [
            value for value in versions.get("versions", []) if value.get("change_description") == change_description
        ]
        if exact_versions:
            if len(exact_versions) != 1:
                raise RuntimeError("workspace A contains duplicate qualification versions")
            saved = exact_versions[0]
        else:
            saved = _require_response(
                client.post(
                    f"/api/v1/projects/{args.project_id}/save",
                    json={"change_description": change_description, "include_raw_data": True},
                ),
                201,
                "workspace A save",
            ).json()
        version = _require_response(
            client.get(f"/api/v1/projects/{args.project_id}/versions/{saved['id']}"),
            200,
            "saved version reload",
        ).json()
        snapshot = version.get("snapshot") or {}
        _require_saved_snapshot(snapshot, projection)
        exported = _require_response(
            client.get(f"/api/v1/projects/{args.project_id}/export/sherpa?version_id={saved['id']}"),
            200,
            "saved-version export",
        )
        with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
            exported_project = json.loads(archive.read("project.json"))
        if (exported_project.get("archive_format") or {}).get("version") != "0.4":
            raise RuntimeError("workspace A export is not current archive schema /0.4")
    archive = _write_private_bytes(archive_path, exported.content, max_bytes=MAX_PRIVATE_ARCHIVE_BYTES)
    _write_private_json(
        args.result,
        {
            "stage": "workspace_a_fresh_process",
            "old_dataset_handle_used": False,
            "definition_receipt": receipt,
            "projection": projection,
            "saved_version_number": saved["version_number"],
            "saved_snapshot_archive_version": "0.4",
            "private_archive": archive,
        },
    )
    return 0


def _stage_b(args: argparse.Namespace) -> int:
    archive_path = args.archive.resolve()
    archive_bytes = _read_private_bytes(archive_path, max_bytes=MAX_PRIVATE_ARCHIVE_BYTES)
    with _client() as client:
        _require_empty_handle_registry()
        imported = _require_response(
            client.post(
                "/api/v1/projects/import",
                files={"file": ("avatar-phase53c.sherpa", archive_bytes, "application/zip")},
            ),
            201,
            "new-workspace import",
        ).json()
        experiments = imported.get("experiments") or []
        candidates = [item for item in experiments if item.get("file_count") == EXPECTED_SHAPE[0]]
        if len(candidates) != 1:
            raise RuntimeError("import did not restore one exact 33-source experiment")
        experiment_id = candidates[0]["id"]
        receipt = _require_response(
            client.get(f"/api/v1/experiments/{experiment_id}/collection-definition"),
            200,
            "imported definition receipt",
        ).json()
        wire = _require_response(
            client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": experiment_id, "asset_id": "spectrum"},
            ),
            200,
            "imported dataset rerun",
        ).json()
        projection = _wire_projection(wire)
        if (
            receipt.get("status") != "attached"
            or receipt.get("definition_sha256") != projection["collection_definition_sha256"]
            or receipt.get("source_manifest_sha256") != projection["source_manifest_sha256"]
            or receipt.get("scientific_collection_sha256") != projection["scientific_collection_sha256"]
        ):
            raise RuntimeError("imported definition receipt is not cross-bound to the rerun dataset")
        versions = _require_response(
            client.get(f"/api/v1/projects/{imported['id']}/versions"), 200, "imported version list"
        ).json()
        if versions.get("total") != 1:
            raise RuntimeError("import did not create exactly one durable initial version")
        version_id = versions["versions"][0]["id"]
        imported_version = _require_response(
            client.get(f"/api/v1/projects/{imported['id']}/versions/{version_id}"),
            200,
            "imported version reload",
        ).json()
        _require_saved_snapshot(imported_version.get("snapshot") or {}, projection)
        reexported = _require_response(
            client.get(f"/api/v1/projects/{imported['id']}/export/sherpa?version_id={version_id}"),
            200,
            "new-workspace re-export",
        )
    reexport = _write_private_bytes(args.reexport.resolve(), reexported.content, max_bytes=MAX_PRIVATE_ARCHIVE_BYTES)
    _write_private_json(
        args.result,
        {
            "stage": "workspace_b_new_database_fresh_process",
            "old_dataset_handle_used": False,
            "restored_source_count": EXPECTED_SHAPE[0],
            "definition_receipt": receipt,
            "projection": projection,
            "imported_version_count": versions["total"],
            "private_reexport": reexport,
        },
    )
    return 0


def _subprocess_env(workspace: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATA_DIR": str(workspace),
            "DATABASE_URL": f"sqlite+aiosqlite:///{workspace / 'spectra_platform.db'}",
            "APP_MODE": "local",
            "MPLCONFIGDIR": str(workspace / ".matplotlib"),
        }
    )
    return env


def _retire_legacy_sidecars(args: argparse.Namespace) -> int:
    """Retire the pre-definition duplicate sample-table sidecars exactly once."""

    workspace = args.workspace.resolve()
    definition_payload = _read_private_bytes(args.definition.resolve(), max_bytes=2 * 1024 * 1024)
    sidecar_root = workspace / ".metadata_overrides"
    receipt = _admit_legacy_sidecar_inventory(
        workspace=workspace,
        experiment_id=args.experiment_id,
        definition_payload=definition_payload,
        sidecar_root=sidecar_root,
        expected_definition_sha256=EXPECTED_DEFINITION_SHA256,
        expected_source_sha256=EXPECTED_SOURCE_SHA256,
    )
    if receipt["sidecar_count"] != EXPECTED_SHAPE[0]:
        raise ValueError("legacy sidecar inventory is not exactly 33 files")

    retired = workspace / "retired-phase5-legacy-sample-sidecars"
    if retired.exists():
        raise ValueError("legacy sidecars were already retired")
    retired.mkdir(mode=0o700)
    for record in receipt["sidecars"]:
        source = sidecar_root / record["sidecar_filename"]
        destination = retired / record["sidecar_filename"]
        os.replace(source, destination)
        os.chmod(destination, 0o600)
    _require_live_duplicate_authority_absent(workspace=workspace, receipt=receipt)
    receipt["live_duplicate_authority_absent"] = True
    _write_private_json(retired / "retirement.json", receipt)
    print("Avatar legacy duplicate sidecars: RETIRED (33 exact definition matches)")
    return 0


def _verify_retired_sidecars(args: argparse.Namespace) -> int:
    """Re-admit an already-retired inventory and publish its source-bound receipt."""

    workspace = args.workspace.resolve()
    definition_payload = _read_private_bytes(args.definition.resolve(), max_bytes=2 * 1024 * 1024)
    retired = workspace / "retired-phase5-legacy-sample-sidecars"
    receipt = _admit_legacy_sidecar_inventory(
        workspace=workspace,
        experiment_id=args.experiment_id,
        definition_payload=definition_payload,
        sidecar_root=retired,
        expected_definition_sha256=EXPECTED_DEFINITION_SHA256,
        expected_source_sha256=EXPECTED_SOURCE_SHA256,
        control_names=frozenset({"retirement.json"}),
    )
    if receipt["sidecar_count"] != EXPECTED_SHAPE[0]:
        raise ValueError("retired sidecar inventory is not exactly 33 files")
    _require_live_duplicate_authority_absent(workspace=workspace, receipt=receipt)
    receipt["live_duplicate_authority_absent"] = True
    _write_private_json(args.receipt.resolve(), receipt)
    print("Avatar retired legacy sidecars: VERIFIED (33 exact source bindings)")
    return 0


def _require_retirement_receipt(
    *,
    workspace: Path,
    experiment_id: int,
    definition_path: Path,
    receipt_path: Path,
    expected_definition_sha256: str = EXPECTED_DEFINITION_SHA256,
    expected_source_sha256: str = EXPECTED_SOURCE_SHA256,
) -> tuple[dict[str, Any], str]:
    workspace = workspace.resolve()
    receipt_path = Path(os.path.abspath(receipt_path))
    if receipt_path.parent != workspace:
        raise ValueError("retirement receipt is outside the exact private workspace")
    try:
        receipt_stat = receipt_path.lstat()
    except OSError as exc:
        raise ValueError("retirement receipt is absent, linked, or unreadable") from exc
    if (
        stat.S_ISLNK(receipt_stat.st_mode)
        or not stat.S_ISREG(receipt_stat.st_mode)
        or (os.name != "nt" and stat.S_IMODE(receipt_stat.st_mode) != 0o600)
    ):
        raise ValueError("retirement receipt is linked, non-regular, or not private")
    definition_payload = _read_private_bytes(definition_path, max_bytes=2 * 1024 * 1024)
    receipt_payload = _read_private_bytes(receipt_path, max_bytes=2 * 1024 * 1024)
    try:
        receipt = json.loads(receipt_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("retirement receipt is not valid JSON") from exc
    retired = workspace / "retired-phase5-legacy-sample-sidecars"
    observed = _admit_legacy_sidecar_inventory(
        workspace=workspace,
        experiment_id=experiment_id,
        definition_payload=definition_payload,
        sidecar_root=retired,
        expected_definition_sha256=expected_definition_sha256,
        expected_source_sha256=expected_source_sha256,
        control_names=frozenset({"retirement.json"}),
    )
    _require_live_duplicate_authority_absent(workspace=workspace, receipt=observed)
    observed["live_duplicate_authority_absent"] = True
    if receipt != observed:
        raise ValueError("retirement receipt differs from the re-admitted source-bound inventory")
    return receipt, _sha256_bytes(receipt_payload)


def _run_stage(arguments: list[str], *, workspace: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *arguments],
        env=_subprocess_env(workspace),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"fresh-process stage failed: {completed.stderr[-2000:]}{completed.stdout[-2000:]}")


def _run(args: argparse.Namespace) -> int:
    workspace_a = args.workspace_a.resolve()
    workspace_b = args.workspace_b.resolve()
    if not (workspace_a / "spectra_platform.db").is_file():
        raise ValueError("workspace A database is absent")
    if workspace_b.exists():
        raise ValueError("workspace B must not exist before qualification")
    retirement, retirement_sha256 = _require_retirement_receipt(
        workspace=workspace_a,
        experiment_id=args.experiment_id,
        definition_path=args.definition.resolve(),
        receipt_path=args.retirement_receipt,
    )
    archive = args.archive.resolve()
    private_report = args.private_report.resolve()
    public_report = args.public_report.resolve()
    run_stem = private_report.stem
    stage_a_result = workspace_a / f"{run_stem}-stage-a.json"
    workspace_b.mkdir(parents=True, mode=0o700)
    stage_b_result = workspace_b / f"{run_stem}-stage-b.json"
    reexport = workspace_b / f"{run_stem}-reexport.sherpa"
    _run_stage(
        [
            "stage-a",
            "--project-id",
            str(args.project_id),
            "--experiment-id",
            str(args.experiment_id),
            "--archive",
            str(archive),
            "--result",
            str(stage_a_result),
        ],
        workspace=workspace_a,
    )
    _run_stage(
        ["stage-b", "--archive", str(archive), "--reexport", str(reexport), "--result", str(stage_b_result)],
        workspace=workspace_b,
    )
    stage_a = json.loads(stage_a_result.read_bytes())
    stage_b = json.loads(stage_b_result.read_bytes())
    if stage_a["projection"] != stage_b["projection"]:
        raise ValueError("workspace A and B scientific projections differ")
    scientific = stage_a["projection"]
    private = {
        "schema_version": SCHEMA_VERSION,
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "workspace_a": stage_a,
        "workspace_b": stage_b,
        "legacy_sidecar_retirement": {"receipt_sha256": retirement_sha256, "receipt": retirement},
    }
    _write_private_json(private_report, private)
    public = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase5_save_restart_new_workspace_portability_complete_author_operated",
        "observed_at": "2026-08-24",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "observation_authority": "author_operated_two_fresh_local_oss_application_processes",
        "process_and_workspace_boundary": {
            "workspace_a_fresh_restart": True,
            "workspace_b_was_absent_before_run": True,
            "workspace_b_new_database": True,
            "old_dataset_handle_used": False,
        },
        "save_export_import": {
            "saved_snapshot_archive_version": stage_a["saved_snapshot_archive_version"],
            "saved_version_number": stage_a["saved_version_number"],
            "private_archive_size_bytes": stage_a["private_archive"]["size_bytes"],
            "private_archive_sha256": stage_a["private_archive"]["sha256"],
            "restored_source_count": stage_b["restored_source_count"],
            "imported_version_count": stage_b["imported_version_count"],
            "new_workspace_reexport_succeeded": True,
            "private_reexport_size_bytes": stage_b["private_reexport"]["size_bytes"],
            "private_reexport_sha256": stage_b["private_reexport"]["sha256"],
        },
        "scientific_projection": scientific,
        "identity_preservation": {
            "workspace_a_equals_workspace_b": True,
            "matrix_exact": True,
            "feature_axis_exact": True,
            "sample_labels_and_table_exact": True,
            "source_definition_and_combined_identity_exact": True,
            "target_absent": True,
        },
        "legacy_sidecar_retirement": {
            "status": "exact_duplicate_authority_retired_private",
            "receipt_sha256": retirement_sha256,
            "sidecar_count": retirement["sidecar_count"],
            "definition_sha256": retirement["definition_sha256"],
            "source_manifest_sha256": retirement["source_manifest_sha256"],
            "exact_definition_equivalence": retirement["exact_definition_equivalence"],
            "exact_source_binding": retirement["exact_source_binding"],
            "raw_source_bytes_changed": retirement["raw_source_bytes_changed"],
            "live_duplicate_authority_absent": retirement["live_duplicate_authority_absent"],
        },
        "privacy_boundary": {
            "raw_source_bytes_published": False,
            "project_archive_published": False,
            "private_transcript_published": False,
            "private_paths_or_database_ids_recorded": False,
            "credentials_or_user_identifiers_recorded": False,
        },
        "claim_boundary": (
            "Author-operated exact save, fresh-process restart, private project export, new-workspace import, "
            "dataset rerun, and re-export for this 33-spectrum corpus only."
        ),
        "nonclaims": [
            "non_author_physical_action_2",
            "pca_or_plsda_result",
            "botanical_authenticity_or_population_result",
            "redistribution_permission",
            "public_corpus_or_project_package",
        ],
    }
    public_report.parent.mkdir(parents=True, exist_ok=True)
    public_report.write_text(json.dumps(public, sort_keys=True, indent=2) + "\n")
    print("Avatar OMNIC Phase 5.3c portability: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace-a", type=Path, required=True)
    run.add_argument("--workspace-b", type=Path, required=True)
    run.add_argument("--project-id", type=int, required=True)
    run.add_argument("--experiment-id", type=int, required=True)
    run.add_argument("--archive", type=Path, required=True)
    run.add_argument("--private-report", type=Path, required=True)
    run.add_argument("--public-report", type=Path, required=True)
    run.add_argument("--definition", type=Path, required=True)
    run.add_argument("--retirement-receipt", type=Path, required=True)
    stage_a = commands.add_parser("stage-a")
    stage_a.add_argument("--project-id", type=int, required=True)
    stage_a.add_argument("--experiment-id", type=int, required=True)
    stage_a.add_argument("--archive", type=Path, required=True)
    stage_a.add_argument("--result", type=Path, required=True)
    stage_b = commands.add_parser("stage-b")
    stage_b.add_argument("--archive", type=Path, required=True)
    stage_b.add_argument("--reexport", type=Path, required=True)
    stage_b.add_argument("--result", type=Path, required=True)
    retire = commands.add_parser("retire-legacy-sidecars")
    retire.add_argument("--workspace", type=Path, required=True)
    retire.add_argument("--definition", type=Path, required=True)
    retire.add_argument("--experiment-id", type=int, required=True)
    verify_retired = commands.add_parser("verify-retired-sidecars")
    verify_retired.add_argument("--workspace", type=Path, required=True)
    verify_retired.add_argument("--definition", type=Path, required=True)
    verify_retired.add_argument("--experiment-id", type=int, required=True)
    verify_retired.add_argument("--receipt", type=Path, required=True)
    check_public = commands.add_parser("check-public")
    check_public.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return _run(args)
    if args.command == "stage-a":
        return _stage_a(args)
    if args.command == "stage-b":
        return _stage_b(args)
    if args.command == "retire-legacy-sidecars":
        return _retire_legacy_sidecars(args)
    if args.command == "verify-retired-sidecars":
        return _verify_retired_sidecars(args)
    return _check_public(args)


if __name__ == "__main__":
    raise SystemExit(main())
