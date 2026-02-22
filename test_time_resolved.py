#!/usr/bin/env python
"""Test time-resolved spectroscopy data (MCR-ALS scenario)."""

import numpy as np

# Import using consistent paths
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis, FeatureAxis


def test_time_resolved_spectroscopy():
    """Test dataset with both time and spectral axes (MCR-ALS input)."""
    print("Testing time-resolved spectroscopy (MCR-ALS scenario)...")

    # Simulate time-resolved spectroscopy data
    # Example: monitoring a chemical reaction over time
    # Shape: (n_time, n_wavelengths)
    n_time = 50  # Time points
    n_wavelengths = 200  # Spectral channels

    # Create synthetic data: mixture of two components changing over time
    time_points = np.linspace(0, 30, n_time)  # 0-30 minutes
    wavelengths = np.linspace(400, 4000, n_wavelengths)  # 400-4000 cm⁻¹

    # Synthetic time-resolved spectra
    X = np.random.rand(n_time, n_wavelengths)

    # Create axes
    time_axis = TimeAxis(values=time_points, units="min", title="Reaction Time")
    spectral_axis = SpectralAxis(values=wavelengths, units="cm-1", title="Wavenumber")

    # CRITICAL: For MCR-ALS data, we need BOTH time and spectral axes
    # Time goes in dimension 0 (observation dimension)
    # Spectral goes in dimension -1 (feature dimension)

    # Create dataset - time axis in the "sample" dimension
    # (This is how MCR-ALS data is structured)
    ds = SherpaDataset(X, feature_axis=spectral_axis)

    # Manually set time axis in dimension 0
    # (We don't use sample_axis= because that expects SampleAxis type)
    time_copy = time_axis.copy()
    time_copy.bind_expected_length(n_time)
    ds._axes[ds._SAMPLE_DIM] = time_copy

    print(f"  Created dataset: shape {ds.shape}")
    print(f"  Time axis: {ds.axis(0).__class__.__name__} with {len(ds.axis(0).values)} points")
    print(f"  Spectral axis: {ds.axis(-1).__class__.__name__} with {len(ds.axis(-1).values)} points")

    # Test generic accessors (these should work!)
    obs_axis = ds.get_observation_axis()
    feat_axis = ds.get_feature_axis()

    print(f"  get_observation_axis(): {obs_axis.__class__.__name__}")
    print(f"  get_feature_axis(): {feat_axis.__class__.__name__}")

    assert obs_axis is not None
    assert isinstance(obs_axis, TimeAxis)
    assert obs_axis.axis_type == "time_minutes"

    assert feat_axis is not None
    assert isinstance(feat_axis, SpectralAxis)
    assert feat_axis.axis_type == "wavenumber"

    # Test type-specific accessors (these have limitations!)
    sample_ax = ds.sample_axis  # Returns None (expected - not a SampleAxis)
    spectral_ax = ds.spectral_axis  # Returns SpectralAxis (works!)
    feature_ax = ds.feature_axis  # Returns SpectralAxis (works!)

    print(f"  sample_axis: {sample_ax}")  # None
    print(f"  spectral_axis: {spectral_ax.__class__.__name__ if spectral_ax else None}")  # SpectralAxis
    print(f"  feature_axis: {feature_ax.__class__.__name__ if feature_ax else None}")  # SpectralAxis

    assert sample_ax is None, "sample_axis should be None for time-resolved data"
    assert spectral_ax is not None
    assert feature_ax is not None

    # Test axis() method (generic accessor by dimension)
    dim0_axis = ds.axis(0)
    dim1_axis = ds.axis(-1)

    assert dim0_axis is not None
    assert isinstance(dim0_axis, TimeAxis)
    assert dim1_axis is not None
    assert isinstance(dim1_axis, SpectralAxis)

    print("✓ Time-resolved spectroscopy dataset works!")
    print("✓ Generic accessors (axis(), get_observation_axis(), get_feature_axis()) work correctly")
    print("⚠ Type-specific accessors (sample_axis) return None (expected for time-resolved data)")


def test_mcr_als_workflow_pattern():
    """Test the recommended pattern for MCR-ALS nodes."""
    print("\nTesting MCR-ALS workflow pattern...")

    # Create time-resolved data
    n_time = 50
    n_wavelengths = 200
    X = np.random.rand(n_time, n_wavelengths)

    time_axis = TimeAxis(values=np.linspace(0, 30, n_time), units="min")
    spectral_axis = SpectralAxis(values=np.linspace(400, 4000, n_wavelengths), units="cm-1")

    ds = SherpaDataset(X, feature_axis=spectral_axis)
    time_copy = time_axis.copy()
    time_copy.bind_expected_length(n_time)
    ds._axes[ds._SAMPLE_DIM] = time_copy

    # RECOMMENDED PATTERN for nodes that work with multi-dimensional data:
    # Use generic accessors instead of type-specific ones

    # ❌ OLD PATTERN (breaks with time-resolved data):
    # x_coord = input_ds.spectral_axis  # Works
    # y_coord = input_ds.sample_axis    # Returns None! Breaks!

    # ✅ NEW PATTERN (works with any axis types):
    x_coord = ds.get_feature_axis()  # Works for any FeatureAxis
    y_coord = ds.get_observation_axis()  # Works for any axis type

    print(f"  Feature axis (x_coord): {x_coord.__class__.__name__}")
    print(f"  Observation axis (y_coord): {y_coord.__class__.__name__}")

    assert x_coord is not None
    assert y_coord is not None
    assert isinstance(x_coord, FeatureAxis)
    assert isinstance(y_coord, TimeAxis)

    print("✓ MCR-ALS workflow pattern works with generic accessors")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Time-Resolved Spectroscopy (MCR-ALS Scenario)")
    print("=" * 60)

    try:
        test_time_resolved_spectroscopy()
        test_mcr_als_workflow_pattern()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nKey Findings:")
        print("1. Time-resolved data uses TimeAxis in dimension 0")
        print("2. Generic accessors (axis(), get_observation_axis(), get_feature_axis()) work for all axis types")
        print("3. Type-specific accessors (sample_axis) return None when axis is different type")
        print("4. MCR-ALS nodes should use generic accessors for compatibility")
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
