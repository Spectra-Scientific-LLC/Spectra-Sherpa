from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.axes import AxisInfo, FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset
from spectra_sherpa.app.services.dag.rank_projection import (
    MODE_1_UNFOLDING,
    input_axis_identity,
    project_mode_1_to_2d,
)


def _cube(*, inner_values: tuple[float, ...] = (10.0, 20.0)) -> SherpaDataset:
    values = np.arange(12, dtype=np.float64).reshape(2, 2, 3)
    return SherpaDataset(
        values,
        sample_axis=SampleAxis(labels=["sample-a", "sample-b"]),
        axes={
            1: AxisInfo(
                values=np.asarray(inner_values),
                labels=["row-a", "row-b"],
                include_mask=np.asarray([True, False]),
                title="Image row",
            )
        },
        feature_axis=FeatureAxis(
            values=np.asarray([1000.0, 900.0, 800.0]),
            labels=["1000", "900", "800"],
            include_mask=np.asarray([True, False, True]),
            title="Wavenumber",
            units="cm-1",
        ),
        layout=DatasetLayoutContext(
            source_shape=values.shape,
            mode_roles=("sample", "spatial_y", "spectral_feature"),
        ),
        title="Cube",
    )


def test_mode_1_projection_is_explicit_c_order_and_preserves_masks() -> None:
    source = _cube()
    projected, receipt = project_mode_1_to_2d(source, operation_id="test.mode_1_unfold", node_id="pca-1")

    np.testing.assert_array_equal(projected.X, source.X.reshape(2, 6, order="C"))
    assert receipt.strategy == MODE_1_UNFOLDING
    assert receipt.input_shape == (2, 2, 3)
    assert receipt.output_shape == (2, 6)
    assert receipt.input_axis_identity_sha256 == input_axis_identity(source)
    assert projected.layout.mode_roles == ("sample", "feature")
    assert projected.layout.original_unfolded_shape == (2, 2, 3)
    assert projected.feature_axis is not None
    assert projected.feature_axis.labels == [
        "spatial_y=row-a | spectral_feature=1000",
        "spatial_y=row-a | spectral_feature=900",
        "spatial_y=row-a | spectral_feature=800",
        "spatial_y=row-b | spectral_feature=1000",
        "spatial_y=row-b | spectral_feature=900",
        "spatial_y=row-b | spectral_feature=800",
    ]
    np.testing.assert_array_equal(
        projected.feature_axis.include_mask,
        np.asarray([True, False, True, False, False, False]),
    )
    entry = projected.provenance[-1]
    assert entry.op_id == "test.mode_1_unfold"
    assert entry.node_id == "pca-1"
    assert entry.parameters == {
        "strategy": MODE_1_UNFOLDING,
        "order": "C",
        "input_shape": (2, 2, 3),
        "input_mode_roles": ("sample", "spatial_y", "spectral_feature"),
        "input_axis_identity_sha256": input_axis_identity(source),
    }


def test_input_axis_identity_covers_inner_coordinates_not_measurements() -> None:
    source = _cube()
    changed_measurements = source.with_data(source.X + 100.0)
    changed_inner_axis = _cube(inner_values=(10.0, 21.0))
    fewer_samples = source[:1, :, :]

    assert input_axis_identity(changed_measurements) == input_axis_identity(source)
    assert input_axis_identity(fewer_samples) == input_axis_identity(source)
    assert input_axis_identity(changed_inner_axis) != input_axis_identity(source)


def test_two_dimensional_input_is_not_projected_or_copied() -> None:
    source = SherpaDataset(np.arange(12, dtype=np.float64).reshape(3, 4))

    projected, receipt = project_mode_1_to_2d(source, operation_id="unused")

    assert projected is source
    assert receipt.strategy == "none"
    assert receipt.input_shape == receipt.output_shape == (3, 4)
