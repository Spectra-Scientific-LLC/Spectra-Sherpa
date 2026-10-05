#!/usr/bin/env python3
"""Run and verify the exact private Avatar held-block PLS-DA qualification.

The source collection is loaded through the durable application collection
authority.  Supervision, deterministic leave-one-block-out validation, held-
out metrics, private row custody, and the terminal all-data refit are all
issued by the generic Phase 7A authorities.  This tool contains no estimator,
fold loop, target inference, or model replay.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-phase7-plsda/3"
RUNTIME_IMPLEMENTATION_COMMIT = "634de416f9959dd21763847b821215c41f55d5a5"
CHECKED_REPORT_SHA256 = "2ecbc6f078be8faaec675750b3c6bb5c4a5b6240a932adae7d7d50e9dadb52cb"
EXPECTED_SECTION_DIGESTS: dict[str, str] = {
    "header": "48f8ca2b9591271b349a336e5e98593bb59e43c68dc06258a331cb5b75d61d54",
    "source_and_supervision": "0eb17440933fcfe59526a4de232849e80c2d3a02c5ae0a424fde2d4c9aca2955",
    "workflow_and_split": "b76666b1e646b6244e677cb725a22cc13acc22fbaab045855fce5dd27dac2f21",
    "validation": "8a5535c76004f8f0d2a09c068dc4f37d3f7f2c9dc9325c63cfed95eccf50b673",
    "full_refit": "c2d3602bedca3e486d25368c0a651718cc72ff8819b258d801a5a465aef50373",
    "private_authority": "2e414f8aa2f94fd9c621310a9d272f42b249219917c5ee6deaf53baed968914c",
    "claim_boundary": "515f2c4f07ba5d005c2e33555aab197178b347f914a00b842db27374becaa7d8",
}

EXPECTED_SOURCE_SHAPE = [33, 1868]
EXPECTED_SELECTED_SHAPE = [33, 1270]
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
EXPECTED_ACTUAL_ENDPOINTS = [3099.1993627563543, 651.8539840297767]
MAX_PRIVATE_REPORT_BYTES = 16 * 1024 * 1024
MAX_PUBLIC_REPORT_BYTES = 1024 * 1024
MAX_PRIVATE_STATE_BYTES = 8 * 1024 * 1024


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object, *, pretty: bool) -> bytes:
    if pretty:
        text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    else:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.encode("utf-8")


def _json_digest(value: object) -> str:
    return _sha256_bytes(_json_bytes(value, pretty=False))


def _array_digest(value: object, *, dtype: str = "<f8") -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype=dtype))
    return _sha256_bytes(array.tobytes(order="C"))


def _bool_digest(value: object) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype=np.bool_)).astype(np.uint8)
    return _sha256_bytes(array.tobytes(order="C"))


def _aggregate_metrics_projection(pooled: Mapping[str, object]) -> dict[str, object]:
    """Project the protocol's first-class aggregate classification outputs."""

    return {
        "accuracy": pooled.get("accuracy"),
        "balanced_accuracy": pooled.get("balanced_accuracy"),
        "macro_f1": pooled.get("macro_f1"),
        "per_class_recall": pooled.get("per_class_recall"),
    }


