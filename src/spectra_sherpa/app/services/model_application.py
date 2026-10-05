"""Apply persisted model artifacts to durable project datasets."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Sequence

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import (
    MAX_COLLECTION_MEMBERS,
    MAX_COLLECTION_SOURCE_BYTES,
    CollectionMember,
    assemble_collection,
    lossless_sample_table_scalar,
    prepared_data_digest,
    require_collection_budget,
)
from spectra_sherpa.app.lib.collection_definition import (
    ValidatedCollectionDefinition,
    apply_collection_definition,
    project_collection_definition,
    scientific_collection_identity,
)
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    copy_registered_reference_collection_extras,
    registered_reference_collection_identity,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.artifact_preprocessing_authority import (
    validate_experiment_source_provenance,
    validate_variable_selection_provenance,
)
from spectra_sherpa.app.services.collection_definitions import read_collection_definition
from spectra_sherpa.app.services.dag import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.io_contracts import extract_target_like
from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import evaluate_classification_v2
from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.app.services.dag.transport import reject_spectrochempy_transport
from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError, get_model_store
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    load_prepared_data_overrides,
    load_prepared_data_overrides_strict,
)
from spectra_sherpa.core.axis_semantics import axis_semantics, canonical_axis_unit
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class _UsePersistedCollectionDefinition:
    """Sentinel distinguishing a prospective definition from normal loading."""


_USE_PERSISTED_COLLECTION_DEFINITION = _UsePersistedCollectionDefinition()


@dataclass
class LoadedProjectDataset:
    dataset: SherpaDataset
    experiment_id: int
    experiment_name: str
    project_id: int | None
    file_ids: list[int]
    stage: str
    asset_id: str | None
    source_manifest_sha256: str
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str | None = None


@dataclass(frozen=True)
class _PinnedArtifactReader:
    """Serve one verified snapshot so application metadata and bytes cannot race."""

    artifact_uid: str
    manifest: dict[str, Any]
    arrays: dict[str, np.ndarray]

    def load(self, artifact_uid: str, *, verify: bool = True) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        del verify  # The snapshot was integrity-verified by ModelStore.load().
        if artifact_uid != self.artifact_uid:
            raise FileNotFoundError(f"Model artifact not found: {artifact_uid}")
        return dict(self.manifest), {name: np.array(values, copy=True) for name, values in self.arrays.items()}


async def load_project_dataset(
    session: "AsyncSession",
    *,
    user_id: int,
    experiment_id: int,
    stage: Literal["raw", "preprocessed", "synthetic"] = "raw",
    file_id: int | None = None,
    file_ids: Sequence[int] | None = None,
    asset_id: str | None = None,
    definition_override: ValidatedCollectionDefinition | _UsePersistedCollectionDefinition = (
        _USE_PERSISTED_COLLECTION_DEFINITION
    ),
    prepared_overrides_by_file: Mapping[str, PreparedDataOverrides] | None = None,
    strict_prepared_data: bool = False,
) -> LoadedProjectDataset:
    """Load a user-owned experiment collection as a SherpaDataset."""
    from sqlalchemy import or_, select

    from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
    from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.services.experiments import experiment_dir

    started = time.perf_counter()
    exp_result = await session.execute(
        select(Experiment)
        .where(Experiment.id == experiment_id, or_(Experiment.user_id == user_id, uses_managed_project_access()))
        .execution_options(populate_existing=True)
    )
    experiment = exp_result.scalar_one_or_none()
    if experiment is None:
        raise ValueError("Dataset not found")

    if uses_managed_project_access():
        await require_scientific_access(session, user_id, experiment.project_id, "read")

    if stage not in {"raw", "preprocessed", "synthetic"}:
        raise ValueError("Dataset stage must be raw, preprocessed, or synthetic")

    if file_id is not None and file_ids is not None:
        raise ValueError("Dataset loading accepts file_id or file_ids, not both")
    selected_file_ids: tuple[int, ...] | None = None
    if file_ids is not None:
        selected_file_ids = tuple(int(value) for value in file_ids)
        if not selected_file_ids or any(value < 1 for value in selected_file_ids):
            raise ValueError("Dataset file selection requires positive file identities")
        if len(set(selected_file_ids)) != len(selected_file_ids):
            raise ValueError("Dataset file selection contains duplicate identities")

    files_query = select(ExperimentFile).where(
        ExperimentFile.experiment_id == experiment_id,
        ExperimentFile.stage == stage,
    )
    if file_id is not None:
        files_query = files_query.where(ExperimentFile.id == file_id)
    elif selected_file_ids is not None:
        files_query = files_query.where(ExperimentFile.id.in_(selected_file_ids))
    files_query = files_query.order_by(ExperimentFile.id).execution_options(populate_existing=True)

    files = list((await session.execute(files_query)).scalars().all())
    if selected_file_ids is not None and {int(file.id) for file in files} != set(selected_file_ids):
        raise ValueError("Dataset file selection is outside the owned experiment stage")
    if not files and file_id is None and stage == "raw":
        synthetic_query = (
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == experiment_id, ExperimentFile.stage == "synthetic")
            .order_by(ExperimentFile.id)
            .execution_options(populate_existing=True)
        )
        files = list((await session.execute(synthetic_query)).scalars().all())
        if files:
            stage = "synthetic"

    if not files:
        raise ValueError("Dataset has no files for the requested scope")
    if len(files) > MAX_COLLECTION_MEMBERS:
        raise ValueError(f"scientific collection exceeds the {MAX_COLLECTION_MEMBERS}-member limit")
    if sum(int(file.file_size_bytes or 0) for file in files) > MAX_COLLECTION_SOURCE_BYTES:
        raise ValueError("scientific collection exceeds the 512 MiB source limit")

    base_dir = experiment_dir(experiment_id)
    helper = ExperimentDatasetReader("model_apply_dataset_loader", {"dataset_id": experiment_id})
    expected_override_keys = {str(file.file_path) for file in files}
    if prepared_overrides_by_file is not None and set(prepared_overrides_by_file) != expected_override_keys:
        raise ValueError("Dataset prepared-data snapshot does not match its exact file set")
    source_paths = [str(file.file_path) for file in files]

    def load_sources() -> list[Any]:
        loaded = []
        for file_path in source_paths:
            path = base_dir / file_path
            if not path.exists():
                raise ValueError(f"Dataset file is missing from storage: {file_path}")
            if prepared_overrides_by_file is not None:
                prepared = prepared_overrides_by_file[file_path]
            elif strict_prepared_data:
                prepared = load_prepared_data_overrides_strict(file_path=str(path))
            else:
                prepared = load_prepared_data_overrides(file_path=str(path))
            loaded.append(
                helper._load_file(
                    str(path),
                    file_name=file_path,
                    asset_id=asset_id,
                    prepared_overrides=prepared.to_sidecar_dict(),
                )
            )
        return loaded

    # Parsing and scientific projection are synchronous; keep them off the API
    # event loop so selection inspection cannot starve health checks or sockets.
    queried = time.perf_counter()
    loaded = await asyncio.to_thread(load_sources)
    parsed = time.perf_counter()

    definition = (
        await asyncio.to_thread(read_collection_definition, experiment_id)
        if definition_override is _USE_PERSISTED_COLLECTION_DEFINITION
        else definition_override
    )
    dataset = await asyncio.to_thread(
        _loaded_files_to_sherpa,
        loaded,
        experiment.name,
        definition=definition,
        project_definition=file_id is not None or selected_file_ids is not None,
    )
    source_manifest = dataset.meta["source_collection"]
    finished = time.perf_counter()
    logger.info(
        "dataset-load experiment=%s files=%s selected=%s query_ms=%.1f parse_ms=%.1f projection_ms=%.1f total_ms=%.1f",
        experiment_id,
        len(files),
        file_id is not None or selected_file_ids is not None,
        (queried - started) * 1000,
        (parsed - queried) * 1000,
        (finished - parsed) * 1000,
        (finished - started) * 1000,
    )
    return LoadedProjectDataset(
        dataset=dataset,
        experiment_id=experiment_id,
        experiment_name=experiment.name,
        project_id=experiment.project_id,
        file_ids=[int(file.id) for file in files],
        stage=stage,
        asset_id=asset_id,
        source_manifest_sha256=str(source_manifest["manifest_digest"]),
        collection_definition_sha256=source_manifest.get("collection_definition_sha256"),
        scientific_collection_sha256=source_manifest.get("scientific_collection_sha256"),
    )


def _loaded_files_to_sherpa(
    loaded: list[Any],
    experiment_name: str,
    *,
    definition: ValidatedCollectionDefinition | None = None,
    project_definition: bool = False,
) -> SherpaDataset:
    reject_spectrochempy_transport(loaded, boundary="model dataset-loader handoff")
    members: list[CollectionMember] = []
    for item in loaded:
        if len(item.source_members) != 1:
            raise ValueError(f"Dataset member {item.file_name!r} lacks one exact source identity")
        source = item.source_members[0]
        members.append(
            CollectionMember(
                dataset=item.dataset,
                file_name=item.file_name,
                size_bytes=source.size_bytes,
                sha256=source.sha256,
                prepared_data_sha256=prepared_data_digest(item.prepared_overrides),
                asset_id=item.selected_asset_id,
            )
        )
        require_collection_budget(members)
    effective_definition = (
        project_collection_definition(definition, members)
        if definition is not None and project_definition
        else definition
    )
    spectra = (
        apply_collection_definition(members, effective_definition)
        if effective_definition is not None
        else assemble_collection(
            members,
            title=experiment_name if len(members) == 1 else f"{experiment_name} ({len(members)} files)",
        )
    )
    # Collection assembly deliberately does not promote arbitrary member
    # metadata. A retained registered reference is the bounded exception: its
    # exact sidecar has already been re-admitted and its single projected
    # member must keep the authority that the server independently verifies
    # before issuing a trial grant. Ordinary paid-user files never enter this
    # branch and retain their normal collection behavior.
    if len(loaded) == 1:
        source = loaded[0].dataset
        copy_registered_reference_collection_extras(
            source,
            spectra,
            selected_asset_id=loaded[0].selected_asset_id,
        )
    manifest = spectra.meta["source_collection"]
    identity = scientific_collection_identity(manifest, effective_definition, spectra)
    if effective_definition is None:
        registered_identity = registered_reference_collection_identity(
            manifest,
            spectra,
            members=[(item.dataset, item.selected_asset_id) for item in loaded],
        )
        if registered_identity is not None:
            identity = registered_identity
    spectra.meta["source_collection"].update(identity)
    reject_spectrochempy_transport(spectra, boundary="model dataset-loader handoff")
    return spectra


async def apply_model_to_dataset(
    artifact_uid: str,
    dataset: SherpaDataset,
    *,
    scope: str = "all",
    execution_evidence: dict[str, Any] | None = None,
    presentation_multiplier: int = 1,
) -> dict[str, Any]:
    """Apply one artifact through the canonical DAG node and evaluator authorities."""
    store = get_model_store()
    try:
        manifest, arrays = store.load(artifact_uid)
    except FileNotFoundError as exc:
        raise ValueError(f"Model artifact not found: {artifact_uid}") from exc
    except ModelArtifactIntegrityError as exc:
        raise ValueError(f"Model artifact is corrupt: {exc}") from exc

    model_type = str(manifest.get("model_type", ""))
    y, target_warnings, target_metadata = _target_for_artifact(dataset, manifest)
    if scope != "all":
        _validate_partition_population(dataset, y, manifest)
    sample_count = int(np.asarray(dataset.X).shape[0])
    from spectra_sherpa.app.services.dag.presentation_limits import MAX_PRESENTATION_VALUES

    output_width = max(
        dataset.X.shape[1],
        int(manifest.get("n_components") or 1),
        len(manifest.get("classes") or []),
        len(manifest.get("target_names") or []),
    )
    if sample_count * output_width * presentation_multiplier > MAX_PRESENTATION_VALUES:
        raise ValueError("Model application exceeds its display limit (100,000 values); select a smaller cohort")
    sample_indices = _scope_indices_for_artifact(sample_count, manifest, scope=scope)
    if dataset.sample_axis is not None and dataset.sample_axis.include_mask is not None:
        sample_indices = sample_indices[np.asarray(dataset.sample_axis.include_mask, dtype=bool)[sample_indices]]
    if sample_indices.size == 0:
        raise ValueError("No included samples remain in the requested model application scope")
    scoped_dataset = dataset if np.array_equal(sample_indices, np.arange(sample_count)) else dataset[sample_indices, :]
    feature_indices = np.arange(dataset.X.shape[-1], dtype=np.int64)
    if dataset.feature_axis is not None and dataset.feature_axis.include_mask is not None:
        feature_indices = feature_indices[np.asarray(dataset.feature_axis.include_mask, dtype=bool)]
        if feature_indices.size == 0:
            raise ValueError("No included features remain in the requested model application selection")
        if feature_indices.size != dataset.X.shape[-1]:
            key = (slice(None),) * (dataset.ndim - 1) + (feature_indices,)
            scoped_dataset = scoped_dataset[key]
    y_scoped = y[sample_indices] if y is not None else None

    input_node_id = "application-model-input"
    model_node_id = "application-model-artifact"
    input_stream = "application-model-dataset"
    executor = DAGExecutor(
        runtime=build_application_execution_runtime(
            model_artifact_reader=_PinnedArtifactReader(
                artifact_uid=artifact_uid,
                manifest=manifest,
                arrays=arrays,
            )
        )
    )
    executor.add_node(
        WorkflowNode(
            node_id=input_node_id,
            node_type="deploy.input",
            parameters={
                "stream_name": input_stream,
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
        )
    )
    executor.add_node(
        WorkflowNode(
            node_id=model_node_id,
            node_type="model.load_apply",
            parameters={"model_id": artifact_uid},
        )
    )
    executor.add_edge(
        WorkflowEdge(
            from_node=input_node_id,
            to_node=model_node_id,
            from_output="default",
            to_input="X_new",
        )
    )
    executor.inject_deployment_input(input_node_id, scoped_dataset, stream_name=input_stream)
    try:
        applied = (await executor.execute())[model_node_id]
    finally:
        if execution_evidence is not None:
            from spectra_sherpa.app.services.dag.presentation_contract import describe_executed_presentations
            from spectra_sherpa.app.services.dag.scientific_values import describe_node_outputs

            descriptors = {
                key: describe_node_outputs(executor.nodes[key].metadata, value)
                for key, value in executor.results.items()
            }
            presentations = {
                key: describe_executed_presentations(executor.nodes[key].metadata, value)
                for key, value in descriptors.items()
            }
            execution_evidence.update(
                outputs=dict(executor.results),
                node_statuses={key: node.status.value for key, node in executor.nodes.items()},
                diagnostics={
                    **executor.diagnostics,
                    "_scientific_values": descriptors,
                    "_scientific_presentations": presentations,
                },
                definition={
                    "schema_version": 1,
                    "nodes": [
                        {
                            "node_id": key,
                            "node_type": node.metadata.node_type,
                            "label": node.metadata.label,
                            "parameters": node._resolve_params(),
                        }
                        for key, node in executor.nodes.items()
                    ],
                    "edges": [
                        {
                            "from_node_id": edge.from_node,
                            "to_node_id": edge.to_node,
                            "from_output": edge.from_output,
                            "to_input": edge.to_input,
                        }
                        for edge in executor.edges
                    ],
                },
            )
    result_matrix = np.asarray(applied["result"])
    node_metadata = dict(applied.get("metadata") or {})
    warnings = list(target_warnings)
    applicability_warning = node_metadata.get("applicability_warning")
    if isinstance(applicability_warning, str) and applicability_warning:
        warnings.append(applicability_warning)

    response: dict[str, Any] = {
        "artifact_uid": artifact_uid,
        "model_type": model_type,
        "scope": scope,
        "sample_indices": sample_indices.tolist(),
        "feature_indices": feature_indices.tolist(),
        "n_samples": int(result_matrix.shape[0]),
        "warnings": warnings,
        "metadata": {
            "classes": list(node_metadata.get("classes", manifest.get("classes", [])) or []),
            "preprocessing_chain": manifest.get("preprocessing_chain", []),
            "training_data_hash": manifest.get("training_data_hash"),
            **target_metadata,
        },
    }

    if node_metadata.get("output_type") == "clustering":
        labels = [lossless_sample_table_scalar(label) for label in applied["labels"]]
        response["predictions"] = labels
        response["cluster_assignments"] = labels
        response["output_type"] = "clustering"
        response["metrics"] = None
        return response

    if node_metadata.get("output_type") == "classification":
        labels_list = [lossless_sample_table_scalar(label) for label in list(applied["labels"])]
        response["predictions"] = labels_list
        output_key = "class_responses" if model_type == "plsda" else "probabilities"
        response[output_key] = np.asarray(result_matrix, dtype=np.float64).tolist()
        response["classification_output_semantics"] = (
            "class_response_scores_not_probabilities" if model_type == "plsda" else "class_probabilities"
        )
        if model_type == "plsda":
            response["decision_margins"] = np.asarray(applied["decision_margins"], dtype=np.float64).tolist()
            response["classification_application_digest"] = str(applied["classification_application_digest"])
        if y_scoped is not None:
            y_true = [lossless_sample_table_scalar(label) for label in y_scoped.tolist()]
            response["true_labels"] = y_true
            response["metrics"] = evaluate_classification_v2(
                labels_list,
                y_true,
                node_id="application-classification-evaluator",
            ).outputs["default"]
        else:
            response["metrics"] = None
        return response

    if node_metadata.get("output_type") == "regression":
        predicted_arr = np.asarray(result_matrix, dtype=np.float64)
        response["predictions"] = predicted_arr.tolist()
        response["metrics"] = (
            evaluate_regression_v2(
                predicted_arr,
                y_scoped,
                node_id="application-regression-evaluator",
            ).outputs["default"]
            if y_scoped is not None
            else None
        )
        applicability = applied.get("applicability")
        if applicability is not None:
            response["applicability"] = applicability
        return response

    if node_metadata.get("output_type") == "decomposition":
        response["transformed"] = np.asarray(result_matrix).tolist()
        response["metrics"] = None
        return response

    raise ValueError(f"Model type {model_type!r} cannot be applied")


def _artifact_selected_target(manifest: dict[str, Any]) -> str | None:
    selected = manifest.get("selected_target")
    if isinstance(selected, str) and selected.strip():
        return selected.strip()
    target_names = manifest.get("target_names")
    if manifest.get("target_mode") == "single" and isinstance(target_names, list) and len(target_names) == 1:
        only = target_names[0]
        return str(only).strip() if str(only).strip() else None
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _target_for_artifact(
    dataset: SherpaDataset,
    manifest: dict[str, Any],
) -> tuple[np.ndarray | None, list[str], dict[str, Any]]:
    """Return apply-time y values interpreted with the artifact's target contract.

    Training nodes persist ``selected_target``/``target_names`` in the model
    manifest. Load & Apply must evaluate labeled data against that same target
    instead of comparing single-target predictions to an unsliced multi-target
    table, which otherwise silently suppresses RMSEP/R²/bias.
    """
    warnings: list[str] = []
    metadata: dict[str, Any] = {}
    selected = _artifact_selected_target(manifest)
    manifest_targets = _string_list(manifest.get("target_names"))
    available_targets = _string_list(manifest.get("available_target_names")) or manifest_targets
    if selected:
        metadata["selected_target"] = selected
        metadata["target_mode"] = "single"
    if manifest_targets:
        metadata["target_names"] = manifest_targets
    if available_targets and available_targets != manifest_targets:
        metadata["available_target_names"] = available_targets

    if dataset.target is None:
        return None, warnings, metadata

    response_identity = manifest.get("response_identity")
    if isinstance(response_identity, dict) and not response_identity.get("names"):
        warnings.append("Evaluation unavailable: the fitted response has no recorded target identity.")
        return None, warnings, metadata

    original_context = dataset.target_context
    if isinstance(response_identity, dict):
        recorded_units = response_identity.get("units") or []
        actual_unit = getattr(original_context, "target_units", None)
        if actual_unit and any(unit is not None and unit != actual_unit for unit in recorded_units):
            raise ValueError("Application target units differ from the saved response authority.")
    context_names = _string_list(getattr(original_context, "target_names", None)) if original_context else []
    if selected:
        names = context_names
        if names.count(selected) == 1 and original_context is not None:
            dataset.target_context = original_context.model_copy(
                update={"target_names": names, "selected_target": selected}
            )
            try:
                target = extract_target_like(dataset)
                return np.asarray(target) if target is not None else None, warnings, metadata
            finally:
                dataset.target_context = original_context

        raise ValueError(
            f"Saved model was trained for target {selected!r}, but that target could not be matched in the "
            "labeled dataset. Bind the matching target before application."
        )

    if manifest_targets and (
        context_names != manifest_targets or getattr(original_context, "selected_target", None) is not None
    ):
        raise ValueError("Application target names and order must match the saved model's complete target contract.")

    target = extract_target_like(dataset)
    return np.asarray(target) if target is not None else None, warnings, metadata


def _applicability_diagnostics(extract: Any, X_ready: np.ndarray) -> dict[str, Any] | None:
    diagnostics_fn = getattr(extract, "applicability_diagnostics", None)
    if not callable(diagnostics_fn):
        return None
    diagnostics = diagnostics_fn(X_ready)
    if not isinstance(diagnostics, dict):
        return None
    return diagnostics


async def compare_models_on_dataset(
    artifact_uids: list[str],
    dataset: SherpaDataset,
    *,
    scope: str = "all",
) -> dict[str, Any]:
    from spectra_sherpa.app.services.dag.presentation_limits import require_bounded_presentation

    require_bounded_presentation(dataset, surface="Model comparison", multiplier=max(1, len(artifact_uids)))
    results = [
        await apply_model_to_dataset(uid, dataset, scope=scope, presentation_multiplier=len(artifact_uids))
        for uid in artifact_uids
    ]
    comparison: dict[str, Any] = {
        "scope": scope,
        "models": results,
        "pairwise": [],
    }
    if len(results) >= 2 and all("predictions" in result for result in results):
        base = results[0]
        base_pred = list(base["predictions"])
        for other in results[1:]:
            other_pred = list(other["predictions"])
            n = min(len(base_pred), len(other_pred))
            disagreements = [i for i in range(n) if base_pred[i] != other_pred[i]]
            comparison["pairwise"].append(
                {
                    "left_artifact_uid": base["artifact_uid"],
                    "right_artifact_uid": other["artifact_uid"],
                    "n_compared": n,
                    "n_disagreements": len(disagreements),
                    "disagreement_fraction": len(disagreements) / n if n else 0.0,
                    "disagreement_indices": disagreements[:1000],
                    "truncated": len(disagreements) > 1000,
                }
            )
    return comparison


def _prepare_X_for_artifact(
    X: np.ndarray,
    y: np.ndarray | None,
    manifest: dict[str, Any],
    *,
    scope: str,
    source_dataset: Any | None = None,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray, list[str]]:
    matrix, target, indices, warnings, _ = _prepare_artifact_input(
        X, y, manifest, scope=scope, source_dataset=source_dataset
    )
    return matrix, target, indices, warnings


def _prepare_artifact_input(
    X: np.ndarray,
    y: np.ndarray | None,
    manifest: dict[str, Any],
    *,
    scope: str,
    source_dataset: Any | None = None,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray, list[str], SherpaDataset | None]:
    warnings: list[str] = []
    chain = manifest.get("preprocessing_chain") or []
    indices = _scope_indices_for_artifact(X.shape[0], manifest, scope=scope)

    X_work = X[indices]
    replay_source = copy.copy(source_dataset) if isinstance(source_dataset, SherpaDataset) else None
    y_work = y[indices] if y is not None else None

    non_transforming_provenance = {
        "data.file_load",
        "data.attach_target",
        "data.train_test_split",
    }
    for step in chain:
        if not isinstance(step, Mapping) or set(step) != {"op_id", "parameters"}:
            raise ValueError("model artifact preprocessing provenance is malformed")
        op_id = step.get("op_id")
        params = step.get("parameters", {})
        if not isinstance(op_id, str) or not op_id or not isinstance(params, Mapping):
            raise ValueError("model artifact preprocessing provenance is malformed")
        params = dict(params)
        if op_id in non_transforming_provenance:
            continue
        if op_id == "spectrasherpa.experiment_dataset_read/2":
            validate_experiment_source_provenance(params)
            continue
        if op_id == "selection.variable_select":
            validate_variable_selection_provenance(
                params,
                manifest=manifest,
                source_dataset=source_dataset,
            )
            continue
        if op_id == "preprocess.scale":
            state = params.get("transform_state")
            if isinstance(state, Mapping):
                from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import (
                    _apply_scale_state,
                    scaled_signal_units,
                )

                X_work = _apply_scale_state(X_work, state, source_dataset=replay_source)
                if replay_source is not None:
                    replay_source.units = scaled_signal_units(replay_source.units, state["method"])
            else:
                raise ValueError(
                    "preprocess.scale has no replayable transform_state; re-train the model with a current "
                    "SpectraSherpa version or apply the same preprocessing upstream before Load & Apply"
                )
            continue
        if op_id == "preprocess.normalize":
            X_work = _apply_normalize_step(X_work, params)
            if replay_source is not None:
                replay_source.units = "dimensionless" if params.get("method") == "snv" else "normalized"
            continue
        if op_id == "preprocess.msc":
            X_work = _apply_msc_step(X_work, params, source_dataset=replay_source)
            if replay_source is not None:
                replay_source.units = params["transform_state"]["input_identity"]["signal_units"]
            continue
        if op_id == "preprocess.emsc":
            X_work = _apply_emsc_step(X_work, params, source_dataset=source_dataset)
            continue
        if op_id == "preprocess.smooth":
            X_work = _apply_smooth_step(X_work, params)
            continue
        if op_id == "preprocess.derivative":
            X_work = _apply_derivative_step(X_work, params)
            if replay_source is not None:
                from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import _update_derivative_units

                _update_derivative_units(replay_source, replay_source, int(str(params["deriv"])))
            continue
        if op_id == "baseline.penalized_ls":
            X_work = _apply_penalized_baseline_step(X_work, params)
            continue
        if op_id == "baseline.rubberband":
            raise ValueError(
                "baseline.rubberband is recorded in the model preprocessing chain but is not replayable "
                "in artifact application. Apply the same rubberband correction upstream before Load & Apply, "
                "or re-train with a replayable baseline method."
            )
        if op_id == "preprocess.osc":
            X_work = _apply_osc_step(X_work, params, source_dataset=source_dataset)
            continue
        raise ValueError(
            f"Processing step {op_id!r} is recorded but has no certified artifact-application replay. "
            "Apply that canonical operation explicitly upstream, or train and export a model whose complete "
            "scientific path is replayable."
        )

    return X_work, y_work, indices, warnings, replay_source


def _validate_partition_population(dataset: SherpaDataset, y: np.ndarray | None, manifest: Mapping[str, Any]) -> None:
    """Stored positions are meaningful only against their original bound inputs."""
    from dataclasses import fields

    from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
        SplitPlan,
        _validate_plan_binding,
        bind_split_groups,
    )

    partition = _find_partition_step(manifest.get("preprocessing_chain") or [])
    if partition is None or any(field.name not in partition for field in fields(SplitPlan)):
        raise ValueError(
            "Saved train/test scope lacks its complete input-bound split plan. "
            "Use included samples or select an artifact with exact partition evidence."
        )
    values = {field.name: partition[field.name] for field in fields(SplitPlan)}
    for key in ("train_indices", "test_indices"):
        values[key] = np.asarray(values[key])
    if values["held_out_groups"] is not None:
        values["held_out_groups"] = tuple(values["held_out_groups"])
    plan = SplitPlan(**values)
    _validate_plan_binding(np.asarray(dataset.X), y, plan, bind_split_groups(dataset))


def _scope_indices_for_artifact(
    sample_count: int,
    manifest: Mapping[str, Any],
    *,
    scope: str,
) -> np.ndarray:
    """Resolve the artifact's declared row scope without performing science."""

    if scope not in {"all", "train", "test"}:
        raise ValueError("Model application scope must be one of: all, train, test")
    indices = np.arange(sample_count, dtype=np.int64)
    if scope == "all":
        return indices
    chain = manifest.get("preprocessing_chain") or []
    partition = _find_partition_step(chain)
    if partition is None:
        raise ValueError(f"Model artifact does not contain train/test partition provenance for scope={scope!r}")
    key = "train_indices" if scope == "train" else "test_indices"
    raw_indices = np.asarray(partition.get(key) or [])
    if raw_indices.ndim != 1 or raw_indices.dtype.kind not in {"i", "u"}:
        raise ValueError("Stored partition indices must be an integer vector")
    indices = np.asarray(raw_indices, dtype=np.int64)
    if indices.size == 0:
        raise ValueError(f"Model artifact does not contain {key}")
    if int(indices.max()) >= sample_count or int(indices.min()) < 0:
        raise ValueError("Stored partition indices do not match this dataset")
    if np.unique(indices).size != indices.size:
        raise ValueError("Stored partition indices contain duplicate samples")
    declared_count = partition.get("n_samples")
    if declared_count is not None and (isinstance(declared_count, bool) or declared_count != sample_count):
        raise ValueError("Stored partition sample count does not match this dataset")
    return indices


