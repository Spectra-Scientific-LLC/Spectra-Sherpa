"""System-level gates for the first canonical New Analysis pipelines."""

from __future__ import annotations

import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry

_CANONICALIZED_TEMPLATE_SUBSET = {
    "bilinear_mixture_synthesis",
    "classification_plsda",
    "emsc_reference_correction",
    "harmonized_nonnegative_spectra",
    "knn_classification",
    "msc_reference_correction",
    "peak_guided_pls",
    "pls_calibration",
    "region_selection_pls",
    "representative_calibration",
    "simca_classification",
    "variable_selection_comparison",
    "variable_selection_pls",
    "vip_assisted_pls",
}
_READY_TEMPLATES = {
    entry["slug"] for entry in TemplateLoader().load_all() if entry["template_data"].get("status") == "ready"
}
_SUPERVISED_TEMPLATES = _CANONICALIZED_TEMPLATE_SUBSET - {
    "bilinear_mixture_synthesis",
    "emsc_reference_correction",
    "harmonized_nonnegative_spectra",
    "msc_reference_correction",
}
_SUPERSEDED_NODE_TYPES = {
    "diagnostics.holdout_evaluation",
    "model.pls",
    "model.pls_predict",
    "selection.sample_partition",
}
_LOCAL_PLS_PIPELINES = {
    "peak_guided_pls",
    "pls_calibration",
    "representative_calibration",
    "variable_selection_pls",
    "vip_assisted_pls",
}
_CLASSIFICATION_PIPELINES = {
    "classification_plsda",
    "knn_classification",
    "simca_classification",
}


def _template(slug: str) -> dict[str, object]:
    templates = {entry["slug"]: entry["template_data"] for entry in TemplateLoader().load_all()}
    return templates[slug]


def _validate_template(template: dict[str, object]) -> list[str]:
    # Importing the package registers the complete built-in catalog used by the
    # real workbench before validating exact ports and types.
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    executor = DAGExecutor(process_pool=None)
    for raw_node in template["nodes"]:  # type: ignore[index]
        node = dict(raw_node)
        parameters = dict(node["parameters"])
        if node["node_type"] == "data.file_load":
            parameters = {
                "experiment_id": 1,
                "file_id": 1,
                "stage": "raw",
            }
            example_binding = node.get("example_binding", {})
            if "selected_target" in example_binding:
                parameters["target_authority"] = {
                    "schema_version": "spectrasherpa-target-authority/1",
                    "column": example_binding["selected_target"],
                    "target_type": example_binding["target_type"],
                    "units": None,
                    "source_digest": "a" * 64,
                }
        executor.add_node(
            WorkflowNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=parameters,
            )
        )
    for raw_edge in template["edges"]:  # type: ignore[index]
        edge = dict(raw_edge)
        executor.add_edge(
            WorkflowEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge.get("from_output", "default"),
                to_input=edge.get("to_input", "default"),
            )
        )
    return [issue.message for issue in executor.validate_full().errors]


@pytest.mark.parametrize("slug", sorted(_READY_TEMPLATES))
def test_every_ready_template_is_one_typed_current_dag(slug: str) -> None:
    template = _template(slug)
    node_types = {node["node_type"] for node in template["nodes"]}  # type: ignore[index]

    assert node_types.isdisjoint(_SUPERSEDED_NODE_TYPES)
    assert _validate_template(template) == []


@pytest.mark.parametrize("slug", sorted(_SUPERVISED_TEMPLATES))
def test_supervised_template_exposes_the_reference_target_edge(slug: str) -> None:
    template = _template(slug)
    nodes = {node["node_id"]: node["node_type"] for node in template["nodes"]}  # type: ignore[index]
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in template["edges"]  # type: ignore[index]
    }
    source_id = next(node_id for node_id, node_type in nodes.items() if node_type == "data.file_load")
    target_id = next(
        node_id for node_id, node_type in nodes.items() if node_type in {"data.train_test_split", "model.fitted_pls"}
    )

    assert (source_id, "target", target_id, "y") in edges


