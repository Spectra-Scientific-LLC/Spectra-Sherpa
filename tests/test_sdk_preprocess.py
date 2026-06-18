from __future__ import annotations

import asyncio

import numpy as np

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes import PLSNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.baseline_nodes import BaselinePenalizedLSNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import NormalizeNode, ScaleNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_deriv_nodes import DerivativeNode, SmoothNode


def _dataset() -> ss.SherpaDataset:
    return ss.data.from_array(
        np.array([[1.0, 2.0, 4.0, 8.0, 16.0], [2.0, 4.0, 8.0, 16.0, 32.0]]),
        x=np.array([1000, 1001, 1002, 1003, 1004], dtype=float),
        samples=["a", "b"],
        units="cm-1",
        data_units="absorbance",
    )


def _execute_node_default(node, **inputs):
    result = asyncio.run(node.execute(**inputs))
    if hasattr(result, "outputs"):
        return result.outputs["default"]
    return result


def _assert_data_matches_node(sdk_result, node, **inputs) -> None:
    node_result = _execute_node_default(node, **inputs)
    np.testing.assert_allclose(np.asarray(sdk_result.data), np.asarray(node_result.data), atol=1e-12)


def test_sdk_wrapper_contract_matches_current_node_metadata() -> None:
    assert NormalizeNode.metadata.node_type == "preprocess.normalize"
    normalize_params = {param.name: param for param in NormalizeNode.metadata.parameters}
    assert normalize_params["method"].default == "snv"

    assert SmoothNode.metadata.node_type == "preprocess.smooth"
    assert DerivativeNode.metadata.node_type == "preprocess.derivative"
    assert BaselinePenalizedLSNode.metadata.node_type == "baseline.penalized_ls"
    assert ScaleNode.metadata.node_type == "preprocess.scale"
    assert PCANode.metadata.node_type == "model.pca"
    assert PLSNode.metadata.node_type == "model.pls"


def test_snv_normalizes_rows_and_records_node_contract() -> None:
    ds = _dataset()
    out = ss.preprocess.snv(ds)

    np.testing.assert_allclose(np.mean(out.data, axis=1), np.zeros(2), atol=1e-12)
    np.testing.assert_allclose(np.std(out.data, axis=1), np.ones(2), atol=1e-12)
    step = out.provenance[-1]
    assert step.op_id == "preprocess.normalize"
    assert dict(step.parameters) == {"method": "snv"}
    assert "normalized" in step.state_effects


def test_snv_matches_normalize_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.snv(ds),
        NormalizeNode(node_id="node.snv", parameters={"method": "snv"}),
        input_data=ds,
    )


def test_msc_records_node_contract() -> None:
    out = ss.preprocess.msc(_dataset(), reference="mean")
    step = out.provenance[-1]
    assert step.op_id == "preprocess.normalize"
    assert dict(step.parameters) == {"method": "msc", "reference": "mean"}


def test_msc_matches_normalize_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.msc(ds, reference="mean"),
        NormalizeNode(node_id="node.msc", parameters={"method": "msc", "reference": "mean"}),
        input_data=ds,
    )


def test_savgol_dispatches_smooth_and_derivative_contracts() -> None:
    ds = _dataset()

    smooth = ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=0)
    smooth_step = smooth.provenance[-1]
    assert smooth_step.op_id == "preprocess.smooth"
    assert dict(smooth_step.parameters) == {"method": "savitzky_golay", "size": 3, "order": 1}

    deriv = ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=1)
    deriv_step = deriv.provenance[-1]
    assert deriv_step.op_id == "preprocess.derivative"
    assert dict(deriv_step.parameters) == {
        "method": "savitzky_golay",
        "size": 3,
        "order": 1,
        "deriv": "1",
    }


def test_savgol_smoothing_matches_smooth_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=0),
        SmoothNode(node_id="node.smooth", parameters={"method": "savitzky_golay", "size": 3, "order": 1}),
        input_data=ds,
    )


def test_savgol_derivative_matches_derivative_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=1),
        DerivativeNode(
            node_id="node.derivative",
            parameters={"method": "savitzky_golay", "size": 3, "order": 1, "deriv": "1"},
        ),
        input_data=ds,
    )


def test_baseline_als_records_node_contract() -> None:
    out = ss.preprocess.baseline_als(_dataset(), lam=1e4, p=0.01, max_iter=10, tol=1e-5)
    step = out.provenance[-1]
    assert step.op_id == "baseline.penalized_ls"
    assert dict(step.parameters) == {"method": "als", "lam": 10000.0, "p": 0.01, "max_iter": 10, "tol": 1e-05}


def test_baseline_als_matches_baseline_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.baseline_als(ds, lam=1e4, p=0.01, max_iter=10, tol=1e-5),
        BaselinePenalizedLSNode(
            node_id="node.baseline",
            parameters={"method": "als", "lam": 1e4, "p": 0.01, "max_iter": 10, "tol": 1e-5},
        ),
        input_data=ds,
    )


def test_mean_center_and_autoscale_record_node_contracts() -> None:
    ds = _dataset()

    centered = ss.preprocess.mean_center(ds)
    centered_step = centered.provenance[-1]
    assert centered_step.op_id == "preprocess.scale"
    assert dict(centered_step.parameters) == {"method": "mean_center"}
    np.testing.assert_allclose(np.mean(centered.data, axis=0), np.zeros(ds.shape[1]), atol=1e-12)

    scaled = ss.preprocess.autoscale(ds, center=True)
    scaled_step = scaled.provenance[-1]
    assert scaled_step.op_id == "preprocess.scale"
    assert dict(scaled_step.parameters) == {"method": "autoscale", "center": True}
    np.testing.assert_allclose(np.std(scaled.data, axis=0), np.ones(ds.shape[1]), atol=1e-12)


def test_mean_center_matches_scale_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.mean_center(ds),
        ScaleNode(node_id="node.mean_center", parameters={"method": "mean_center"}),
        input_data=ds,
    )


def test_autoscale_matches_scale_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.autoscale(ds, center=True),
        ScaleNode(node_id="node.autoscale", parameters={"method": "autoscale", "center": True}),
        input_data=ds,
    )
