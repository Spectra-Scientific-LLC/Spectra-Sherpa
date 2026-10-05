from __future__ import annotations

import pytest

from spectra_sherpa.app.services.dag.saved_graph_admission import (
    CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
    SavedGraphAdmissionError,
    admit_saved_workflow_graph,
)

RETIRED_PROTOTYPE_NODE_TYPES = (
    "data.my_dataset",
    "data.source",
    "model.pls",
    "model.pls_predict",
    "diagnostics.holdout_evaluation",
    "selection.sample_partition",
)


@pytest.mark.parametrize(
    "parameters",
    [{"method": "snv", "std_ddof": ddof, "scale_method": "max"} for ddof in (0, 1)]
    + [{"method": "scale", "std_ddof": 0, "scale_method": method} for method in ("max", "area", "minmax")],
)
def test_normalize_inspector_options_are_admitted(parameters: dict[str, object]) -> None:
    node = {"node_id": "normalize", "node_type": "preprocess.normalize", "parameters": parameters}
    admission = admit_saved_workflow_graph([node], [])
    assert admission.nodes == (node,)


@pytest.mark.parametrize("node_type", RETIRED_PROTOTYPE_NODE_TYPES)
def test_saved_graph_admission_rejects_every_retired_prototype(node_type: str) -> None:
    with pytest.raises(SavedGraphAdmissionError, match="not admitted by the current registry"):
        admit_saved_workflow_graph(
            [{"node_id": "retired", "node_type": node_type, "parameters": {}}],
            [],
        )


def test_saved_graph_admission_accepts_current_parameter_and_edge_incomplete_canvas() -> None:
    # Persistence admission intentionally does not require a runnable graph;
    # scientists may save a partially connected current canvas.
    admit_saved_workflow_graph(
        [
            {
                "node_id": "source",
                "node_type": "data.file_load",
                "parameters": {},
            }
        ],
        [],
    )


@pytest.mark.parametrize("node_type", ["classification.knn", "classification.plsda", "classification.simca"])
def test_current_classifier_graph_requires_exact_persisted_semantics(node_type: str) -> None:
    source = [{"node_id": "model", "node_type": node_type, "parameters": {}}]

    with pytest.raises(SavedGraphAdmissionError, match="has no current classifier-validation authority"):
        admit_saved_workflow_graph(source, [])

    admission = admit_saved_workflow_graph(
        source,
        [],
        classifier_validation_semantics=CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
    )
    assert admission.nodes == (source[0],)

    with pytest.raises(SavedGraphAdmissionError, match="semantics are not current"):
        admit_saved_workflow_graph(source, [], classifier_validation_semantics="unknown/1")


@pytest.mark.parametrize(
    ("node_type", "parameters", "changed_port"),
    [
        ("classification.knn", {"n_neighbors": 3, "cv_folds": 5}, "predictions"),
        ("classification.plsda", {"n_components": 2, "scale": True, "cv_folds": 5}, "predictions"),
        ("classification.simca", {"n_components": 2, "cv_folds": 5}, "metrics"),
    ],
)
@pytest.mark.parametrize("connected", [False, True])
def test_saved_classifier_graph_refuses_changed_legacy_output_semantics(
    node_type: str,
    parameters: dict[str, object],
    changed_port: str,
    connected: bool,
) -> None:
    nodes = [{"node_id": "model", "node_type": node_type, "parameters": parameters}]
    edges: list[dict[str, object]] = []
    if connected:
        nodes.append(
            {
                "node_id": "score",
                "node_type": "diagnostics.classification_evaluator",
                "parameters": {},
            }
        )
        edges.append(
            {
                "from_node_id": "model",
                "from_output": changed_port,
                "to_node_id": "score",
                "to_input": "default",
            }
        )

    with pytest.raises(SavedGraphAdmissionError, match="cannot be auto-migrated"):
        admit_saved_workflow_graph(nodes, edges)


def test_new_graph_admission_does_not_silently_accept_retired_local_cv_parameter() -> None:
    with pytest.raises(SavedGraphAdmissionError, match="cannot be auto-migrated"):
        admit_saved_workflow_graph(
            [
                {
                    "node_id": "model",
                    "node_type": "classification.plsda",
                    "parameters": {"n_components": 2, "scale": True, "cv_folds": 5},
                }
            ],
            [],
            current_graph=True,
        )


@pytest.mark.parametrize(
    "value",
    [True, "5", float("nan"), float("inf"), None, {}, 1, 1.5, 21, 10**100],
)
def test_saved_classifier_migration_refuses_malformed_retired_value(value: object) -> None:
    with pytest.raises(SavedGraphAdmissionError, match="retired parameter 'cv_folds' is malformed"):
        admit_saved_workflow_graph(
            [
                {
                    "node_id": "model",
                    "node_type": "classification.knn",
                    "parameters": {"n_neighbors": 3, "cv_folds": value},
                }
            ],
            [],
        )


def test_saved_simca_refuses_historically_invalid_integer_valued_float() -> None:
    with pytest.raises(SavedGraphAdmissionError, match="retired parameter 'cv_folds' is malformed"):
        admit_saved_workflow_graph(
            [
                {
                    "node_id": "model",
                    "node_type": "classification.simca",
                    "parameters": {"n_components": 2, "cv_folds": 5.0},
                }
            ],
            [],
        )


def test_saved_graph_admission_rejects_invalid_supplied_draft_value() -> None:
    with pytest.raises(SavedGraphAdmissionError, match="must be a finite number"):
        admit_saved_workflow_graph(
            [
                {
                    "node_id": "source",
                    "node_type": "data.file_load",
                    "parameters": {"experiment_id": "not-an-id"},
                }
            ],
            [],
        )


def test_saved_graph_admission_accepts_explicit_null_for_optional_parameter() -> None:
    admit_saved_workflow_graph(
        [
            {
                "node_id": "species",
                "node_type": "synthesis.species",
                "parameters": {"species_name": "Species A", "molar_absorptivity": None},
            }
        ],
        [],
    )


def test_saved_graph_admission_rejects_duplicate_id_and_missing_edge_endpoint() -> None:
    current = {
        "node_id": "source",
        "node_type": "data.file_load",
        "parameters": {"experiment_id": 1, "file_id": 1, "stage": "raw"},
    }
    with pytest.raises(SavedGraphAdmissionError, match="duplicate node ID"):
        admit_saved_workflow_graph([current, current], [])
    with pytest.raises(SavedGraphAdmissionError, match="references a missing node"):
        admit_saved_workflow_graph(
            [current],
            [
                {
                    "from_node_id": "source",
                    "to_node_id": "missing",
                    "from_output": "default",
                    "to_input": "default",
                }
            ],
        )
