"""Catalog-wide guards for the defaults supplied by the workflow canvas."""

from pathlib import Path

import pytest
import yaml

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry, validate_execute_port_contract
from spectra_sherpa.app.services.dag.saved_graph_admission import (
    SavedGraphAdmissionError,
    admit_saved_workflow_graph,
)

CATALOG = node_registry.list_nodes()
TEMPLATES = Path(__file__).parents[1] / "src/spectra_sherpa/data/templates"


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param(
            metadata,
            id=metadata.node_type,
        )
        for metadata in CATALOG
    ],
)
def test_catalog_defaults_can_be_saved_as_a_draft(metadata):
    parameters = {
        parameter.name: parameter.default for parameter in metadata.parameters if parameter.default is not None
    }
    admit_saved_workflow_graph(
        [{"node_id": "new_node", "node_type": metadata.node_type, "parameters": parameters}],
        [],
        current_graph=True,
    )


@pytest.mark.parametrize("node_type,node_class", list(node_registry._nodes.items()))
def test_registered_execute_signature_accepts_declared_ports(node_type, node_class):
    assert not validate_execute_port_contract(node_class), node_type


@pytest.mark.parametrize(
    "path",
    sorted(path for path in TEMPLATES.glob("*.yaml") if not path.name.startswith("_")),
    ids=lambda path: path.stem,
)
def test_template_parameters_and_edges_are_current(path):
    template = yaml.safe_load(path.read_text())
    graph = template["template_data"]
    admit_saved_workflow_graph(graph["nodes"], graph.get("edges", []), current_graph=True)


@pytest.mark.parametrize("node_type,retired", [("analysis.peak_finding", "method"), ("model.efa", "direction")])
def test_retired_ui_parameters_remain_rejected(node_type, retired):
    with pytest.raises(SavedGraphAdmissionError, match="undeclared"):
        admit_saved_workflow_graph(
            [{"node_id": "old_node", "node_type": node_type, "parameters": {retired: "retired"}}],
            [],
            current_graph=True,
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"source_mode": "experiment_collection"},
        {"source_mode": "experiment_collection", "experiment_id": 12},
        {"source_mode": "experiment_collection", "experiment_id": 12, "asset_id": "asset"},
        {"folder_path": "/tmp/spectra", "pattern": ""},
    ],
)
def test_incomplete_group_source_saves_without_becoming_executable(parameters):
    node = {"node_id": "source", "node_type": "data.load_group", "parameters": parameters}
    admitted = admit_saved_workflow_graph([node], [], current_graph=True)
    assert admitted.nodes[0]["parameters"] == parameters
    with pytest.raises(ValueError):
        node_registry.create_node("data.load_group", "source", parameters).validate_parameters()


@pytest.mark.parametrize(
    "parameters",
    [
        {"source_mode": "unknown"},
        {"source_mode": "experiment_collection", "experiment_id": -1},
        {"source_mode": "experiment_collection", "experiment_id": True},
        {"source_mode": "experiment_collection", "folder_path": "/tmp"},
        {"source_mode": "experiment_collection", "source_manifest_sha256": "invalid"},
        {"source_mode": "experiment_collection", "scientific_collection_sha256": "invalid"},
        {"recursive": "yes"},
        {"method": "retired"},
    ],
)
def test_invalid_group_source_values_are_not_admitted_as_drafts(parameters):
    with pytest.raises(SavedGraphAdmissionError):
        admit_saved_workflow_graph(
            [{"node_id": "source", "node_type": "data.load_group", "parameters": parameters}],
            [],
            current_graph=True,
        )