def _find_partition_step(chain: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in chain:
        if step.get("op_id") == "data.train_test_split":
            params = step.get("parameters")
            return dict(params) if isinstance(params, Mapping) else None
    return None


def _apply_normalize_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import (
        NormalizeNode,
        _normalize_dispatch,
    )

    state = params.get("transform_state")
    if not isinstance(state, Mapping):
        raise ValueError("preprocess.normalize requires its complete canonical transform_state")
    raw = {key: value for key, value in params.items() if key != "transform_state"}
    expected = {parameter.name for parameter in NormalizeNode.metadata.parameters}
    if set(raw) != expected:
        raise ValueError("preprocess.normalize requires its complete canonical parameter record")
    projected = NormalizeNode.metadata.canonicalize_parameters(raw)
    method = str(projected["method"])
    if state.get("method") != method:
        raise ValueError("preprocess.normalize transform_state method does not match its canonical parameters")
    if method == "snv":
        if state.get("replay") != "sample_local" or state.get("std_ddof") != projected["std_ddof"]:
            raise ValueError("preprocess.normalize SNV transform_state is inconsistent")
    elif method == "scale":
        if state.get("replay") != "sample_local" or state.get("scale_method") != projected["scale_method"]:
            raise ValueError("preprocess.normalize scale transform_state is inconsistent")
    return _normalize_dispatch(X, **projected)


def _apply_msc_step(
    X: np.ndarray,
    params: dict[str, Any],
    *,
    source_dataset: Any | None,
) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import (
        MSCNode,
        _apply_msc_state,
        _feature_axis,
    )

    required = {"reference_method", "state_serializer", "transform_state"}
    if set(params) != required:
        raise ValueError("preprocess.msc requires its complete canonical parameter and fitted-state record")
    state = params.get("transform_state")
    if not isinstance(state, Mapping):
        raise ValueError("preprocess.msc requires its complete canonical fitted state")
    projected = MSCNode.metadata.canonicalize_parameters({"reference_method": params["reference_method"]})
    contract = MSCNode.metadata.resolved_execution_contract()
    if contract is None or params["state_serializer"] != contract.payload["fitted_state_serializer"]:
        raise ValueError("preprocess.msc state serializer is not canonical")
    if state.get("reference_method") != projected["reference_method"]:
        raise ValueError("preprocess.msc parameters do not match its fitted state")
    axis_values: np.ndarray | None = None
    axis_units: str | None = None
    if source_dataset is not None:
        axis_values, axis_units = _feature_axis(source_dataset, features=X.shape[1])
    return _apply_msc_state(
        X,
        state,
        feature_axis_values=axis_values,
        feature_axis_units=axis_units,
        source_dataset=source_dataset,
    )


def _apply_emsc_step(
    X: np.ndarray,
    params: dict[str, Any],
    *,
    source_dataset: Any | None,
) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node import (
        EMSCNode,
        _apply_emsc_state,
        _axis_record,
    )

    required = {"reference_method", "poly_order", "state_serializer", "transform_state"}
    if set(params) != required:
        raise ValueError("preprocess.emsc requires its complete canonical parameter and fitted-state record")
    state = params.get("transform_state")
    if not isinstance(state, Mapping):
        raise ValueError("preprocess.emsc requires its complete canonical fitted state")
    if params["state_serializer"] != "spectra.emsc-reference-json.v1":
        raise ValueError("preprocess.emsc state serializer is not canonical")
    projected = EMSCNode.metadata.canonicalize_parameters(
        {"reference_method": params["reference_method"], "poly_order": params["poly_order"]}
    )
    if (
        state.get("reference_method") != projected["reference_method"]
        or state.get("poly_order") != projected["poly_order"]
    ):
        raise ValueError("preprocess.emsc parameters do not match its fitted state")
    if source_dataset is None:
        raise ValueError("preprocess.emsc replay requires the exact source dataset feature axis")
    axis_values, axis_units = _axis_record(source_dataset, features=X.shape[1])
    return _apply_emsc_state(
        X,
        state,
        feature_axis_values=axis_values,
        feature_axis_units=axis_units,
    )


def _apply_osc_step(
    X: np.ndarray,
    params: dict[str, Any],
    *,
    source_dataset: Any | None,
) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.osc_node import (
        OSCNode,
        _apply_osc_state,
        _axis_record,
    )

    required = {
        "algorithm",
        "n_components",
        "state_serializer",
        "transform_state",
        "variance_removed_percent",
    }
    if set(params) != required:
        raise ValueError("preprocess.osc requires its complete canonical parameter and fitted-state record")
    state = params.get("transform_state")
    if not isinstance(state, Mapping):
        raise ValueError("preprocess.osc requires its complete canonical fitted state")
    projected = OSCNode.metadata.canonicalize_parameters({"n_components": params["n_components"]})
    contract = OSCNode.metadata.resolved_execution_contract()
    if contract is None or params["state_serializer"] != contract.payload["fitted_state_serializer"]:
        raise ValueError("preprocess.osc state serializer is not canonical")
    if params["algorithm"] != state.get("algorithm") or projected["n_components"] != state.get("n_components"):
        raise ValueError("preprocess.osc parameters do not match its fitted state")
    variance_removed = params["variance_removed_percent"]
    if (
        isinstance(variance_removed, bool)
        or not isinstance(variance_removed, (int, float))
        or not np.isfinite(variance_removed)
        or float(variance_removed) < 0.0
        or float(variance_removed) > 100.0
    ):
        raise ValueError("preprocess.osc variance removed must be between zero and 100")
    if not np.isclose(
        float(variance_removed),
        float(state.get("training_centered_variance_removed_percent", np.nan)),
        rtol=0.0,
        atol=0.0,
    ):
        raise ValueError("preprocess.osc variance diagnostic does not match its fitted state")
    if source_dataset is None:
        raise ValueError("preprocess.osc replay requires the exact source dataset feature axis")
    axis_values, axis_units = _axis_record(source_dataset, features=X.shape[1])
    return _apply_osc_state(
        X,
        state,
        feature_axis_values=axis_values,
        feature_axis_units=axis_units,
    )


def _apply_penalized_baseline_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node import (
        BaselinePenalizedLSNode,
        _penalized_baseline_dispatch,
    )

    projected = BaselinePenalizedLSNode.metadata.canonicalize_parameters(params)
    corrected, _diagnostics = _penalized_baseline_dispatch(X, **projected)
    return corrected


def _apply_smooth_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import (
        SmoothNode,
        _smooth_dispatch,
    )

    expected = {parameter.name for parameter in SmoothNode.metadata.parameters}
    if set(params) != expected:
        raise ValueError("preprocess.smooth requires its complete canonical parameter record")
    projected = SmoothNode.metadata.canonicalize_parameters(params)
    return _smooth_dispatch(X, **projected)


def _apply_derivative_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import (
        DerivativeNode,
        _derivative_dispatch,
    )

    raw = {key: value for key, value in params.items() if key != "delta"}
    expected = {parameter.name for parameter in DerivativeNode.metadata.parameters}
    if set(raw) != expected or set(params) != expected | {"delta"}:
        raise ValueError("preprocess.derivative requires its complete canonical parameter and axis record")
    projected = DerivativeNode.metadata.canonicalize_parameters(raw)
    delta = params["delta"]
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not np.isfinite(delta) or delta == 0:
        raise ValueError("preprocess.derivative axis spacing must be a finite non-zero number")
    return _derivative_dispatch(X, delta=delta, **projected)


def _apply_feature_mask(
    X: np.ndarray,
    dataset: SherpaDataset,
    manifest: dict[str, Any],
) -> tuple[np.ndarray, list[str]]:
    feature_mask = manifest.get("feature_mask")
    if feature_mask is None:
        return X, []
    mask = np.asarray(feature_mask, dtype=bool)
    selected_count = int(mask.sum())
    if mask.size == X.shape[1]:
        return X[:, mask], [f"Applied saved feature mask ({mask.size} -> {selected_count} features)"]
    if selected_count == X.shape[1]:
        return X, []
    raise ValueError(
        "Feature mask mismatch: model artifact mask does not match supplied dataset feature count "
        f"(mask={mask.size}, selected={selected_count}, supplied={X.shape[1]})"
    )


def validate_prepared_feature_contract(X: np.ndarray, manifest: dict[str, Any]) -> None:
    """Validate the final matrix shape after preprocessing and feature replay."""
    expected_features = manifest.get("n_features")
    if expected_features is None:
        return
    expected = int(expected_features)
    supplied = int(X.shape[1])
    if supplied != expected:
        raise ValueError(f"Feature count mismatch after preprocessing replay: model expects {expected}, got {supplied}")


def validate_feature_contract(
    X: np.ndarray,
    dataset: SherpaDataset | Any,
    manifest: dict[str, Any],
) -> None:
    """Hard-fail if an artifact is applied to incompatible feature space.

    Artifact application is operationally dangerous when the feature axis drifts:
    the model can still produce numbers, but they are chemically meaningless.
    This guard validates feature count, stored selection masks, axis values, and
    units whenever those contracts are present in the manifest.
    """
    expected_raw = manifest.get("n_features")
    if expected_raw is None:
        return
    expected_features = int(expected_raw)
    supplied_features = int(X.shape[1])

    feature_mask = manifest.get("feature_mask")
    mask: np.ndarray | None = None
    axis_masked = False
    if feature_mask is not None:
        mask = np.asarray(feature_mask, dtype=bool)
        if supplied_features == expected_features:
            axis_masked = False
        elif mask.size == supplied_features and int(mask.sum()) == expected_features:
            axis_masked = True
        else:
            raise ValueError(
                "Feature-contract mismatch: artifact expects "
                f"{expected_features} selected features from a {mask.size}-feature source, "
                f"but dataset has {supplied_features} features"
            )
    elif supplied_features != expected_features:
        raise ValueError(
            f"Feature count mismatch: artifact expects {expected_features} features, "
            f"but dataset has {supplied_features}"
        )

    expected_axis = manifest.get("feature_axis")
    if expected_axis is None:
        return
    expected_values = np.asarray(expected_axis, dtype=np.float64)
    if expected_values.size != expected_features:
        raise ValueError(
            "Feature-contract mismatch: artifact manifest has "
            f"{expected_values.size} feature-axis points for {expected_features} features"
        )

    if not isinstance(dataset, SherpaDataset):
        raise ValueError("Feature-contract mismatch: dataset has no typed feature axis for artifact validation")

    axis = dataset.get_feature_axis()
    if axis is None or axis.values is None:
        raise ValueError("Feature-contract mismatch: dataset has no feature-axis values")

    actual_values = np.asarray(axis.values, dtype=np.float64)
    if mask is not None and mask.size == actual_values.size and int(mask.sum()) == expected_features:
        # For non-contiguous variable selections, compare selected coordinates
        # as actual_wn[mask], not actual_wn[:len(selected)].
        actual_values = actual_values[mask]
    elif axis_masked:
        raise ValueError(
            "Feature-contract mismatch: artifact feature mask cannot be applied to dataset feature-axis values"
        )

    if actual_values.size != expected_values.size:
        raise ValueError(
            "Feature-contract mismatch: dataset feature-axis length "
            f"{actual_values.size} does not match artifact length {expected_values.size}"
        )
    if not np.allclose(actual_values, expected_values, rtol=1e-6, atol=1e-6, equal_nan=False):
        raise ValueError("Feature-contract mismatch: dataset feature-axis values differ from the artifact")

    expected_units = manifest.get("feature_axis_units")
    if expected_units:
        actual_units = getattr(axis, "units", None)
        if not actual_units:
            raise ValueError("Feature-contract mismatch: dataset feature-axis units are missing")
        if canonical_axis_unit(str(actual_units)) != canonical_axis_unit(str(expected_units)):
            raise ValueError(
                "Feature-contract mismatch: dataset feature-axis units "
                f"{actual_units!r} differ from artifact units {expected_units!r}"
            )

    expected_quantity = manifest.get("feature_axis_quantity")
    if expected_quantity is not None:
        actual_semantics = axis_semantics(
            axis_class=type(axis).__name__,
            title=getattr(axis, "title", None),
            units=getattr(axis, "units", None),
            quantity=getattr(axis, "quantity", None),
        )
        if actual_semantics.quantity is None:
            raise ValueError("Feature-contract mismatch: dataset feature-axis quantity is missing")
        if actual_semantics.quantity.value != expected_quantity:
            raise ValueError(
                "Feature-contract mismatch: dataset feature-axis quantity "
                f"{actual_semantics.quantity.value!r} differs from artifact quantity {expected_quantity!r}"
            )
