from __future__ import annotations

import numpy as np

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step


def test_from_array_builds_sherpa_dataset_with_axes_and_target() -> None:
    X = np.arange(12, dtype=float).reshape(3, 4)
    ds = ss.data.from_array(
        X,
        x=np.array([1000.0, 1100.0, 1200.0, 1300.0]),
        samples=["s1", "s2", "s3"],
        y=np.array([1.0, 2.0, 3.0]),
        y_name="assay",
        target_type="continuous",
        technique="NIR",
        units="cm-1",
        title="NIR calibration",
    )

    assert isinstance(ds, ss.SherpaDataset)
    np.testing.assert_allclose(ds.data, X)
    assert ds.feature_axis is not None
    np.testing.assert_allclose(ds.feature_axis.values, np.array([1000.0, 1100.0, 1200.0, 1300.0]))
    assert ds.feature_axis.units == "cm-1"
    assert ds.sample_axis is not None
    assert ds.sample_axis.labels == ["s1", "s2", "s3"]
    np.testing.assert_allclose(ds.target, np.array([1.0, 2.0, 3.0]))
    assert ds.target_context.target_name == "assay"
    assert ds.target_context.target_type == "continuous"
    assert ds.domain.technique == "NIR"
    assert ds.title == "NIR calibration"


def test_like_preserves_metadata_and_history() -> None:
    ds = ss.data.from_array(
        [[1.0, 2.0], [3.0, 4.0]],
        x=[1000.0, 1001.0],
        samples=["a", "b"],
        y=[0.1, 0.2],
        y_name="assay",
        technique="Raman",
    )
    add_processing_step(ds, "data.source", {"source": "unit"})

    out = ss.data.like(ds, np.zeros((2, 2)), units="corrected")

    assert isinstance(out, ss.SherpaDataset)
    np.testing.assert_allclose(out.data, np.zeros((2, 2)))
    assert out.feature_axis is not None
    np.testing.assert_allclose(out.feature_axis.values, ds.feature_axis.values)
    assert out.sample_axis is not None
    assert out.sample_axis.labels == ["a", "b"]
    np.testing.assert_allclose(out.target, np.array([0.1, 0.2]))
    assert out.target_context.target_name == "assay"
    assert out.domain.technique == "Raman"
    assert out.units == "corrected"
    assert out.provenance[0].op_id == "data.source"


def test_to_numpy_round_trip() -> None:
    ds = ss.data.from_array([[1.0, 2.0]])
    arr = ss.data.to_numpy(ds)
    np.testing.assert_allclose(arr, np.array([[1.0, 2.0]]))
    arr[0, 0] = 99
    assert ds.data[0, 0] == 1.0


def test_read_csv_delegates_to_existing_loader_with_explicit_target(tmp_path) -> None:
    csv_path = tmp_path / "nir.csv"
    csv_path.write_text("sample_id,1000,1001,assay\ns1,1.0,2.0,0.1\ns2,3.0,4.0,0.2\n", encoding="ascii")

    ds = ss.data.read_csv(csv_path, x="wavelength", y="assay", target_type="continuous")

    assert ds.shape == (2, 2)
    assert ds.sample_axis is not None
    assert ds.sample_axis.labels == ["s1", "s2"]
    assert ds.feature_axis is not None
    np.testing.assert_allclose(ds.feature_axis.values, np.array([1000.0, 1001.0]))
    np.testing.assert_allclose(ds.target, np.array([0.1, 0.2]))
    assert ds.target_context.target_name == "assay"
    assert ds.target_context.target_type == "continuous"
