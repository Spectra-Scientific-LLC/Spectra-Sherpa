"""Execution-local dataset binding for project Batch verification.

This module changes source custody, not scientific algorithms: fitting, splits,
evaluation, artifact publication and retention remain owned by the normal DAG
execution path. Nothing here writes a saved workflow or its source selection.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import numpy as np
from fastapi import HTTPException

from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.services.model_application import LoadedProjectDataset
from spectra_sherpa.app.services.workflow_access import workflow_requires_canonical_artifact_grant
from spectra_sherpa.core.scientific_refusal import ScientificInputRefusal


@dataclass
class VerificationRefusalContext:
    """Public model context populated only after normal ownership/integrity admission."""

    target_name: str | None = None


class BatchAuthorityChanged(HTTPException):
    """Re-admission failure: no partial scientific output may be published."""

    def __init__(self):
        super().__init__(409, "Batch source authority changed; review a fresh preflight before retrying")


def preflight_refusal_reason(status_code: int) -> str:
    """Public recovery advice for admitted refusal statuses, never exception text."""
    return {
        400: "The dataset or model could not be read. Re-import the dataset or choose another saved model.",
        409: (
            "Saved inputs changed or failed integrity checks. " "Reload the dataset and model, then retry preflight."
        ),
        422: "This combination is not valid. Review the workflow, dataset selection and target settings.",
    }[status_code]


def verification_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def included_dataset(dataset):
    """Use the definition's inclusion decisions, never an old model partition."""
    if dataset.ndim != 2:
        raise ValueError("Batch verification requires a two-dimensional dataset definition.")
    selected = dataset
    for dimension, axis in enumerate((dataset.sample_axis, dataset.feature_axis)):
        mask = getattr(axis, "include_mask", None)
        if mask is not None:
            indices = np.flatnonzero(mask)
            if not len(indices):
                raise ValueError("The dataset definition has no included samples or features.")
            selected = selected[indices, :] if dimension == 0 else selected[:, indices]
    if not all(selected.shape):
        raise ValueError("The dataset definition is empty.")
    return selected


def _rebind_target_intent(parameters, dataset):
    from spectra_sherpa.app.lib.target_authority import issue_target_authority
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset
    from spectra_sherpa.core.target_authority import admit_target_authority

    authority = admit_target_authority(parameters.get("target_authority"))
    if parameters.get("target_mode") not in {None, "", "auto", "dataset_default"}:
        raise ValueError("Save an explicit target authority before using this legacy target selection in Batch.")
    if authority is None:
        if parameters.get("group_column"):
            raise ValueError("The workflow's group selection needs an explicit target authority.")
        return {}, dataset
    observed = issue_target_authority(dataset, column=authority.column, target_type=authority.target_type)
    if observed.units != authority.units:
        raise ValueError("The new dataset target units differ from the workflow's saved target.")
    selected = getattr(dataset.target_context, "selected_authority", None)
    if selected is not None and (selected.column, selected.target_type) != (authority.column, authority.target_type):
        raise ValueError("The dataset definition selects a different target than this workflow.")
    group = parameters.get("group_column") or ""
    selected_dataset = attach_selected_target_dataset(
        dataset,
        target_type=observed.target_type,
        target_column=observed.column,
        group_column=group,
        node_id="batch-target-admission",
        target_authority=observed,
    )
    return {"target_authority": observed.canonical_dict(), "group_column": group}, selected_dataset


def preflight_source_partition(definition, dataset):
    """Plan a source-adjacent split with the canonical planner, without fitting.

    Downstream data-dependent branches are still executed by the DAG; their
    numerical outcomes cannot be promised by static admission.
    """
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
        bind_split_groups,
        bind_split_target,
        plan_train_test_split,
    )

    source_ids = {node["node_id"] for node in definition["nodes"] if node["node_type"] == "data.collection_load"}
    for node in definition["nodes"]:
        if node["node_type"] != "data.train_test_split":
            continue
        incoming = [edge for edge in definition["edges"] if edge["to_node_id"] == node["node_id"]]
        if any(edge["from_node_id"] not in source_ids for edge in incoming):
            continue
        parameters = node_registry.create_node(node["node_type"], node["node_id"], node["parameters"])._resolve_params()
        target, _ = bind_split_target(dataset, None)
        plan_train_test_split(
            dataset.X,
            target,
            method=parameters["split_method"],
            test_size=parameters["test_size"],
            random_seed=parameters["random_seed"],
            distance_metric=parameters["distance_metric"],
            n_components=parameters["n_components"],
            groups=bind_split_groups(dataset, use_source_assignment=parameters["split_method"] == "group_holdout"),
            held_out_groups=parameters.get("held_out_groups") or [],
        )


