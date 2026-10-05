#!/usr/bin/env python3
"""Qualify zero-fit saved-model restart and project portability for Avatar.

The exact reviewed Phase 6 project archive and Phase 7 private canonical
fitted-artifact report are received as private inputs.  Stage A restores the
Phase 6 PCA artifact into a previously absent workspace, installs the Phase 7
PLS-DA full refit through the generic canonical bridge, and replaces the
training workflow with one application-only DAG.  Fresh processes then rerun
that saved DAG in restarted workspace A and imported workspace B.

Complete matrices, labels, model UUIDs, database identities, archives, and
paths remain in mode-0600 private custody.  The checked report is path-free and
row-free.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.abc
import importlib.metadata as importlib_metadata
import io
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.core.file_io import open_regular_readonly

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-phase8-application/1"
WORKFLOW_NAME = "Avatar Phase 8 saved-model application"
WORKFLOW_DESCRIPTION = "Exact 3100-650 cm-1 selection with saved PCA and canonical PLS-DA application"
SAVE_DESCRIPTION = "Phase 8B zero-fit saved-model restart and portability qualification"
RUNTIME_IMPLEMENTATION_COMMIT = "41adf847719f5d6e90a8178b1b3ba935e13b0179"
CHECKED_REPORT_SHA256 = "31799e1ffd94abc2db4bb7ea81a5761c3cde5e97c81ab96a189e94614dbe01c9"

EXPECTED_PHASE6_PUBLIC_SHA256 = "19d8e09e22ee9d9eff7f1deed4b2ba4422e7426b84c6f6928d83211341fb9771"
EXPECTED_PHASE6_PRIVATE_SHA256 = "ccaddd264b24495f6c815a390b33bb20f04ca089410b3054d93476db967ba55c"
EXPECTED_PHASE6_ARCHIVE_SHA256 = "ca0ee2b1d2eb22e4fc566a7e718e45a70600cd255197d23b63aaea2964e3f9ff"
EXPECTED_PHASE7_PUBLIC_SHA256 = "2ecbc6f078be8faaec675750b3c6bb5c4a5b6240a932adae7d7d50e9dadb52cb"
EXPECTED_PHASE7_PRIVATE_SHA256 = "ccc0042b8f65d0b662a44066cd7dcea2c4baa0b12edbf530fa7f96b0795076d4"
EXPECTED_SCP_VERSION = "0.8.1"
OPERATOR_CODE = "YF"
EXPECTED_RUNTIME_DISTRIBUTIONS = {
    "numpy": "1.26.4",
    "scikit-learn": "1.9.0",
    "scipy": "1.17.1",
    "spectra-sherpa": "0.5.30",
    "spectrasherpa-server": "0.5.0",
}

EXPECTED_SOURCE_SHAPE = [33, 1868]
EXPECTED_SELECTED_SHAPE = [33, 1270]
EXPECTED_PCA_SCORE_SHAPE = [33, 3]
EXPECTED_PLSDA_RESPONSE_SHAPE = [33, 11]
EXPECTED_SOURCE_VALUES_SHA256 = "66f6f64a08cb0a875ba654f7e9e66949a698c435292cf3fb8cd4c7ae784e2b76"
EXPECTED_SOURCE_AXIS_SHA256 = "f0fb31d4690ff770f518574e19353ee4b2bb6d46f43abdbd90a18aef6293ed6b"
EXPECTED_SELECTED_VALUES_SHA256 = "f9f9766b56023a7bbdfc35be2d440fc06956826555b33ba8d418a55645c06b73"
EXPECTED_SELECTED_AXIS_SHA256 = "c568c142241172cd1d995b9ad4ceb96f4e05579954e23695a51b0ba4595e4df7"
EXPECTED_SELECTION_MASK_SHA256 = "509b48e5d79961679c2d55f868b2d9bc18f77ad721ada8172f57e887c6e06a36"
EXPECTED_SAMPLE_TABLE_SHA256 = "1b13a7b34c0d9034bc06f397d9fb1bce1b3aa00491f7a50446a8769c483a5d38"
EXPECTED_SAMPLE_LABELS_SHA256 = "46a8bf29309c9756b6852a1391d3ab7a76e0c5ac94a87179a90a5090cd9f1573"
EXPECTED_DEFINITION_SHA256 = "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"
EXPECTED_SOURCE_MANIFEST_SHA256 = "199a9b04f7abacdc0ab73eef70fec44133abcd041f87c7e1855af3b753e8fcd8"
EXPECTED_SCIENTIFIC_COLLECTION_SHA256 = "144889847a230ed56ee28e532f790e7dc15883a19328c2cfcc3eb84e1b08e243"
EXPECTED_DATASET_ID = "avatar-essential-oils/1:canonical-phase4"

MAX_PRIVATE_JSON_BYTES = 32 * 1024 * 1024
MAX_PRIVATE_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PUBLIC_REPORT_BYTES = 1024 * 1024


class _DenySpectroChemPy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == "spectrochempy" or fullname.startswith("spectrochempy."):
            raise ModuleNotFoundError("Phase 8 application processes deny SpectroChemPy")
        return None


def _scp_loaded() -> bool:
    return any(name == "spectrochempy" or name.startswith("spectrochempy.") for name in sys.modules)


def _install_scp_denial() -> None:
    if _scp_loaded():
        raise RuntimeError("SpectroChemPy was loaded before the Phase 8 guard")
    sys.meta_path.insert(0, _DenySpectroChemPy())


def _installed_scp_version() -> str:
    """Attest the optional distribution without importing its package."""

    try:
        version = importlib_metadata.version("spectrochempy")
    except importlib_metadata.PackageNotFoundError as exc:
        raise RuntimeError("Phase 8 optional-installed profile lacks SpectroChemPy") from exc
    if version != EXPECTED_SCP_VERSION:
        raise RuntimeError("Phase 8 optional-installed SpectroChemPy version differs")
    if _scp_loaded():
        raise RuntimeError("SpectroChemPy was imported while attesting its distribution")
    return version


def _runtime_identity() -> dict[str, Any]:
    observed = {name: importlib_metadata.version(name) for name in EXPECTED_RUNTIME_DISTRIBUTIONS}
    if observed != EXPECTED_RUNTIME_DISTRIBUTIONS:
        raise RuntimeError("Phase 8 numerical/application distribution identity differs")
    return {
        "schema_version": "spectrasherpa-avatar-phase8-runtime/1",
        "source_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "operator_code": OPERATOR_CODE,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "distributions": observed,
    }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _pretty_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _json_digest(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _array_digest(value: Any, *, dtype: str = "<f8") -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype=dtype))
    return _sha256(array.tobytes(order="C"))


def _training_data_hash(value: Any) -> str:
    array = np.asarray(value, dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("utf-8"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _bool_digest(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype=np.bool_)).astype(np.uint8)
    return _sha256(array.tobytes(order="C"))


def _parse_unique_json(payload: bytes, label: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _private_path(path: Path, *, require_absent: bool) -> Path:
    lexical = Path(os.path.abspath(path))
    parent = lexical.parent
    observed_parent = parent.lstat()
    if (
        stat.S_ISLNK(observed_parent.st_mode)
        or not stat.S_ISDIR(observed_parent.st_mode)
        or (os.name != "nt" and stat.S_IMODE(observed_parent.st_mode) & 0o077)
        or parent.resolve(strict=True) != parent
    ):
        raise ValueError("private path parent must be a mode-private non-linked directory")
    try:
        observed = lexical.lstat()
    except FileNotFoundError:
        if not require_absent:
            raise ValueError("private input is absent")
    else:
        if require_absent:
            raise ValueError("private output must be absent")
        if (
            stat.S_ISLNK(observed.st_mode)
            or not stat.S_ISREG(observed.st_mode)
            or (os.name != "nt" and stat.S_IMODE(observed.st_mode) != 0o600)
        ):
            raise ValueError("private input must be a mode-0600 regular non-linked file")
    return lexical


def _read_private(path: Path, *, limit: int) -> bytes:
    lexical = _private_path(path, require_absent=False)
    before = lexical.lstat()
    if before.st_size < 1 or before.st_size > limit:
        raise ValueError("private input exceeds its byte contract")
    descriptor = open_regular_readonly(lexical)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != before.st_size
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("private input changed during admission")
        retained = bytearray()
        while len(retained) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(retained)))
            if not chunk:
                break
            retained.extend(chunk)
    finally:
        os.close(descriptor)
    if len(retained) != before.st_size or len(retained) > limit:
        raise ValueError("private input changed or exceeded its byte contract")
    return bytes(retained)


def _read_public(path: Path, *, limit: int) -> bytes:
    lexical = Path(os.path.abspath(path))
    try:
        before = lexical.lstat()
    except OSError as exc:
        raise ValueError(f"public input is unreadable: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("public input must be a regular non-linked file")
    if before.st_size < 1 or before.st_size > limit:
        raise ValueError("public input exceeds its byte contract")
    descriptor = open_regular_readonly(lexical)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != before.st_size
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("public input changed during admission")
        retained = bytearray()
        while len(retained) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(retained)))
            if not chunk:
                break
            retained.extend(chunk)
    finally:
        os.close(descriptor)
    if len(retained) != before.st_size or len(retained) > limit:
        raise ValueError("public input changed or exceeded its byte contract")
    return bytes(retained)


def _atomic_write(path: Path, payload: bytes, *, private: bool, limit: int) -> dict[str, Any]:
    if not payload or len(payload) > limit:
        raise ValueError("output exceeds its byte contract")
    if private:
        destination = _private_path(path, require_absent=True)
    else:
        destination = Path(os.path.abspath(path))
        if destination.parent.resolve(strict=True) != destination.parent:
            raise ValueError("public output parent must not traverse a link")
        if destination.exists() or destination.is_symlink():
            raise ValueError("public output must be absent")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600 if private else 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"size_bytes": len(payload), "sha256": _sha256(payload)}


def _require_input(payload: bytes, expected_sha256: str, label: str) -> None:
    if _sha256(payload) != expected_sha256:
        raise ValueError(f"{label} differs from its reviewed SHA-256 authority")


def _client() -> Any:
    from starlette.testclient import TestClient

    from spectra_sherpa.app.main import app

    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53108))


def _require_response(response: Any, status: int, label: str) -> Any:
    if response.status_code != status:
        raise RuntimeError(f"{label} failed ({response.status_code}): {response.text[-2000:]}")
    return response


def _require_empty_registry() -> None:
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    if dataset_registry.retained_bytes != 0:
        raise RuntimeError("fresh Phase 8 process unexpectedly retained a dataset handle")


def _install_fitted_lifecycle_denial() -> dict[str, Any]:
    """Replace every registered fitted-state entry point before execution."""

    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    ensure_type_registry_loaded()
    attempted: list[str] = []

    def denied(self: Any, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempted.append(type(self).__name__)
        raise RuntimeError("Phase 8 prohibits every fitted lifecycle entry point")

    patched: list[str] = []
    for operation_id, node_class in sorted(node_registry._nodes.items()):
        if hasattr(node_class, "fit_fitted_state"):
            setattr(node_class, "fit_fitted_state", denied)
            patched.append(operation_id)

    from spectra_sherpa.app.services.dag import fold_graph_executor

    def denied_refit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempted.append("canonical-refit")
        raise RuntimeError("Phase 8 prohibits canonical validation/refit execution")

    for name in (
        "execute_candidate_validation",
        "execute_candidate_validation_with_private_classification_trace",
        "execute_selected_candidate_full_refit",
    ):
        if hasattr(fold_graph_executor, name):
            setattr(fold_graph_executor, name, denied_refit)
    return {"patched_operation_count": len(patched), "attempted": attempted}


def _configure_workspace(workspace: Path) -> None:
    if any(name.startswith("spectra_sherpa.app.") for name in sys.modules):
        raise RuntimeError("workspace must be configured before application modules are loaded")
    os.environ.update(
        {
            "DATA_DIR": str(workspace),
            "DATABASE_URL": f"sqlite+aiosqlite:///{workspace / 'spectra_platform.db'}",
            "APP_MODE": "local",
            "MPLCONFIGDIR": str(workspace / ".matplotlib"),
        }
    )


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


def _application_workflow_payload(
    *, project_id: int, experiment_id: int, pca_model_id: str, plsda_model_id: str
) -> dict[str, Any]:
    return {
        "name": WORKFLOW_NAME,
        "description": WORKFLOW_DESCRIPTION,
        "status": "draft",
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
                "node_id": "pca_apply",
                "node_type": "model.load_apply",
                "label": "Apply retained PCA",
                "parameters": {"model_id": pca_model_id},
                "position_x": 540,
                "position_y": -100,
            },
            {
                "node_id": "plsda_apply",
                "node_type": "model.load_apply",
                "label": "Apply canonical full-refit PLS-DA",
                "parameters": {"model_id": plsda_model_id},
                "position_x": 540,
                "position_y": 100,
            },
        ],
        "edges": [
            {"from_node_id": "source", "to_node_id": "window", "from_output": "default", "to_input": "X"},
            {
                "from_node_id": "window",
                "to_node_id": "pca_apply",
                "from_output": "X_selected",
                "to_input": "X_new",
            },
            {
                "from_node_id": "window",
                "to_node_id": "plsda_apply",
                "from_output": "X_selected",
                "to_input": "X_new",
            },
        ],
        "create_version": False,
        "change_description": SAVE_DESCRIPTION,
    }


def _portable_workflow(workflow: Mapping[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for item in workflow.get("nodes", []):
        if not isinstance(item, Mapping):
            raise ValueError("application workflow has a malformed node")
        parameters = deepcopy(dict(item.get("parameters") or {}))
        if item.get("node_type") == "data.load_group":
            parameters["experiment_id"] = "<portable-experiment-id>"
        if item.get("node_type") == "model.load_apply":
            parameters["model_id"] = f"<portable-{str(item.get('node_id')).replace('_apply', '')}-model-id>"
        nodes.append({"node_id": item.get("node_id"), "node_type": item.get("node_type"), "parameters": parameters})
    edges = [
        {
            "from_node_id": item.get("from_node_id"),
            "to_node_id": item.get("to_node_id"),
            "from_output": item.get("from_output"),
            "to_input": item.get("to_input"),
        }
        for item in workflow.get("edges", [])
        if isinstance(item, Mapping)
    ]
    projection = {
        "nodes": sorted(nodes, key=lambda item: str(item["node_id"])),
        "edges": sorted(edges, key=_json_digest),
    }
    expected = _application_workflow_payload(
        project_id=0,
        experiment_id=0,
        pca_model_id="pca",
        plsda_model_id="plsda",
    )
    expected_projection = {
        "nodes": sorted(
            [
                {
                    "node_id": item["node_id"],
                    "node_type": item["node_type"],
                    "parameters": (
                        {**item["parameters"], "experiment_id": "<portable-experiment-id>"}
                        if item["node_type"] == "data.load_group"
                        else (
                            {
                                **item["parameters"],
                                "model_id": f"<portable-{item['node_id'].replace('_apply', '')}-model-id>",
                            }
                            if item["node_type"] == "model.load_apply"
                            else item["parameters"]
                        )
                    ),
                }
                for item in expected["nodes"]
            ],
            key=lambda item: str(item["node_id"]),
        ),
        "edges": sorted(expected["edges"], key=_json_digest),
    }
    if projection != expected_projection:
        raise ValueError("saved workflow differs from the frozen application-only DAG")
    return projection


def _contract_digests() -> dict[str, str]:
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    ensure_type_registry_loaded()
    return {
        operation: node_registry.get_metadata(operation).resolved_execution_contract().digest
        for operation in ("data.load_group", "selection.variable_select", "model.load_apply")
    }


async def _bridge_phase7(
    *,
    project_id: int,
    experiment_id: int,
    phase7: Mapping[str, Any],
) -> tuple[Any, dict[str, Any]]:
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401
    from spectra_sherpa.app.db.session import async_session
    from spectra_sherpa.app.services.canonical_model_bridge import (
        bridge_canonical_plsda_artifact,
        persist_canonical_plsda_bridge,
    )
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
    from spectra_sherpa.sdk.validate import make_leave_one_group_out_classification_plan

    canonical = phase7.get("canonical_fitted_artifact")
    if not isinstance(canonical, Mapping) or set(canonical) != {"manifest", "artifact_sha256", "state_bytes_utf8"}:
        raise ValueError("Phase 7 private canonical-artifact record is malformed")
    manifest = canonical.get("manifest")
    states = canonical.get("state_bytes_utf8")
    if not isinstance(manifest, Mapping) or not isinstance(states, Mapping):
        raise ValueError("Phase 7 private canonical-artifact members are malformed")
    artifact = CanonicalFittedArtifact.from_serialized(
        _canonical_json(manifest),
        {str(node_id): str(payload).encode("utf-8") for node_id, payload in states.items()},
    )
    if artifact.artifact_digest != canonical.get("artifact_sha256"):
        raise ValueError("Phase 7 canonical artifact digest differs")

    async with async_session() as session:
        loaded = await load_project_dataset(
            session,
            user_id=1,
            experiment_id=experiment_id,
            stage="raw",
            asset_id="spectrum",
            strict_prepared_data=True,
        )
        if loaded.project_id != project_id or list(loaded.dataset.shape) != EXPECTED_SOURCE_SHAPE:
            raise ValueError("restored Phase 6 source is not the exact training collection")
        attached = attach_target_dataset(
            loaded.dataset,
            None,
            target_type="categorical",
            node_id="attach-supervision",
            target_source="sample_table_column",
            target_column="specimen_id",
            group_column="block",
        )
        binding = bind_sample_table_supervision(
            attached,
            target_column="specimen_id",
            target_type="categorical",
            group_column="block",
        )
        plan = make_leave_one_group_out_classification_plan(
            binding.target,
            binding.groups,
            require_one_per_class_group=True,
        )
        SpectralDatasetCapability.from_dataset(
            attached,
            custody_id="avatar-essential-oils-phase7",
            dataset_ref_digest=binding.digest,
            split_plan_digest=plan.digest,
            groups=binding.groups,
        )
        validation = phase7.get("validation")
        if not isinstance(validation, Mapping) or validation.get("split_plan_digest") != plan.digest:
            raise ValueError("restored training capability differs from reviewed Phase 7")
        selector = node_registry.create_node(
            "selection.variable_select",
            "window",
            {"method": "interval", "region_start": 3100.0, "region_end": 650.0},
        )
        selection_result = await selector.execute(X=attached)
        outputs = selection_result.outputs
        mask = np.asarray(outputs["mask"], dtype=np.bool_)
        selected = outputs["default"]
        if (
            list(selected.shape) != EXPECTED_SELECTED_SHAPE
            or _array_digest(selected.X) != EXPECTED_SELECTED_VALUES_SHA256
            or _bool_digest(mask) != EXPECTED_SELECTION_MASK_SHA256
        ):
            raise ValueError("Phase 8 stateless selection differs from the reviewed authority")
        bridge = bridge_canonical_plsda_artifact(
            artifact,
            graph_payload=dict(phase7["graph"]),
            training_dataset=attached,
            experiment_id=experiment_id,
            asset_id="spectrum",
            validation_execution=dict(validation),
            original_capability_metadata=dict(phase7["original_capability_metadata"]),
            custody_id="avatar-essential-oils-phase7",
            feature_mask=mask.tolist(),
            selection_report=outputs["selection_report"],
        )

        async def re_admit() -> Any:
            fresh = await load_project_dataset(
                session,
                user_id=1,
                experiment_id=experiment_id,
                stage="raw",
                asset_id="spectrum",
                strict_prepared_data=True,
            )
            return attach_target_dataset(
                fresh.dataset,
                None,
                target_type="categorical",
                node_id="attach-supervision",
                target_source="sample_table_column",
                target_column="specimen_id",
                group_column="block",
            )

        row, receipt = await persist_canonical_plsda_bridge(
            session,
            user_id=1,
            project_id=project_id,
            training_dataset_id=experiment_id,
            bridge=bridge,
            re_admit_training_dataset=re_admit,
            display_name="Avatar Phase 7 canonical full-refit PLS-DA",
        )
        return row, receipt


def _model_inventory(client: Any, project_id: int) -> dict[str, dict[str, Any]]:
    items = _require_response(
        client.get("/api/v1/models/select", params={"project_id": project_id}),
        200,
        "model inventory",
    ).json()
    if not isinstance(items, list) or len(items) != 2:
        raise ValueError("Phase 8 requires exactly two active project models")
    by_type = {str(item.get("model_type")): item for item in items if isinstance(item, Mapping)}
    if set(by_type) != {"pca", "plsda"} or len(by_type) != 2:
        raise ValueError("Phase 8 requires exactly one active PCA and one active PLS-DA artifact")
    return by_type


def _load_reviewed_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    phase6_private_bytes = _read_private(args.phase6_private_report, limit=MAX_PRIVATE_JSON_BYTES)
    phase7_private_bytes = _read_private(args.phase7_private_report, limit=MAX_PRIVATE_JSON_BYTES)
    _require_input(phase6_private_bytes, EXPECTED_PHASE6_PRIVATE_SHA256, "Phase 6 private report")
    _require_input(phase7_private_bytes, EXPECTED_PHASE7_PRIVATE_SHA256, "Phase 7 private report")
    return (
        _parse_unique_json(phase6_private_bytes, "Phase 6 private report"),
        _parse_unique_json(phase7_private_bytes, "Phase 7 private report"),
    )


def _stage_a(args: argparse.Namespace) -> int:
    _install_scp_denial()
    scp_version = _installed_scp_version()
    runtime_identity = _runtime_identity()
    _require_empty_registry()
    fit_guard = _install_fitted_lifecycle_denial()
    phase6_archive = _read_private(args.phase6_archive, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    _require_input(phase6_archive, EXPECTED_PHASE6_ARCHIVE_SHA256, "Phase 6 archive")
    phase6_private, phase7_private = _load_reviewed_inputs(args)

    with _client() as client:
        imported = _require_response(
            client.post(
                "/api/v1/projects/import",
                files={"file": ("avatar-phase6.sherpa", io.BytesIO(phase6_archive), "application/zip")},
            ),
            201,
            "Phase 6 workspace import",
        ).json()
        project_id = int(imported["id"])
        experiments = [item for item in imported.get("experiments", []) if item.get("file_count") == 33]
        workflows = list(imported.get("workflows", []))
        models = list(imported.get("models", []))
        if len(experiments) != 1 or len(workflows) != 1 or len(models) != 1 or models[0].get("model_type") != "pca":
            raise ValueError("Phase 6 archive did not restore one source, workflow, and PCA model")
        experiment_id = int(experiments[0]["id"])
        workflow_id = int(workflows[0]["id"])
        pca_model_id = str(models[0]["artifact_uid"])

        plsda_row, bridge_receipt = asyncio.run(
            _bridge_phase7(project_id=project_id, experiment_id=experiment_id, phase7=phase7_private)
        )
        inventory = _model_inventory(client, project_id)
        if (
            inventory["pca"]["artifact_uid"] != pca_model_id
            or inventory["plsda"]["artifact_uid"] != plsda_row.artifact_uid
        ):
            raise ValueError("active model inventory differs from the restored and bridged artifacts")
        payload = _application_workflow_payload(
            project_id=project_id,
            experiment_id=experiment_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_row.artifact_uid,
        )
        _require_response(
            client.put(f"/api/v1/workflows/{workflow_id}", json=payload),
            200,
            "application workflow replacement",
        )
        workflow = _require_response(client.get(f"/api/v1/workflows/{workflow_id}"), 200, "workflow reload").json()
        portable = _portable_workflow(workflow)
        preflight = _require_response(
            client.post(f"/api/v1/workflows/{workflow_id}/preflight"), 200, "application workflow preflight"
        ).json()
        if not preflight.get("is_valid") or preflight.get("error_count") != 0:
            raise ValueError("application workflow failed exact typed preflight")
        execution = _require_response(
            client.post(f"/api/v1/workflows/{workflow_id}/execute", json={}),
            200,
            "initial application workflow",
        ).json()
        result = _summarize_execution(
            client,
            execution,
            project_id=project_id,
            experiment_id=experiment_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_row.artifact_uid,
            phase6_private=phase6_private,
            phase7_private=phase7_private,
            portable_workflow=portable,
        )
        saved = _require_response(
            client.post(
                f"/api/v1/projects/{project_id}/save",
                json={"change_description": SAVE_DESCRIPTION, "include_raw_data": True},
            ),
            201,
            "Phase 8 project save",
        ).json()
        exported = _require_response(
            client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved['id']}"),
            200,
            "Phase 8 saved project export",
        )
        with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
            project = _parse_unique_json(archive.read("project.json"), "Phase 8 project snapshot")
        if (project.get("archive_format") or {}).get("version") != "0.4" or len(project.get("models", [])) != 2:
            raise ValueError("Phase 8 saved archive is not the exact /0.4 two-model project")
    if fit_guard["attempted"]:
        raise ValueError("Phase 8 invoked a prohibited fitted lifecycle")
    archive_record = _atomic_write(args.archive, exported.content, private=True, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    _atomic_write(
        args.result,
        _pretty_json(
            {
                "stage": "workspace_a_initial_zero_fit_process",
                "project_id": project_id,
                "experiment_id": experiment_id,
                "workflow_id": workflow_id,
                "pca_model_id": pca_model_id,
                "plsda_model_id": plsda_row.artifact_uid,
                "saved_version_number": saved["version_number"],
                "archive": archive_record,
                "spectrochempy_loaded": _scp_loaded(),
                "spectrochempy_import_denied": True,
                "spectrochempy_distribution_version": scp_version,
                "runtime_attestation": runtime_identity,
                "fitted_lifecycle": {"patched_operation_count": fit_guard["patched_operation_count"], "attempts": 0},
                "bridge_receipt": bridge_receipt,
                **result,
            }
        ),
        private=True,
        limit=MAX_PRIVATE_JSON_BYTES,
    )
    return 0


def _result_mapping(execution: Mapping[str, Any], node_id: str) -> Mapping[str, Any]:
    results = execution.get("results")
    if not isinstance(results, Mapping) or not isinstance(results.get(node_id), Mapping):
        raise ValueError(f"workflow result is missing {node_id}")
    return results[node_id]


def _finite_matrix(value: Any, shape: list[int], label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if list(array.shape) != shape or not np.isfinite(array).all():
        raise ValueError(f"{label} differs from expected finite shape {shape}")
    return array


def _require_exact_workflow_science(
    execution: Mapping[str, Any],
    reviewed_science: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_result = _result_mapping(execution, "source")
    window_result = _result_mapping(execution, "window")
    source_wire = source_result.get("default")
    selected_wire = window_result.get("X_selected")
    if not isinstance(source_wire, Mapping) or not isinstance(selected_wire, Mapping):
        raise ValueError("saved workflow omitted its source or selected dataset wire")

    source_X = _finite_matrix(source_wire.get("data"), EXPECTED_SOURCE_SHAPE, "workflow source X")
    selected_X = _finite_matrix(selected_wire.get("data"), EXPECTED_SELECTED_SHAPE, "workflow selected X")
    source_axis_wire = source_wire.get("x_axis")
    selected_axis_wire = selected_wire.get("x_axis")
    source_y = source_wire.get("y_axis")
    selected_y = selected_wire.get("y_axis")
    if not all(isinstance(value, Mapping) for value in (source_axis_wire, selected_axis_wire, source_y, selected_y)):
        raise ValueError("saved workflow axes are malformed")
    source_axis = np.asarray(source_axis_wire.get("data"), dtype=np.float64)
    selected_axis = np.asarray(selected_axis_wire.get("data"), dtype=np.float64)
    if (
        source_axis.shape != (EXPECTED_SOURCE_SHAPE[1],)
        or selected_axis.shape != (EXPECTED_SELECTED_SHAPE[1],)
        or not np.isfinite(source_axis).all()
        or not np.isfinite(selected_axis).all()
        or not np.all(np.diff(source_axis) < 0.0)
        or source_axis_wire.get("axis_class") != "SpectralAxis"
        or selected_axis_wire.get("axis_class") != "SpectralAxis"
        or source_axis_wire.get("title") != "Wavenumber"
        or selected_axis_wire.get("title") != "Wavenumber"
        or source_axis_wire.get("units") != "cm-1"
        or selected_axis_wire.get("units") != "cm-1"
    ):
        raise ValueError("saved workflow spectral axes differ from the exact FTIR authority")
    for wire in (source_wire, selected_wire):
        if (
            wire.get("units") != "absorbance"
            or wire.get("data_role") != "X_spectra"
            or wire.get("data_modality") != "spectra"
            or wire.get("target_context") != {}
            or wire.get("is_time_series") is not False
        ):
            raise ValueError("saved workflow dataset semantics differ from exact absorbance spectra")
    if source_wire.get("dataset_id") != EXPECTED_DATASET_ID:
        raise ValueError("saved workflow source dataset identity differs")

    labels = source_y.get("labels")
    table = source_y.get("sample_table")
    if (
        not isinstance(labels, list)
        or len(labels) != EXPECTED_SOURCE_SHAPE[0]
        or not isinstance(table, Mapping)
        or selected_y.get("labels") != labels
        or selected_y.get("sample_table") != table
        or selected_y.get("include_mask") != source_y.get("include_mask")
    ):
        raise ValueError("saved workflow changed exact sample identity during selection")
    source_collection = (source_wire.get("metadata") or {}).get("source_collection")
    if not isinstance(source_collection, Mapping):
        raise ValueError("saved workflow source lacks its collection identity")

    mask = np.asarray(window_result.get("mask"))
    if mask.shape != (EXPECTED_SOURCE_SHAPE[1],) or mask.dtype.kind != "b":
        raise ValueError("saved workflow interval mask is not exact boolean state")
    if (
        _bool_digest(mask) != EXPECTED_SELECTION_MASK_SHA256
        or not np.array_equal(selected_X, source_X[:, mask])
        or not np.array_equal(selected_axis, source_axis[mask])
    ):
        raise ValueError("saved workflow selected dataset is not the exact source projection")
    selection_report = window_result.get("selection_report")
    if (
        not isinstance(selection_report, Mapping)
        or selection_report.get("method") != "interval"
        or selection_report.get("reference_samples") != EXPECTED_SOURCE_SHAPE[0]
        or selection_report.get("reference_features") != EXPECTED_SOURCE_SHAPE[1]
        or selection_report.get("selected_features") != EXPECTED_SELECTED_SHAPE[1]
        or selection_report.get("feature_axis_values_sha256") != EXPECTED_SOURCE_AXIS_SHA256
        or selection_report.get("feature_mask_sha256") != EXPECTED_SELECTION_MASK_SHA256
    ):
        raise ValueError("saved workflow selection report differs from the frozen interval")

    observed_source = {
        "shape": EXPECTED_SOURCE_SHAPE,
        "values_sha256": _array_digest(source_X),
        "feature_axis_sha256": _array_digest(source_axis),
        "sample_labels_sha256": _json_digest(labels),
        "sample_table_sha256": _json_digest(table),
        "dataset_id": source_wire.get("dataset_id"),
        "target_state": "absent",
        "collection_definition_sha256": source_collection.get("collection_definition_sha256"),
        "source_manifest_sha256": source_collection.get("source_manifest_sha256"),
        "scientific_collection_sha256": source_collection.get("scientific_collection_sha256"),
    }
    observed_selection = {
        "method": "interval",
        "requested_bounds_cm-1": [3100.0, 650.0],
        "actual_endpoints_cm-1": [float(selected_axis[0]), float(selected_axis[-1])],
        "shape": EXPECTED_SELECTED_SHAPE,
        "selected_values_sha256": _array_digest(selected_X),
        "selected_axis_sha256": _array_digest(selected_axis),
        "mask_sha256": _bool_digest(mask),
    }
    if observed_source != reviewed_science.get("source_collection") or observed_selection != reviewed_science.get(
        "selection"
    ):
        raise ValueError("actual saved-workflow source or selection differs from reviewed Phase 6")
    return observed_source, observed_selection


def _require_pca_manifest_science(
    manifest: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    *,
    expected_integrity_sha256: str,
    expected_serializer: str,
    expected_training_dataset_id: int,
    expected_training_data_hash: str,
    expected_feature_axis_sha256: str,
    expected_feature_mask_sha256: str,
    expected_loadings_sha256: str,
    expected_explained_variance_ratio_sha256: str,
    expected_eigenvalues_sha256: str,
) -> str:
    """Validate and digest the storage-independent PCA manifest authority."""

    required_arrays = {"loadings", "explained_variance_ratio", "explained_variance", "mean", "scores"}
    if set(arrays) != required_arrays:
        raise ValueError("persisted PCA decoded array inventory differs")
    projected_arrays: dict[str, np.ndarray] = {}
    for name, value in arrays.items():
        observed = np.asarray(value)
        if observed.dtype != np.dtype("float64") or not np.isfinite(observed).all():
            raise ValueError(f"persisted PCA array {name} is not finite float64")
        projected_arrays[name] = observed
    expected_inventory = {
        name: {"shape": list(value.shape), "dtype": "float64"} for name, value in projected_arrays.items()
    }
    mask_value = manifest.get("feature_mask")
    axis_value = np.asarray(manifest.get("feature_axis"), dtype=np.float64)
    selected_value = np.asarray(manifest.get("selected_features"), dtype=np.float64)
    if (
        not isinstance(mask_value, list)
        or len(mask_value) != EXPECTED_SOURCE_SHAPE[1]
        or any(type(value) is not bool for value in mask_value)
        or axis_value.shape != (EXPECTED_SELECTED_SHAPE[1],)
        or selected_value.shape != axis_value.shape
        or not np.isfinite(axis_value).all()
        or not np.array_equal(selected_value, axis_value)
    ):
        raise ValueError("persisted PCA feature-axis or mask authority is malformed")
    mask = np.asarray(mask_value, dtype=np.bool_)
    if int(mask.sum()) != EXPECTED_SELECTED_SHAPE[1]:
        raise ValueError("persisted PCA feature mask selects the wrong feature count")

    chain = manifest.get("preprocessing_chain")
    if not isinstance(chain, list) or len(chain) != 2 or not all(isinstance(item, Mapping) for item in chain):
        raise ValueError("persisted PCA preprocessing chain is malformed")
    source_step, selection_step = chain
    source_parameters = source_step.get("parameters")
    selection_parameters = selection_step.get("parameters")
    expected_source_keys = {
        "asset_id",
        "collection_definition_sha256",
        "dataset_id",
        "file_count",
        "scientific_collection_sha256",
        "source_manifest_sha256",
        "stage",
    }
    expected_report = {
        "detected_extrema_indices": [],
        "feature_axis_values_sha256": EXPECTED_SOURCE_AXIS_SHA256,
        "feature_mask_sha256": EXPECTED_SELECTION_MASK_SHA256,
        "method": "interval",
        "parameters": {"invert": False, "method": "interval", "region_end": 650.0, "region_start": 3100.0},
        "predictive_performance_claimed": False,
        "reference_features": EXPECTED_SOURCE_SHAPE[1],
        "reference_samples": EXPECTED_SOURCE_SHAPE[0],
        "schema": "spectrasherpa.selection.variable_select.report/1",
        "score_sha256": None,
        "selected_features": EXPECTED_SELECTED_SHAPE[1],
        "selection_scope": "target_free_feature_rule_not_predictive_validation",
    }
    if (
        source_step.get("op_id") != "spectrasherpa.experiment_dataset_read/2"
        or not isinstance(source_parameters, Mapping)
        or set(source_parameters) != expected_source_keys
        or source_parameters.get("asset_id") != "spectrum"
        or source_parameters.get("file_count") != EXPECTED_SOURCE_SHAPE[0]
        or source_parameters.get("stage") != "raw"
        or source_parameters.get("dataset_id") != expected_training_dataset_id
        or source_parameters.get("collection_definition_sha256") != EXPECTED_DEFINITION_SHA256
        or source_parameters.get("source_manifest_sha256") != EXPECTED_SOURCE_MANIFEST_SHA256
        or source_parameters.get("scientific_collection_sha256") != EXPECTED_SCIENTIFIC_COLLECTION_SHA256
        or isinstance(source_parameters.get("dataset_id"), bool)
        or not isinstance(source_parameters.get("dataset_id"), int)
        or source_parameters.get("dataset_id") < 1
        or selection_step.get("op_id") != "selection.variable_select"
        or not isinstance(selection_parameters, Mapping)
        or set(selection_parameters) != {"feature_mask", "selection_report"}
        or selection_parameters.get("feature_mask") != mask_value
        or selection_parameters.get("selection_report") != expected_report
    ):
        raise ValueError("persisted PCA preprocessing authority differs")

    evr = projected_arrays["explained_variance_ratio"]
    if (
        set(manifest)
        != {
            "arrays",
            "artifact_authority",
            "artifact_uid",
            "feature_axis",
            "feature_axis_class",
            "feature_axis_title",
            "feature_axis_units",
            "feature_mask",
            "integrity_hash",
            "metrics",
            "model_type",
            "n_components",
            "n_features",
            "node_id",
            "preprocessing_chain",
            "scale_mode",
            "scaled",
            "selected_features",
            "serializer",
            "standardized",
            "training_data_hash",
        }
        or manifest.get("artifact_authority") != "workbench_native_or_imported_model"
        or manifest.get("model_type") != "pca"
        or manifest.get("node_id") != "pca"
        or manifest.get("serializer") != expected_serializer
        or manifest.get("integrity_hash") != expected_integrity_sha256
        or manifest.get("n_components") != 3
        or manifest.get("n_features") != EXPECTED_SELECTED_SHAPE[1]
        or manifest.get("standardized") is not False
        or manifest.get("scaled") is not False
        or manifest.get("scale_mode") is not None
        or manifest.get("feature_axis_class") != "SpectralAxis"
        or manifest.get("feature_axis_title") != "Wavenumber"
        or manifest.get("feature_axis_units") != "cm-1"
        or manifest.get("arrays") != expected_inventory
        or manifest.get("metrics")
        != {"cumulative_variance": np.cumsum(evr).tolist(), "explained_variance_ratio": evr.tolist()}
        or manifest.get("training_data_hash") != expected_training_data_hash
        or _array_digest(axis_value) != expected_feature_axis_sha256
        or _bool_digest(mask) != expected_feature_mask_sha256
        or _array_digest(projected_arrays["loadings"]) != expected_loadings_sha256
        or _array_digest(evr) != expected_explained_variance_ratio_sha256
        or _array_digest(projected_arrays["explained_variance"]) != expected_eigenvalues_sha256
    ):
        raise ValueError("persisted PCA manifest science differs from the reviewed authority")

    portable = deepcopy(dict(manifest))
    portable.pop("artifact_uid")
    portable["preprocessing_chain"][0]["parameters"]["dataset_id"] = "portable-training-dataset"
    return _json_digest(portable)


def _require_pca_artifact_binding(
    *,
    manifest: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    detail: Mapping[str, Any],
    inspection: Mapping[str, Any],
    phase6_private: Mapping[str, Any],
    phase6_science: Mapping[str, Any],
    expected_training_dataset_id: int,
) -> dict[str, Any]:
    """Bind the verified stored PCA bytes to the reviewed Phase 6 state."""

    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import validate_pca_fitted_state

    retained = phase6_private["workspace_a_initial"]["private"]
    reviewed = phase6_science["pca"]
    retained_state = validate_pca_fitted_state(deepcopy(retained["fitted_state"]))
    selected = _finite_matrix(retained["selected_matrix"], EXPECTED_SELECTED_SHAPE, "Phase 6 selected matrix")
    selected_axis = np.asarray(retained["selected_axis"], dtype=np.float64)
    if selected_axis.shape != (EXPECTED_SELECTED_SHAPE[1],) or not np.isfinite(selected_axis).all():
        raise ValueError("Phase 6 selected feature axis is malformed")
    if (
        _array_digest(selected) != EXPECTED_SELECTED_VALUES_SHA256
        or _array_digest(selected_axis) != EXPECTED_SELECTED_AXIS_SHA256
    ):
        raise ValueError("Phase 6 selected science differs from its frozen authority")

    expected_arrays = {
        "loadings": np.asarray(retained_state["arrays"]["loadings"], dtype=np.float64),
        "explained_variance_ratio": np.asarray(retained_state["arrays"]["explained_variance_ratio"], dtype=np.float64),
        "explained_variance": np.asarray(retained_state["arrays"]["explained_variance"], dtype=np.float64),
        "mean": np.asarray(retained_state["arrays"]["mean"], dtype=np.float64),
        "scores": np.asarray(retained["scores"], dtype=np.float64),
    }
    expected_inventory = {
        name: {"shape": list(value.shape), "dtype": "float64"} for name, value in expected_arrays.items()
    }
    if set(arrays) != set(expected_arrays):
        raise ValueError("persisted PCA decoded array inventory differs from Phase 6")
    for name, expected in expected_arrays.items():
        observed = np.asarray(arrays[name])
        if observed.dtype != np.dtype("float64") or not np.array_equal(observed, expected):
            raise ValueError(f"persisted PCA array {name} differs from reviewed Phase 6")

    inspected_manifest = inspection.get("manifest")
    inspected_arrays = inspection.get("arrays")
    if not isinstance(inspected_manifest, Mapping) or dict(inspected_manifest) != dict(manifest):
        raise ValueError("persisted PCA manifest differs from its inspected projection")
    if not isinstance(inspected_arrays, Mapping) or set(inspected_arrays) != set(expected_inventory):
        raise ValueError("persisted PCA inspected array inventory differs")
    for name, expected in expected_inventory.items():
        item = inspected_arrays[name]
        if not isinstance(item, Mapping) or {"shape": item.get("shape"), "dtype": item.get("dtype")} != expected:
            raise ValueError(f"persisted PCA inspected array {name} differs")

    mask_value = manifest.get("feature_mask")
    if (
        not isinstance(mask_value, list)
        or len(mask_value) != EXPECTED_SOURCE_SHAPE[1]
        or any(type(item) is not bool for item in mask_value)
    ):
        raise ValueError("persisted PCA feature mask is not the exact boolean authority")
    mask = np.asarray(mask_value, dtype=np.bool_)
    if int(mask.sum()) != EXPECTED_SELECTED_SHAPE[1] or _bool_digest(mask) != EXPECTED_SELECTION_MASK_SHA256:
        raise ValueError("persisted PCA feature mask differs from Phase 6")

    chain = manifest.get("preprocessing_chain")
    if not isinstance(chain, list) or len(chain) != 2 or not all(isinstance(item, Mapping) for item in chain):
        raise ValueError("persisted PCA preprocessing chain is malformed")
    source_step, selection_step = chain
    source_parameters = source_step.get("parameters")
    selection_parameters = selection_step.get("parameters")
    if (
        source_step.get("op_id") != "spectrasherpa.experiment_dataset_read/2"
        or not isinstance(source_parameters, Mapping)
        or source_parameters.get("asset_id") != "spectrum"
        or source_parameters.get("file_count") != EXPECTED_SOURCE_SHAPE[0]
        or source_parameters.get("stage") != "raw"
        or source_parameters.get("collection_definition_sha256") != EXPECTED_DEFINITION_SHA256
        or source_parameters.get("source_manifest_sha256") != EXPECTED_SOURCE_MANIFEST_SHA256
        or source_parameters.get("scientific_collection_sha256") != EXPECTED_SCIENTIFIC_COLLECTION_SHA256
        or isinstance(source_parameters.get("dataset_id"), bool)
        or not isinstance(source_parameters.get("dataset_id"), int)
        or source_parameters.get("dataset_id") < 1
        or selection_step.get("op_id") != "selection.variable_select"
        or not isinstance(selection_parameters, Mapping)
        or set(selection_parameters) != {"feature_mask", "selection_report"}
        or selection_parameters.get("feature_mask") != mask_value
    ):
        raise ValueError("persisted PCA preprocessing authority differs from Phase 6")
    selection_report = selection_parameters.get("selection_report")
    if (
        not isinstance(selection_report, Mapping)
        or selection_report.get("method") != "interval"
        or selection_report.get("reference_samples") != EXPECTED_SOURCE_SHAPE[0]
        or selection_report.get("reference_features") != EXPECTED_SOURCE_SHAPE[1]
        or selection_report.get("selected_features") != EXPECTED_SELECTED_SHAPE[1]
        or selection_report.get("feature_axis_values_sha256") != EXPECTED_SOURCE_AXIS_SHA256
        or selection_report.get("feature_mask_sha256") != EXPECTED_SELECTION_MASK_SHA256
        or selection_report.get("predictive_performance_claimed") is not False
        or selection_report.get("selection_scope") != "target_free_feature_rule_not_predictive_validation"
        or selection_report.get("parameters")
        != {"invert": False, "method": "interval", "region_end": 650.0, "region_start": 3100.0}
    ):
        raise ValueError("persisted PCA selection report differs from Phase 6")

    reviewed_evr = np.asarray(reviewed["explained_variance_ratio"], dtype=np.float64)
    reviewed_eigenvalues = np.asarray(reviewed["eigenvalues"], dtype=np.float64)
    manifest_axis = np.asarray(manifest.get("feature_axis"), dtype=np.float64)
    selected_features = np.asarray(manifest.get("selected_features"), dtype=np.float64)
    expected_training_hash = _training_data_hash(selected)
    manifest_science_sha256 = _require_pca_manifest_science(
        manifest,
        expected_arrays,
        expected_integrity_sha256=reviewed["artifact_integrity_hash"],
        expected_serializer=reviewed["artifact_serializer"],
        expected_training_dataset_id=expected_training_dataset_id,
        expected_training_data_hash=expected_training_hash,
        expected_feature_axis_sha256=_array_digest(selected_axis),
        expected_feature_mask_sha256=_bool_digest(mask),
        expected_loadings_sha256=reviewed["loadings_sha256"],
        expected_explained_variance_ratio_sha256=reviewed["explained_variance_ratio_sha256"],
        expected_eigenvalues_sha256=reviewed["eigenvalues_sha256"],
    )
    if (
        set(manifest)
        != {
            "arrays",
            "artifact_authority",
            "artifact_uid",
            "feature_axis",
            "feature_axis_class",
            "feature_axis_title",
            "feature_axis_units",
            "feature_mask",
            "integrity_hash",
            "metrics",
            "model_type",
            "n_components",
            "n_features",
            "node_id",
            "preprocessing_chain",
            "scale_mode",
            "scaled",
            "selected_features",
            "serializer",
            "standardized",
            "training_data_hash",
        }
        or manifest.get("artifact_authority") != "workbench_native_or_imported_model"
        or manifest.get("model_type") != "pca"
        or manifest.get("node_id") != "pca"
        or manifest.get("serializer") != reviewed["artifact_serializer"]
        or manifest.get("integrity_hash") != reviewed["artifact_integrity_hash"]
        or manifest.get("n_components") != 3
        or manifest.get("n_features") != EXPECTED_SELECTED_SHAPE[1]
        or manifest.get("standardized") is not False
        or manifest.get("scaled") is not False
        or manifest.get("scale_mode") is not None
        or manifest.get("feature_axis_class") != "SpectralAxis"
        or manifest.get("feature_axis_title") != "Wavenumber"
        or manifest.get("feature_axis_units") != "cm-1"
        or manifest_axis.shape != selected_axis.shape
        or selected_features.shape != selected_axis.shape
        or not np.array_equal(manifest_axis, selected_axis)
        or not np.array_equal(selected_features, selected_axis)
        or manifest.get("arrays") != expected_inventory
        or manifest.get("metrics")
        != {
            "cumulative_variance": np.cumsum(reviewed_evr).tolist(),
            "explained_variance_ratio": reviewed_evr.tolist(),
        }
        or manifest.get("training_data_hash") != expected_training_hash
        or detail.get("integrity_hash") != reviewed["artifact_integrity_hash"]
        or detail.get("training_data_hash") != expected_training_hash
        or detail.get("model_type") != "pca"
        or detail.get("n_components") != 3
        or detail.get("n_features") != EXPECTED_SELECTED_SHAPE[1]
        or inspection.get("artifact_uid") != detail.get("artifact_uid")
        or _array_digest(expected_arrays["loadings"]) != reviewed["loadings_sha256"]
        or _array_digest(expected_arrays["explained_variance_ratio"]) != reviewed["explained_variance_ratio_sha256"]
        or _array_digest(expected_arrays["explained_variance"]) != reviewed["eigenvalues_sha256"]
        or not np.array_equal(expected_arrays["explained_variance_ratio"], reviewed_evr)
        or not np.array_equal(expected_arrays["explained_variance"], reviewed_eigenvalues)
        or retained_state["state_content_digest"] != reviewed["state_content_digest"]
        or retained_state["source_contract_digest"] != reviewed["source_contract_digest"]
    ):
        raise ValueError("persisted PCA artifact is not the reviewed Phase 6 authority")

    return {
        "model_type": "pca",
        "n_features": EXPECTED_SELECTED_SHAPE[1],
        "n_components": 3,
        "artifact_integrity_sha256": manifest["integrity_hash"],
        "manifest_science_sha256": manifest_science_sha256,
        "serializer": manifest["serializer"],
        "state_content_digest": retained_state["state_content_digest"],
        "source_contract_digest": retained_state["source_contract_digest"],
        "training_data_hash": expected_training_hash,
        "feature_axis_sha256": _array_digest(selected_axis),
        "feature_mask_sha256": _bool_digest(mask),
        "loadings_sha256": _array_digest(expected_arrays["loadings"]),
        "explained_variance_ratio_sha256": _array_digest(expected_arrays["explained_variance_ratio"]),
        "eigenvalues_sha256": _array_digest(expected_arrays["explained_variance"]),
    }


def _summarize_execution(
    client: Any,
    execution: Mapping[str, Any],
    *,
    project_id: int,
    experiment_id: int,
    pca_model_id: str,
    plsda_model_id: str,
    phase6_private: Mapping[str, Any],
    phase7_private: Mapping[str, Any],
    portable_workflow: Mapping[str, Any],
) -> dict[str, Any]:
    if execution.get("status") != "completed" or execution.get("error") is not None:
        raise ValueError("saved application workflow did not complete")
    phase6_science = phase6_private["workspace_a_initial"]["scientific"]
    source, selection = _require_exact_workflow_science(execution, phase6_science)
    pca = _result_mapping(execution, "pca_apply")
    plsda = _result_mapping(execution, "plsda_apply")
    scores = _finite_matrix(pca.get("result"), EXPECTED_PCA_SCORE_SHAPE, "PCA scores")
    responses = _finite_matrix(plsda.get("result"), EXPECTED_PLSDA_RESPONSE_SHAPE, "PLS-DA responses")
    labels = plsda.get("labels")
    margins = np.asarray(plsda.get("decision_margins"), dtype=np.float64)
    if (
        not isinstance(labels, list)
        or len(labels) != 33
        or margins.shape != (33,)
        or not np.isfinite(margins).all()
        or np.any(margins < 0.0)
    ):
        raise ValueError("PLS-DA application labels or margins are malformed")
    expected_scores = np.asarray(phase6_private["workspace_a_initial"]["private"]["scores"], dtype=np.float64)
    phase6_score_max_abs = float(np.max(np.abs(scores - expected_scores)))
    if not np.allclose(scores, expected_scores, rtol=0.0, atol=1e-10):
        raise ValueError(
            "saved PCA application differs from reviewed Phase 6 scores "
            f"(max_abs={phase6_score_max_abs}, "
            f"observed={_array_digest(scores)}, expected={_array_digest(expected_scores)})"
        )
    if pca.get("model_id") != pca_model_id or plsda.get("model_id") != plsda_model_id:
        raise ValueError("saved workflow applied the wrong model identity")
    pca_detail = _require_response(client.get(f"/api/v1/models/{pca_model_id}"), 200, "PCA detail").json()
    plsda_detail = _require_response(client.get(f"/api/v1/models/{plsda_model_id}"), 200, "PLS-DA detail").json()
    pca_inspect = _require_response(client.get(f"/api/v1/models/{pca_model_id}/inspect"), 200, "PCA inspect").json()
    plsda_inspect = _require_response(
        client.get(f"/api/v1/models/{plsda_model_id}/inspect"), 200, "PLS-DA inspect"
    ).json()
    if pca_detail.get("model_type") != "pca" or plsda_detail.get("model_type") != "plsda":
        raise ValueError("saved model detail families differ")
    from spectra_sherpa.app.services.model_store import get_model_store

    pca_manifest, pca_arrays = get_model_store().load(pca_model_id, verify=True)
    pca_authority = _require_pca_artifact_binding(
        manifest=pca_manifest,
        arrays=pca_arrays,
        detail=pca_detail,
        inspection=pca_inspect,
        phase6_private=phase6_private,
        phase6_science=phase6_science,
        expected_training_dataset_id=experiment_id,
    )
    lineage = (plsda_inspect.get("manifest") or {}).get("canonical_training_lineage")
    if not isinstance(lineage, Mapping):
        raise ValueError("saved PLS-DA inspection lacks canonical lineage")
    from spectra_sherpa.app.services.dag.classification_application import (
        CLASS_RESPONSE_SEMANTICS,
        validate_classification_application,
    )

    application_digest = plsda.get("classification_application_digest")
    semantics = (plsda.get("metadata") or {}).get("classification_output_semantics")
    ordered_classes = (plsda.get("metadata") or {}).get("classes")
    state_digest = lineage.get("application_state_digest")
    if not isinstance(ordered_classes, list) or len(ordered_classes) != 11:
        raise ValueError("PLS-DA application classes are malformed")
    application = validate_classification_application(
        predictions=labels,
        responses=responses,
        classes=ordered_classes,
        fitted_state_digest=state_digest,
        semantics=semantics,
    )
    if (
        semantics != CLASS_RESPONSE_SEMANTICS
        or application_digest != application.application_digest
        or not np.array_equal(margins, application.margins)
    ):
        raise ValueError("PLS-DA workflow output differs from the shared application authority")
    expected_artifact_digest = phase7_private["canonical_fitted_artifact"]["artifact_sha256"]
    if lineage.get("canonical_artifact_digest") != expected_artifact_digest:
        raise ValueError("saved PLS-DA lineage differs from reviewed Phase 7")
    scientific = {
        "source_collection": deepcopy(source),
        "selection": deepcopy(selection),
        "workflow": {
            "portable_projection_sha256": _json_digest(portable_workflow),
            "execution_contract_digests": _contract_digests(),
        },
        "models": {
            "pca": pca_authority,
            "plsda": {
                "model_type": "plsda",
                "n_features": plsda_detail.get("n_features"),
                "n_components": plsda_detail.get("n_components"),
                "class_count": len(ordered_classes),
                "canonical_artifact_sha256": expected_artifact_digest,
                "canonical_state_content_sha256": lineage.get("canonical_state_content_digest"),
                "canonical_state_contract_sha256": lineage.get("canonical_state_contract_digest"),
                "lineage_sha256": lineage.get("lineage_digest"),
                "validation_execution_sha256": lineage.get("validation_execution_digest"),
                "full_refit_execution_sha256": lineage.get("full_refit_execution_digest"),
                "training_data_hash": plsda_detail.get("training_data_hash"),
            },
        },
        "outputs": {
            "pca_scores_shape": EXPECTED_PCA_SCORE_SHAPE,
            "pca_scores_sha256": _array_digest(scores),
            "pca_phase6_reference_max_abs_difference": phase6_score_max_abs,
            "plsda_response_shape": EXPECTED_PLSDA_RESPONSE_SHAPE,
            "plsda_responses_sha256": _array_digest(responses),
            "ordered_classes_sha256": _json_digest(ordered_classes),
            "decisions_sha256": _json_digest(labels),
            "decision_margins_sha256": _array_digest(margins),
            "decision_margin_summary": {
                "minimum": float(np.min(margins)),
                "median": float(np.median(margins)),
                "maximum": float(np.max(margins)),
            },
            "classification_application_sha256": application_digest,
            "classification_output_semantics": semantics,
        },
    }
    return {
        "scientific": scientific,
        "private": {
            "project_id": project_id,
            "experiment_id": experiment_id,
            "workflow_id": execution.get("workflow_id"),
            "workflow_integrity_hash": execution.get("integrity_hash"),
            "pca_model_id": pca_model_id,
            "plsda_model_id": plsda_model_id,
            "pca_scores": scores.tolist(),
            "plsda_responses": responses.tolist(),
            "plsda_ordered_classes": ordered_classes,
            "plsda_decisions": labels,
            "plsda_decision_margins": margins.tolist(),
            "pca_manifest_projection": pca_inspect.get("manifest"),
            "plsda_manifest_projection": plsda_inspect.get("manifest"),
        },
    }


def _load_private_json(path: Path, label: str) -> dict[str, Any]:
    return _parse_unique_json(_read_private(path, limit=MAX_PRIVATE_JSON_BYTES), label)


def _require_stage_archive(payload: bytes, stage_a: Mapping[str, Any]) -> dict[str, Any]:
    expected = stage_a.get("archive")
    observed = {"size_bytes": len(payload), "sha256": _sha256(payload)}
    if (
        not isinstance(expected, Mapping)
        or set(expected) != {"size_bytes", "sha256"}
        or expected.get("size_bytes") != observed["size_bytes"]
        or expected.get("sha256") != observed["sha256"]
    ):
        raise ValueError("Phase 8 Stage B archive differs from the exact Stage A export")
    return observed


def _read_reexport_member(
    archive: zipfile.ZipFile,
    member_name: Any,
    *,
    label: str,
    max_bytes: int,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Boundedly read and hash one exact re-export member."""

    if not isinstance(member_name, str) or not member_name or member_name != member_name.strip():
        raise ValueError(f"Phase 8 re-export {label} member identity is invalid")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise ValueError(f"Phase 8 re-export {label} member limit is invalid")
    try:
        info = archive.getinfo(member_name)
    except KeyError as exc:
        raise ValueError(f"Phase 8 re-export {label} member is missing") from exc
    if (
        info.is_dir()
        or info.flag_bits & 0x1
        or info.file_size < 0
        or info.file_size > max_bytes
        or (expected_size is not None and info.file_size != expected_size)
    ):
        raise ValueError(f"Phase 8 re-export {label} member size or type differs")
    digest = hashlib.sha256()
    payload = bytearray()
    observed_size = 0
    with archive.open(info, "r") as stream:
        while True:
            chunk = stream.read(min(1024 * 1024, max_bytes + 1 - observed_size))
            if not chunk:
                break
            observed_size += len(chunk)
            if observed_size > max_bytes:
                raise ValueError(f"Phase 8 re-export {label} member exceeds its byte contract")
            digest.update(chunk)
            payload.extend(chunk)
    observed_sha256 = digest.hexdigest()
    if observed_size != info.file_size or (expected_sha256 is not None and observed_sha256 != expected_sha256):
        raise ValueError(f"Phase 8 re-export {label} member content differs")
    return bytes(payload), {"size_bytes": observed_size, "sha256": observed_sha256}


