from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import DerivativeNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import NormalizeNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node import BaselinePenalizedLSNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import SmoothNode
from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact


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
    assert FittedPLSV2Node.metadata.node_type == "model.fitted_pls"


def test_snv_normalizes_rows_and_records_node_contract() -> None:
    ds = _dataset()
    out = ss.preprocess.snv(ds)

    np.testing.assert_allclose(np.mean(out.data, axis=1), np.zeros(2), atol=1e-12)
    np.testing.assert_allclose(np.std(out.data, axis=1), np.ones(2), atol=1e-12)
    step = out.provenance[-1]
    assert step.op_id == "preprocess.normalize"
    assert dict(step.parameters) == {
        "method": "snv",
        "std_ddof": 0,
        "scale_method": "max",
        "transform_state": {
            "method": "snv",
            "std_ddof": 0,
            "replay": "sample_local",
        },
    }
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
    assert step.op_id == "preprocess.msc"
    parameters = dict(step.parameters)
    assert parameters["reference_method"] == "mean"
    assert parameters["state_serializer"] == "spectra.msc-reference-json.v2"
    assert parameters["transform_state"]["serializer"] == "spectra.msc-reference-json.v2"
    np.testing.assert_allclose(
        parameters["transform_state"]["reference_spectrum"],
        np.mean(_dataset().data, axis=0),
    )


def test_msc_sdk_provenance_replays_the_fitted_reference_on_new_samples() -> None:
    training = _dataset()
    transformed = ss.preprocess.msc(training, reference="mean")
    new_samples = np.asarray(training.data, dtype=np.float64) * 1.3 + 0.2
    application = training.with_data(new_samples)
    manifest = {
        "preprocessing_chain": [
            {
                "op_id": transformed.provenance[-1].op_id,
                "parameters": dict(transformed.provenance[-1].parameters),
            }
        ]
    }

    replayed, _, _, warnings = _prepare_X_for_artifact(
        new_samples,
        None,
        manifest,
        scope="all",
        source_dataset=application,
    )

    reference = np.mean(np.asarray(training.data, dtype=np.float64), axis=0)
    design = np.vstack([reference, np.ones(reference.shape[0])]).T
    expected = np.empty_like(new_samples)
    for index, spectrum in enumerate(new_samples):
        slope, intercept = np.linalg.lstsq(design, spectrum, rcond=None)[0]
        expected[index] = (spectrum - intercept) / slope
    np.testing.assert_allclose(replayed, expected)
    assert warnings == []


def test_msc_matches_registered_msc_node_execute() -> None:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode

    ds = _dataset()
    sdk_result = ss.preprocess.msc(ds, reference="mean")
    node_result = _execute_node_default(
        MSCNode(node_id="node.msc", parameters={"reference_method": "mean"}),
        input_data=ds,
    )

    np.testing.assert_allclose(np.asarray(sdk_result.data), np.asarray(node_result.data), atol=1e-12)
    assert sdk_result.provenance[-1].state_effects == node_result.provenance[-1].state_effects
    assert sdk_result.units == node_result.units == "absorbance"


def test_savgol_dispatches_smooth_and_derivative_contracts() -> None:
    ds = _dataset()

    smooth = ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=0)
    smooth_step = smooth.provenance[-1]
    assert smooth_step.op_id == "preprocess.smooth"
    assert dict(smooth_step.parameters) == {
        "method": "savitzky_golay",
        "size": 3,
        "order": 1,
        "lam": 100.0,
        "d": "2",
        "sigma": 2.0,
    }

    deriv = ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=1)
    deriv_step = deriv.provenance[-1]
    assert deriv_step.op_id == "preprocess.derivative"
    assert dict(deriv_step.parameters) == {
        "method": "savitzky_golay",
        "size": 3,
        "order": 1,
        "deriv": "1",
        "gap": 5,
        "segment": 5,
        "delta": 1.0,
    }