def _aggregate_metrics_are_closed(value: object) -> bool:
    """Require the complete finite first-class metric projection."""

    if not isinstance(value, Mapping) or set(value) != {
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "per_class_recall",
    }:
        return False
    for name in ("accuracy", "balanced_accuracy", "macro_f1"):
        scalar = value[name]
        if isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not np.isfinite(float(scalar)):
            return False
        if not 0.0 <= float(scalar) <= 1.0:
            return False
    recall = value["per_class_recall"]
    return bool(
        isinstance(recall, Mapping)
        and recall
        and all(
            isinstance(label, str)
            and label
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and np.isfinite(float(score))
            and 0.0 <= float(score) <= 1.0
            for label, score in recall.items()
        )
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _spectrochempy_loaded() -> bool:
    return any(name == "spectrochempy" or name.startswith("spectrochempy.") for name in sys.modules)


def _configure_workspace(workspace: Path) -> None:
    if any(name.startswith("spectra_sherpa.app.") for name in sys.modules):
        raise ValueError("workspace must be configured before application modules are loaded")
    os.environ.update(
        {
            "DATA_DIR": str(workspace),
            "DATABASE_URL": f"sqlite+aiosqlite:///{workspace / 'spectra_platform.db'}",
            "APP_MODE": "local",
            "MPLCONFIGDIR": str(workspace / ".matplotlib"),
        }
    )


def _private_output(path: Path) -> Path:
    lexical = Path(os.path.abspath(path))
    parent = lexical.parent
    try:
        parent_stat = parent.lstat()
    except OSError as exc:
        raise ValueError("private output parent is absent") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or (os.name != "nt" and stat.S_IMODE(parent_stat.st_mode) & 0o077)
        or parent.resolve(strict=True) != parent
    ):
        raise ValueError("private output parent must be a private non-linked directory")
    if lexical.exists() or lexical.is_symlink():
        raise ValueError("private output must be absent")
    return lexical


def _atomic_write(path: Path, payload: bytes, *, private: bool, limit: int) -> dict[str, object]:
    if not payload or len(payload) > limit:
        raise ValueError("output exceeds its bounded byte contract")
    lexical = _private_output(path) if private else Path(os.path.abspath(path))
    if not private:
        lexical.parent.mkdir(parents=True, exist_ok=True)
        if lexical.is_symlink() or (lexical.exists() and not lexical.is_file()):
            raise ValueError("public output must be a regular non-linked file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{lexical.name}.", dir=lexical.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600 if private else 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, lexical)
        if private:
            lexical.chmod(0o600)
        directory = os.open(lexical.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"size_bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _read_regular(path: Path, *, private: bool, limit: int) -> bytes:
    lexical = Path(os.path.abspath(path))
    try:
        observed = lexical.lstat()
    except OSError as exc:
        raise ValueError("report is absent") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode) or observed.st_size > limit:
        raise ValueError("report is not an admitted bounded regular file")
    if private and os.name != "nt" and stat.S_IMODE(observed.st_mode) & 0o077:
        raise ValueError("private report permissions are not restrictive")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lexical, flags)
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode) or current.st_size != observed.st_size:
            raise ValueError("report identity changed during admission")
        payload = bytearray()
        while len(payload) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > limit:
        raise ValueError("report exceeds its bounded byte contract")
    return bytes(payload)


