"""Score a workbench sheet using a campaign's recorded cross-validation protocol.

A sheet opened from an optimization-campaign candidate keeps the campaign's
validation scope. Its terminal evaluator is not scored on the rows the model
was fitted on. Instead the sheet's analysis chain (every step between the data
boundary and the evaluator) is re-admitted as a validation graph and run
through the same fold executor the campaign used, on folds rebuilt from the
sheet's data. Data identity and positional fold identity are compared separately
with the campaign. New data may be evaluated, but the result explicitly discloses
when original sample identity or fold membership is not verified.

Only the evaluator's result changes. Upstream steps still run on all rows so
the sheet remains inspectable; their outputs are full-data fits, as on any
other sheet.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.sdk.validate import (
    SplitPlan,
    make_classification_split_plan,
    make_leave_one_group_out_classification_plan,
    make_split_plan,
)

SHEET_FOLD_VALIDATION_VERSION = "spectrasherpa-sheet-fold-validation/1"
HELD_OUT_SHEET_FOLD_VALIDATION_VERSION = "spectrasherpa-sheet-fold-validation/2"
SHEET_FOLD_VALIDATION_RESULT_VERSION = "spectrasherpa-sheet-fold-validation-result/1"
_PLAN_FIELDS = frozenset(
    {"schema_version", "task_type", "outer_splits", "split_digest", "dataset_content_digest", "origin"}
)
_BOUNDARY_TYPES = frozenset({"data.file_load", "data.load_group", "data.collection_load", "data.attach_target"})
_EVALUATOR_TYPES = frozenset({"diagnostics.regression_evaluator", "diagnostics.classification_evaluator"})
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class SheetFoldValidationError(ValueError):
    """The sheet cannot be scored with its recorded folds; the message is user-facing."""


@dataclass(frozen=True)
class SheetFoldValidationPlan:
    """The campaign's validation scope, attached to one sheet."""

    task_type: str
    outer_splits: int
    split_digest: str
    dataset_content_digest: str | None
    origin: str
    holdout: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: object) -> "SheetFoldValidationPlan":
        if not isinstance(value, Mapping):
            raise SheetFoldValidationError("Sheet fold-validation plan must be an object")
        held_out = value.get("schema_version") == HELD_OUT_SHEET_FOLD_VALIDATION_VERSION
        if set(value) != (_PLAN_FIELDS | {"holdout"} if held_out else _PLAN_FIELDS):
            raise SheetFoldValidationError("Sheet fold-validation plan fields are closed")
        if value["schema_version"] not in {SHEET_FOLD_VALIDATION_VERSION, HELD_OUT_SHEET_FOLD_VALIDATION_VERSION}:
            raise SheetFoldValidationError("Sheet fold-validation plan version is unsupported")
        outer_splits = value["outer_splits"]
        content = value["dataset_content_digest"]
        origin = value["origin"]
        if value["task_type"] not in {"regression", "classification"}:
            raise SheetFoldValidationError("Sheet fold-validation task is unsupported")
        if isinstance(outer_splits, bool) or not isinstance(outer_splits, int) or not 2 <= outer_splits <= 20:
            raise SheetFoldValidationError("Sheet fold-validation fold count is invalid")
        if not isinstance(value["split_digest"], str) or _DIGEST.fullmatch(value["split_digest"]) is None:
            raise SheetFoldValidationError("Sheet fold-validation split identity is invalid")
        if content is not None and (not isinstance(content, str) or _DIGEST.fullmatch(content) is None):
            raise SheetFoldValidationError("Sheet fold-validation dataset identity is invalid")
        if not isinstance(origin, str) or not origin.strip() or len(origin) > 200:
            raise SheetFoldValidationError("Sheet fold-validation origin is invalid")
        holdout = None
        if held_out:
            from .retained_holdout import read_retained_holdout

            try:
                holdout = read_retained_holdout(value["holdout"])
            except ValueError as exc:
                raise SheetFoldValidationError(str(exc)) from exc
        return cls(value["task_type"], outer_splits, value["split_digest"], content, origin, holdout)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                HELD_OUT_SHEET_FOLD_VALIDATION_VERSION if self.holdout else SHEET_FOLD_VALIDATION_VERSION
            ),
            **({"holdout": self.holdout} if self.holdout else {}),
            "task_type": self.task_type,
            "outer_splits": self.outer_splits,
            "split_digest": self.split_digest,
            "dataset_content_digest": self.dataset_content_digest,
            "origin": self.origin,
        }


def reconstruct_split_plan(
    *,
    task_type: str,
    n_samples: int,
    outer_splits: int,
    target: Sequence[Any],
    groups: Sequence[Any] | None,
) -> SplitPlan:
    """Build the one split plan shared by campaign admission, execution, refit and sheets."""

    if task_type == "classification" and groups is not None:
        split = make_leave_one_group_out_classification_plan(target, groups)
        if len(split.folds) != outer_splits:
            raise ValueError("declared grouped fold count differs from the exact group identity")
        return split
    if task_type == "classification":
        return make_classification_split_plan(target, n_splits=outer_splits)
    return make_split_plan(n_samples, n_splits=outer_splits, groups=groups)


