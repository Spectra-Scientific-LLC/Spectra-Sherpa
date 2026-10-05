from __future__ import annotations

from types import SimpleNamespace


def test_saved_definition_preserves_hash_without_materializing_defaults():
    from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
    from spectra_sherpa.app.services.run_params import (
        build_effective_params_snapshot,
        build_saved_definition_snapshot,
    )

    node = SimpleNamespace(
        node_id="model_1", node_type="classification.plsda", label="PLS-DA", parameters={"n_components": 2}
    )
    workflow = SimpleNamespace(name="Baseline", nodes=[node], edges=[])
    workflow.integrity_hash = compute_workflow_hash([vars(node)], [])
    effective = build_effective_params_snapshot(workflow.nodes)
    assert "scale" in effective[node.node_id]
    definition = build_saved_definition_snapshot(workflow)
    assert compute_workflow_hash(definition["nodes"], definition["edges"]) == workflow.integrity_hash
    assert definition["nodes"][0]["parameters"] == {"n_components": 2}
    assert definition["data_context"] == {
        "schema_version": 1,
        "data_source_id": None,
        "source_name": None,
        "source_origin": None,
    }
    assert compute_workflow_hash([{**vars(node), "parameters": effective[node.node_id]}], []) != workflow.integrity_hash
    node.parameters["n_components"] = 9
    assert definition["nodes"][0]["parameters"] == {"n_components": 2}


def test_effective_params_snapshot_materializes_plsda_defaults():
    from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

    snapshot = build_effective_params_snapshot(
        [
            SimpleNamespace(
                node_id="model_1",
                node_type="classification.plsda",
                parameters={"n_components": 5},
            )
        ]
    )

    assert snapshot["model_1"]["n_components"] == 5
    assert snapshot["model_1"]["scale"] is False
    assert set(snapshot["model_1"]) == {"n_components", "scale"}


def test_effective_params_snapshot_falls_back_for_legacy_nodes():
    from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

    snapshot = build_effective_params_snapshot(
        [
            SimpleNamespace(
                node_id="legacy_1",
                node_type="data.legacy_source",
                parameters={"source": "old-template"},
            )
        ]
    )

    assert snapshot == {"legacy_1": {"source": "old-template"}}


def test_saved_definition_retains_sheet_source_identity_for_reports():
    from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot

    workflow = SimpleNamespace(
        name="Wine PCA",
        integrity_hash="a" * 64,
        primary_data_source_id=12,
        primary_data_source=SimpleNamespace(display_name="Wine (bundled example)"),
        data_origin="example",
        nodes=[],
        edges=[],
    )

    assert build_saved_definition_snapshot(workflow)["data_context"] == {
        "schema_version": 1,
        "data_source_id": 12,
        "source_name": "Wine (bundled example)",
        "source_origin": "example",
    }