def _source_projection(loaded: object) -> tuple[object, dict[str, object]]:
    from spectra_sherpa.app.lib.sherpa_dataset import SpectralAxis

    dataset = loaded.dataset
    axis = dataset.get_feature_axis()
    sample_axis = dataset.sample_axis
    if (
        list(dataset.shape) != EXPECTED_SOURCE_SHAPE
        or not np.issubdtype(dataset.X.dtype, np.floating)
        or not np.isfinite(dataset.X).all()
        or not isinstance(axis, SpectralAxis)
        or axis.values is None
        or list(np.asarray(axis.values).shape) != [1868]
        or not np.isfinite(axis.values).all()
        or not np.all(np.diff(axis.values) < 0.0)
        or axis.title != "Wavenumber"
        or axis.units != "cm-1"
        or str(dataset.data_role) != "X_spectra"
        or str(dataset.units).casefold() != "absorbance"
        or dataset.target is not None
        or dataset.target_context.target_type is not None
        or sample_axis is None
        or sample_axis.labels is None
        or not isinstance(sample_axis.sample_table, Mapping)
    ):
        raise ValueError("source collection differs from the exact target-free FTIR authority")
    labels = list(sample_axis.labels)
    table = {str(name): list(values) for name, values in sorted(sample_axis.sample_table.items())}
    source_collection = dataset.meta.get("source_collection")
    if not isinstance(source_collection, Mapping):
        raise ValueError("source collection lacks its combined identity")
    observed = {
        "dataset_id": dataset.dataset_id,
        "shape": list(dataset.shape),
        "values_sha256": _array_digest(dataset.X),
        "feature_axis_sha256": _array_digest(axis.values),
        "sample_labels_sha256": _json_digest(labels),
        "sample_table_sha256": _json_digest(table),
        "source_manifest_sha256": loaded.source_manifest_sha256,
        "collection_definition_sha256": loaded.collection_definition_sha256,
        "scientific_collection_sha256": loaded.scientific_collection_sha256,
        "target_state": "absent",
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
    if observed != expected:
        raise ValueError("source collection identity differs from the checked Phase 5 authority")
    mask = (np.asarray(axis.values) >= 650.0) & (np.asarray(axis.values) <= 3100.0)
    selected = np.asarray(dataset.X)[:, mask]
    selected_axis = np.asarray(axis.values)[mask]
    if (
        list(selected.shape) != EXPECTED_SELECTED_SHAPE
        or selected_axis[[0, -1]].tolist() != EXPECTED_ACTUAL_ENDPOINTS
        or _bool_digest(mask) != EXPECTED_SELECTION_MASK_SHA256
        or _array_digest(selected) != EXPECTED_SELECTED_VALUES_SHA256
        or _array_digest(selected_axis) != EXPECTED_SELECTED_AXIS_SHA256
    ):
        raise ValueError("source collection does not reproduce the frozen interval projection")
    return dataset, observed


def _per_class_recall(metrics: Mapping[str, object]) -> dict[str, float]:
    labels = metrics["labels"]
    matrix = metrics["confusion_matrix"]
    if not isinstance(labels, list) or not isinstance(matrix, list) or len(labels) != len(matrix):
        raise ValueError("classification metrics have malformed class authority")
    result: dict[str, float] = {}
    for index, label in enumerate(labels):
        row = matrix[index]
        if not isinstance(label, str) or not isinstance(row, list) or len(row) != len(labels):
            raise ValueError("classification metrics have malformed class authority")
        denominator = sum(int(value) for value in row)
        if denominator <= 0:
            raise ValueError("classification metrics omit a declared class")
        result[label] = int(row[index]) / denominator
    return result


def _bounded_metrics(record: object) -> dict[str, object]:
    payload = record.as_dict()
    expected_keys = {
        "registry_version",
        "task_type",
        "n_samples",
        "labels",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "mcc",
        "confusion_matrix",
    }
    if set(payload) != expected_keys or payload["task_type"] != "classification":
        raise ValueError("classification metric projection is not closed")
    payload["per_class_recall"] = _per_class_recall(payload)
    return payload


def _split_plan_payload(plan: object) -> dict[str, object]:
    return {
        "schema_version": "spectra-split-plan/2",
        "method": plan.method,
        "n_samples": plan.n_samples,
        "grouped": plan.grouped,
        "folds": [
            {
                "train": np.asarray(fold.train, dtype=np.int64).tolist(),
                "test": np.asarray(fold.test, dtype=np.int64).tolist(),
            }
            for fold in plan.folds
        ],
        "held_out_groups": list(plan.held_out_groups),
    }


async def _execute_exact(project_id: int, experiment_id: int) -> tuple[dict[str, object], dict[str, object]]:
    if _spectrochempy_loaded():
        raise ValueError("Phase 7 qualification must begin without SpectroChemPy loaded")
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.classification_evaluator_node  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401
    from spectra_sherpa.app.db.session import async_session
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
    from spectra_sherpa.app.services.dag.fold_graph_executor import (
        execute_candidate_validation_with_private_classification_trace,
        execute_selected_candidate_full_refit,
    )
    from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision
    from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.types import ensure_type_registry_loaded
    from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
    from spectra_sherpa.sdk.validate import make_leave_one_group_out_classification_plan

    ensure_type_registry_loaded()
    async with async_session() as session:
        loaded = await load_project_dataset(
            session,
            user_id=1,
            experiment_id=experiment_id,
            stage="raw",
            asset_id="spectrum",
            strict_prepared_data=True,
        )
    if loaded.project_id != project_id or loaded.experiment_id != experiment_id or len(loaded.file_ids) != 33:
        raise ValueError("qualification source does not belong to the exact project experiment")
    source, source_projection = _source_projection(loaded)
    attached = attach_target_dataset(
        source,
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
    if (
        plan.method != "leave_one_group_out_classification"
        or plan.held_out_groups != (1, 2, 3)
        or [len(fold.train) for fold in plan.folds] != [22, 22, 22]
        or [len(fold.test) for fold in plan.folds] != [11, 11, 11]
    ):
        raise ValueError("exact three-block split authority differs")
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="avatar-essential-oils-phase7",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    # Phase 8's authenticated no-fit ModelStore bridge must reconstruct the
    # original capability envelope exactly. Its provenance contains an
    # issuance timestamp, so retaining only the two capability digests is not
    # sufficient custody. Keep the complete bounded metadata private and
    # publish only its digest.
    original_capability_metadata = capability.to_wire()["metadata"]
    original_capability_metadata_sha256 = _json_digest(original_capability_metadata)
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "window",
                "selection.variable_select",
                {"method": "interval", "region_start": 3100.0, "region_end": 650.0},
            ),
            WorkflowNode("model", "classification.plsda", {"n_components": 5, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [
            WorkflowEdge("window", "model"),
            WorkflowEdge("model", "score", from_output="predictions", to_input="default"),
        ],
    )
    operation_ids = tuple(node.operation_id for node in graph.nodes)
    profile = managed_optimization_profile()
    runtime_attestation = profile.runtime_attestation(operation_ids)
    validation, trace = await execute_candidate_validation_with_private_classification_trace(graph, capability, plan)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)
    artifact = CanonicalFittedArtifact.from_full_refit_execution(refit)
    if _spectrochempy_loaded():
        raise ValueError("Phase 7 qualification loaded SpectroChemPy unexpectedly")

    labels = list(source.sample_axis.labels)
    table = source.sample_axis.sample_table
    fold_private: list[dict[str, object]] = []
    fold_public: list[dict[str, object]] = []
    all_test_indices: list[int] = []
    for ordinal, (split_fold, public_fold, private_fold, held_group) in enumerate(
        zip(plan.folds, validation.folds, trace.folds, plan.held_out_groups, strict=True), start=1
    ):
        test_indices = list(private_fold.test_indices)
        train_indices = [int(value) for value in split_fold.train]
        all_test_indices.extend(test_indices)
        if (
            test_indices != [int(value) for value in split_fold.test]
            or any(table["block"][index] != held_group for index in test_indices)
            or np.asarray(private_fold.class_responses).shape != (11, 11)
            or np.asarray(private_fold.decision_margins).shape != (11,)
            or np.any(np.asarray(private_fold.decision_margins) < 0.0)
        ):
            raise ValueError("private fold trace differs from its exact held-block partition")
        state_bytes = private_fold.fitted_state.canonical_state_bytes()
        if len(state_bytes) > MAX_PRIVATE_STATE_BYTES:
            raise ValueError("private fold fitted state exceeds its byte ceiling")
        state = json.loads(state_bytes)
        arrays = state.get("arrays") if isinstance(state, Mapping) else None
        if not isinstance(arrays, Mapping) or not {"coefficients", "x_loadings"}.issubset(arrays):
            raise ValueError("private fold state lacks coefficients and loadings")
        rows = []
        for local_index, source_index in enumerate(test_indices):
            rows.append(
                {
                    "source_index": source_index,
                    "sample_id": labels[source_index],
                    "specimen_id": table["specimen_id"][source_index],
                    "block": table["block"][source_index],
                    "truth": private_fold.truth[local_index],
                    "prediction": private_fold.predictions[local_index],
                    "margin": float(private_fold.decision_margins[local_index]),
                    "class_responses": np.asarray(private_fold.class_responses)[local_index].tolist(),
                }
            )
        public_metrics = _bounded_metrics(public_fold.metrics)
        fold_public.append(
            {
                "fold_ordinal": ordinal,
                "held_out_block": held_group,
                "training_count": len(train_indices),
                "test_count": len(test_indices),
                "partition_digest": public_fold.partition_digest,
                "fitted_state_digest": public_fold.fitted_state_digest,
                "prediction_application_digest": public_fold.prediction_application_digest,
                "metrics": public_metrics,
                "decision_margin_summary": {
                    "minimum": float(np.min(private_fold.decision_margins)),
                    "median": float(np.median(private_fold.decision_margins)),
                    "maximum": float(np.max(private_fold.decision_margins)),
                    "values_sha256": _array_digest(private_fold.decision_margins),
                },
            }
        )
        fold_private.append(
            {
                "fold_ordinal": ordinal,
                "held_out_block": held_group,
                "train_indices": train_indices,
                "test_indices": test_indices,
                "train_sample_ids": [labels[index] for index in train_indices],
                "test_rows": rows,
                "class_labels": list(private_fold.class_labels),
                "fitted_state": state,
                "fitted_state_digest": private_fold.fitted_state_digest,
                "application_digest": private_fold.application_digest,
            }
        )
    if sorted(all_test_indices) != list(range(33)):
        raise ValueError("held-block validation does not score every row exactly once")

    pooled = _bounded_metrics(validation.metrics)
    correct = sum(int(row[index]) for index, row in enumerate(pooled["confusion_matrix"]))
    private_report = {
        "schema_version": SCHEMA_VERSION,
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "source": source_projection,
        "supervision_binding": dict(binding.record),
        "supervision_binding_sha256": binding.digest,
        "split_plan": _split_plan_payload(plan),
        "split_plan_sha256": plan.digest,
        "graph": graph.as_dict(),
        "graph_sha256": graph.digest,
        "runtime_attestation": runtime_attestation.as_dict(),
        "original_capability_metadata": original_capability_metadata,
        "original_capability_metadata_sha256": original_capability_metadata_sha256,
        "validation": validation.as_dict(),
        "validation_sha256": validation.digest,
        "folds": fold_private,
        "full_refit": refit.as_dict(),
        "full_refit_sha256": refit.digest,
        "canonical_fitted_artifact": {
            "manifest": artifact.payload,
            "artifact_sha256": artifact.artifact_digest,
            "state_bytes_utf8": {
                node_id: payload.decode("utf-8") for node_id, payload in sorted(artifact.state_bytes.items())
            },
        },
    }
    contract_digests = {node.operation_id: node.contract.digest for node in graph.nodes}
    public_report = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase7_exact_closed_set_plsda_pipeline_and_phase8_custody_complete_author_operated",
        "observed_at": "2026-08-25",
        "runtime_implementation_commit": RUNTIME_IMPLEMENTATION_COMMIT,
        "source_and_supervision": {
            "source_collection": source_projection,
            "target_column": "specimen_id",
            "group_column": "block",
            "target_type": "categorical",
            "target_is_predictor": False,
            "group_is_predictor": False,
            "class_count": 11,
            "block_count": 3,
            "supervision_binding_sha256": binding.digest,
        },
        "workflow_and_split": {
            "graph_sha256": graph.digest,
            "execution_contract_digests": contract_digests,
            "managed_profile_id": profile.profile_id,
            "managed_profile_version": profile.profile_version,
            "managed_profile_sha256": profile.digest,
            "runtime_attestation": runtime_attestation.as_dict(),
            "split_method": plan.method,
            "split_plan_sha256": plan.digest,
            "held_out_blocks": list(plan.held_out_groups),
            "fold_count": 3,
            "training_count_per_fold": 22,
            "test_count_per_fold": 11,
            "all_rows_scored_once": True,
            "selection": {
                "method": "interval",
                "requested_bounds_cm-1": [3100.0, 650.0],
                "actual_endpoints_cm-1": EXPECTED_ACTUAL_ENDPOINTS,
                "selected_shape": EXPECTED_SELECTED_SHAPE,
                "mask_sha256": EXPECTED_SELECTION_MASK_SHA256,
                "selected_axis_sha256": EXPECTED_SELECTED_AXIS_SHA256,
                "selected_values_sha256": EXPECTED_SELECTED_VALUES_SHA256,
            },
            "model": {
                "operation_id": "classification.plsda",
                "n_components": 5,
                "scale": False,
                "decision_rule": "maximum_raw_dummy_response",
                "response_semantics": "class_response_scores_not_probabilities",
                "margin_rule": "largest_response_minus_second_largest_response",
            },
        },
        "validation": {
            "validation_execution_sha256": validation.digest,
            "n_samples": 33,
            "correct_decisions": correct,
            "chance_accuracy_reference": 1.0 / 11.0,
            "aggregate_metrics": _aggregate_metrics_projection(pooled),
            "pooled_metrics": pooled,
            "per_block": fold_public,
            "predeclared_five_components": True,
            "scale_false_frozen_after_author_probe": True,
            "untouched_independent_validation": False,
        },
        "full_refit": {
            "full_refit_execution_sha256": refit.digest,
            "validation_execution_sha256": validation.digest,
            "canonical_fitted_artifact_sha256": artifact.artifact_digest,
            "original_capability_metadata_retained_private": True,
            "original_capability_metadata_sha256": original_capability_metadata_sha256,
            "fitted_state_count": len(refit.fitted_states),
            "performance_estimate_attached_to_refit": False,
            "purpose": "application_artifact_only_not_independent_performance_evidence",
        },
        "privacy_boundary": {
            "raw_or_selected_spectra_published": False,
            "row_predictions_or_response_matrices_published": False,
            "coefficients_loadings_or_fitted_states_published": False,
            "private_paths_ids_or_artifact_uids_published": False,
            "supplier_information_published": False,
        },
        "claim_boundary": (
            "Author-operated custody reissue of the same frozen exact-corpus closed-set specimen-ID PLS-DA "
            "pipeline, retaining the original capability metadata required for later authenticated zero-fit "
            "application. No parameter, target, split, performance interpretation, or scientific claim changed."
        ),
        "nonclaims": [
            "non_author_physical_action_2",
            "botanical_identity_or_authenticity_validation",
            "population_new_lot_supplier_or_new_instrument_performance",
            "calibrated_probability_confidence_or_uncertainty",
            "untouched_independent_confirmation_after_author_probe",
            "redistribution_permission_or_public_corpus",
            "restart_import_or_paired_platform_repeatability_phase8_not_yet_executed",
        ],
    }
    return private_report, public_report