def fold_validation_chain(
    nodes: Mapping[str, str],
    edges: Sequence[WorkflowEdge],
    evaluator_id: str,
    *,
    holdout: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]] | None:
    """Return ``(boundary_node_id, chain_node_ids)`` for an evaluator, or ``None``.

    ``None`` means the evaluator is not a fold-validated terminal: it has an
    explicit reference-value edge (the scientist chose local scoring) or it
    is not a supervised evaluator. A malformed chain raises instead.
    """

    if nodes.get(evaluator_id) not in _EVALUATOR_TYPES:
        return None
    if any(edge.to_node == evaluator_id and edge.to_input == "y_true" for edge in edges):
        return None
    chain = [evaluator_id]
    current = evaluator_id
    while True:
        incoming = [edge for edge in edges if edge.to_node == current]
        if len(incoming) != 1:
            raise SheetFoldValidationError(
                "Cross-validation with the campaign folds needs one unbranched chain from the data to the evaluator"
            )
        upstream = incoming[0].from_node
        if holdout is not None and upstream == holdout["split_node_id"]:
            if nodes.get(upstream) != "data.train_test_split" or incoming[0].from_output != "X_train":
                raise SheetFoldValidationError("Campaign cross-validation must start from the retained training rows")
            return upstream, list(reversed(chain))
        if nodes.get(upstream) in _BOUNDARY_TYPES:
            # Target attachment is a boundary only if its input was not fitted
            # globally. Otherwise preprocessing would escape fold isolation.
            from spectra_sherpa.app.services.dag.node_base import node_registry
            from spectra_sherpa.execution_contract_vocabulary import LifecycleKind

            pending = [edge.from_node for edge in edges if edge.to_node == upstream]
            seen: set[str] = set()
            while pending:
                ancestor = pending.pop()
                if ancestor in seen:
                    continue
                seen.add(ancestor)
                metadata = node_registry.get_metadata(nodes[ancestor])
                lifecycle = metadata.resolved_execution_contract().payload["lifecycle_kind"]
                if lifecycle in {LifecycleKind.FITTED_TRANSFORM.value, LifecycleKind.FITTED_MODEL.value}:
                    raise SheetFoldValidationError(
                        "Move fitted preprocessing after target attachment so it is fitted inside each validation fold."
                    )
                pending.extend(edge.from_node for edge in edges if edge.to_node == ancestor)
            return upstream, list(reversed(chain))
        if upstream in chain or upstream not in nodes:
            raise SheetFoldValidationError("The analysis chain is not connected to a data source")
        chain.append(upstream)
        current = upstream


def _supervised_inputs(dataset: SherpaDataset) -> tuple[np.ndarray, np.ndarray | None, str | None]:
    """Return target, groups and dataset identity exactly as a campaign binds them."""

    from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision
    from spectra_sherpa.core.target_authority import admit_target_authority

    record = dataset.meta.get("supervision_binding")
    if isinstance(record, Mapping):
        authority = admit_target_authority(record.get("target_authority"), optional=False)
        binding = bind_sample_table_supervision(
            dataset,
            target_column=authority.column,
            target_type=authority.target_type,
            group_column=record.get("group_column"),
            target_authority=authority,
        )
        if binding.digest != record.get("supervision_binding_sha256"):
            raise SheetFoldValidationError("The sheet's sample-table supervision changed since it was attached")
        return binding.target, binding.groups, binding.digest
    if dataset.target is None:
        raise SheetFoldValidationError("Cross-validation needs a target on the sheet's data")
    return np.asarray(dataset.target), None, None


