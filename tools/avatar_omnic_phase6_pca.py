#!/usr/bin/env python3
"""Qualify the private Avatar PCA workflow without publishing private arrays.

The orchestrator executes one saved ``data.load_group`` →
``selection.variable_select`` → ``model.pca`` graph in three independent
application processes: initial workspace A, restarted workspace A, and a new
workspace B restored from the private project archive.  Complete selected
spectra, scores, loadings, sample identities, pair identities, archives, and
application identifiers stay in mode-0600 private records.  The checked report
contains only bounded path-free identities and descriptive summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.metadata
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.file_permissions import restrict_file_descriptor
from spectra_sherpa.core.file_io import open_regular_readonly

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-phase6-pca/1"
WORKFLOW_NAME = "Avatar Phase 6 canonical PCA"
WORKFLOW_DESCRIPTION = "Frozen 3100-650 cm-1 interval and three-component native PCA"
SAVE_DESCRIPTION = "Phase 6B exact PCA restart and portability qualification"
RUNTIME_IMPLEMENTATION_COMMIT = "273e76a1d96a2a207a0fbb875e7f425a062ea0fe"
EXPECTED_SOURCE_SHAPE = [33, 1868]
EXPECTED_SELECTED_SHAPE = [33, 1270]
EXPECTED_SCORE_SHAPE = [33, 3]
EXPECTED_LOADING_SHAPE = [3, 1270]
EXPECTED_SOURCE_VALUES_SHA256 = "66f6f64a08cb0a875ba654f7e9e66949a698c435292cf3fb8cd4c7ae784e2b76"
EXPECTED_SOURCE_AXIS_SHA256 = "f0fb31d4690ff770f518574e19353ee4b2bb6d46f43abdbd90a18aef6293ed6b"
EXPECTED_SAMPLE_TABLE_SHA256 = "1b13a7b34c0d9034bc06f397d9fb1bce1b3aa00491f7a50446a8769c483a5d38"
EXPECTED_SAMPLE_LABELS_SHA256 = "46a8bf29309c9756b6852a1391d3ab7a76e0c5ac94a87179a90a5090cd9f1573"
EXPECTED_DEFINITION_SHA256 = "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"
EXPECTED_SOURCE_MANIFEST_SHA256 = "199a9b04f7abacdc0ab73eef70fec44133abcd041f87c7e1855af3b753e8fcd8"
EXPECTED_SCIENTIFIC_COLLECTION_SHA256 = "144889847a230ed56ee28e532f790e7dc15883a19328c2cfcc3eb84e1b08e243"
EXPECTED_DATASET_ID = "avatar-essential-oils/1:canonical-phase4"
EXPECTED_ACTUAL_ENDPOINTS = [3099.1993627563543, 651.8539840297767]
EXPECTED_SCP_VERSION = "0.8.1"
MAX_PRIVATE_JSON_BYTES = 16 * 1024 * 1024
MAX_PRIVATE_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PUBLIC_REPORT_BYTES = 1024 * 1024
CHECKED_REPORT_SHA256 = "19d8e09e22ee9d9eff7f1deed4b2ba4422e7426b84c6f6928d83211341fb9771"
EXPECTED_PORTABILITY_SHA256 = "98fed2a1360429da1b6f20ec143ec247a204824c06127cb863e9be2d1bc1e67c"
EXPECTED_WORKFLOW_AUTHORITY_SHA256 = "cd78c9abe95dd9b22f02f897c655112c949d6408d6d203740e160be06f4b4661"
EXPECTED_SELECTION_PROJECTION_SHA256 = "c4cf3655e8ea481204255b1d24935049d2b13108fbf1f1d7698b4ee92ddff6c3"
EXPECTED_PCA_PROJECTION_SHA256 = "d9496343003b38f3268de2c73c633a37de044db3b1c04e9c334819b1da63c476"
EXPECTED_DESCRIPTIVE_PROJECTION_SHA256 = "00dd48f319ead2b99bf6ef60fdcb2231f868060857f9e90515bbd964714cdc68"
EXPECTED_PRIVATE_AUTHORITY_SHA256 = "c7fb61bd6af49ce02a0374355c760d96a8f40086953ec3afc571d24d58f1962f"
EXPECTED_CLAIM_BOUNDARY_SHA256 = "08a11cc07557ebd3cbecb519f5dffc70836f0baf2d95f653c7c397c3d2109c62"


class _DenySpectroChemPy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == "spectrochempy" or fullname.startswith("spectrochempy."):
            raise ModuleNotFoundError("Phase 6 base-profile proof denies the optional SpectroChemPy runtime")
        return None


def _install_scp_import_denial() -> None:
    if _scp_loaded():
        raise RuntimeError("SpectroChemPy was imported before the Phase 6 base-profile guard")
    sys.meta_path.insert(0, _DenySpectroChemPy())


def _scp_loaded() -> bool:
    return any(name == "spectrochempy" or name.startswith("spectrochempy.") for name in sys.modules)


def _require_installed_scp_distribution() -> str:
    try:
        version = importlib.metadata.version("spectrochempy")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Phase 6 optional-profile proof requires the qualified SpectroChemPy distribution") from exc
    if version != EXPECTED_SCP_VERSION:
        raise RuntimeError(
            f"Phase 6 optional-profile proof requires SpectroChemPy {EXPECTED_SCP_VERSION}, observed {version}"
        )
    return version


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return _sha256_bytes(payload)


def _array(value: Any, *, shape: list[int] | None = None, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if shape is not None and list(array.shape) != shape:
        raise ValueError(f"{name} has shape {list(array.shape)}, expected {shape}")
    if array.ndim < 1 or not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite and non-empty")
    return array


def _array_digest(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype="<f8"))
    return _sha256_bytes(array.tobytes(order="C"))


def _bool_digest(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype=np.bool_))
    return _sha256_bytes(array.astype(np.uint8).tobytes(order="C"))


def _training_data_hash(value: Any) -> str:
    array = np.asarray(value, dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("utf-8"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _private_parent(path: Path) -> Path:
    lexical = Path(os.path.abspath(path))
    parent = lexical.parent
    try:
        observed = parent.lstat()
    except OSError as exc:
        raise ValueError("private output parent is absent or unreadable") from exc
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISDIR(observed.st_mode)
        or (os.name != "nt" and stat.S_IMODE(observed.st_mode) & 0o077)
        or parent.resolve(strict=True) != parent
    ):
        raise ValueError("private output parent must be a private non-linked directory")
    try:
        leaf = lexical.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError("private output is unreadable") from exc
    else:
        if stat.S_ISLNK(leaf.st_mode) or not stat.S_ISREG(leaf.st_mode):
            raise ValueError("private output must not be linked or non-regular")
    return lexical


def _write_private_bytes(path: Path, payload: bytes, *, limit: int) -> dict[str, Any]:
    if len(payload) > limit:
        raise ValueError("private output exceeds its byte ceiling")
    destination = _private_parent(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        restrict_file_descriptor(descriptor)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"size_bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _write_private_json(path: Path, value: Any) -> dict[str, Any]:
    return _write_private_bytes(path, _json_bytes(value), limit=MAX_PRIVATE_JSON_BYTES)


def _read_private_bytes(path: Path, *, limit: int) -> bytes:
    lexical = Path(os.path.abspath(path))
    try:
        observed = lexical.lstat()
    except OSError as exc:
        raise ValueError("private input is absent or unreadable") from exc
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISREG(observed.st_mode)
        or (os.name != "nt" and stat.S_IMODE(observed.st_mode) != 0o600)
        or observed.st_size > limit
    ):
        raise ValueError("private input must be bounded, mode-0600, regular, and non-linked")
    descriptor = open_regular_readonly(lexical)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (os.name != "nt" and stat.S_IMODE(opened.st_mode) != 0o600)
            or opened.st_size != observed.st_size
            or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
        ):
            raise ValueError("private input changed during bounded admission")
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("private input exceeds its byte ceiling")
    return payload


def _write_public_json(path: Path, value: Any) -> None:
    destination = Path(os.path.abspath(path))
    parent = destination.parent
    if parent.resolve(strict=True) != parent:
        raise ValueError("public report parent must not traverse a symlink")
    try:
        observed = destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError("public report is unreadable") from exc
    else:
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise ValueError("public report must not be linked or non-regular")
    payload = _json_bytes(value)
    if len(payload) > MAX_PUBLIC_REPORT_BYTES:
        raise ValueError("public report exceeds its byte ceiling")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_public_bytes(path: Path) -> bytes:
    lexical = Path(os.path.abspath(path))
    try:
        observed = lexical.lstat()
    except OSError as exc:
        raise ValueError("public report is absent or unreadable") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise ValueError("public report must be regular and non-linked")
    if observed.st_size > MAX_PUBLIC_REPORT_BYTES:
        raise ValueError("public report exceeds its byte ceiling")
    descriptor = open_regular_readonly(lexical)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != observed.st_size
            or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
        ):
            raise ValueError("public report changed during bounded admission")
        payload = handle.read(MAX_PUBLIC_REPORT_BYTES + 1)
    if len(payload) > MAX_PUBLIC_REPORT_BYTES:
        raise ValueError("public report exceeds its byte ceiling")
    return payload


def _require_response(response: Any, status: int, label: str) -> Any:
    if response.status_code != status:
        raise RuntimeError(f"{label} failed ({response.status_code}): {response.text[-1200:]}")
    return response


def _client():
    from starlette.testclient import TestClient

    from spectra_sherpa.app.main import app

    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53053))


def _require_empty_registry() -> None:
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    if dataset_registry.retained_bytes != 0:
        raise RuntimeError("fresh process unexpectedly contains a retained dataset handle")


def _source_parameters(experiment_id: int) -> dict[str, Any]:
    return {
        "source_mode": "experiment_collection",
        "experiment_id": experiment_id,
        "stage": "raw",
        "asset_id": "spectrum",
        "source_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
        "collection_definition_sha256": EXPECTED_DEFINITION_SHA256,
        "scientific_collection_sha256": EXPECTED_SCIENTIFIC_COLLECTION_SHA256,
    }


def _workflow_payload(*, project_id: int, experiment_id: int) -> dict[str, Any]:
    return {
        "name": WORKFLOW_NAME,
        "description": WORKFLOW_DESCRIPTION,
        "status": "draft",
        "project_id": project_id,
        "technique": "FTIR",
        "sample_type": "essential oil",
        "nodes": [
            {
                "node_id": "source",
                "node_type": "data.load_group",
                "label": "Exact 33-source collection",
                "parameters": _source_parameters(experiment_id),
                "position_x": 0,
                "position_y": 0,
            },
            {
                "node_id": "window",
                "node_type": "selection.variable_select",
                "label": "3100-650 cm-1",
                "parameters": {"method": "interval", "region_start": 3100.0, "region_end": 650.0},
                "position_x": 260,
                "position_y": 0,
            },
            {
                "node_id": "pca",
                "node_type": "model.pca",
                "label": "Native PCA (3 PCs)",
                "parameters": {"n_components": "3", "standardized": False, "scaled": False},
                "position_x": 520,
                "position_y": 0,
            },
        ],
        "edges": [
            {
                "from_node_id": "source",
                "to_node_id": "window",
                "from_output": "default",
                "to_input": "X",
            },
            {
                "from_node_id": "window",
                "to_node_id": "pca",
                "from_output": "X_selected",
                "to_input": "default",
            },
        ],
    }


def _portable_workflow_projection(workflow: Mapping[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for raw in workflow.get("nodes", []):
        if not isinstance(raw, Mapping):
            raise ValueError("workflow contains a malformed node")
        parameters = dict(raw.get("parameters") or {})
        if raw.get("node_type") == "data.load_group":
            parameters["experiment_id"] = "<portable-experiment-id>"
        nodes.append(
            {
                "node_id": raw.get("node_id"),
                "node_type": raw.get("node_type"),
                "parameters": parameters,
            }
        )
    edges = [
        {
            "from_node_id": raw.get("from_node_id"),
            "to_node_id": raw.get("to_node_id"),
            "from_output": raw.get("from_output"),
            "to_input": raw.get("to_input"),
        }
        for raw in workflow.get("edges", [])
        if isinstance(raw, Mapping)
    ]
    projection = {
        "nodes": sorted(nodes, key=lambda item: str(item["node_id"])),
        "edges": sorted(edges, key=_json_digest),
    }
    expected = _workflow_payload(project_id=0, experiment_id=0)
    expected_projection = {
        "nodes": sorted(
            [
                {
                    "node_id": item["node_id"],
                    "node_type": item["node_type"],
                    "parameters": (
                        {**item["parameters"], "experiment_id": "<portable-experiment-id>"}
                        if item["node_type"] == "data.load_group"
                        else item["parameters"]
                    ),
                }
                for item in expected["nodes"]
            ],
            key=lambda item: item["node_id"],
        ),
        "edges": sorted(expected["edges"], key=_json_digest),
    }
    if projection != expected_projection:
        raise ValueError("saved workflow differs from the frozen portable graph")
    return projection


def _contract_digests() -> dict[str, str]:
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    ensure_type_registry_loaded()
    from spectra_sherpa.app.services.dag.node_base import node_registry

    return {
        name: node_registry.get_metadata(name).resolved_execution_contract().digest
        for name in ("data.load_group", "selection.variable_select", "model.pca")
    }


def _path_free_descriptive_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove row/class labels while retaining the frozen descriptive result."""

    specimen_ids = report.get("specimen_ids")
    block_ids = report.get("block_ids")
    ordered_paths = report.get("ordered_paths")
    if not isinstance(specimen_ids, list) or not isinstance(block_ids, list) or not isinstance(ordered_paths, list):
        raise ValueError("PCA descriptive report lacks its bounded identity sets")
    if len(specimen_ids) != 11 or len(block_ids) != 3 or len(ordered_paths) != 3:
        raise ValueError("PCA descriptive report does not describe the exact 11-by-3 acquisition")
    safe_paths: list[dict[str, Any]] = []
    for ordinal, value in enumerate(ordered_paths, start=1):
        if not isinstance(value, Mapping):
            raise ValueError("PCA ordered-path summary is malformed")
        safe_paths.append(
            {
                "block_ordinal": ordinal,
                "ordered_sample_ids_sha256": value.get("ordered_sample_ids_sha256"),
                "ordered_scores_sha256": value.get("ordered_scores_sha256"),
                "spearman_by_component": value.get("spearman_by_component"),
                "successive_path_length": value.get("successive_path_length"),
            }
        )
    return {
        "schema_version": report.get("schema_version"),
        "score_shape": report.get("score_shape"),
        "sample_identity_sha256": report.get("sample_identity_sha256"),
        "specimen_count": len(specimen_ids),
        "block_count": len(block_ids),
        "within_specimen_pairwise_distance": report.get("within_specimen_pairwise_distance"),
        "between_specimen_centroid_distance": report.get("between_specimen_centroid_distance"),
        "between_to_within_mean_ratio": report.get("between_to_within_mean_ratio"),
        "specimen_centroids_sha256": report.get("specimen_centroids_sha256"),
        "block_centroids": report.get("block_centroids"),
        "block_centroids_sha256": report.get("block_centroids_sha256"),
        "block_r_squared": report.get("block_r_squared"),
        "block_effect_interpretation": report.get("block_effect_interpretation"),
        "order_specimen_fully_aliased": report.get("order_specimen_fully_aliased"),
        "order_identifiability": report.get("order_identifiability"),
        "ordered_paths": safe_paths,
    }