@pytest.mark.parametrize(
    ("window", "polyorder", "deriv"),
    [
        (3.5, 1, 0),
        (3, 1.5, 0),
        (3, 1, 0.5),
        (3, 1, True),
    ],
)
def test_savgol_sdk_rejects_values_that_would_require_hidden_coercion(
    window: object,
    polyorder: object,
    deriv: object,
) -> None:
    with pytest.raises(ValueError):
        ss.preprocess.savgol(
            _dataset(),
            window=window,  # type: ignore[arg-type]
            polyorder=polyorder,  # type: ignore[arg-type]
            deriv=deriv,  # type: ignore[arg-type]
        )


def test_savgol_sdk_uses_and_records_physical_axis_spacing() -> None:
    x = np.arange(0.0, 10.0, 2.0)
    ds = ss.data.from_array(
        np.vstack([x**2, (x + 1.0) ** 2]),
        x=x,
        samples=["a", "b"],
        units="cm-1",
        data_units="absorbance",
    )

    derivative = ss.preprocess.savgol(ds, window=3, polyorder=2, deriv=1)

    np.testing.assert_allclose(derivative.data[:, 1:-1], np.vstack([2.0 * x, 2.0 * (x + 1.0)])[:, 1:-1])
    assert derivative.provenance[-1].parameters["delta"] == 2.0


def test_savgol_smoothing_matches_smooth_node_execute() -> None:
    ds = _dataset()

    _assert_data_matches_node(
        ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=0),
        SmoothNode(node_id="node.smooth", parameters={"method": "savitzky_golay", "size": 3, "order": 1}),
        input_data=ds,
    )


def test_savgol_derivative_matches_derivative_node_execute() -> None:
    ds = _dataset()
    sdk_result = ss.preprocess.savgol(ds, window=3, polyorder=1, deriv=1)
    node_result = _execute_node_default(
        DerivativeNode(
            node_id="node.derivative",
            parameters={"method": "savitzky_golay", "size": 3, "order": 1, "deriv": "1"},
        ),
        input_data=ds,
    )

    np.testing.assert_allclose(np.asarray(sdk_result.data), np.asarray(node_result.data), atol=1e-12)
    assert sdk_result.provenance[-1].state_effects == node_result.provenance[-1].state_effects
    assert sdk_result.units == node_result.units == "d(absorbance)/d(cm-1)"


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
    from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity

    ds = _dataset()

    centered = ss.preprocess.mean_center(ds)
    centered_step = centered.provenance[-1]
    assert centered_step.op_id == "preprocess.scale"
    assert dict(centered_step.parameters) == {
        "method": "mean_center",
        "center": True,
        "state_serializer": "spectra.scale-reference-json.v2",
        "transform_state": {
            "serializer": "spectra.scale-reference-json.v2",
            "input_identity": {
                **fitted_input_identity(ds, features=ds.n_features),
                "axis": tuple(fitted_input_identity(ds, features=ds.n_features)["axis"]),
            },
            "method": "mean_center",
            "center": True,
            "mean": tuple(np.mean(ds.data, axis=0).tolist()),
            "scale": None,
        },
    }
    np.testing.assert_allclose(np.mean(centered.data, axis=0), np.zeros(ds.shape[1]), atol=1e-12)

    scaled = ss.preprocess.autoscale(ds, center=True)
    scaled_step = scaled.provenance[-1]
    assert scaled_step.op_id == "preprocess.scale"
    scaled_parameters = dict(scaled_step.parameters)
    assert scaled_parameters["method"] == "autoscale"
    assert scaled_parameters["center"] is True
    assert scaled_parameters["state_serializer"] == "spectra.scale-reference-json.v2"
    assert dict(scaled_parameters["transform_state"]) == {
        "serializer": "spectra.scale-reference-json.v2",
        "input_identity": {
            **fitted_input_identity(ds, features=ds.n_features),
            "axis": tuple(fitted_input_identity(ds, features=ds.n_features)["axis"]),
        },
        "method": "autoscale",
        "center": True,
        "mean": tuple(np.mean(ds.data, axis=0).tolist()),
        "scale": tuple(np.std(ds.data, axis=0).tolist()),
    }
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
