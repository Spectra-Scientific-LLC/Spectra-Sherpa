"""Managed model-reader authority follows the admitted execution, including workers."""

from unittest.mock import Mock

import pytest

from spectra_sherpa.core.model_artifact import ReadOnlyModelArtifactReader


def test_model_reader_refuses_unadmitted_identity_before_storage(tmp_path):
    reader = ReadOnlyModelArtifactReader(tmp_path, allowed_artifact_uids=("allowed",))
    assert reader._artifact_dir("allowed") == tmp_path / "models" / "allowed"
    with pytest.raises(FileNotFoundError, match="not admitted"):
        reader.load("foreign-project-model")
    with pytest.raises(ValueError):
        ReadOnlyModelArtifactReader(tmp_path)._artifact_dir("../escape")


def test_application_and_worker_readers_share_the_same_closed_model_grant(monkeypatch):
    from spectra_sherpa.app.services import execution_runtime

    ambient = Mock()
    monkeypatch.setattr(execution_runtime, "get_model_store", lambda: ambient)
    runtime = execution_runtime.build_application_execution_runtime(allowed_model_artifact_uids=("allowed",))
    for reader in (runtime.model_artifact_reader, runtime.worker_model_artifact_reader):
        with pytest.raises(FileNotFoundError, match="not admitted"):
            reader.load("foreign-project-model")
    ambient.load.assert_not_called()


def test_scoped_reader_cannot_be_replaced_by_an_ambient_override(monkeypatch):
    from spectra_sherpa.app.services import execution_runtime

    monkeypatch.setattr(execution_runtime, "get_model_store", Mock())
    with pytest.raises(ValueError, match="cannot override"):
        execution_runtime.build_application_execution_runtime(
            allowed_model_artifact_uids=(),
            model_artifact_reader=Mock(),
        )


@pytest.mark.asyncio
async def test_connected_model_reference_cannot_expand_admitted_dag_authority(monkeypatch):
    """A model_ref edge wins over parameters, but never over the run's grant."""
    import numpy as np

    import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import execution_runtime
    from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

    ambient = Mock()
    monkeypatch.setattr(execution_runtime, "get_model_store", lambda: ambient)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.get_default_pool", lambda: None)
    executor = DAGExecutor(
        runtime=execution_runtime.build_application_execution_runtime(
            allowed_model_artifact_uids=("allowed",),
        )
    )
    executor.add_node(WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1}))
    for node_id in ("upstream", "apply"):
        executor.add_node(WorkflowNode(node_id, "model.load_apply", {"model_id": "allowed"}))
        executor.add_edge(WorkflowEdge(from_node="source", to_node=node_id, from_output="default", to_input="X_new"))
    executor.add_edge(WorkflowEdge(from_node="upstream", to_node="apply", from_output="model_id", to_input="model_ref"))
    executor.inject_result("source", SherpaDataset(np.ones((2, 3))))
    # Simulate an upstream result pointing outside the preflight-authorized set.
    executor.inject_result("upstream", {"model_id": "foreign-project-model", "result": [[0.0]]})
    with pytest.raises(ValueError, match="foreign-project-model.*not found"):
        await executor.execute()
    ambient.load.assert_not_called()