def _section_projections(report: Mapping[str, object]) -> dict[str, object]:
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
        "source_and_supervision": report.get("source_and_supervision"),
        "workflow_and_split": report.get("workflow_and_split"),
        "validation": report.get("validation"),
        "full_refit": report.get("full_refit"),
        "private_authority": report.get("private_evidence_authority"),
        "claim_boundary": {
            "privacy_boundary": report.get("privacy_boundary"),
            "claim_boundary": report.get("claim_boundary"),
            "nonclaims": report.get("nonclaims"),
        },
    }


def _semantic_failures(report: object, expected_sections: Mapping[str, str]) -> list[str]:
    failures: list[str] = []
    if not isinstance(report, Mapping) or set(report) != {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "status",
        "observed_at",
        "runtime_implementation_commit",
        "source_and_supervision",
        "workflow_and_split",
        "validation",
        "full_refit",
        "privacy_boundary",
        "claim_boundary",
        "nonclaims",
        "private_evidence_authority",
    }:
        return ["checked Phase 7 report does not use its closed top-level schema"]
    for name, projection in _section_projections(report).items():
        expected = expected_sections.get(name)
        if not _is_sha256(expected) or _json_digest(projection) != expected:
            failures.append(f"checked Phase 7 {name.replace('_', ' ')} authority differs")
    validation = report.get("validation")
    workflow = report.get("workflow_and_split")
    refit = report.get("full_refit")
    private = report.get("private_evidence_authority")
    privacy = report.get("privacy_boundary")
    if not isinstance(validation, Mapping) or validation.get("n_samples") != 33:
        failures.append("checked Phase 7 validation sample count differs")
    elif (
        not isinstance(validation.get("pooled_metrics"), Mapping)
        or not _aggregate_metrics_are_closed(validation.get("aggregate_metrics"))
        or validation.get("aggregate_metrics") != _aggregate_metrics_projection(validation["pooled_metrics"])
    ):
        failures.append("checked Phase 7 first-class aggregate metrics differ from the pooled authority")
    if (
        not isinstance(workflow, Mapping)
        or workflow.get("held_out_blocks") != [1, 2, 3]
        or workflow.get("fold_count") != 3
        or workflow.get("training_count_per_fold") != 22
        or workflow.get("test_count_per_fold") != 11
        or workflow.get("all_rows_scored_once") is not True
    ):
        failures.append("checked Phase 7 split projection differs")
    if (
        not isinstance(refit, Mapping)
        or refit.get("performance_estimate_attached_to_refit") is not False
        or refit.get("original_capability_metadata_retained_private") is not True
        or not _is_sha256(refit.get("original_capability_metadata_sha256"))
        or refit.get("validation_execution_sha256")
        != (validation.get("validation_execution_sha256") if isinstance(validation, Mapping) else None)
    ):
        failures.append("checked Phase 7 terminal-refit boundary differs")
    if (
        not isinstance(private, Mapping)
        or set(private) != {"private_report_size_bytes", "private_report_sha256", "private_report_published"}
        or private.get("private_report_published") is not False
        or not _is_sha256(private.get("private_report_sha256"))
        or not isinstance(private.get("private_report_size_bytes"), int)
    ):
        failures.append("checked Phase 7 private-report authority is malformed")
    if not isinstance(privacy, Mapping) or not privacy or not all(value is False for value in privacy.values()):
        failures.append("checked Phase 7 privacy boundary differs")
    return failures


