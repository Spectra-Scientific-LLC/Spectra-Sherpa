"""Unit tests for substitute_parent_data_loaders().

The agentic workflow-generation path validates that proposed DAGs inherit
the parent workflow's data loaders verbatim. Cheaper LLMs drift on loader
params (most commonly omit `stage`, defaulting to "raw"), flipping the
fingerprint and failing validation. The substitution helper rewrites the
proposed loaders' params with the parent's actual params by
node-type-and-position before fingerprinting, making the feature
model-agnostic.
"""

from __future__ import annotations

from types import SimpleNamespace

from spectra_sherpa.app.schemas.workflows import WorkflowDagSpec, WorkflowDagSpecNode
from spectra_sherpa.app.services.tools.builtin.workflow import (
    _data_loader_fingerprints,
    substitute_parent_data_loaders,
)


def _parent_loader(node_id: str, **params):
    """Mimic an ORM WorkflowNode for the loader path."""
    return SimpleNamespace(node_id=node_id, node_type="data.file_load", parameters=params)


def test_substitution_fixes_drifted_stage_field_on_dict_spec() -> None:
    """LLM drops `stage` (defaults to "raw"), substitution restores parent's "preprocessed"."""
    parent_nodes = [_parent_loader("p_src", experiment_id=42, file_id=7, stage="preprocessed")]

    proposed = {
        "nodes": [
            {
                "id": "src_1",
                "type": "data.file_load",
                "parameters": {"experiment_id": 42, "file_id": 7},  # missing `stage`
            },
            {"id": "pca_1", "type": "model.pca", "parameters": {"n_components": 3}},
        ],
        "edges": [],
    }

    substitute_parent_data_loaders(proposed, parent_nodes)

    assert proposed["nodes"][0]["parameters"] == {"experiment_id": 42, "file_id": 7, "stage": "preprocessed"}
    assert proposed["nodes"][1]["parameters"] == {"n_components": 3}, "non-loader node must be untouched"

    parent_fingerprints = _data_loader_fingerprints(
        [{"node_type": n.node_type, "parameters": n.parameters} for n in parent_nodes]
    )
    proposed_fingerprints = _data_loader_fingerprints(
        [{"node_type": n["type"], "parameters": n["parameters"]} for n in proposed["nodes"]]
    )
    assert parent_fingerprints <= proposed_fingerprints, "fingerprints must match after substitution"


def test_substitution_mutates_pydantic_dag_spec() -> None:
    """Route-handler path passes a Pydantic WorkflowDagSpec; mutation must propagate."""
    parent_nodes = [_parent_loader("p_src", experiment_id=1, file_id=2, stage="raw")]

    dag_spec = WorkflowDagSpec(
        nodes=[
            WorkflowDagSpecNode(
                id="src_1", type="data.file_load", parameters={"experiment_id": 1, "file_id": 99}  # wrong file_id
            ),
        ],
        edges=[],
    )

    substitute_parent_data_loaders(dag_spec, parent_nodes)

    assert dag_spec.nodes[0].parameters == {"experiment_id": 1, "file_id": 2, "stage": "raw"}


def test_substitution_preserves_correct_loader_params() -> None:
    """If LLM already emitted the parent's exact params, the helper is a no-op."""
    parent_nodes = [_parent_loader("p_src", experiment_id=10, file_id=20, stage="raw")]
    proposed = {
        "nodes": [
            {
                "id": "src_1",
                "type": "data.file_load",
                "parameters": {"experiment_id": 10, "file_id": 20, "stage": "raw"},
            },
        ],
        "edges": [],
    }
    before = dict(proposed["nodes"][0]["parameters"])

    substitute_parent_data_loaders(proposed, parent_nodes)

    assert proposed["nodes"][0]["parameters"] == before


def test_substitution_handles_multiple_loaders_by_position() -> None:
    """Two parent loaders + two drifted proposed loaders → 1:1 by workflow order.

    Parent stages are non-default ("preprocessed"/"normalized") so the missing-
    stage proposals genuinely fingerprint differently and exercise the
    substitution path rather than the early-skip-on-match branch.
    """
    parent_nodes = [
        _parent_loader("p_train", experiment_id=1, file_id=10, stage="preprocessed"),
        _parent_loader("p_test", experiment_id=1, file_id=11, stage="normalized"),
    ]
    proposed = {
        "nodes": [
            {"id": "train_1", "type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 10}},
            {"id": "test_1", "type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 11}},
        ],
        "edges": [],
    }

    substitute_parent_data_loaders(proposed, parent_nodes)

    assert proposed["nodes"][0]["parameters"]["stage"] == "preprocessed"
    assert proposed["nodes"][1]["parameters"]["stage"] == "normalized"
    assert proposed["nodes"][0]["parameters"]["file_id"] == 10
    assert proposed["nodes"][1]["parameters"]["file_id"] == 11


def test_substitution_noop_when_parent_has_no_loaders() -> None:
    """No parent loaders → no substitution (and validator will catch downstream)."""
    parent_nodes = [SimpleNamespace(node_id="p_pca", node_type="model.pca", parameters={"n_components": 5})]
    proposed = {
        "nodes": [{"id": "src_1", "type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 2}}],
        "edges": [],
    }
    before = dict(proposed["nodes"][0]["parameters"])

    substitute_parent_data_loaders(proposed, parent_nodes)

    assert proposed["nodes"][0]["parameters"] == before


def test_substitution_skips_non_loader_proposed_nodes() -> None:
    """Non-loader proposed nodes (PCA, classifier, etc.) must not be touched."""
    parent_nodes = [_parent_loader("p_src", experiment_id=1, file_id=2, stage="raw")]
    proposed = {
        "nodes": [
            {"id": "src_1", "type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 2}},
            {"id": "pca_1", "type": "model.pca", "parameters": {"n_components": 3}},
            {"id": "plot_1", "type": "viz.scatter", "parameters": {"color_by": "label"}},
        ],
        "edges": [],
    }

    substitute_parent_data_loaders(proposed, parent_nodes)

    assert proposed["nodes"][1]["parameters"] == {"n_components": 3}
    assert proposed["nodes"][2]["parameters"] == {"color_by": "label"}
