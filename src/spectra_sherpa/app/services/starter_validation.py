"""Read-only starter split feasibility through the execution authorities.

This checks population feasibility, not model quality or numerical CV rank.
Unknown upstream transformations are explicitly not checked, never simulated.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.workflow_population import source_population_outputs
from spectra_sherpa.app.services.dag.io_contracts import resolve_target_names
from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
    bind_split_groups,
    materialize_split_outputs,
    plan_train_test_split,
    prepare_split_source,
    require_independent_classification_groups,
    require_known_specimen_cross_block_plan,
)
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode, TrainTestSplitNode
from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision
from spectra_sherpa.core.specimen_independence import independence_violations
from spectra_sherpa.sdk.validate import make_classification_split_plan, make_split_plan


async def preview_starter_validation(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], sources: dict[str, Any]
) -> dict[str, Any]:
    """Check source-bound supervised populations before starter persistence."""
    by_id = {str(node["node_id"]): node for node in nodes}
    classifiers = [node for node in nodes if str(node["node_type"]).startswith("classification.")]
    automatic_pls = [
        node
        for node in nodes
        if node["node_type"] == "model.fitted_pls"
        and node.get("parameters", {}).get("component_fit_mode") == "one_standard_error"
    ]
    if not classifiers and not automatic_pls:
        return {"status": "not_checked", "reason": "No supervised population preflight requested."}
    missing = object()
    resolved: dict[str, Any] = {}

    async def source_for(node_id: str, visiting: frozenset[str] = frozenset()) -> Any:
        if node_id in resolved:
            return resolved[node_id]
        if node_id in visiting:
            return missing
        node = by_id.get(node_id)
        if node_id in sources and node and node["node_type"] in {"data.file_load", "data.collection_load"}:
            parameters = node.get("parameters", {})
            resolved[node_id] = source_population_outputs(
                sources[node_id],
                node_id=node_id,
                exclusions=parameters.get("workflow_exclusions"),
                source_binding=parameters,
            )["default"]
            return resolved[node_id]
        incoming = [edge for edge in edges if str(edge["to_node_id"]) == node_id]
        if not node or node["node_type"] != "data.filter_samples" or len(incoming) != 1:
            return missing
        edge = incoming[0]
        if edge.get("from_output", "default") != "default":
            return missing
        source = await source_for(str(edge["from_node_id"]), visiting | {node_id})
        if source is missing:
            return missing
        filtered = await FilterSamplesNode(node_id, node.get("parameters", {})).execute(X=source)
        resolved[node_id] = filtered["default"]
        return resolved[node_id]

    previews = []
    for node in nodes:
        if node["node_type"] != "data.train_test_split":
            continue
        node_id = str(node["node_id"])
        incoming = [edge for edge in edges if str(edge["to_node_id"]) == node_id]
        predictors = [edge for edge in incoming if edge.get("to_input", "X") in {"X", "default"}]
        if len(predictors) != 1 or predictors[0].get("from_output", "default") != "default":
            continue
        predictor = predictors[0]
        # The same source's target port is the embedded response authority.
        # A genuinely separate target source remains explicitly unchecked.
        others = [edge for edge in incoming if edge is not predictor]
        if len(others) > 1 or any(
            edge.get("to_input") != "y"
            or edge.get("from_output") != "target"
            or edge["from_node_id"] != predictor["from_node_id"]
            for edge in others
        ):
            continue
        try:
            source = await source_for(str(predictor["from_node_id"]))
            if source is missing:
                continue
            p = TrainTestSplitNode.metadata.canonicalize_parameters(node.get("parameters", {}))
            ds, matrix, labels, context, source_indices = prepare_split_source(source, None)
            if context is None or context.target_type not in (
                {"categorical", "continuous"} if automatic_pls else {"categorical"}
            ):
                continue
            groups = bind_split_groups(ds, use_source_assignment=p["split_method"] == "group_holdout")
            require_independent_classification_groups(
                ds, groups, context, split_method=p["split_method"], validation_goal=p["validation_goal"]
            )
            plan = plan_train_test_split(
                matrix,
                labels,
                method=p["split_method"],
                test_size=p["test_size"],
                random_seed=p["random_seed"],
                distance_metric=p["distance_metric"],
                n_components=p["n_components"],
                groups=groups,
                held_out_groups=p["held_out_groups"],
            )
            if p["validation_goal"] == "known_specimen_cross_block":
                require_known_specimen_cross_block_plan(ds, plan, labels, context)
        except ValueError as exc:
            # These are pure scientific planners; no file access or storage errors.
            return {"status": "refused", "reason": f"Cannot form this training/test partition: {exc}"}
        item: dict[str, Any] = {
            "node_id": node_id,
            "split_digest": plan.digest,
            "training_count": int(plan.train_indices.size),
            "held_out_count": int(plan.test_indices.size),
        }
        direct_automatic = [
            by_id[str(edge["to_node_id"])]
            for edge in edges
            if edge["from_node_id"] == node_id
            and edge.get("from_output") == "X_train"
            and by_id.get(str(edge["to_node_id"])) in automatic_pls
        ]
        for model in direct_automatic:
            from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node

            parameters = FittedPLSV2Node.metadata.canonicalize_parameters(model.get("parameters", {}))
            if labels is None or (labels.ndim > 1 and labels.shape[1] != 1):
                return {"status": "refused", "reason": "Automatic PLS selection requires one continuous response."}
            try:
                # Materialize and re-admit the actual training partition using
                # the same authority as execution. An outer assignment is not
                # an inner specimen grouping, and receipts may change on slicing.
                training = materialize_split_outputs(
                    ds,
                    matrix,
                    labels,
                    plan,
                    node_id=node_id,
                    target_context=context,
                    groups=groups,
                    source_indices=source_indices,
                )["X_train"]
                from spectra_sherpa.app.services.dag.nodes.modeling.component_validation import cv_unavailable_reason

                reason = cv_unavailable_reason(training)
                if reason:
                    return {"status": "refused", "reason": f"Automatic PLS selection unavailable: {reason}"}
                attached = admit_attached_sample_table_supervision(training)
                training_groups = None if attached is None else attached.groups
                training_table = training.sample_axis.sample_table if training.sample_axis is not None else None
                target_names = (
                    resolve_target_names(None, training)
                    or (
                        [context.selected_target or context.target_name]
                        if context and (context.selected_target or context.target_name)
                        else []
                    )
                    or parameters.get("target_names", [])
                )
                violations = independence_violations(
                    training_table,
                    n_samples=int(plan.train_indices.size),
                    target_type="continuous",
                    target_names=target_names,
                    groups=training_groups,
                )
                if violations:
                    return {"status": "refused", "reason": violations[0].message}
                inner = make_split_plan(
                    int(plan.train_indices.size),
                    n_splits=parameters["component_cv_folds"],
                    groups=training_groups,
                )
                if min(len(fold.train) for fold in inner.folds) < 2:
                    raise ValueError("too few training rows")
                item["component_cv"] = {"status": "population_feasible"}
            except ValueError:
                return {
                    "status": "refused",
                    "reason": (
                        "Automatic PLS selection needs enough independent training samples or groups "
                        "for its component CV folds. Reduce the fold count, add independent samples, "
                        "or choose a justified manual latent-variable count."
                    ),
                }
        direct_plsda = any(
            edge["from_node_id"] == node_id
            and edge.get("from_output") == "X_train"
            and by_id.get(str(edge["to_node_id"]), {}).get("node_type") == "classification.plsda"
            for edge in edges
        )
        if direct_plsda and labels is not None:
            if np.unique(labels[plan.train_indices]).size < 2:
                return {
                    "status": "refused",
                    "reason": (
                        "PLS-DA requires at least two classes in the training partition. "
                        "Choose a stratified split or review the selected classes."
                    ),
                }
            try:
                # The fitted classifier reads its training supervision receipt,
                # not the outer Training/Validation assignment labels.
                training = materialize_split_outputs(
                    ds,
                    matrix,
                    labels,
                    plan,
                    node_id=node_id,
                    target_context=context,
                    groups=groups,
                    source_indices=source_indices,
                )["X_train"]
                attached = admit_attached_sample_table_supervision(training)
                training_groups = None if attached is None else attached.groups
                violations = independence_violations(
                    training.sample_axis.sample_table if training.sample_axis is not None else None,
                    n_samples=training.n_samples,
                    target_type="categorical",
                    target_names=resolve_target_names(None, training)
                    or (
                        [context.selected_target or context.target_name]
                        if context and (context.selected_target or context.target_name)
                        else []
                    ),
                    groups=training_groups,
                )
                if violations:
                    item["component_cv"] = {"status": "unavailable", "reason": violations[0].message}
                    previews.append(item)
                    continue
                make_classification_split_plan(labels[plan.train_indices], groups=training_groups)
                item["component_cv"] = {"status": "population_feasible"}
            except ValueError:
                item["component_cv"] = {
                    "status": "unavailable",
                    "reason": (
                        "Component CV unavailable: too few independent training samples "
                        "to retain every class in every fold. "
                        "This checks class populations only; model fitting must still succeed "
                        "before held-out evaluation."
                    ),
                }
        previews.append(item)
    return {"status": "feasible" if previews else "not_checked", "splits": previews}
