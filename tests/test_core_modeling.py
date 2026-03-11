import numpy as np
import pytest

pytest.importorskip("spectrochempy")

from spectra_sherpa.app.services.dag.nodes.modeling import MCRNode, PCRNode, PLSNode


@pytest.mark.asyncio
async def test_pls_node_accepts_array():
    # Bug 11: PLSNode should accept arrays matching metadata signature
    node = PLSNode("pls_test")
    X_array = np.random.rand(10, 50)
    y_array = np.random.rand(10)

    # This should not raise ValueError from bind_X(allow_array=False)
    result = await node.execute(X=X_array, y=y_array)
    assert "model" in result


@pytest.mark.asyncio
async def test_mcr_node_constraints():
    # Bug 10: MCRNode should apply constraints
    node = MCRNode(
        "mcr_test", parameters={"n_components": 2, "max_iter": 5, "non_negative_C": True, "non_negative_St": True}
    )

    # Create simple dataset
    X_array = np.abs(np.random.rand(10, 50))
    ds = scp.NDDataset(X_array)

    result = await node.execute(input_data=ds)
    mcr_model = result["model"]

    # Internal SCP instances should reflect the solver selection
    assert mcr_model.solverConc == "nnls"
    assert mcr_model.solverSpec == "nnls"


@pytest.mark.asyncio
async def test_pcr_node_scaling(monkeypatch):
    # Bug 12: PCRNode should pass mean=scale when Scale Data=False
    node = PCRNode("pcr_test", parameters={"n_components": 2, "scale": False})

    pipeline_capture = []
    import sklearn.pipeline

    original_pipeline = sklearn.pipeline.Pipeline

    def mock_pipeline(steps):
        pipeline_capture.append(steps)
        return original_pipeline(steps)

    monkeypatch.setattr(sklearn.pipeline, "Pipeline", mock_pipeline)

    X_array = np.random.rand(10, 50)
    y_array = np.random.rand(10)
    ds = scp.NDDataset(X_array)

    await node.execute(X=ds, y=y_array)

    # Assert the scaler step has with_mean=False as expected from scale=False
    scaler = pipeline_capture[0][0][1]
    assert scaler.with_mean is False
    assert scaler.with_std is False
