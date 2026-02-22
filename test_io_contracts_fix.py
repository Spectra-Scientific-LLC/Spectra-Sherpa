#!/usr/bin/env python
"""Test that io_contracts.build_dataset_like preserves new axis types."""

import sys
import numpy as np

# Add src to path
sys.path.insert(0, "./src")

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis, MZAxis, PotentialAxis
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like


def test_build_dataset_like_preserves_time_axis():
    """Test that build_dataset_like preserves TimeAxis through transformations."""
    print("Testing build_dataset_like with TimeAxis...")

    # Create time-resolved spectroscopy data
    n_time = 50
    n_wavelengths = 200
    X = np.random.rand(n_time, n_wavelengths)

    time_axis = TimeAxis(
        values=np.linspace(0, 30, n_time),
        units="min",
        title="Reaction Time"
    )
    spec_axis = SpectralAxis(
        values=np.linspace(400, 4000, n_wavelengths),
        units="cm-1",
        title="Wavenumber"
    )

    # Create source dataset
    source = SherpaDataset(X, feature_axis=spec_axis)
    time_copy = time_axis.copy()
    time_copy.bind_expected_length(n_time)
    source._axes[source._SAMPLE_DIM] = time_copy

    print(f"  Source observation axis: {source.get_observation_axis().__class__.__name__}")
    print(f"  Source feature axis: {source.get_feature_axis().__class__.__name__}")

    # Transform data (simulate preprocessing)
    transformed_data = source.X * 2.0 + 1.0

    # Build new dataset (simulates what preprocessing nodes do)
    result = build_dataset_like(transformed_data, source)

    print(f"  Result observation axis: {result.get_observation_axis().__class__.__name__ if result.get_observation_axis() else 'None'}")
    print(f"  Result feature axis: {result.get_feature_axis().__class__.__name__ if result.get_feature_axis() else 'None'}")

    # Verify axes preserved
    obs_axis = result.get_observation_axis()
    feat_axis = result.get_feature_axis()

    assert obs_axis is not None, "Observation axis was lost!"
    assert isinstance(obs_axis, TimeAxis), f"Expected TimeAxis, got {type(obs_axis)}"
    assert obs_axis.axis_type == "time_minutes"

    assert feat_axis is not None, "Feature axis was lost!"
    assert isinstance(feat_axis, SpectralAxis), f"Expected SpectralAxis, got {type(feat_axis)}"
    assert feat_axis.axis_type == "wavenumber"

    print("✓ TimeAxis preserved through build_dataset_like")


def test_build_dataset_like_preserves_mz_axis():
    """Test that build_dataset_like preserves MZAxis."""
    print("\nTesting build_dataset_like with MZAxis...")

    # Create mass spec data
    n_samples = 10
    n_mz = 100
    X = np.random.rand(n_samples, n_mz)

    mz_axis = MZAxis(
        values=np.linspace(50, 500, n_mz),
        units="m/z",
        title="Mass-to-Charge"
    )

    # Create source dataset
    source = SherpaDataset(X, feature_axis=mz_axis)

    # Transform
    transformed_data = source.X - np.mean(source.X, axis=0)

    # Build new dataset
    result = build_dataset_like(transformed_data, source)

    # Verify MZAxis preserved
    feat_axis = result.get_feature_axis()
    assert feat_axis is not None, "Feature axis was lost!"
    assert isinstance(feat_axis, MZAxis), f"Expected MZAxis, got {type(feat_axis)}"
    assert feat_axis.axis_type == "mass_to_charge"

    print("✓ MZAxis preserved through build_dataset_like")


def test_build_dataset_like_with_shape_change():
    """Test that axes are cleared when shape changes."""
    print("\nTesting build_dataset_like with shape change...")

    # Create source
    n_samples = 50
    n_features = 200
    X = np.random.rand(n_samples, n_features)

    time_axis = TimeAxis(values=np.linspace(0, 30, n_samples), units="min")
    spec_axis = SpectralAxis(values=np.linspace(400, 4000, n_features), units="cm-1")

    source = SherpaDataset(X, feature_axis=spec_axis)
    source._axes[source._SAMPLE_DIM] = time_axis.copy()

    # Transform to DIFFERENT shape (e.g., PCA scores)
    n_components = 5
    transformed_data = np.random.rand(n_samples, n_components)  # Different n_features!

    # Build new dataset
    result = build_dataset_like(transformed_data, source)

    # Observation axis should still be preserved (same n_samples)
    obs_axis = result.get_observation_axis()
    assert obs_axis is not None
    assert isinstance(obs_axis, TimeAxis)

    # Feature axis should be cleared (different n_features)
    feat_axis = result.get_feature_axis()
    assert feat_axis is None, "Feature axis should be cleared when shape changes"

    print("✓ Axes correctly handled when shape changes")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing io_contracts.build_dataset_like with New Axis Types")
    print("=" * 60)

    try:
        test_build_dataset_like_preserves_time_axis()
        test_build_dataset_like_preserves_mz_axis()
        test_build_dataset_like_with_shape_change()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nKey Achievement:")
        print("build_dataset_like() now preserves ANY axis type (TimeAxis, MZAxis, etc.)")
        print("This enables new axis types to propagate through workflows!")
        return 0

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