def _require_workflow(client: Any, *, project_id: int, experiment_id: int, create: bool) -> tuple[int, dict[str, Any]]:
    listing = _require_response(
        client.get("/api/v1/workflows", params={"project_id": project_id, "limit": 100}), 200, "workflow list"
    ).json()
    matches = [item for item in listing if item.get("name") == WORKFLOW_NAME]
    if len(matches) > 1:
        raise RuntimeError("workspace contains duplicate Phase 6 workflows")
    if matches:
        workflow_id = matches[0]["id"]
    elif create:
        workflow_id = _require_response(
            client.post(
                "/api/v1/workflows", json=_workflow_payload(project_id=project_id, experiment_id=experiment_id)
            ),
            201,
            "workflow creation",
        ).json()["id"]
    else:
        raise RuntimeError("saved Phase 6 workflow is absent")
    workflow = _require_response(client.get(f"/api/v1/workflows/{workflow_id}"), 200, "workflow reload").json()
    portable = _portable_workflow_projection(workflow)
    preflight = _require_response(
        client.post(f"/api/v1/workflows/{workflow_id}/preflight"), 200, "workflow preflight"
    ).json()
    if not preflight.get("is_valid") or preflight.get("error_count") != 0:
        raise RuntimeError("saved workflow did not pass typed preflight")
    return workflow_id, {
        "portable_projection_sha256": _json_digest(portable),
        "execution_contract_digests": _contract_digests(),
    }