def prepare_sheet_fold_validation(
    plan: SheetFoldValidationPlan,
    chain_nodes: Sequence[WorkflowNode],
    chain_edges: Sequence[WorkflowEdge],
    dataset: object,
) -> tuple[dict[str, Any], dict[str, Any], SplitPlan]:
    """Admit the chain, rebuild the recorded folds and issue the fold capability.

    Returns picklable inputs for :func:`run_sheet_fold_validation`, which is
    the scientific step and runs wherever the executor runs other nodes.
    """

    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, admit_validation_graph

    if not isinstance(dataset, SherpaDataset):
        raise SheetFoldValidationError("Cross-validation needs the sheet's spectral dataset at its data boundary")
    _ensure_type_registry()
    try:
        graph = admit_validation_graph(list(chain_nodes), list(chain_edges))
    except ValidationGraphError as exc:
        raise SheetFoldValidationError(
            f"This analysis chain cannot be cross-validated with the campaign folds: {exc}"
        ) from exc
    target, groups, dataset_ref_digest = _supervised_inputs(dataset)
    try:
        split = reconstruct_split_plan(
            task_type=plan.task_type,
            n_samples=int(dataset.shape[0]),
            outer_splits=plan.outer_splits,
            target=target,
            groups=groups,
        )
    except ValueError as exc:
        raise SheetFoldValidationError(f"The campaign folds cannot be rebuilt from this data: {exc}") from exc
    sample_axis = dataset.sample_axis
    feature_axis = dataset.get_feature_axis()
    masks = [axis.include_mask for axis in (sample_axis, feature_axis) if axis is not None]
    if any(mask is not None and not np.all(mask) for mask in masks):
        raise SheetFoldValidationError(
            "Cross-validation with the campaign folds needs every sample and feature included; "
            "remove sample or feature exclusions, or wire explicit reference values instead"
        )
    # The same minimal projection a campaign dispatch scores: spectra, target and
    # feature axis. Sample-table columns never become fold inputs.
    fold_dataset = SherpaDataset(X=np.asarray(dataset.X), target=target, feature_axis=feature_axis)
    capability = SpectralDatasetCapability.from_dataset(
        fold_dataset,
        custody_id="workbench-sheet-fold-validation",
        dataset_ref_digest=dataset_ref_digest,
        split_plan_digest=split.digest,
        groups=groups,
    )
    return graph.as_dict(), dict(capability.to_wire()), split


def _ensure_type_registry() -> None:
    """A spawned worker starts without the application's loaded type registry."""

    from pathlib import Path

    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[2] / "types")


def run_sheet_fold_validation(graph_wire: dict[str, Any], capability_wire: dict[str, Any], split: SplitPlan) -> dict:
    """Worker-pool entry point: a fresh process has no running event loop."""

    return asyncio.run(run_sheet_fold_validation_async(graph_wire, capability_wire, split))


async def run_sheet_fold_validation_async(
    graph_wire: dict[str, Any], capability_wire: dict[str, Any], split: SplitPlan
) -> dict:
    """Re-admit the chain and capability, then score every recorded fold."""

    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.classification_evaluator_node  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
    from spectra_sherpa.app.services.dag.fold_graph_executor import execute_candidate_validation
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.validation_graph import validation_graph_from_dict

    _ensure_type_registry()
    graph = validation_graph_from_dict(graph_wire)
    capability = SpectralDatasetCapability.from_wire(capability_wire)
    execution = await execute_candidate_validation(graph, capability, split)
    return {**execution.as_dict(), "validation_execution_digest": execution.digest}


def sheet_fold_validation_result(plan: SheetFoldValidationPlan, execution: Mapping[str, Any], *, split: SplitPlan):
    """Project a fold execution onto the evaluator's ordinary result ports."""

    from spectra_sherpa.app.services.dag.node_base import NodeResult

    scope = {
        "schema_version": SHEET_FOLD_VALIDATION_RESULT_VERSION,
        "scope": "cross_validation",
        "development_population": "retained_training_partition" if plan.holdout else "source_population",
        "held_out_rows_excluded": len(plan.holdout["test_indices"]) if plan.holdout else 0,
        "source_run_id": plan.holdout["source_run_id"] if plan.holdout else None,
        "origin": plan.origin,
        "method": split.method,
        "n_folds": len(split.folds),
        "split_digest": split.digest,
        "origin_split_digest": plan.split_digest,
        "data_identity": (
            "verified_same"
            if plan.dataset_content_digest is not None
            and execution.get("capability_content_digest") == plan.dataset_content_digest
            else "unknown"
        ),
        "same_fold_indices": split.digest == plan.split_digest,
        "origin_dataset_content_digest": plan.dataset_content_digest,
        "evaluated_dataset_content_digest": execution.get("capability_content_digest"),
        "comparison_notice": (
            "Original data identity and fold assignment verified."
            if plan.dataset_content_digest is not None
            and execution.get("capability_content_digest") == plan.dataset_content_digest
            and split.digest == plan.split_digest
            else "New cross-validation evaluation; original sample identity or fold membership is not verified."
        ),
        "fold_metrics": [fold["metrics"] for fold in execution["folds"]],
        "validation_execution_digest": execution["validation_execution_digest"],
    }
    receipt = {
        "schema_version": "spectrasherpa-population-authority/1",
        "role": "cross_validation",
        "population": None,
        "fitted_populations": [],
        "qualification": "fold_executor_verified",
    }
    metrics = {"task_type": execution["task_type"], **execution["metrics"], "fold_validation": scope}
    metrics["population_authority"] = receipt
    return NodeResult(
        outputs={"default": metrics},
        diagnostics={"fold_validation": scope, "population_authority": receipt},
    )


__all__ = [
    "SHEET_FOLD_VALIDATION_VERSION",
    "SheetFoldValidationError",
    "SheetFoldValidationPlan",
    "fold_validation_chain",
    "prepare_sheet_fold_validation",
    "reconstruct_split_plan",
    "run_sheet_fold_validation",
    "sheet_fold_validation_result",
]