@pytest.mark.parametrize("slug", sorted(_CLASSIFICATION_PIPELINES))
def test_classification_template_exposes_training_and_test_labels(slug: str) -> None:
    template = _template(slug)
    nodes = {node["node_id"]: node["node_type"] for node in template["nodes"]}  # type: ignore[index]
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in template["edges"]  # type: ignore[index]
    }
    split_id = next(node_id for node_id, node_type in nodes.items() if node_type == "data.train_test_split")
    model_id = next(node_id for node_id, node_type in nodes.items() if node_type.startswith("classification."))
    evaluator_id = next(
        node_id for node_id, node_type in nodes.items() if node_type == "diagnostics.classification_evaluator"
    )

    assert (split_id, "y_train", model_id, "y") in edges
    assert (split_id, "y_test", evaluator_id, "y_true") in edges


def test_every_template_parameter_is_declared_by_the_live_node_registry() -> None:
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    undeclared: list[tuple[str, str, list[str]]] = []
    for entry in TemplateLoader().load_all():
        for node in entry["template_data"]["nodes"]:
            metadata = node_registry.get_metadata(node["node_type"])
            declared = {parameter.name for parameter in metadata.parameters}
            extras = sorted(set(node.get("parameters", {})) - declared)
            if extras:
                undeclared.append((entry["slug"], node["node_type"], extras))

    assert undeclared == []


@pytest.mark.parametrize("slug", sorted(_LOCAL_PLS_PIPELINES))
def test_local_pls_template_exposes_one_fit_apply_evaluate_path(slug: str) -> None:
    template = _template(slug)
    nodes = {node["node_id"]: node["node_type"] for node in template["nodes"]}  # type: ignore[index]
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in template["edges"]  # type: ignore[index]
    }

    apply_id = next(node_id for node_id, node_type in nodes.items() if node_type == "model.predict_regression")
    evaluator_type = (
        "diagnostics.labeled_regression_evaluator" if slug == "pls_calibration" else "diagnostics.regression_evaluator"
    )
    evaluator_ids = [node_id for node_id, node_type in nodes.items() if node_type == evaluator_type]
    assert len(evaluator_ids) == 1
    evaluator_id = evaluator_ids[0]
    split_id = next(node_id for node_id, node_type in nodes.items() if node_type == "data.train_test_split")
    fit_id = next(
        source_id
        for source_id, from_output, target_id, to_input in edges
        if target_id == apply_id and from_output == "fitted_state" and to_input == "fitted_state"
    )

    assert (split_id, "y_train", fit_id, "y") in edges
    assert (fit_id, "fitted_state", apply_id, "fitted_state") in edges
    assert (apply_id, "default", evaluator_id, "default") in edges
    assert (split_id, "y_test", evaluator_id, "y_true") in edges
    if slug == "pls_calibration":
        assert (split_id, "X_test", evaluator_id, "sample_context") in edges


def test_pls_calibration_autoscaling_is_fitted_inside_the_model() -> None:
    template = _template("pls_calibration")
    nodes = {node["node_type"]: node for node in template["nodes"]}  # type: ignore[index]

    assert "preprocess.scale" not in nodes
    assert nodes["model.fitted_pls"]["parameters"]["scale"] is True


@pytest.mark.parametrize("slug", ["variable_selection_pls", "vip_assisted_pls"])
def test_vip_template_derives_one_training_mask_and_reuses_it_for_held_out_data(slug: str) -> None:
    template = _template(slug)
    nodes = {node["node_id"]: node["node_type"] for node in template["nodes"]}  # type: ignore[index]
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in template["edges"]  # type: ignore[index]
    }
    full_fit = next(node_id for node_id, node_type in nodes.items() if node_type == "model.fitted_pls")
    selectors = [node_id for node_id, node_type in nodes.items() if node_type == "selection.variable_select"]

    assert len(selectors) == 2
    train_selector = next(
        node_id
        for node_id in selectors
        if nodes[node_id] == "selection.variable_select"
        and (full_fit, "vip_scores", node_id, "importance_scores") in edges
    )
    test_selector = next(node_id for node_id in selectors if node_id != train_selector)
    parameters = {node["node_id"]: node["parameters"] for node in template["nodes"]}  # type: ignore[index]

    assert parameters[train_selector]["method"] == "vip"
    assert parameters[test_selector]["method"] == "apply_mask"
    assert (train_selector, "mask", test_selector, "mask") in edges
    assert (full_fit, "vip_scores", test_selector, "importance_scores") not in edges
