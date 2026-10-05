from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis


def test_simca_extract_rejects_samples_outside_all_class_limits():
    from spectra_sherpa.app.lib.fitted_state import SIMCAExtract

    extract = SIMCAExtract(
        class_loadings={
            "A": np.array([[1.0, 0.0]]),
            "B": np.array([[1.0, 0.0]]),
        },
        class_eigenvalues={
            "A": np.array([1.0]),
            "B": np.array([1.0]),
        },
        class_means={
            "A": np.array([0.0, 0.0]),
            "B": np.array([10.0, 0.0]),
        },
        class_scales={
            "A": np.array([1.0, 1.0]),
            "B": np.array([1.0, 1.0]),
        },
        pca_means={
            "A": np.array([0.0, 0.0]),
            "B": np.array([0.0, 0.0]),
        },
        classes=["A", "B"],
        T2_limits={"A": 1.0, "B": 1.0},
        Q_limits={"A": 0.1, "B": 0.1},
        n_components=1,
    )

    labels, _ = extract.predict(np.array([[100.0, 100.0]]))

    assert labels.tolist() == ["unassigned"]


@pytest.mark.asyncio
async def test_knn_default_model_scales_features_before_distance_calculation():
    from spectra_sherpa.app.lib.fitted_state import KNNExtract
    from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import (
        KNNNode,
        apply_knn_fitted_state,
    )

    X = SherpaDataset(
        X=np.array(
            [
                [0.0, 0.0],
                [10.0, 0.0],
                [1000.0, 100.0],
                [1010.0, 100.0],
            ]
        ),
        sample_axis=SampleAxis(labels=["a0", "a1", "b0", "b1"]),
        target=np.array(["A", "A", "B", "B"], dtype=object),
    )
    node = KNNNode(node_id="knn_scale", parameters={"n_neighbors": 1})

    result = await node.execute(X=X)

    fitted_state = result.outputs["fitted_state"]
    assert fitted_state["serializer"] == "spectrasherpa.model-artifact.knn/1"
    assert fitted_state["scale"] is True
    assert not np.array_equal(np.asarray(fitted_state["x_mean"]), np.zeros(X.X.shape[1]))
    artifact = result.outputs["_model_artifact"]
    assert artifact["metadata"]["model_type"] == "knn"
    assert "x_mean" in artifact["arrays"]
    assert "x_scale" in artifact["arrays"]

    query = np.array([[900.0, 0.0]])
    scaled_extract = KNNExtract.from_artifact(artifact["metadata"], artifact["arrays"])
    raw_extract = KNNExtract(
        X_train=X.X,
        y_train_encoded=np.array([0, 0, 1, 1], dtype=np.int64),
        classes=["A", "B"],
        k=1,
    )

    assert raw_extract.predict(query)[0].tolist() == ["B"]
    assert scaled_extract.predict(query)[0].tolist() == ["A"]
    assert apply_knn_fitted_state(query, fitted_state)[0].tolist() == ["A"]


@pytest.mark.asyncio
async def test_savgol_derivative_uses_physical_axis_spacing():
    from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import DerivativeNode

    x = np.arange(0.0, 14.0, 2.0)
    ds = SherpaDataset(
        X=(x**2).reshape(1, -1),
        feature_axis=SpectralAxis(values=x, units="cm-1"),
        sample_axis=SampleAxis(labels=["s0"]),
        units="intensity",
    )
    node = DerivativeNode(
        node_id="deriv_delta",
        parameters={"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
    )

    execution = await node.execute(input_data=ds)
    result = execution.outputs["default"]

    np.testing.assert_allclose(result.X[0, 2:-2], 2.0 * x[2:-2], atol=1e-10)


@pytest.mark.asyncio
async def test_derivative_rejects_nonuniform_axis_for_physical_units():
    from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import DerivativeNode

    x = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
    ds = SherpaDataset(X=x.reshape(1, -1), feature_axis=SpectralAxis(values=x, units="cm-1"))
    node = DerivativeNode(
        node_id="deriv_nonuniform",
        parameters={"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
    )

    with pytest.raises(ValueError, match="evenly spaced"):
        await node.execute(input_data=ds)


@pytest.mark.asyncio
async def test_hca_accepts_ui_metric_aliases():
    from spectra_sherpa.app.services.dag.nodes.modeling.clustering_nodes import HCANode

    X = SherpaDataset(X=np.array([[0.0, 0.0], [0.0, 1.0], [5.0, 5.0], [5.0, 6.0]]))
    node = HCANode(node_id="hca_manhattan", parameters={"n_clusters": 2, "linkage": "average", "metric": "manhattan"})

    result = await node.execute(input_data=X)

    assert len(result.outputs["labels"]) == 4


def test_percent_transmittance_conversion_uses_declared_units_not_magnitude():
    from spectra_sherpa.app.lib.spectral.conversions import transmittance_to_absorbance

    ds = SherpaDataset(X=np.array([[0.8, 80.0]]), units="%T")
    ds.meta["reference_applied"] = True

    result = transmittance_to_absorbance(ds)

    np.testing.assert_allclose(result.X, -np.log10(np.array([[0.008, 0.8]])))
    assert result.units == "absorbance"


def test_fractional_transmittance_rejects_percent_scaled_values_without_declared_percent_units():
    from spectra_sherpa.app.lib.spectral.conversions import transmittance_to_absorbance

    ds = SherpaDataset(X=np.array([[80.0]]), units="transmittance")
    ds.meta["reference_applied"] = True

    with pytest.raises(ValueError, match="fractional values"):
        transmittance_to_absorbance(ds)


def test_transmittance_conversion_refuses_display_label_without_ratio_units():
    from spectra_sherpa.app.lib.spectral.conversions import transmittance_to_absorbance

    ds = SherpaDataset(X=np.array([[0.8]]), units=None)
    ds.domain.data_quantity = "Transmittance"
    ds.meta["reference_applied"] = True

    with pytest.raises(ValueError, match="requires explicit percent or fractional ratio units"):
        transmittance_to_absorbance(ds)


def test_unknown_units_are_not_relabelled_as_absorbance():
    from spectra_sherpa.app.lib.spectral.conversions import ensure_absorbance

    ds = SherpaDataset(X=np.array([[10.0, 12.0]]), units="counts")

    with pytest.raises(ValueError, match="Cannot auto-convert"):
        ensure_absorbance(ds)


def test_matrix_csv_leaves_unknown_numeric_axis_blank(tmp_path):
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa

    path = tmp_path / "generic_sensor_export.csv"
    path.write_text("sample,100,200,300\nA,1,2,3\nB,4,5,6\n", encoding="utf-8")

    ds = load_csv_as_sherpa(path)

    assert ds.feature_axis.title is None
    assert ds.feature_axis.units is None


def test_matrix_csv_does_not_infer_axis_from_filename(tmp_path):
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa

    path = tmp_path / "diesel_nir.csv"
    path.write_text("sample,900,1000,1100\nA,1,2,3\nB,4,5,6\n", encoding="utf-8")

    ds = load_csv_as_sherpa(path)

    assert ds.feature_axis.title is None
    assert ds.feature_axis.units is None