def _collection_identity(wire: Mapping[str, Any]) -> dict[str, Any]:
    metadata = wire.get("metadata")
    y_axis = wire.get("y_axis")
    x_axis = wire.get("x_axis")
    if not isinstance(metadata, Mapping) or not isinstance(y_axis, Mapping) or not isinstance(x_axis, Mapping):
        raise ValueError("dataset wire lacks typed axes or metadata")
    source = metadata.get("source_collection")
    labels = y_axis.get("labels")
    table = y_axis.get("sample_table")
    if not isinstance(source, Mapping) or not isinstance(labels, list) or not isinstance(table, Mapping):
        raise ValueError("dataset wire lacks collection or sample identity")
    source_values = _array(wire.get("data"), shape=EXPECTED_SOURCE_SHAPE, name="source matrix")
    source_axis = _array(x_axis.get("data"), shape=[EXPECTED_SOURCE_SHAPE[1]], name="source feature axis")
    if wire.get("shape") != EXPECTED_SOURCE_SHAPE:
        raise ValueError("source wire shape metadata differs from its exact matrix")
    _require_spectral_wire_semantics(wire, expected_shape=EXPECTED_SOURCE_SHAPE, label="source")
    projection = {
        "dataset_id": wire.get("dataset_id"),
        "shape": list(source_values.shape),
        "values_sha256": _array_digest(source_values),
        "feature_axis_sha256": _array_digest(source_axis),
        "sample_labels_sha256": _json_digest(labels),
        "sample_table_sha256": _json_digest(table),
        "source_manifest_sha256": source.get("source_manifest_sha256"),
        "collection_definition_sha256": source.get("collection_definition_sha256"),
        "scientific_collection_sha256": source.get("scientific_collection_sha256"),
        "target_state": (
            "absent"
            if "target" not in wire and wire.get("target_context") in (None, {})
            else "present_or_contextualized"
        ),
    }
    expected = {
        "dataset_id": EXPECTED_DATASET_ID,
        "shape": EXPECTED_SOURCE_SHAPE,
        "values_sha256": EXPECTED_SOURCE_VALUES_SHA256,
        "feature_axis_sha256": EXPECTED_SOURCE_AXIS_SHA256,
        "sample_labels_sha256": EXPECTED_SAMPLE_LABELS_SHA256,
        "sample_table_sha256": EXPECTED_SAMPLE_TABLE_SHA256,
        "source_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
        "collection_definition_sha256": EXPECTED_DEFINITION_SHA256,
        "scientific_collection_sha256": EXPECTED_SCIENTIFIC_COLLECTION_SHA256,
        "target_state": "absent",
    }
    mismatches = [name for name, value in expected.items() if projection.get(name) != value]
    if mismatches:
        raise ValueError(f"source collection differs in: {', '.join(mismatches)}")
    return projection


def _require_spectral_wire_semantics(wire: Mapping[str, Any], *, expected_shape: list[int], label: str) -> None:
    x_axis = wire.get("x_axis")
    if (
        wire.get("shape") != expected_shape
        or wire.get("units") != "absorbance"
        or wire.get("data_role") != "X_spectra"
        or not isinstance(x_axis, Mapping)
        or x_axis.get("axis_class") != "SpectralAxis"
        or x_axis.get("title") != "Wavenumber"
        or x_axis.get("units") != "cm-1"
    ):
        raise ValueError(f"{label} dataset does not retain the exact FTIR spectral semantics")
    if "target" in wire or wire.get("target_context") not in (None, {}):
        raise ValueError(f"{label} dataset unexpectedly carries a modeling target")