def _require_reexport_source_manifest(entries: list[dict[str, Any]], expected_sha256: Any) -> dict[str, Any]:
    """Recompute the order-sensitive source identity from admitted ZIP bytes."""

    from spectra_sherpa.app.lib.collection_assembly import source_collection_manifest

    observed = source_collection_manifest(entries)
    if observed.get("manifest_digest") != expected_sha256:
        raise ValueError("Phase 8 re-export actual source bytes do not reproduce the source manifest")
    return observed


def _require_reexport_model_training_source(
    manifest: dict[str, Any],
    model_record: Mapping[str, Any],
    *,
    owner_project_id: Any,
    experiment_index: Mapping[int, tuple[int, dict[str, Any]]],
) -> int | None:
    """Bind a re-exported model to an experiment actually in archive custody."""

    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes.projects import _bind_archived_model_training_source

    if not isinstance(model_record, dict):
        raise ValueError("Phase 8 re-export model record is not mutable canonical JSON")
    try:
        _bind_archived_model_training_source(
            manifest,
            model_record,
            owner_project_id=owner_project_id,
            experiments=dict(experiment_index),
        )
    except HTTPException as exc:
        raise ValueError("Phase 8 re-export model training source is outside archive custody") from exc
    value = model_record.get("training_dataset_id")
    return value if type(value) is int else None


