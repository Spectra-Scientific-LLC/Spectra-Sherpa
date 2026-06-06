import numpy as np
import pytest

pytest.importorskip("spectrochempy")
import spectrochempy as scp

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.modeling import MCRNode, PCRNode, PLSNode
from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import _compare_mcr_to_target


@pytest.mark.asyncio
async def test_pls_node_accepts_array():
    # Bug 11: PLSNode should accept arrays matching metadata signature
    node = PLSNode("pls_test")
    X_array = np.random.rand(10, 50)
    y_array = np.random.rand(10)

    # This should not raise ValueError from bind_X(allow_array=False)
    result = await node.execute(X=X_array, y=y_array)
    assert "model" in result.outputs


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
    mcr_model = result.outputs["model"]

    # Internal SCP instances should reflect the solver selection
    assert mcr_model.solverConc == "nnls"
    assert mcr_model.solverSpec == "nnls"


def test_mcr_ground_truth_comparison_matches_permuted_scaled_components():
    target = np.array(
        [
            [0.0, 10.0],
            [1.0, 7.5],
            [2.0, 7.0],
            [3.0, 3.0],
            [4.0, 2.5],
        ],
        dtype=float,
    )
    recovered = np.column_stack(
        [
            0.5 * target[:, 1] + 2.0,
            2.0 * target[:, 0] - 1.0,
        ]
    )
    ds = SherpaDataset(
        np.random.rand(target.shape[0], 12),
        target=target,
        target_context=TargetContext(target_names=["A", "B"], target_units="ppm"),
    )

    comparison = _compare_mcr_to_target(
        recovered,
        ds,
        selected_target_index=0,
        selected_component_index=1,
        component_labels=["C1", "C2"],
    )

    assert comparison is not None
    assert comparison["type"] == "predicted_vs_actual"
    assert comparison["target_units"] == "ppm"
    assert comparison["mean_abs_correlation"] == pytest.approx(1.0)
    assert comparison["mean_normalized_rmse"] == pytest.approx(0.0, abs=1e-12)
    assert [m["target_name"] for m in comparison["matched_components"]] == ["B", "A"]
    assert comparison["selected_match"]["target_name"] == "A"
    assert comparison["selected_match"]["component_name"] == "C2"
    assert comparison["metrics"]["R2"] == pytest.approx(1.0)
    assert comparison["metrics"]["RMSE"] == pytest.approx(0.0, abs=1e-12)
    assert len(comparison["data"]) == target.shape[0]
    for pair in comparison["metadata"]["candidate_pairs"]:
        assert len(pair["actual"]) == target.shape[0]
        assert len(pair["predicted"]) == target.shape[0]
    assert set(comparison["data"][0]) >= {
        "sample_index",
        "sample_label",
        "target_component",
        "recovered_component",
        "target",
        "inferred",
        "raw_recovered",
        "residual",
    }
    assert comparison["series"][0]["name"] == "A"
    assert comparison["metadata"]["candidate_pairs"]
    assert comparison["metadata"]["suggested_matches"]


def test_mcr_ground_truth_comparison_keeps_one_pair_per_sample_for_synthetic_benchmark():
    from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

    ds = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    target = np.asarray(ds.target, dtype=float)
    recovered = target[:, :4].copy()

    comparison = _compare_mcr_to_target(
        recovered,
        ds,
        selected_target_index=2,
        selected_component_index=2,
        component_labels=["Water", "Carbon dioxide", "Methane", "Nitrous oxide"],
    )

    assert comparison is not None
    assert len(comparison["data"]) == 50
    assert len(comparison["series"][0]["actual"]) == 50
    assert len(comparison["series"][0]["predicted"]) == 50
    methane_pair = next(
        pair
        for pair in comparison["metadata"]["candidate_pairs"]
        if pair["target_name"] == "Methane" and pair["component_name"] == "Methane"
    )
    assert len(methane_pair["actual"]) == 50
    assert len(methane_pair["predicted"]) == 50
    assert len(set(np.round(methane_pair["actual"], 8))) == 50


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