def _require_exact_selection_projection(
    source_wire: Mapping[str, Any], selected_wire: Mapping[str, Any], mask_value: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source = _array(source_wire.get("data"), shape=EXPECTED_SOURCE_SHAPE, name="source matrix")
    source_axis = _array(
        (source_wire.get("x_axis") or {}).get("data"),
        shape=[EXPECTED_SOURCE_SHAPE[1]],
        name="source feature axis",
    )
    selected = _array(selected_wire.get("data"), shape=EXPECTED_SELECTED_SHAPE, name="selected matrix")
    selected_axis = _array(
        (selected_wire.get("x_axis") or {}).get("data"),
        shape=[EXPECTED_SELECTED_SHAPE[1]],
        name="selected feature axis",
    )
    _require_spectral_wire_semantics(source_wire, expected_shape=EXPECTED_SOURCE_SHAPE, label="source")
    _require_spectral_wire_semantics(selected_wire, expected_shape=EXPECTED_SELECTED_SHAPE, label="selected")
    # Derived datasets receive a fresh runtime handle; every scientific field
    # around that process-local identifier must remain exact.
    for field in ("title", "units", "data_role", "data_modality", "domain", "is_time_series"):
        if selected_wire.get(field) != source_wire.get(field):
            raise ValueError(f"selection changed the dataset {field} semantic")
    mask = np.asarray(mask_value, dtype=np.bool_)
    if mask.shape != (EXPECTED_SOURCE_SHAPE[1],) or int(np.sum(mask)) != EXPECTED_SELECTED_SHAPE[1]:
        raise ValueError("selection mask does not bind 1,270 of 1,868 variables")
    if not np.array_equal(selected, source[:, mask]):
        raise ValueError("selected matrix is not the exact masked source projection")
    if not np.array_equal(selected_axis, source_axis[mask]):
        raise ValueError("selected axis is not the exact masked source-axis projection")
    source_y = source_wire.get("y_axis") or {}
    selected_y = selected_wire.get("y_axis") or {}
    if selected_y.get("labels") != source_y.get("labels") or selected_y.get("sample_table") != source_y.get(
        "sample_table"
    ):
        raise ValueError("selection changed sample labels, table, or row order")
    return selected, selected_axis, mask


def _require_pca_state_output_binding(
    state: Mapping[str, Any],
    *,
    loadings: np.ndarray,
    explained: np.ndarray,
    eigenvalues: np.ndarray,
    selected_axis: np.ndarray,
    selected_axis_wire: Mapping[str, Any],
    expected_contract_digest: str,
    expected_input_axis_identity_sha256: str,
) -> None:
    if set(state) != {
        "arrays",
        "metadata",
        "schema_version",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
    }:
        raise ValueError("PCA fitted state does not use its closed schema")
    if (
        state.get("schema_version") != "spectrasherpa.model.pca-state/4"
        or state.get("serializer") != "spectrasherpa.model-artifact.pca/3"
        or state.get("source_contract_digest") != expected_contract_digest
    ):
        raise ValueError("PCA fitted-state identity differs from the executed node contract")
    arrays = state.get("arrays")
    metadata = state.get("metadata")
    if not isinstance(arrays, Mapping) or set(arrays) != {
        "center",
        "explained_variance",
        "explained_variance_ratio",
        "loadings",
        "mean",
        "offset",
        "scale",
    }:
        raise ValueError("PCA fitted-state array inventory differs")
    if not isinstance(metadata, Mapping) or set(metadata) != {
        "feature_axis_labels_sha256",
        "feature_axis_quantity",
        "feature_axis_units",
        "feature_axis_values_sha256",
        "input_axis_identity_sha256",
        "input_shape",
        "n_components",
        "n_features",
        "reference_samples",
        "rank_projection_strategy",
        "scale_mode",
        "scaled",
        "sign_rule",
        "standardized",
    }:
        raise ValueError("PCA fitted-state metadata inventory differs")
    if (
        not np.array_equal(np.asarray(arrays["loadings"], dtype=np.float64), loadings)
        or not np.array_equal(np.asarray(arrays["explained_variance_ratio"], dtype=np.float64), explained)
        or not np.array_equal(np.asarray(arrays["explained_variance"], dtype=np.float64), eigenvalues)
    ):
        raise ValueError("PCA fitted-state arrays differ from the node outputs")
    expected_metadata = {
        "feature_axis_labels_sha256": None,
        "feature_axis_quantity": selected_axis_wire.get("quantity"),
        "feature_axis_units": selected_axis_wire.get("units"),
        "feature_axis_values_sha256": _array_digest(selected_axis),
        "input_axis_identity_sha256": expected_input_axis_identity_sha256,
        "input_shape": list(EXPECTED_SELECTED_SHAPE),
        "n_components": 3,
        "n_features": EXPECTED_SELECTED_SHAPE[1],
        "reference_samples": EXPECTED_SELECTED_SHAPE[0],
        "rank_projection_strategy": "none",
        "scale_mode": None,
        "scaled": False,
        "sign_rule": "largest_absolute_loading_positive",
        "standardized": False,
    }
    if dict(metadata) != expected_metadata:
        raise ValueError("PCA fitted-state metadata differs from the selected scientific input")


def _require_pca_output_semantics(
    scores_wire: Mapping[str, Any],
    loadings_wire: Mapping[str, Any],
    selected_wire: Mapping[str, Any],
) -> None:
    selected_y = selected_wire.get("y_axis") or {}
    scores_y = scores_wire.get("y_axis") or {}
    if scores_y.get("labels") != selected_y.get("labels") or scores_y.get("sample_table") != selected_y.get(
        "sample_table"
    ):
        raise ValueError("PCA scores changed sample labels, table, or row order")
    selected_x = selected_wire.get("x_axis") or {}
    loadings_x = loadings_wire.get("x_axis") or {}
    if (
        loadings_x.get("axis_class") != selected_x.get("axis_class")
        or loadings_x.get("title") != selected_x.get("title")
        or loadings_x.get("units") != selected_x.get("units")
        or not np.array_equal(
            np.asarray(loadings_x.get("data"), dtype=np.float64),
            np.asarray(selected_x.get("data"), dtype=np.float64),
        )
    ):
        raise ValueError("PCA loadings changed the selected feature-axis semantics")


def _require_artifact_binding(
    inspection: Mapping[str, Any],
    detail: Mapping[str, Any],
    persisted_manifest: Mapping[str, Any],
    persisted_arrays: Mapping[str, np.ndarray],
    *,
    selected_axis: np.ndarray,
    selected_axis_wire: Mapping[str, Any],
    loadings: np.ndarray,
    explained: np.ndarray,
    eigenvalues: np.ndarray,
    scores: np.ndarray,
    state_arrays: Mapping[str, Any],
    mask: np.ndarray,
    selected: np.ndarray,
) -> None:
    manifest = inspection.get("manifest")
    arrays = inspection.get("arrays")
    if not isinstance(manifest, Mapping) or not isinstance(arrays, Mapping):
        raise ValueError("persisted PCA artifact inspection is malformed")
    if dict(manifest) != dict(persisted_manifest):
        raise ValueError("persisted PCA manifest differs from its inspected projection")
    expected_arrays = {
        "loadings": {"shape": list(loadings.shape), "dtype": "float64"},
        "explained_variance_ratio": {"shape": list(explained.shape), "dtype": "float64"},
        "explained_variance": {"shape": list(eigenvalues.shape), "dtype": "float64"},
        "mean": {"shape": [EXPECTED_SELECTED_SHAPE[1]], "dtype": "float64"},
        "scores": {"shape": list(scores.shape), "dtype": "float64"},
    }
    if set(arrays) != set(expected_arrays):
        raise ValueError("persisted PCA artifact array inventory differs")
    for name, expected in expected_arrays.items():
        observed = arrays[name]
        if (
            not isinstance(observed, Mapping)
            or {
                "shape": observed.get("shape"),
                "dtype": observed.get("dtype"),
            }
            != expected
        ):
            raise ValueError(f"persisted PCA artifact array {name} differs")
    if set(persisted_arrays) != set(expected_arrays):
        raise ValueError("persisted PCA artifact decoded array inventory differs")
    expected_values = {
        "loadings": loadings,
        "explained_variance_ratio": explained,
        "explained_variance": eigenvalues,
        "mean": np.asarray(state_arrays.get("mean"), dtype=np.float64),
        "scores": scores,
    }
    for name, expected in expected_values.items():
        if not np.array_equal(np.asarray(persisted_arrays[name]), expected):
            raise ValueError(f"persisted PCA artifact array {name} differs from the node/state result")
    expected_training_hash = _training_data_hash(selected)
    feature_mask = np.asarray(manifest.get("feature_mask"), dtype=np.bool_)
    if (
        manifest.get("model_type") != "pca"
        or manifest.get("serializer") != "spectrasherpa.model-artifact.pca/3"
        or manifest.get("n_components") != 3
        or manifest.get("n_features") != EXPECTED_SELECTED_SHAPE[1]
        or manifest.get("standardized") is not False
        or manifest.get("scaled") is not False
        or manifest.get("scale_mode") is not None
        or manifest.get("feature_axis_class") != "SpectralAxis"
        or manifest.get("feature_axis_units") != selected_axis_wire.get("units")
        or manifest.get("feature_axis_title") != selected_axis_wire.get("title")
        or not np.array_equal(np.asarray(manifest.get("feature_axis"), dtype=np.float64), selected_axis)
        or not np.array_equal(np.asarray(manifest.get("selected_features"), dtype=np.float64), selected_axis)
        or not np.array_equal(np.asarray(detail.get("feature_axis"), dtype=np.float64), selected_axis)
        or manifest.get("arrays") != expected_arrays
        or manifest.get("metrics", {}).get("explained_variance_ratio") != explained.tolist()
        or feature_mask.shape != (EXPECTED_SOURCE_SHAPE[1],)
        or not np.array_equal(feature_mask, mask)
        or manifest.get("training_data_hash") != expected_training_hash
        or detail.get("training_data_hash") != expected_training_hash
        or manifest.get("integrity_hash") != detail.get("integrity_hash")
        or inspection.get("artifact_uid") != detail.get("artifact_uid")
    ):
        raise ValueError("persisted PCA artifact is not cross-bound to the node result")


def _summarize_execution(
    client: Any, execution: Mapping[str, Any], workflow_authority: Mapping[str, Any]
) -> dict[str, Any]:
    from spectra_sherpa.app.lib.pca_reporting import build_pca_block_report
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import apply_pca_fitted_state

    if execution.get("status") != "completed" or execution.get("error") is not None:
        raise RuntimeError("workflow execution did not complete without serialization errors")
    if execution.get("node_statuses") != {"source": "completed", "window": "completed", "pca": "completed"}:
        raise RuntimeError("workflow node status set is incomplete")
    results = execution.get("results")
    if not isinstance(results, Mapping) or set(results) != {"source", "window", "pca"}:
        raise RuntimeError("workflow result set is not the exact three-node graph")
    source_wire = results["source"]["default"]
    source_identity = _collection_identity(source_wire)
    window = results["window"]
    selected_wire = window["X_selected"]
    selected, selected_axis, mask = _require_exact_selection_projection(source_wire, selected_wire, window.get("mask"))
    if list(selected_axis[[0, -1]]) != EXPECTED_ACTUAL_ENDPOINTS or not np.all(np.diff(selected_axis) < 0.0):
        raise ValueError("selected axis does not preserve the exact descending measured interval")
    selected_y = selected_wire.get("y_axis") or {}
    if _json_digest(selected_y.get("sample_table")) != EXPECTED_SAMPLE_TABLE_SHA256:
        raise ValueError("variable selection changed the exact sample table")

    pca = results["pca"]
    scores_wire = pca["scores"]
    loadings_wire = pca["loadings"]
    _require_pca_output_semantics(scores_wire, loadings_wire, selected_wire)
    scores = _array(scores_wire.get("data"), shape=EXPECTED_SCORE_SHAPE, name="PCA scores")
    loadings = _array(loadings_wire.get("data"), shape=EXPECTED_LOADING_SHAPE, name="PCA loadings")
    explained = _array(pca.get("explained_variance"), shape=[3], name="explained variance ratio")
    eigenvalues = _array(pca.get("eigenvalues"), shape=[3], name="PCA eigenvalues")
    if np.any(np.diff(explained) > 0.0) or np.any(np.diff(eigenvalues) > 0.0):
        raise ValueError("PCA variance/eigenvalues are not descending")
    cumulative = np.cumsum(explained)
    k90 = int(np.searchsorted(cumulative, 0.90, side="left") + 1)
    if k90 != 1 or max(3, k90) != 3 or cumulative[-1] < 0.90:
        raise ValueError("PCA component-retention rule was not satisfied")
    if not np.allclose(loadings @ loadings.T, np.eye(3), rtol=0.0, atol=1e-12):
        raise ValueError("PCA loadings are not orthonormal")
    anchors: list[dict[str, Any]] = []
    for component in range(3):
        index = int(np.argmax(np.abs(loadings[component])))
        value = float(loadings[component, index])
        if value <= 0.0:
            raise ValueError("PCA sign convention is not largest-absolute-loading positive")
        anchors.append({"component": component + 1, "feature_index": index, "loading": value})
    state = pca.get("model")
    if not isinstance(state, Mapping) or state.get("serializer") != "spectrasherpa.model-artifact.pca/3":
        raise ValueError("PCA fitted state is not the current canonical serializer")
    selected_x_axis = selected_wire.get("x_axis") or {}
    replay_input = SherpaDataset(
        X=selected,
        feature_axis=SpectralAxis(
            values=selected_axis,
            units=selected_x_axis.get("units"),
            title=selected_x_axis.get("title"),
            quantity=selected_x_axis.get("quantity"),
        ),
        units=selected_wire.get("units"),
        data_role=selected_wire.get("data_role"),
    )
    from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity

    _require_pca_state_output_binding(
        state,
        loadings=loadings,
        explained=explained,
        eigenvalues=eigenvalues,
        selected_axis=selected_axis,
        selected_axis_wire=selected_x_axis,
        expected_contract_digest=workflow_authority["execution_contract_digests"]["model.pca"],
        expected_input_axis_identity_sha256=input_axis_identity(replay_input),
    )
    replay = apply_pca_fitted_state(replay_input, dict(state))
    replay_max_abs = float(np.max(np.abs(replay - scores)))
    if replay_max_abs > 1e-10:
        raise ValueError("PCA fitted-state replay differs from the fitted scores")
    labels = scores_wire.get("y_axis", {}).get("labels")
    table = scores_wire.get("y_axis", {}).get("sample_table")
    if not isinstance(labels, list) or not isinstance(table, Mapping):
        raise ValueError("PCA scores lack their exact sample identity")
    report = build_pca_block_report(scores, sample_labels=labels, sample_table=table)

    model_uid = pca.get("model_id")
    if not isinstance(model_uid, str) or not model_uid:
        raise ValueError("PCA execution did not persist an artifact")
    inspection = _require_response(
        client.get(f"/api/v1/models/{model_uid}/inspect"), 200, "PCA artifact inspection"
    ).json()
    detail = _require_response(client.get(f"/api/v1/models/{model_uid}"), 200, "PCA artifact detail").json()
    from spectra_sherpa.app.services.model_store import get_model_store

    persisted_manifest, persisted_arrays = get_model_store().load(model_uid)
    if (
        inspection.get("model_type") != "pca"
        or detail.get("model_type") != "pca"
        or detail.get("n_features") != 1270
        or detail.get("n_components") != 3
    ):
        raise ValueError("persisted PCA artifact does not match the fitted state")
    _require_artifact_binding(
        inspection,
        detail,
        persisted_manifest,
        persisted_arrays,
        selected_axis=selected_axis,
        selected_axis_wire=selected_x_axis,
        loadings=loadings,
        explained=explained,
        eigenvalues=eigenvalues,
        scores=scores,
        state_arrays=state["arrays"],
        mask=mask,
        selected=selected,
    )
    model_state_digest = state.get("state_content_digest")
    if not isinstance(model_state_digest, str) or len(model_state_digest) != 64:
        raise ValueError("PCA fitted state lacks its canonical content digest")

    scientific = {
        "source_collection": source_identity,
        "selection": {
            "method": "interval",
            "requested_bounds_cm-1": [3100.0, 650.0],
            "actual_endpoints_cm-1": EXPECTED_ACTUAL_ENDPOINTS,
            "shape": EXPECTED_SELECTED_SHAPE,
            "mask_sha256": _bool_digest(mask),
            "selected_axis_sha256": _array_digest(selected_axis),
            "selected_values_sha256": _array_digest(selected),
        },
        "pca": {
            "parameters": {"n_components": "3", "standardized": False, "scaled": False},
            "scores_shape": EXPECTED_SCORE_SHAPE,
            "loadings_shape": EXPECTED_LOADING_SHAPE,
            "scores_sha256": _array_digest(scores),
            "loadings_sha256": _array_digest(loadings),
            "explained_variance_ratio": explained.tolist(),
            "explained_variance_ratio_sha256": _array_digest(explained),
            "eigenvalues": eigenvalues.tolist(),
            "eigenvalues_sha256": _array_digest(eigenvalues),
            "cumulative_variance": cumulative.tolist(),
            "k90": k90,
            "k_display": 3,
            "loading_sign_convention": "largest_absolute_loading_positive",
            "loading_sign_anchors": anchors,
            "displayed_eigenvalue_gaps": np.diff(eigenvalues * -1.0).tolist(),
            "state_content_digest": model_state_digest,
            "source_contract_digest": state.get("source_contract_digest"),
            "replay_max_abs_difference": replay_max_abs,
            "artifact_integrity_hash": detail.get("integrity_hash"),
            "artifact_serializer": inspection.get("manifest", {}).get("serializer"),
        },
        "descriptive_report": _path_free_descriptive_summary(report.public_summary),
        "workflow_authority": dict(workflow_authority),
    }
    private = {
        "selected_matrix": selected.tolist(),
        "selected_axis": selected_axis.tolist(),
        "sample_labels": labels,
        "sample_table": table,
        "scores": scores.tolist(),
        "loadings": loadings.tolist(),
        "fitted_state": state,
        "private_pairs": report.private_pairs,
        "artifact_uid": model_uid,
        "workflow_integrity_hash": execution.get("integrity_hash"),
    }
    return {"scientific": scientific, "private": private}


def _execute_saved_workflow(client: Any, workflow_id: int, authority: Mapping[str, Any]) -> dict[str, Any]:
    execution = _require_response(
        client.post(f"/api/v1/workflows/{workflow_id}/execute", json={}), 200, "saved workflow execution"
    ).json()
    return _summarize_execution(client, execution, authority)


def _stage_a(args: argparse.Namespace) -> int:
    scp_distribution_version = _require_installed_scp_distribution()
    with _client() as client:
        _require_empty_registry()
        workflow_id, authority = _require_workflow(
            client, project_id=args.project_id, experiment_id=args.experiment_id, create=True
        )
        result = _execute_saved_workflow(client, workflow_id, authority)
        versions = _require_response(
            client.get(f"/api/v1/projects/{args.project_id}/versions"), 200, "project version list"
        ).json()
        matches = [item for item in versions.get("versions", []) if item.get("change_description") == SAVE_DESCRIPTION]
        if len(matches) > 1:
            raise RuntimeError("workspace contains duplicate Phase 6 qualification versions")
        saved = (
            matches[0]
            if matches
            else _require_response(
                client.post(
                    f"/api/v1/projects/{args.project_id}/save",
                    json={"change_description": SAVE_DESCRIPTION, "include_raw_data": True},
                ),
                201,
                "project save",
            ).json()
        )
        exported = _require_response(
            client.get(f"/api/v1/projects/{args.project_id}/export/sherpa?version_id={saved['id']}"),
            200,
            "saved project export",
        )
        with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
            project = json.loads(archive.read("project.json"))
        if (project.get("archive_format") or {}).get("version") != "0.4":
            raise RuntimeError("saved project does not use current archive schema /0.4")
    archive_record = _write_private_bytes(args.archive, exported.content, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    _write_private_json(
        args.result,
        {
            "stage": "workspace_a_initial_fresh_process",
            "old_dataset_handle_used": False,
            "spectrochempy_loaded": _scp_loaded(),
            "spectrochempy_import_denied": os.getenv("SPECTRA_PHASE6_DENY_SCP_IMPORT") == "1",
            "spectrochempy_distribution_version": scp_distribution_version,
            "saved_version_number": saved["version_number"],
            "archive": archive_record,
            **result,
        },
    )
    return 0


def _stage_restart(args: argparse.Namespace) -> int:
    with _client() as client:
        _require_empty_registry()
        workflow_id, authority = _require_workflow(
            client, project_id=args.project_id, experiment_id=args.experiment_id, create=False
        )
        result = _execute_saved_workflow(client, workflow_id, authority)
    _write_private_json(
        args.result,
        {
            "stage": "workspace_a_restart_fresh_process",
            "old_dataset_handle_used": False,
            "spectrochempy_loaded": _scp_loaded(),
            "spectrochempy_import_denied": os.getenv("SPECTRA_PHASE6_DENY_SCP_IMPORT") == "1",
            "spectrochempy_distribution_version": None,
            **result,
        },
    )
    return 0


def _stage_import(args: argparse.Namespace) -> int:
    scp_distribution_version = _require_installed_scp_distribution()
    archive_payload = _read_private_bytes(args.archive, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    with _client() as client:
        _require_empty_registry()
        imported = _require_response(
            client.post(
                "/api/v1/projects/import",
                files={"file": ("avatar-phase6.sherpa", archive_payload, "application/zip")},
            ),
            201,
            "new-workspace import",
        ).json()
        experiments = [item for item in imported.get("experiments", []) if item.get("file_count") == 33]
        workflows = [item for item in imported.get("workflows", []) if item.get("name") == WORKFLOW_NAME]
        if len(experiments) != 1 or len(workflows) != 1:
            raise RuntimeError("import did not restore the exact experiment and saved workflow")
        workflow_id, authority = _require_workflow(
            client,
            project_id=imported["id"],
            experiment_id=experiments[0]["id"],
            create=False,
        )
        if workflow_id != workflows[0]["id"]:
            raise RuntimeError("imported workflow identity is inconsistent")
        result = _execute_saved_workflow(client, workflow_id, authority)
        versions = _require_response(
            client.get(f"/api/v1/projects/{imported['id']}/versions"), 200, "imported version list"
        ).json()
        if versions.get("total") != 1:
            raise RuntimeError("new workspace did not restore exactly one saved version")
        reexported = _require_response(
            client.get(f"/api/v1/projects/{imported['id']}/export/sherpa?version_id={versions['versions'][0]['id']}"),
            200,
            "new-workspace re-export",
        )
    reexport = _write_private_bytes(args.reexport, reexported.content, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    _write_private_json(
        args.result,
        {
            "stage": "workspace_b_import_fresh_process",
            "old_dataset_handle_used": False,
            "spectrochempy_loaded": _scp_loaded(),
            "spectrochempy_import_denied": os.getenv("SPECTRA_PHASE6_DENY_SCP_IMPORT") == "1",
            "spectrochempy_distribution_version": scp_distribution_version,
            "restored_source_count": 33,
            "restored_version_count": 1,
            "reexport": reexport,
            **result,
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


def _run_stage(arguments: list[str], *, workspace: Path, deny_scp_import: bool = False) -> None:
    env = _subprocess_env(workspace)
    if deny_scp_import:
        env["SPECTRA_PHASE6_DENY_SCP_IMPORT"] = "1"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *arguments],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"fresh-process stage failed: {completed.stderr[-3000:]}{completed.stdout[-3000:]}")


def _load_stage(path: Path) -> dict[str, Any]:
    payload = _read_private_bytes(path, limit=MAX_PRIVATE_JSON_BYTES)
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("private stage result is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("private stage result must be an object")
    return value


def _closed_run_output_paths(args: argparse.Namespace, workspace_a: Path, workspace_b: Path) -> dict[str, Path]:
    archive = Path(os.path.abspath(args.archive))
    private_report = Path(os.path.abspath(args.private_report))
    public_report = Path(os.path.abspath(args.public_report))
    outputs = {
        "archive": archive,
        "private_report": private_report,
        "public_report": public_report,
        "reexport": archive.parent / f"{archive.stem}-workspace-b-reexport.sherpa",
        "stage_a": private_report.parent / f"{private_report.stem}-stage-a.json",
        "restart": private_report.parent / f"{private_report.stem}-restart.json",
        "stage_b": private_report.parent / f"{private_report.stem}-stage-b.json",
    }
    identities: dict[str, str] = {}
    for name, path in outputs.items():
        key = str(path).casefold()
        if key in identities:
            raise ValueError(f"Phase 6 output paths collide: {identities[key]} and {name}")
        identities[key] = name
        if path.exists() or path.is_symlink():
            raise ValueError(f"Phase 6 output {name} must be absent before qualification")
        for workspace_name, workspace in (("workspace A", workspace_a), ("workspace B", workspace_b)):
            try:
                path.relative_to(workspace)
            except ValueError:
                pass
            else:
                raise ValueError(f"Phase 6 output {name} must be outside {workspace_name}")
    return outputs


def _public_projection(
    stage_a: Mapping[str, Any],
    stage_b: Mapping[str, Any],
    archive: Mapping[str, Any],
    reexport: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase6_exact_saved_pca_restart_and_new_workspace_portability_complete_author_operated",
        "observed_at": "2026-08-24",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "observation_authority": "author_operated_three_fresh_local_oss_application_processes",
        "process_and_workspace_boundary": {
            "workspace_a_initial_process": True,
            "workspace_a_fresh_restart": True,
            "workspace_b_was_absent_before_run": True,
            "workspace_b_new_database": True,
            "old_dataset_handle_used": False,
            "optional_profile_spectrochempy_loaded": False,
            "optional_profile_spectrochempy_distribution": {
                "name": "spectrochempy",
                "qualified_version": EXPECTED_SCP_VERSION,
                "initial_process_version": stage_a["spectrochempy_distribution_version"],
                "imported_process_version": stage_b["spectrochempy_distribution_version"],
            },
            "comparison_process_spectrochempy_import_denied": True,
            "comparison_process_distribution_absence_claimed": False,
        },
        "workflow_and_artifact_portability": {
            "saved_snapshot_archive_version": "0.4",
            "saved_version_number": stage_a["saved_version_number"],
            "private_archive_size_bytes": archive["size_bytes"],
            "private_archive_sha256": archive["sha256"],
            "restored_source_count": 33,
            "restored_version_count": 1,
            "new_workspace_reexport_succeeded": True,
            "private_reexport_size_bytes": reexport["size_bytes"],
            "private_reexport_sha256": reexport["sha256"],
        },
        "scientific_result": stage_a["scientific"],
        "identity_preservation": {
            "initial_equals_restart_equals_import": True,
            "source_and_selected_matrix_exact": True,
            "scores_loadings_variance_and_state_exact": True,
            "sample_identity_and_descriptive_summary_exact": True,
            "artifact_integrity_exact": True,
            "workflow_uid_remap_allowed_scientific_graph_exact": True,
            "target_absent": True,
            "import_denied_execution_equals_optional_profile": True,
        },
        "privacy_boundary": {
            "raw_or_selected_spectra_published": False,
            "complete_scores_or_loadings_published": False,
            "sample_or_pair_identities_published": False,
            "project_archive_or_transcript_published": False,
            "private_paths_database_ids_or_artifact_uids_published": False,
        },
        "claim_boundary": (
            "Author-operated exact exploratory PCA workflow execution, fresh-process restart, private project "
            "export, new-workspace import, artifact-bound rerun, and descriptive block summary for this exact "
            "33-spectrum acquisition corpus only."
        ),
        "nonclaims": [
            "non_author_physical_action_2",
            "botanical_authenticity_or_population_result",
            "instrument_drift_or_causal_order_effect",
            "classification_or_plsda_result",
            "redistribution_permission",
            "public_corpus_or_project_package",
        ],
    }


def _run(args: argparse.Namespace) -> int:
    workspace_a = args.workspace_a.resolve()
    workspace_b = args.workspace_b.resolve()
    if not (workspace_a / "spectra_platform.db").is_file():
        raise ValueError("workspace A database is absent")
    if workspace_b.exists():
        raise ValueError("workspace B must be absent before qualification")
    outputs = _closed_run_output_paths(args, workspace_a, workspace_b)
    archive = outputs["archive"]
    reexport = outputs["reexport"]
    stage_a_path = outputs["stage_a"]
    restart_path = outputs["restart"]
    stage_b_path = outputs["stage_b"]
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
            str(stage_a_path),
        ],
        workspace=workspace_a,
    )
    _run_stage(
        [
            "stage-restart",
            "--project-id",
            str(args.project_id),
            "--experiment-id",
            str(args.experiment_id),
            "--result",
            str(restart_path),
        ],
        workspace=workspace_a,
        deny_scp_import=True,
    )
    workspace_b.mkdir(mode=0o700, parents=True)
    _run_stage(
        [
            "stage-import",
            "--archive",
            str(archive),
            "--reexport",
            str(reexport),
            "--result",
            str(stage_b_path),
        ],
        workspace=workspace_b,
    )
    stage_a = _load_stage(stage_a_path)
    restart = _load_stage(restart_path)
    stage_b = _load_stage(stage_b_path)
    if (
        stage_a["spectrochempy_loaded"]
        or stage_a["spectrochempy_import_denied"]
        or restart["spectrochempy_loaded"]
        or not restart["spectrochempy_import_denied"]
        or stage_b["spectrochempy_loaded"]
        or stage_b["spectrochempy_import_denied"]
        or stage_a["spectrochempy_distribution_version"] != EXPECTED_SCP_VERSION
        or restart["spectrochempy_distribution_version"] is not None
        or stage_b["spectrochempy_distribution_version"] != EXPECTED_SCP_VERSION
    ):
        raise ValueError("optional/base runtime profile identities were not exercised exactly")
    if not (stage_a["scientific"] == restart["scientific"] == stage_b["scientific"]):
        raise ValueError("initial, restarted, and imported scientific PCA projections differ")
    private = {
        "schema_version": SCHEMA_VERSION,
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "workspace_a_initial": stage_a,
        "workspace_a_restart": restart,
        "workspace_b_import": stage_b,
    }
    private_record = _write_private_json(outputs["private_report"], private)
    public = _public_projection(stage_a, stage_b, stage_a["archive"], stage_b["reexport"])
    public["private_evidence_authority"] = {
        "private_report_size_bytes": private_record["size_bytes"],
        "private_report_sha256": private_record["sha256"],
        "private_report_published": False,
    }
    _write_public_json(outputs["public_report"], public)
    print("Avatar OMNIC Phase 6B PCA: PASS")
    return 0


def validate_checked_report(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        payload = _read_public_bytes(path)
    except ValueError as exc:
        return [str(exc)]
    if CHECKED_REPORT_SHA256.startswith("TO_BE_") or _sha256_bytes(payload) != CHECKED_REPORT_SHA256:
        failures.append("checked Phase 6 report digest differs from the reviewed authority")
    try:
        report = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return failures + ["checked Phase 6 report is not valid JSON"]
    if not isinstance(report, dict) or set(report) != {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "status",
        "observed_at",
        "runtime_implementation_commit",
        "observation_authority",
        "process_and_workspace_boundary",
        "workflow_and_artifact_portability",
        "scientific_result",
        "identity_preservation",
        "privacy_boundary",
        "claim_boundary",
        "nonclaims",
        "private_evidence_authority",
    }:
        failures.append("checked Phase 6 report does not use its closed top-level schema")
        return failures
    if report.get("schema_version") != SCHEMA_VERSION:
        failures.append("checked Phase 6 report schema differs")
    expected_header = {
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase6_exact_saved_pca_restart_and_new_workspace_portability_complete_author_operated",
        "observed_at": "2026-08-24",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "observation_authority": "author_operated_three_fresh_local_oss_application_processes",
    }
    if any(report.get(name) != value for name, value in expected_header.items()):
        failures.append("checked Phase 6 report header authority differs")
    claim_projection = {
        "claim_boundary": report.get("claim_boundary"),
        "nonclaims": report.get("nonclaims"),
    }
    if (
        report.get("claim_boundary")
        != "Author-operated exact exploratory PCA workflow execution, fresh-process restart, private project "
        "export, new-workspace import, artifact-bound rerun, and descriptive block summary for this exact "
        "33-spectrum acquisition corpus only."
        or report.get("nonclaims")
        != [
            "non_author_physical_action_2",
            "botanical_authenticity_or_population_result",
            "instrument_drift_or_causal_order_effect",
            "classification_or_plsda_result",
            "redistribution_permission",
            "public_corpus_or_project_package",
        ]
        or _json_digest(claim_projection) != EXPECTED_CLAIM_BOUNDARY_SHA256
    ):
        failures.append("checked Phase 6 claim and nonclaim boundary differs")
    private_authority = report.get("private_evidence_authority")
    if (
        private_authority
        != {
            "private_report_published": False,
            "private_report_sha256": "ccaddd264b24495f6c815a390b33bb20f04ca089410b3054d93476db967ba55c",
            "private_report_size_bytes": 5167728,
        }
        or _json_digest(private_authority) != EXPECTED_PRIVATE_AUTHORITY_SHA256
    ):
        failures.append("checked Phase 6 private-evidence authority differs")
    portability = report.get("workflow_and_artifact_portability")
    if (
        portability
        != {
            "saved_snapshot_archive_version": "0.4",
            "saved_version_number": 2,
            "private_archive_size_bytes": 346201,
            "private_archive_sha256": "ca0ee2b1d2eb22e4fc566a7e718e45a70600cd255197d23b63aaea2964e3f9ff",
            "restored_source_count": 33,
            "restored_version_count": 1,
            "new_workspace_reexport_succeeded": True,
            "private_reexport_size_bytes": 346333,
            "private_reexport_sha256": "5bc91599db9e2aa52fb7d4f6670484a61b362bd32bcd9db7cba0b0bfb1c7fe19",
        }
        or _json_digest(portability) != EXPECTED_PORTABILITY_SHA256
    ):
        failures.append("checked Phase 6 project/artifact portability authority differs")
    process = report.get("process_and_workspace_boundary")
    expected_process = {
        "workspace_a_initial_process": True,
        "workspace_a_fresh_restart": True,
        "workspace_b_was_absent_before_run": True,
        "workspace_b_new_database": True,
        "old_dataset_handle_used": False,
        "optional_profile_spectrochempy_loaded": False,
        "optional_profile_spectrochempy_distribution": {
            "name": "spectrochempy",
            "qualified_version": EXPECTED_SCP_VERSION,
            "initial_process_version": EXPECTED_SCP_VERSION,
            "imported_process_version": EXPECTED_SCP_VERSION,
        },
        "comparison_process_spectrochempy_import_denied": True,
        "comparison_process_distribution_absence_claimed": False,
    }
    if process != expected_process:
        failures.append("checked Phase 6 process/profile boundary differs")
    preservation = report.get("identity_preservation")
    if (
        not isinstance(preservation, dict)
        or set(preservation)
        != {
            "initial_equals_restart_equals_import",
            "source_and_selected_matrix_exact",
            "scores_loadings_variance_and_state_exact",
            "sample_identity_and_descriptive_summary_exact",
            "artifact_integrity_exact",
            "workflow_uid_remap_allowed_scientific_graph_exact",
            "target_absent",
            "import_denied_execution_equals_optional_profile",
        }
        or not all(value is True for value in preservation.values())
    ):
        failures.append("checked Phase 6 identity-preservation projection differs")
    privacy = report.get("privacy_boundary")
    if (
        not isinstance(privacy, dict)
        or set(privacy)
        != {
            "raw_or_selected_spectra_published",
            "complete_scores_or_loadings_published",
            "sample_or_pair_identities_published",
            "project_archive_or_transcript_published",
            "private_paths_database_ids_or_artifact_uids_published",
        }
        or not all(value is False for value in privacy.values())
    ):
        failures.append("checked Phase 6 privacy projection differs")
    scientific = report.get("scientific_result")
    if not isinstance(scientific, dict) or set(scientific) != {
        "source_collection",
        "selection",
        "pca",
        "descriptive_report",
        "workflow_authority",
    }:
        failures.append("checked Phase 6 scientific projection is malformed")
    else:
        source = scientific["source_collection"]
        if not isinstance(source, dict) or source != {
            "dataset_id": EXPECTED_DATASET_ID,
            "shape": EXPECTED_SOURCE_SHAPE,
            "values_sha256": EXPECTED_SOURCE_VALUES_SHA256,
            "feature_axis_sha256": EXPECTED_SOURCE_AXIS_SHA256,
            "sample_labels_sha256": EXPECTED_SAMPLE_LABELS_SHA256,
            "sample_table_sha256": EXPECTED_SAMPLE_TABLE_SHA256,
            "source_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
            "collection_definition_sha256": EXPECTED_DEFINITION_SHA256,
            "scientific_collection_sha256": EXPECTED_SCIENTIFIC_COLLECTION_SHA256,
            "target_state": "absent",
        }:
            failures.append("checked Phase 6 source projection differs")
        selection = scientific["selection"]
        if (
            not isinstance(selection, dict)
            or set(selection)
            != {
                "method",
                "requested_bounds_cm-1",
                "actual_endpoints_cm-1",
                "shape",
                "mask_sha256",
                "selected_axis_sha256",
                "selected_values_sha256",
            }
            or selection.get("method") != "interval"
            or selection.get("requested_bounds_cm-1") != [3100.0, 650.0]
            or selection.get("actual_endpoints_cm-1") != EXPECTED_ACTUAL_ENDPOINTS
            or selection.get("shape") != EXPECTED_SELECTED_SHAPE
        ):
            failures.append("checked Phase 6 selection projection differs")
        if _json_digest(selection) != EXPECTED_SELECTION_PROJECTION_SHA256:
            failures.append("checked Phase 6 exact selection authority differs")
        pca = scientific["pca"]
        if (
            not isinstance(pca, dict)
            or pca.get("scores_shape") != EXPECTED_SCORE_SHAPE
            or pca.get("loadings_shape") != EXPECTED_LOADING_SHAPE
            or pca.get("k90") != 1
            or pca.get("k_display") != 3
            or pca.get("parameters") != {"n_components": "3", "standardized": False, "scaled": False}
            or pca.get("loading_sign_convention") != "largest_absolute_loading_positive"
            or not isinstance(pca.get("replay_max_abs_difference"), (int, float))
            or not 0.0 <= pca["replay_max_abs_difference"] <= 1e-10
        ):
            failures.append("checked Phase 6 PCA projection differs")
        if _json_digest(pca) != EXPECTED_PCA_PROJECTION_SHA256:
            failures.append("checked Phase 6 exact PCA authority differs")
        descriptive = scientific["descriptive_report"]
        if (
            not isinstance(descriptive, dict)
            or descriptive.get("specimen_count") != 11
            or descriptive.get("block_count") != 3
            or descriptive.get("score_shape") != EXPECTED_SCORE_SHAPE
            or (descriptive.get("within_specimen_pairwise_distance") or {}).get("count") != 33
            or (descriptive.get("between_specimen_centroid_distance") or {}).get("count") != 55
            or descriptive.get("order_specimen_fully_aliased") is not True
            or not isinstance(descriptive.get("block_r_squared"), (int, float))
            or not 0.0 <= descriptive["block_r_squared"] <= 1.0
        ):
            failures.append("checked Phase 6 descriptive projection differs")
        if _json_digest(descriptive) != EXPECTED_DESCRIPTIVE_PROJECTION_SHA256:
            failures.append("checked Phase 6 exact descriptive authority differs")
        workflow = scientific["workflow_authority"]
        if (
            workflow
            != {
                "execution_contract_digests": {
                    "data.load_group": "86a0e358919e48ecfa0b33bd72949efd2cc39128a88ee2b331129a1ff2a58e44",
                    "selection.variable_select": "23c7daed13e970bb233aa4d25b54f47433957448ce91a9a47fcf21c376481006",
                    "model.pca": "2eb6ed1dffbcce614b2bf8efeea6f77bd99179807a56f0affc26a79be1025b2c",
                },
                "portable_projection_sha256": "3e90027a1f905219885e51f4efb76270ec7b86cf909528c813d56437d97b5f10",
            }
            or _json_digest(workflow) != EXPECTED_WORKFLOW_AUTHORITY_SHA256
        ):
            failures.append("checked Phase 6 workflow authority differs")
    text = payload.decode("utf-8", errors="replace")
    for forbidden in ("private-input", "/Users/", '"workflow_id"', '"artifact_uid"', '"sample_id"', '"specimen_id"'):
        if forbidden in text:
            failures.append(f"checked Phase 6 report leaks forbidden private token {forbidden!r}")
    return failures


def _check_public(args: argparse.Namespace) -> int:
    failures = validate_checked_report(args.report)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Avatar OMNIC Phase 6B checked report: PASS")
    return 0


def main() -> int:
    if os.getenv("SPECTRA_PHASE6_DENY_SCP_IMPORT") == "1":
        _install_scp_import_denial()
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
    stage_a = commands.add_parser("stage-a")
    stage_a.add_argument("--project-id", type=int, required=True)
    stage_a.add_argument("--experiment-id", type=int, required=True)
    stage_a.add_argument("--archive", type=Path, required=True)
    stage_a.add_argument("--result", type=Path, required=True)
    restart = commands.add_parser("stage-restart")
    restart.add_argument("--project-id", type=int, required=True)
    restart.add_argument("--experiment-id", type=int, required=True)
    restart.add_argument("--result", type=Path, required=True)
    imported = commands.add_parser("stage-import")
    imported.add_argument("--archive", type=Path, required=True)
    imported.add_argument("--reexport", type=Path, required=True)
    imported.add_argument("--result", type=Path, required=True)
    check = commands.add_parser("check-public")
    check.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return _run(args)
    if args.command == "stage-a":
        return _stage_a(args)
    if args.command == "stage-restart":
        return _stage_restart(args)
    if args.command == "stage-import":
        return _stage_import(args)
    return _check_public(args)


if __name__ == "__main__":
    raise SystemExit(main())