def _admit_reexport_model(
    archive: zipfile.ZipFile,
    model_record: Mapping[str, Any],
    expected_model: Mapping[str, Any],
    *,
    owner_project_id: Any,
    experiment_index: Mapping[int, tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    """Re-admit one model from its actual re-export manifest and NPZ bytes."""

    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes.projects import (
        _preflight_model_npz,
        _validate_canonical_model_projection,
        _validate_received_model_manifest,
    )
    from spectra_sherpa.core.model_artifact import ModelManifestJSONError, parse_model_manifest_json

    uid = model_record.get("artifact_uid")
    model_type = model_record.get("model_type")
    if not isinstance(uid, str) or not uid or model_type not in {"pca", "plsda"}:
        raise ValueError("Phase 8 re-export model identity is malformed")
    manifest_payload, manifest_member = _read_reexport_member(
        archive,
        f"models/{uid}/manifest.json",
        label=f"{model_type} manifest",
        max_bytes=MAX_PRIVATE_JSON_BYTES,
    )
    arrays_payload, arrays_member = _read_reexport_member(
        archive,
        f"models/{uid}/arrays.npz",
        label=f"{model_type} arrays",
        max_bytes=MAX_PRIVATE_ARCHIVE_BYTES,
        expected_sha256=model_record.get("integrity_hash"),
    )
    try:
        manifest = parse_model_manifest_json(manifest_payload)
        _require_reexport_model_training_source(
            manifest,
            model_record,
            owner_project_id=owner_project_id,
            experiment_index=experiment_index,
        )
        declared_bytes, declared_inventory = _preflight_model_npz(
            arrays_payload,
            max_decoded_bytes=MAX_PRIVATE_ARCHIVE_BYTES,
        )
        _validate_received_model_manifest(
            manifest,
            artifact_uid=uid,
            model_record=dict(model_record),
            arrays_payload=arrays_payload,
            array_inventory=declared_inventory,
        )
        with np.load(io.BytesIO(arrays_payload), allow_pickle=False) as npz:
            arrays = {name: np.asarray(npz[name]) for name in npz.files}
        observed_inventory = {
            name: (tuple(int(value) for value in array.shape), array.dtype.str) for name, array in arrays.items()
        }
        if observed_inventory != declared_inventory or sum(array.nbytes for array in arrays.values()) != declared_bytes:
            raise ValueError("Phase 8 re-export model array inventory differs")
        _validate_canonical_model_projection(manifest, arrays, dict(model_record))
    except (HTTPException, ModelManifestJSONError) as exc:
        raise ValueError("Phase 8 re-export model bytes failed canonical admission") from exc

    if model_type == "pca":
        manifest_science_sha256 = _require_pca_manifest_science(
            manifest,
            arrays,
            expected_integrity_sha256=str(expected_model.get("artifact_integrity_sha256")),
            expected_serializer=str(expected_model.get("serializer")),
            expected_training_dataset_id=int(model_record.get("training_dataset_id")),
            expected_training_data_hash=str(expected_model.get("training_data_hash")),
            expected_feature_axis_sha256=str(expected_model.get("feature_axis_sha256")),
            expected_feature_mask_sha256=str(expected_model.get("feature_mask_sha256")),
            expected_loadings_sha256=str(expected_model.get("loadings_sha256")),
            expected_explained_variance_ratio_sha256=str(expected_model.get("explained_variance_ratio_sha256")),
            expected_eigenvalues_sha256=str(expected_model.get("eigenvalues_sha256")),
        )
        if manifest_science_sha256 != expected_model.get("manifest_science_sha256"):
            raise ValueError("Phase 8 re-export PCA bytes differ from reviewed Phase 6")
    else:
        lineage = manifest.get("canonical_training_lineage")
        if (
            not isinstance(lineage, Mapping)
            or lineage.get("lineage_digest") != expected_model.get("lineage_sha256")
            or lineage.get("canonical_artifact_digest") != expected_model.get("canonical_artifact_sha256")
            or lineage.get("canonical_state_content_digest") != expected_model.get("canonical_state_content_sha256")
            or lineage.get("canonical_state_contract_digest") != expected_model.get("canonical_state_contract_sha256")
            or lineage.get("validation_execution_digest") != expected_model.get("validation_execution_sha256")
            or lineage.get("full_refit_execution_digest") != expected_model.get("full_refit_execution_sha256")
            or manifest.get("training_data_hash") != expected_model.get("training_data_hash")
        ):
            raise ValueError("Phase 8 re-export PLS-DA bytes differ from reviewed Phase 7")

    return {
        "manifest": manifest_member,
        "arrays": arrays_member,
        "manifest_science_sha256": manifest_science_sha256 if model_type == "pca" else None,
        "decoded_array_projection_sha256": _json_digest(
            {
                name: {
                    "shape": list(value.shape),
                    "dtype": value.dtype.str,
                    "sha256": _array_digest(value, dtype=value.dtype.str),
                }
                for name, value in sorted(arrays.items())
            }
        ),
    }


def _require_application_workflow(
    client: Any,
    *,
    project_id: int,
    experiment_id: int,
    workflow_id: int,
    pca_model_id: str,
    plsda_model_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = _require_response(client.get(f"/api/v1/workflows/{workflow_id}"), 200, "workflow reload").json()
    if (
        workflow.get("project_id") != project_id
        or workflow.get("name") != WORKFLOW_NAME
        or not isinstance(workflow.get("nodes"), list)
    ):
        raise ValueError("saved application workflow has the wrong project or identity")
    nodes = {str(item.get("node_id")): item for item in workflow["nodes"] if isinstance(item, Mapping)}
    if set(nodes) != {"source", "window", "pca_apply", "plsda_apply"}:
        raise ValueError("saved application workflow node inventory differs")
    if (
        (nodes["source"].get("parameters") or {}).get("experiment_id") != experiment_id
        or (nodes["pca_apply"].get("parameters") or {}).get("model_id") != pca_model_id
        or (nodes["plsda_apply"].get("parameters") or {}).get("model_id") != plsda_model_id
    ):
        raise ValueError("saved application workflow source/model bindings differ")
    portable = _portable_workflow(workflow)
    preflight = _require_response(
        client.post(f"/api/v1/workflows/{workflow_id}/preflight"), 200, "application workflow preflight"
    ).json()
    if not preflight.get("is_valid") or preflight.get("error_count") != 0:
        raise ValueError("application workflow failed exact typed preflight")
    execution = _require_response(
        client.post(f"/api/v1/workflows/{workflow_id}/execute", json={}),
        200,
        "saved application workflow",
    ).json()
    return execution, portable


def _require_reexport_semantics(
    payload: bytes,
    *,
    expected_science: Mapping[str, Any],
    expected_workflow: Mapping[str, Any],
) -> dict[str, Any]:
    if not payload or len(payload) > MAX_PRIVATE_ARCHIVE_BYTES:
        raise ValueError("Phase 8 re-export exceeds its byte contract")
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            project = _parse_unique_json(archive.read("project.json"), "Phase 8 re-export project payload")
            from fastapi import HTTPException

            from spectra_sherpa.app.api.v1.routes.projects import (
                _admit_project_snapshot_graphs,
                _snapshot_experiment_index,
                _validate_current_project_archive,
            )

            try:
                _validate_current_project_archive(archive, project, is_sherpa_object=False)
                _admit_project_snapshot_graphs(project)
            except HTTPException as exc:
                raise ValueError("Phase 8 re-export failed canonical archive admission") from exc
            experiments = project.get("experiments")
            models = project.get("models")
            workflows = project.get("workflows")
            if (
                not isinstance(experiments, list)
                or len(experiments) != 1
                or not isinstance(models, list)
                or len(models) != 2
                or not isinstance(workflows, list)
                or len(workflows) != 1
            ):
                raise ValueError("Phase 8 re-export inventory differs")
            experiment = experiments[0]
            if not isinstance(experiment, Mapping) or not isinstance(experiment.get("files"), list):
                raise ValueError("Phase 8 re-export experiment is malformed")
            source = expected_science.get("source_collection")
            if (
                not isinstance(source, Mapping)
                or len(experiment["files"]) != 33
                or experiment.get("collection_definition_sha256") != source.get("collection_definition_sha256")
                or experiment.get("collection_source_manifest_sha256") != source.get("source_manifest_sha256")
                or experiment.get("scientific_collection_sha256") != source.get("scientific_collection_sha256")
            ):
                raise ValueError("Phase 8 re-export source authority differs")
            file_projection: list[dict[str, Any]] = []
            source_manifest_entries: list[dict[str, Any]] = []
            for item in experiment["files"]:
                if not isinstance(item, Mapping):
                    raise ValueError("Phase 8 re-export source member record is malformed")
                _source_payload, source_member = _read_reexport_member(
                    archive,
                    item.get("archive_member"),
                    label="source",
                    max_bytes=MAX_PRIVATE_ARCHIVE_BYTES,
                    expected_size=item.get("saved_size_bytes"),
                    expected_sha256=item.get("saved_sha256"),
                )
                _prepared_payload, prepared_member = _read_reexport_member(
                    archive,
                    item.get("prepared_data_archive_member"),
                    label="prepared-data",
                    max_bytes=MAX_PRIVATE_JSON_BYTES,
                    expected_sha256=item.get("saved_prepared_data_sha256"),
                )
                file_projection.append(
                    {
                        "file_name": item.get("file_path"),
                        "source": source_member,
                        "prepared_data": prepared_member,
                    }
                )
                source_manifest_entries.append(
                    {
                        "file_name": item.get("file_path"),
                        "size_bytes": source_member["size_bytes"],
                        "sha256": source_member["sha256"],
                        "prepared_data_sha256": prepared_member["sha256"],
                    }
                )
            if len(file_projection) != 33:
                raise ValueError("Phase 8 re-export source member projection differs")
            _require_reexport_source_manifest(source_manifest_entries, source.get("source_manifest_sha256"))
            definition_payload, definition_member = _read_reexport_member(
                archive,
                experiment.get("collection_definition_archive_member"),
                label="collection definition",
                max_bytes=MAX_PRIVATE_JSON_BYTES,
                expected_size=experiment.get("collection_definition_size_bytes"),
                expected_sha256=experiment.get("collection_definition_sha256"),
            )
            if _parse_unique_json(definition_payload, "Phase 8 re-export collection definition") != experiment.get(
                "collection_definition"
            ):
                raise ValueError("Phase 8 re-export collection-definition bytes differ from its record")
            by_type = {str(item.get("model_type")): item for item in models if isinstance(item, Mapping)}
            expected_models = expected_science.get("models")
            if set(by_type) != {"pca", "plsda"} or not isinstance(expected_models, Mapping):
                raise ValueError("Phase 8 re-export model families differ")
            pca = by_type["pca"]
            plsda = by_type["plsda"]
            expected_pca = expected_models.get("pca")
            expected_plsda = expected_models.get("plsda")
            if (
                not isinstance(expected_pca, Mapping)
                or not isinstance(expected_plsda, Mapping)
                or pca.get("n_features") != expected_pca.get("n_features")
                or pca.get("n_components") != expected_pca.get("n_components")
                or pca.get("integrity_hash") != expected_pca.get("artifact_integrity_sha256")
                or pca.get("training_data_hash") != expected_pca.get("training_data_hash")
                or plsda.get("n_features") != expected_plsda.get("n_features")
                or plsda.get("n_components") != expected_plsda.get("n_components")
                or plsda.get("canonical_lineage_digest") != expected_plsda.get("lineage_sha256")
                or plsda.get("validation_evidence_digest") != expected_plsda.get("validation_execution_sha256")
                or plsda.get("training_data_hash") != expected_plsda.get("training_data_hash")
            ):
                raise ValueError("Phase 8 re-export model science differs")
            experiment_index = _snapshot_experiment_index(project)
            admitted_models = {
                "pca": _admit_reexport_model(
                    archive,
                    pca,
                    expected_pca,
                    owner_project_id=project.get("id"),
                    experiment_index=experiment_index,
                ),
                "plsda": _admit_reexport_model(
                    archive,
                    plsda,
                    expected_plsda,
                    owner_project_id=project.get("id"),
                    experiment_index=experiment_index,
                ),
            }
            portable = _portable_workflow(workflows[0])
            if portable != expected_workflow:
                raise ValueError("Phase 8 re-export application workflow differs")
            projection = {
                "archive_format": project.get("archive_format"),
                "member_count": len(archive.infolist()),
                "source": {
                    "file_count": 33,
                    "file_projection_sha256": _json_digest(file_projection),
                    "collection_definition_member": definition_member,
                    "collection_definition_sha256": experiment.get("collection_definition_sha256"),
                    "source_manifest_sha256": experiment.get("collection_source_manifest_sha256"),
                    "scientific_collection_sha256": experiment.get("scientific_collection_sha256"),
                },
                "models": {
                    "pca": {
                        "n_features": pca.get("n_features"),
                        "n_components": pca.get("n_components"),
                        "integrity_hash": pca.get("integrity_hash"),
                        "training_data_hash": pca.get("training_data_hash"),
                        "member_projection": admitted_models["pca"],
                    },
                    "plsda": {
                        "n_features": plsda.get("n_features"),
                        "n_components": plsda.get("n_components"),
                        "canonical_lineage_digest": plsda.get("canonical_lineage_digest"),
                        "validation_evidence_digest": plsda.get("validation_evidence_digest"),
                        "training_data_hash": plsda.get("training_data_hash"),
                        "member_projection": admitted_models["plsda"],
                    },
                },
                "workflow_sha256": _json_digest(portable),
            }
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("Phase 8 re-export is not a valid closed project archive") from exc
    return {
        "schema_version": "spectrasherpa-avatar-phase8-reexport/1",
        "archive_member_count": projection["member_count"],
        "source_count": 33,
        "model_count": 2,
        "workflow_count": 1,
        "semantic_projection_sha256": _json_digest(projection),
    }


def _stage_restart(args: argparse.Namespace) -> int:
    _install_scp_denial()
    scp_version = _installed_scp_version()
    runtime_identity = _runtime_identity()
    _require_empty_registry()
    fit_guard = _install_fitted_lifecycle_denial()
    phase6_private, phase7_private = _load_reviewed_inputs(args)
    stage_a = _load_private_json(args.stage_a_result, "Phase 8 Stage A result")
    required = ("project_id", "experiment_id", "workflow_id", "pca_model_id", "plsda_model_id")
    if stage_a.get("stage") != "workspace_a_initial_zero_fit_process" or any(name not in stage_a for name in required):
        raise ValueError("Phase 8 Stage A restart authority is malformed")
    project_id = int(stage_a["project_id"])
    experiment_id = int(stage_a["experiment_id"])
    workflow_id = int(stage_a["workflow_id"])
    pca_model_id = str(stage_a["pca_model_id"])
    plsda_model_id = str(stage_a["plsda_model_id"])
    with _client() as client:
        inventory = _model_inventory(client, project_id)
        if (
            inventory["pca"].get("artifact_uid") != pca_model_id
            or inventory["plsda"].get("artifact_uid") != plsda_model_id
        ):
            raise ValueError("restarted workspace model inventory differs")
        execution, portable = _require_application_workflow(
            client,
            project_id=project_id,
            experiment_id=experiment_id,
            workflow_id=workflow_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_model_id,
        )
        result = _summarize_execution(
            client,
            execution,
            project_id=project_id,
            experiment_id=experiment_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_model_id,
            phase6_private=phase6_private,
            phase7_private=phase7_private,
            portable_workflow=portable,
        )
    if fit_guard["attempted"]:
        raise ValueError("Phase 8 restart invoked a prohibited fitted lifecycle")
    _atomic_write(
        args.result,
        _pretty_json(
            {
                "stage": "workspace_a_restart_zero_fit_process",
                "project_id": project_id,
                "experiment_id": experiment_id,
                "workflow_id": workflow_id,
                "pca_model_id": pca_model_id,
                "plsda_model_id": plsda_model_id,
                "spectrochempy_loaded": _scp_loaded(),
                "spectrochempy_import_denied": True,
                "spectrochempy_distribution_version": scp_version,
                "runtime_attestation": runtime_identity,
                "fitted_lifecycle": {"patched_operation_count": fit_guard["patched_operation_count"], "attempts": 0},
                **result,
            }
        ),
        private=True,
        limit=MAX_PRIVATE_JSON_BYTES,
    )
    return 0


def _stage_import(args: argparse.Namespace) -> int:
    _install_scp_denial()
    scp_version = _installed_scp_version()
    runtime_identity = _runtime_identity()
    _require_empty_registry()
    fit_guard = _install_fitted_lifecycle_denial()
    phase6_private, phase7_private = _load_reviewed_inputs(args)
    archive_payload = _read_private(args.archive, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    stage_a = _load_private_json(args.stage_a_result, "Phase 8 Stage A result")
    input_archive = _require_stage_archive(archive_payload, stage_a)
    with _client() as client:
        imported = _require_response(
            client.post(
                "/api/v1/projects/import",
                files={"file": ("avatar-phase8.sherpa", io.BytesIO(archive_payload), "application/zip")},
            ),
            201,
            "Phase 8 new-workspace import",
        ).json()
        project_id = int(imported["id"])
        experiments = [item for item in imported.get("experiments", []) if item.get("file_count") == 33]
        workflows = [item for item in imported.get("workflows", []) if item.get("name") == WORKFLOW_NAME]
        if len(experiments) != 1 or len(workflows) != 1 or len(imported.get("models", [])) != 2:
            raise ValueError("Phase 8 import did not restore one source, workflow, and two models")
        experiment_id = int(experiments[0]["id"])
        workflow_id = int(workflows[0]["id"])
        inventory = _model_inventory(client, project_id)
        pca_model_id = str(inventory["pca"]["artifact_uid"])
        plsda_model_id = str(inventory["plsda"]["artifact_uid"])
        execution, portable = _require_application_workflow(
            client,
            project_id=project_id,
            experiment_id=experiment_id,
            workflow_id=workflow_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_model_id,
        )
        result = _summarize_execution(
            client,
            execution,
            project_id=project_id,
            experiment_id=experiment_id,
            pca_model_id=pca_model_id,
            plsda_model_id=plsda_model_id,
            phase6_private=phase6_private,
            phase7_private=phase7_private,
            portable_workflow=portable,
        )
        versions = _require_response(
            client.get(f"/api/v1/projects/{project_id}/versions"), 200, "imported project versions"
        ).json()
        if versions.get("total") != 1 or len(versions.get("versions", [])) != 1:
            raise ValueError("Phase 8 import did not restore exactly one saved version")
        reexported = _require_response(
            client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={versions['versions'][0]['id']}"),
            200,
            "Phase 8 new-workspace re-export",
        )
    if fit_guard["attempted"]:
        raise ValueError("Phase 8 import invoked a prohibited fitted lifecycle")
    reexport_semantics = _require_reexport_semantics(
        reexported.content,
        expected_science=result["scientific"],
        expected_workflow=portable,
    )
    reexport = _atomic_write(args.reexport, reexported.content, private=True, limit=MAX_PRIVATE_ARCHIVE_BYTES)
    _atomic_write(
        args.result,
        _pretty_json(
            {
                "stage": "workspace_b_import_zero_fit_process",
                "project_id": project_id,
                "experiment_id": experiment_id,
                "workflow_id": workflow_id,
                "pca_model_id": pca_model_id,
                "plsda_model_id": plsda_model_id,
                "storage_uid_remapped": (
                    pca_model_id != str(stage_a.get("pca_model_id"))
                    or plsda_model_id != str(stage_a.get("plsda_model_id"))
                ),
                "restored_source_count": 33,
                "restored_model_count": 2,
                "restored_workflow_count": 1,
                "restored_version_count": 1,
                "input_archive": input_archive,
                "reexport": reexport,
                "reexport_semantics": reexport_semantics,
                "spectrochempy_loaded": _scp_loaded(),
                "spectrochempy_import_denied": True,
                "spectrochempy_distribution_version": scp_version,
                "runtime_attestation": runtime_identity,
                "fitted_lifecycle": {"patched_operation_count": fit_guard["patched_operation_count"], "attempts": 0},
                **result,
            }
        ),
        private=True,
        limit=MAX_PRIVATE_JSON_BYTES,
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
        raise RuntimeError(f"fresh Phase 8 process failed: {completed.stderr[-4000:]}{completed.stdout[-4000:]}")


def _closed_output_paths(args: argparse.Namespace, workspace_a: Path, workspace_b: Path) -> dict[str, Path]:
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
    protected = {
        str(Path(os.path.abspath(args.phase6_archive))).casefold(),
        str(Path(os.path.abspath(args.phase6_private_report))).casefold(),
        str(Path(os.path.abspath(args.phase7_private_report))).casefold(),
    }
    identities: dict[str, str] = {}
    for name, path in outputs.items():
        identity = str(path).casefold()
        if identity in identities or identity in protected:
            raise ValueError(f"Phase 8 output path {name} collides with another authority")
        identities[identity] = name
        if path.exists() or path.is_symlink():
            raise ValueError(f"Phase 8 output {name} must be absent before qualification")
        for workspace in (workspace_a, workspace_b):
            try:
                path.relative_to(workspace)
            except ValueError:
                pass
            else:
                raise ValueError(f"Phase 8 output {name} must remain outside both workspaces")
    return outputs


def _same_application_outputs(*stages: Mapping[str, Any]) -> bool:
    keys = (
        "pca_scores",
        "plsda_responses",
        "plsda_ordered_classes",
        "plsda_decisions",
        "plsda_decision_margins",
    )
    first = stages[0].get("private") if stages else None
    return isinstance(first, Mapping) and all(
        isinstance(stage.get("private"), Mapping) and all(stage["private"].get(key) == first.get(key) for key in keys)
        for stage in stages[1:]
    )


def _require_common_runtime(*stages: Mapping[str, Any]) -> dict[str, Any]:
    identities = [stage.get("runtime_attestation") for stage in stages]
    if (
        not identities
        or not isinstance(identities[0], Mapping)
        or any(identity != identities[0] for identity in identities[1:])
        or identities[0].get("source_commit") != RUNTIME_IMPLEMENTATION_COMMIT
        or identities[0].get("operator_code") != OPERATOR_CODE
        or identities[0].get("distributions") != EXPECTED_RUNTIME_DISTRIBUTIONS
    ):
        raise ValueError("Phase 8 stages do not share one exact runtime/operator authority")
    return deepcopy(dict(identities[0]))


def _public_projection(
    stage_a: Mapping[str, Any],
    restart: Mapping[str, Any],
    stage_b: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase8_exact_zero_fit_saved_model_restart_and_portability_complete_author_operated",
        "observed_at": "2026-08-25",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "process_boundary": {
            "fresh_process_count": 3,
            "workspace_a_initial": True,
            "workspace_a_restart": True,
            "workspace_b_was_absent": True,
            "workspace_b_new_database": True,
            "old_dataset_handle_used": False,
            "pca_fit_or_refit_count": 0,
            "plsda_fit_or_refit_count": 0,
            "all_fitted_lifecycle_entry_points_denied": True,
            "spectrochempy_distribution": {
                "name": "spectrochempy",
                "version": EXPECTED_SCP_VERSION,
                "installed_in_exact_profile": True,
                "loaded_in_any_stage": False,
                "import_denied_in_every_stage": True,
                "distribution_absence_claimed": False,
            },
            "paired_platform_executed": False,
            "runtime_attestation": _require_common_runtime(stage_a, restart, stage_b),
        },
        "project_portability": {
            "archive_schema_version": "0.4",
            "saved_version_number": stage_a["saved_version_number"],
            "source_count": 33,
            "active_model_count": 2,
            "application_workflow_count": 1,
            "workspace_b_restored_version_count": stage_b["restored_version_count"],
            "workspace_b_input_archive_exact": True,
            "storage_uid_remap_allowed": True,
            "workspace_b_storage_uid_remapped": stage_b["storage_uid_remapped"],
            "private_archive_size_bytes": stage_a["archive"]["size_bytes"],
            "private_archive_sha256": stage_a["archive"]["sha256"],
            "private_reexport_size_bytes": stage_b["reexport"]["size_bytes"],
            "private_reexport_sha256": stage_b["reexport"]["sha256"],
            "private_reexport_semantic_projection_sha256": stage_b["reexport_semantics"]["semantic_projection_sha256"],
        },
        "scientific_result": deepcopy(stage_a["scientific"]),
        "identity_preservation": {
            "initial_equals_restart_equals_import": True,
            "source_selection_and_sample_identity_exact": True,
            "pca_saved_application_bit_exact_across_phase8_stages": True,
            "pca_phase6_reference_within_absolute_1e-10": True,
            "plsda_responses_classes_decisions_and_margins_bit_exact": True,
            "canonical_plsda_lineage_exact_across_import_roundtrip": True,
            "project_workflow_and_model_family_bindings_exact": True,
        },
        "privacy_boundary": {
            "raw_or_selected_spectra_published": False,
            "complete_scores_loadings_or_responses_published": False,
            "sample_specimen_or_class_labels_published": False,
            "model_uids_database_ids_or_private_paths_published": False,
            "project_archive_or_reexport_published": False,
            "supplier_information_published": False,
        },
        "claim_boundary": (
            "Author-operated exact-corpus local saved-model application, fresh-process restart, and private "
            "new-workspace import/re-export proof with zero PCA or PLS-DA fits/refits in every Phase 8 process."
        ),
        "nonclaims": [
            "new_accuracy_estimate_or_model_selection",
            "botanical_authenticity_or_population_new_lot_new_instrument_performance",
            "calibrated_probability_confidence_or_uncertainty",
            "paired_platform_repeatability_not_executed",
            "untouched_independent_confirmation",
            "redistribution_permission_or_public_corpus",
            "non_author_physical_action_2",
        ],
    }


def _run(args: argparse.Namespace) -> int:
    workspace_a = Path(os.path.abspath(args.workspace_a))
    workspace_b = Path(os.path.abspath(args.workspace_b))
    if workspace_a == workspace_b or workspace_a in workspace_b.parents or workspace_b in workspace_a.parents:
        raise ValueError("Phase 8 workspaces A and B must be distinct and non-nested")
    if workspace_a.exists() or workspace_a.is_symlink() or workspace_b.exists() or workspace_b.is_symlink():
        raise ValueError("Phase 8 workspaces A and B must both be absent before qualification")
    outputs = _closed_output_paths(args, workspace_a, workspace_b)
    workspace_a.mkdir(mode=0o700, parents=True)
    common = [
        "--phase6-private-report",
        str(args.phase6_private_report),
        "--phase7-private-report",
        str(args.phase7_private_report),
    ]
    _run_stage(
        [
            "stage-a",
            "--phase6-archive",
            str(args.phase6_archive),
            *common,
            "--archive",
            str(outputs["archive"]),
            "--result",
            str(outputs["stage_a"]),
        ],
        workspace=workspace_a,
    )
    _run_stage(
        [
            "stage-restart",
            *common,
            "--stage-a-result",
            str(outputs["stage_a"]),
            "--result",
            str(outputs["restart"]),
        ],
        workspace=workspace_a,
    )
    workspace_b.mkdir(mode=0o700, parents=True)
    _run_stage(
        [
            "stage-import",
            *common,
            "--stage-a-result",
            str(outputs["stage_a"]),
            "--archive",
            str(outputs["archive"]),
            "--reexport",
            str(outputs["reexport"]),
            "--result",
            str(outputs["stage_b"]),
        ],
        workspace=workspace_b,
    )
    stage_a = _load_private_json(outputs["stage_a"], "Phase 8 Stage A result")
    restart = _load_private_json(outputs["restart"], "Phase 8 restart result")
    stage_b = _load_private_json(outputs["stage_b"], "Phase 8 Stage B result")
    stages = (stage_a, restart, stage_b)
    if any(
        stage.get("spectrochempy_loaded") is not False
        or stage.get("spectrochempy_import_denied") is not True
        or stage.get("spectrochempy_distribution_version") != EXPECTED_SCP_VERSION
        or (stage.get("fitted_lifecycle") or {}).get("attempts") != 0
        or (stage.get("fitted_lifecycle") or {}).get("patched_operation_count", 0) < 1
        for stage in stages
    ):
        raise ValueError("Phase 8 process profile or zero-fit boundary differs")
    if not (stage_a.get("scientific") == restart.get("scientific") == stage_b.get("scientific")):
        raise ValueError("Phase 8 scientific projections differ across fresh processes")
    _require_common_runtime(*stages)
    if stage_b.get("input_archive") != stage_a.get("archive"):
        raise ValueError("Phase 8 workspace B did not consume the exact Stage A archive bytes")
    if not _same_application_outputs(*stages):
        raise ValueError("Phase 8 saved-DAG numeric outputs differ across fresh processes")
    private = {
        "schema_version": SCHEMA_VERSION,
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "phase6_inputs": {
            "archive_sha256": EXPECTED_PHASE6_ARCHIVE_SHA256,
            "private_report_sha256": EXPECTED_PHASE6_PRIVATE_SHA256,
        },
        "phase7_input": {"private_report_sha256": EXPECTED_PHASE7_PRIVATE_SHA256},
        "workspace_a_initial": stage_a,
        "workspace_a_restart": restart,
        "workspace_b_import": stage_b,
    }
    private_record = _atomic_write(
        outputs["private_report"], _pretty_json(private), private=True, limit=MAX_PRIVATE_JSON_BYTES
    )
    public = _public_projection(stage_a, restart, stage_b)
    public["private_evidence_authority"] = {
        "private_report_size_bytes": private_record["size_bytes"],
        "private_report_sha256": private_record["sha256"],
        "private_report_published": False,
    }
    _atomic_write(outputs["public_report"], _pretty_json(public), private=False, limit=MAX_PUBLIC_REPORT_BYTES)
    print("Avatar OMNIC Phase 8B application portability: PASS")
    return 0


def _section_projections(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "header": {
            key: report.get(key)
            for key in (
                "schema_version",
                "dataset_id",
                "dataset_version",
                "status",
                "observed_at",
                "runtime_implementation_commit",
            )
        },
        "process_boundary": report.get("process_boundary"),
        "project_portability": report.get("project_portability"),
        "scientific_result": report.get("scientific_result"),
        "identity_preservation": report.get("identity_preservation"),
        "private_authority": report.get("private_evidence_authority"),
        "claim_boundary": {
            "privacy_boundary": report.get("privacy_boundary"),
            "claim_boundary": report.get("claim_boundary"),
            "nonclaims": report.get("nonclaims"),
        },
    }


def _semantic_failures(report: object, expected_sections: Mapping[str, str]) -> list[str]:
    if not isinstance(report, Mapping) or set(report) != {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "status",
        "observed_at",
        "runtime_implementation_commit",
        "process_boundary",
        "project_portability",
        "scientific_result",
        "identity_preservation",
        "privacy_boundary",
        "claim_boundary",
        "nonclaims",
        "private_evidence_authority",
    }:
        return ["checked Phase 8 report does not use its closed top-level schema"]
    failures: list[str] = []
    for name, projection in _section_projections(report).items():
        expected = expected_sections.get(name)
        if not isinstance(expected, str) or len(expected) != 64 or _json_digest(projection) != expected:
            failures.append(f"checked Phase 8 {name.replace('_', ' ')} authority differs")
    process = report.get("process_boundary")
    portability = report.get("project_portability")
    science = report.get("scientific_result")
    identity = report.get("identity_preservation")
    private = report.get("private_evidence_authority")
    if (
        not isinstance(process, Mapping)
        or process.get("pca_fit_or_refit_count") != 0
        or process.get("plsda_fit_or_refit_count") != 0
        or process.get("all_fitted_lifecycle_entry_points_denied") is not True
    ):
        failures.append("checked Phase 8 zero-fit process boundary differs")
    if (
        not isinstance(portability, Mapping)
        or portability.get("source_count") != 33
        or portability.get("active_model_count") != 2
        or portability.get("archive_schema_version") != "0.4"
    ):
        failures.append("checked Phase 8 project portability boundary differs")
    outputs = science.get("outputs") if isinstance(science, Mapping) else None
    if (
        not isinstance(outputs, Mapping)
        or outputs.get("pca_scores_shape") != EXPECTED_PCA_SCORE_SHAPE
        or outputs.get("plsda_response_shape") != EXPECTED_PLSDA_RESPONSE_SHAPE
    ):
        failures.append("checked Phase 8 saved application output boundary differs")
    if not isinstance(identity, Mapping) or not identity or not all(value is True for value in identity.values()):
        failures.append("checked Phase 8 identity-preservation boundary differs")
    if (
        not isinstance(private, Mapping)
        or set(private) != {"private_report_size_bytes", "private_report_sha256", "private_report_published"}
        or private.get("private_report_published") is not False
        or not isinstance(private.get("private_report_size_bytes"), int)
        or not isinstance(private.get("private_report_sha256"), str)
        or len(private["private_report_sha256"]) != 64
    ):
        failures.append("checked Phase 8 private authority is malformed")
    return failures


EXPECTED_SECTION_DIGESTS: dict[str, str] = {
    "header": "b4c3e02839a62f7282d46ab2049f397c5a5accaf6f4def37a20ed28f70693c14",
    "process_boundary": "df63e9bb7ded52741cd0f8f56c16c8c7041e1411bf58682c167c45738cf30e1a",
    "project_portability": "197a39a1e40ba8f37b6cccaa5457e6226dc5b609f4ca38a2438515c5630027e0",
    "scientific_result": "f05fbe195f0c78034d8aeb49172cefd6783aa6ab7cded24650b22d47b555b416",
    "identity_preservation": "a62824d5a18b74e1449ee1f70ba29e2098ad157cde5f223329cb0042cc225731",
    "private_authority": "9b69150b4c48e7b597ee3f66b45428bb38a6cecd128197ec8146df1457c7244b",
    "claim_boundary": "9ef57be106595919bce022ef2769451a0fdd36b63f2183c9240b804a8563decc",
}


def validate_checked_report(path: Path) -> list[str]:
    try:
        payload = _read_public(path, limit=MAX_PUBLIC_REPORT_BYTES)
    except ValueError as exc:
        return [f"checked Phase 8 report admission failed: {exc}"]
    failures: list[str] = []
    if CHECKED_REPORT_SHA256.startswith("TO_BE_") or _sha256(payload) != CHECKED_REPORT_SHA256:
        failures.append("checked Phase 8 report digest differs from the reviewed authority")
    if len(payload) < 2 or len(payload) > MAX_PUBLIC_REPORT_BYTES:
        failures.append("checked Phase 8 report exceeds its public byte boundary")
    try:
        report = _parse_unique_json(payload, "checked Phase 8 report")
    except ValueError as exc:
        return failures + [str(exc)]
    failures.extend(_semantic_failures(report, EXPECTED_SECTION_DIGESTS))
    text = payload.decode("utf-8", errors="replace")
    for forbidden in (
        "/Users/",
        "/private/",
        "private-input",
        '"sample_id"',
        '"specimen_id"',
        '"class_responses"',
        '"pca_scores"',
        '"artifact_uid"',
        '"project_id"',
        '"experiment_id"',
        '"workflow_id"',
        '"user_id"',
    ):
        if forbidden in text:
            failures.append(f"checked Phase 8 report leaks forbidden token {forbidden!r}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    stage_a = commands.add_parser("stage-a")
    stage_a.add_argument("--phase6-archive", type=Path, required=True)
    stage_a.add_argument("--phase6-private-report", type=Path, required=True)
    stage_a.add_argument("--phase7-private-report", type=Path, required=True)
    stage_a.add_argument("--archive", type=Path, required=True)
    stage_a.add_argument("--result", type=Path, required=True)
    restart = commands.add_parser("stage-restart")
    restart.add_argument("--phase6-private-report", type=Path, required=True)
    restart.add_argument("--phase7-private-report", type=Path, required=True)
    restart.add_argument("--stage-a-result", type=Path, required=True)
    restart.add_argument("--result", type=Path, required=True)
    imported = commands.add_parser("stage-import")
    imported.add_argument("--phase6-private-report", type=Path, required=True)
    imported.add_argument("--phase7-private-report", type=Path, required=True)
    imported.add_argument("--stage-a-result", type=Path, required=True)
    imported.add_argument("--archive", type=Path, required=True)
    imported.add_argument("--reexport", type=Path, required=True)
    imported.add_argument("--result", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace-a", type=Path, required=True)
    run.add_argument("--workspace-b", type=Path, required=True)
    run.add_argument("--phase6-archive", type=Path, required=True)
    run.add_argument("--phase6-private-report", type=Path, required=True)
    run.add_argument("--phase7-private-report", type=Path, required=True)
    run.add_argument("--archive", type=Path, required=True)
    run.add_argument("--private-report", type=Path, required=True)
    run.add_argument("--public-report", type=Path, required=True)
    check = commands.add_parser("check-public")
    check.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "stage-a":
        return _stage_a(args)
    if args.command == "stage-restart":
        return _stage_restart(args)
    if args.command == "stage-import":
        return _stage_import(args)
    if args.command == "run":
        return _run(args)
    failures = validate_checked_report(args.report)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Avatar OMNIC Phase 8B checked report: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
