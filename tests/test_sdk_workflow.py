from __future__ import annotations

import pytest

import spectra_sherpa.sdk as ss


def _workflow(**overrides):
    values = {
        "nodes": [
            {"node_id": "source", "node_type": "data.file_load", "parameters": {}},
            {"node_id": "model", "node_type": "model.fitted_pls", "parameters": {"n_components": 3}},
        ],
        "edges": [{"from_node_id": "source", "to_node_id": "model"}],
    }
    values.update(overrides)
    return ss.workflow.workflow_spec(**values)


def test_portable_workflow_is_content_addressed_and_ignores_visual_fields() -> None:
    first = _workflow()
    second = _workflow(
        nodes=[
            {
                "node_id": "model",
                "node_type": "model.fitted_pls",
                "parameters": {"n_components": 3},
                "label": "cosmetic",
                "position_x": 900,
            },
            {"node_id": "source", "node_type": "data.file_load", "parameters": {}, "position_y": 50},
        ],
        edges=[{"from_node_id": "source", "to_node_id": "model", "from_output": "default", "to_input": "default"}],
    )

    assert first.workflow_digest == second.workflow_digest
    assert ss.workflow.verify_workflow(first)
    assert ss.workflow.verify_workflow(first.as_dict())


def test_portable_workflow_rejects_tampering_cycles_and_unknown_nodes() -> None:
    manifest = _workflow().as_dict()
    model = next(node for node in manifest["nodes"] if node["node_id"] == "model")
    model["parameters"]["n_components"] = 5
    assert ss.workflow.verify_workflow(manifest) is False
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="digest mismatch"):
        ss.workflow.WorkflowSpec.from_dict(manifest)
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="acyclic"):
        _workflow(
            edges=[{"from_node_id": "source", "to_node_id": "model"}, {"from_node_id": "model", "to_node_id": "source"}]
        )
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="not present"):
        _workflow(edges=[{"from_node_id": "source", "to_node_id": "missing"}])
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="current canonical registry"):
        _workflow(nodes=[{"node_id": "unknown", "node_type": "unknown.node", "parameters": {}}], edges=[])


@pytest.mark.parametrize(
    "node_type",
    [
        "data.my_dataset",
        "data.source",
        "diagnostics.holdout_evaluation",
        "model.pls",
        "model.pls_predict",
        "selection.sample_partition",
    ],
)
def test_public_workflow_constructor_rejects_retired_prototypes(node_type: str) -> None:
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="current canonical registry"):
        ss.workflow.workflow_spec(nodes=[{"node_id": "retired", "node_type": node_type, "parameters": {}}], edges=[])


def test_unversioned_workflow_is_rejected_instead_of_migrated() -> None:
    assert ss.workflow.verify_workflow({"nodes": [], "edges": []}) is False
    assert not hasattr(ss.workflow, "migrate_workflow")
    assert not hasattr(ss.workflow, "_frozen_v1_workflow_from_dict")
    assert not hasattr(ss.workflow, "_frozen_v1_workflow_spec")


def test_portable_workflow_requires_serializable_parameters_and_unique_node_ids() -> None:
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="canonical-JSON"):
        _workflow(
            nodes=[{"node_id": "source", "node_type": "data.file_load", "parameters": {"nan": float("nan")}}],
            edges=[],
        )
    with pytest.raises(ss.workflow.WorkflowSchemaError, match="duplicate workflow node_id"):
        _workflow(
            nodes=[
                {"node_id": "source", "node_type": "data.file_load", "parameters": {}},
                {"node_id": "source", "node_type": "model.fitted_pls", "parameters": {}},
            ],
            edges=[],
        )