def validate_checked_report(path: Path) -> list[str]:
    try:
        payload = _read_regular(path, private=False, limit=MAX_PUBLIC_REPORT_BYTES)
    except ValueError as exc:
        return [str(exc)]
    failures = []
    if not _is_sha256(CHECKED_REPORT_SHA256) or _sha256_bytes(payload) != CHECKED_REPORT_SHA256:
        failures.append("checked Phase 7 report digest differs from the reviewed authority")
    try:
        report = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return failures + ["checked Phase 7 report is not valid JSON"]
    failures.extend(_semantic_failures(report, EXPECTED_SECTION_DIGESTS))
    text = payload.decode("utf-8", errors="replace")
    for forbidden in (
        "/Users/",
        "private-input",
        '"sample_id"',
        '"source_index"',
        '"class_responses"',
        '"artifact_uid"',
        '"workspace_id"',
        '"user_id"',
    ):
        if forbidden in text:
            failures.append(f"checked Phase 7 report leaks forbidden private token {forbidden!r}")
    return failures


def _run(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    if not (workspace / "spectra_platform.db").is_file():
        raise ValueError("private qualification workspace database is absent")
    _configure_workspace(workspace)
    private_path = _private_output(args.private_report)
    public_path = Path(os.path.abspath(args.public_report))
    if str(private_path).casefold() == str(public_path).casefold():
        raise ValueError("private and public report paths must be distinct")
    for path in (private_path, public_path):
        try:
            path.relative_to(workspace)
        except ValueError:
            pass
        else:
            raise ValueError("qualification outputs must remain outside the live workspace")
    private, public = asyncio.run(_execute_exact(args.project_id, args.experiment_id))
    private_record = _atomic_write(
        private_path,
        _json_bytes(private, pretty=True),
        private=True,
        limit=MAX_PRIVATE_REPORT_BYTES,
    )
    public["private_evidence_authority"] = {
        "private_report_size_bytes": private_record["size_bytes"],
        "private_report_sha256": private_record["sha256"],
        "private_report_published": False,
    }
    _atomic_write(
        public_path,
        _json_bytes(public, pretty=True),
        private=False,
        limit=MAX_PUBLIC_REPORT_BYTES,
    )
    print("Avatar OMNIC Phase 7B PLS-DA: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--project-id", type=int, required=True)
    run.add_argument("--experiment-id", type=int, required=True)
    run.add_argument("--private-report", type=Path, required=True)
    run.add_argument("--public-report", type=Path, required=True)
    check = commands.add_parser("check-public")
    check.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return _run(args)
    failures = validate_checked_report(args.report)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Avatar OMNIC Phase 7B checked report: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
