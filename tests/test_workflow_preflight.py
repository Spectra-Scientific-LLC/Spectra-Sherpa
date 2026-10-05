"""M4.2 semantic preflight: typed admission and bounded legacy migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra_sherpa.app.services.dag import executor as dag_executor
from spectra_sherpa.app.services.dag import node_catalog_contract, workflow_preflight
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeRegistry,
    PortMetadata,
)
from spectra_sherpa.app.services.dag.node_base import node_registry as live_node_registry
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract


@pytest.fixture(autouse=True)
def loaded_registry():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _contract(node_type: str, input_ref: str | None, output_ref: str | None) -> NodeExecutionContract:
    payload = live_node_registry.get_metadata("preprocess.smooth").resolved_execution_contract().as_dict()
    payload.update(
        operation_id=node_type,
        implementation_id=f"test.{node_type}",
        semantic_inputs=(
            [_port("input", "spectrasherpa://types/SpectralDataset/1.0")]
            if input_ref is None and output_ref is None
            else ([] if input_ref is None else [_port("input", input_ref)])
        ),
        semantic_outputs=[] if output_ref is None else [_port("output", output_ref)],
        managed_optimization_profiles=["test_profile"],
    )
    return NodeExecutionContract.from_dict(payload)


def _port(name: str, type_ref: str) -> dict[str, object]:
    return {
        "name": name,
        "type_ref": type_ref,
        "required": True,
        "variadic": False,
        "accepted_data_roles": [],
    }


def _register(
    registry: NodeRegistry,
    node_type: str,
    input_ref: str | None,
    output_ref: str | None,
    contracted: bool,
) -> None:
    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type=node_type,
        category="test",
        label=node_type,
        description="",
        input_ports=[] if input_ref is None else [PortMetadata("input", input_ref)],
        output_ports=([] if contracted else None) if output_ref is None else [PortMetadata("output", output_ref)],
        execution_contract=_contract(node_type, input_ref, output_ref) if contracted else None,
    )

    class _Node(Node):
        async def execute(self, *args, **kwargs):
            return None

    _Node.metadata = metadata
    registry.register(_Node)


@pytest.fixture
def registry(monkeypatch) -> NodeRegistry:
    isolated = NodeRegistry()
    monkeypatch.setattr(workflow_preflight, "node_registry", isolated)
    monkeypatch.setattr(dag_executor, "node_registry", isolated)
    return isolated


@pytest.fixture
def nodes():
    return ("data.test_preflight_source", "test.preflight_target")


def test_contracted_incompatible_typed_edge_is_an_error(registry, nodes) -> None:
    _register(registry, nodes[0], None, "spectrasherpa://types/SpectralDataset/1.0", True)
    _register(registry, nodes[1], "spectrasherpa://types/FittedModel/1.0", None, True)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {}), WorkflowNode(nodes[1], nodes[1], {})],
        [WorkflowEdge(nodes[0], nodes[1], "output", "input")],
    )
    assert report.is_valid is False
    assert report.edges[0].status == "invalid"
    assert [issue.code for issue in report.issues] == ["incompatible_semantic_edge"]


def test_uncontracted_edge_is_rejected_without_a_compatibility_path(registry, nodes) -> None:
    _register(registry, nodes[0], None, None, False)
    _register(registry, nodes[1], None, None, False)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {}), WorkflowNode(nodes[1], nodes[1], {})],
        [WorkflowEdge(nodes[0], nodes[1])],
    )
    assert report.is_valid is False
    assert report.edges[0].status == "invalid"
    assert [issue.code for issue in report.issues] == [
        "missing_execution_contract",
        "missing_execution_contract",
        "missing_declared_port",
    ]


def test_contracted_missing_port_fails_closed(registry, nodes) -> None:
    _register(registry, nodes[0], None, None, True)
    _register(registry, nodes[1], "spectrasherpa://types/SpectralDataset/1.0", None, True)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {}), WorkflowNode(nodes[1], nodes[1], {})],
        [WorkflowEdge(nodes[0], nodes[1])],
    )
    assert report.is_valid is False
    assert report.issues[0].code == "invalid_execution_contract"


def test_default_edge_shorthand_resolves_the_first_declared_port(registry, nodes) -> None:
    type_ref = "spectrasherpa://types/SpectralDataset/1.0"
    _register(registry, nodes[0], None, type_ref, True)
    _register(registry, nodes[1], type_ref, None, True)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {}), WorkflowNode(nodes[1], nodes[1], {})],
        [WorkflowEdge(nodes[0], nodes[1])],
    )
    assert report.is_valid is True
    assert report.edges[0].status == "typed_valid"


def test_duplicate_node_ids_are_rejected_before_metadata_can_be_overwritten(registry, nodes) -> None:
    _register(registry, nodes[0], None, "spectrasherpa://types/SpectralDataset/1.0", True)
    report = preflight_workflow(
        [WorkflowNode("duplicate", nodes[0], {}), WorkflowNode("duplicate", nodes[0], {})],
        [],
    )
    assert report.is_valid is False
    assert [issue.code for issue in report.issues] == ["duplicate_node_id"]


def test_dangling_edge_is_an_inspectable_admission_error(registry, nodes) -> None:
    """A saved edge to a missing node is rejected, never raised as a 500."""
    _register(registry, nodes[0], None, "spectrasherpa://types/SpectralDataset/1.0", True)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {})],
        [WorkflowEdge(nodes[0], "missing-node")],
    )
    assert report.is_valid is False
    assert any(issue.code == "invalid_graph_edge" for issue in report.issues)


def test_unavailable_type_registry_blocks_execution_but_preserves_inspection(registry, nodes, monkeypatch) -> None:
    type_ref = "spectrasherpa://types/SpectralDataset/1.0"
    _register(registry, nodes[0], None, type_ref, True)
    _register(registry, nodes[1], type_ref, None, True)
    monkeypatch.setattr(type_registry, "_loaded", False)
    report = preflight_workflow(
        [WorkflowNode(nodes[0], nodes[0], {}), WorkflowNode(nodes[1], nodes[1], {})],
        [WorkflowEdge(nodes[0], nodes[1])],
    )
    assert report.is_valid is False
    assert report.issues[0].code == "type_registry_unavailable"
    assert report.edges[0].status == "invalid"


def test_optional_runtime_dependency_is_required_only_for_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        node_catalog_contract,
        "distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )
    graph = [
        WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1}),
        WorkflowNode("efa", "model.efa", {}),
    ]
    edges = [WorkflowEdge("source", "efa")]

    strict = preflight_workflow(graph, edges)
    persisted_project = preflight_workflow(graph, edges, require_runtime_dependencies=False)

    assert strict.is_valid is False
    assert "spectrochempy_unavailable" in [issue.code for issue in strict.issues]
    assert persisted_project.is_valid is True