def bind_workflow_definition(definition: dict[str, Any], loaded: LoadedProjectDataset):
    """Produce a detached execution graph, refusing ambiguous source custody."""
    result = copy.deepcopy(definition)
    nodes = result["nodes"]
    if result.get("fold_validation_plan") is not None:
        raise ValueError("This workflow has a dataset-bound validation plan; create a reusable split workflow first.")
    if workflow_requires_canonical_artifact_grant([SimpleNamespace(**node) for node in nodes]):
        raise ValueError("This sealed application workflow cannot be retrained; choose Apply trained model.")
    sources = []
    for node in nodes:
        contract = node_registry.get_metadata(node["node_type"]).resolved_execution_contract().payload
        if contract["lifecycle_kind"] == "data_source":
            sources.append(node)
        if contract["lifecycle_kind"] == "artifact_application" and node["parameters"].get("model_id"):
            raise ValueError("This workflow loads an existing model; use a training workflow for a fresh fit.")
    if len(sources) != 1 or sources[0]["node_type"] not in {"data.file_load", "data.collection_load"}:
        raise ValueError("Select a workflow with one unambiguous project dataset source.")
    source = sources[0]
    target_parameters, selected = _rebind_target_intent(source["parameters"], copy.deepcopy(loaded.dataset))
    selected = included_dataset(selected)
    for node in nodes:
        contract = node_registry.get_metadata(node["node_type"]).resolved_execution_contract().payload
        if contract["target_access"] in {"required", "fit_only"} and selected.target is None:
            raise ScientificInputRefusal(
                "reference_targets_required",
                detail=f"{node['node_id']} requires reference targets for training/evaluation.",
            )
        task = contract["supervised_task"]
        target_type = getattr(selected.target_context, "target_type", None)
        if selected.target is not None and (
            (task == "regression" and target_type == "categorical")
            or (task == "classification" and target_type == "continuous")
        ):
            raise ValueError(f"{node['node_id']} requires {task} targets, not {target_type} targets.")
    if any(edge["to_node_id"] == source["node_id"] for edge in result["edges"]):
        raise ValueError("The dataset source must be at the head of the workflow.")
    if any(
        edge["from_node_id"] == source["node_id"]
        and edge.get("from_output", "default") not in {None, "default", "target"}
        for edge in result["edges"]
    ):
        raise ValueError("This source uses additional output bindings that Batch cannot replace unambiguously.")
    source["node_type"] = "data.collection_load"
    source["parameters"] = {
        **target_parameters,
        "experiment_id": loaded.experiment_id,
        "stage": loaded.stage,
        "selected_file_ids": [str(file_id) for file_id in loaded.file_ids],
        "asset_id": loaded.asset_id or "",
        "source_manifest_sha256": loaded.source_manifest_sha256,
        "collection_definition_sha256": loaded.collection_definition_sha256 or "",
        "scientific_collection_sha256": loaded.scientific_collection_sha256 or "",
    }
    result["data_context"] = {
        "schema_version": 1,
        "experiment_id": loaded.experiment_id,
        "source_name": loaded.experiment_name,
        "source_origin": "current",
    }
    preflight = preflight_workflow(
        [WorkflowNode(node_id=n["node_id"], node_type=n["node_type"], parameters=n["parameters"]) for n in nodes],
        [
            WorkflowEdge(e["from_node_id"], e["to_node_id"], e.get("from_output"), e.get("to_input"))
            for e in result["edges"]
        ],
    )
    errors = [issue.message for issue in preflight.issues if issue.level == "error"]
    if errors:
        raise ValueError("; ".join(errors))
    preflight_source_partition(result, selected)
    result["integrity_hash"] = compute_workflow_hash(nodes, result["edges"])
    return result, replace(loaded, dataset=selected)


@dataclass(frozen=True)
class BatchWorkflowBinding:
    """Server-admitted binding; never accepted directly from an HTTP caller."""

    loaded: LoadedProjectDataset
    definition: dict[str, Any]
    original_definition: dict[str, Any]
    metadata: dict[str, Any]
    verify_current: Any
    reservation_id: int

    @property
    def nodes(self):
        return [SimpleNamespace(**node) for node in self.definition["nodes"]]

    @property
    def source_id(self) -> str:
        return next(node["node_id"] for node in self.definition["nodes"] if node["node_type"] == "data.collection_load")
