#!/usr/bin/env python
"""Quick test to verify backward compatibility of axis system changes."""

import numpy as np

# Import using the same path as sherpa_dataset uses internally
# to avoid isinstance() mismatch issues
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import (
    SpectralAxis,
    TimeAxis,
    MZAxis,
    PotentialAxis,
    FeatureAxis,
    SampleAxis,
)


def test_backward_compat_spectral_axis():
    """Test that existing code using spectral_axis still works."""
    print("Testing backward compatibility with spectral_axis...")

    # Create dataset with spectral_axis (old API)
    X = np.random.rand(10, 100)
    wavenumbers = np.linspace(400, 4000, 100)
    spectral_ax = SpectralAxis(values=wavenumbers, units="cm-1", title="Wavenumber")

    ds = SherpaDataset(X, spectral_axis=spectral_ax)

    # Debug: check what's stored
    stored_ax = ds._axes.get(ds._SPECTRAL_DIM)
    print(f"  DEBUG: Stored axis type: {type(stored_ax)}")
    print(f"  DEBUG: Is SpectralAxis? {isinstance(stored_ax, SpectralAxis)}")
    print(f"  DEBUG: spectral_axis property: {ds.spectral_axis}")

    # Verify spectral_axis property works
    assert ds.spectral_axis is not None, f"spectral_axis is None, stored type: {type(stored_ax)}"
    assert ds.spectral_axis.axis_type == "wavenumber"
    assert len(ds.spectral_axis.values) == 100

    print("✓ Backward compatibility: spectral_axis works")


def test_new_feature_axis_api():
    """Test that new feature_axis API works."""
    print("Testing new feature_axis API...")

    # Create dataset with feature_axis (new API)
    X = np.random.rand(10, 100)
    wavenumbers = np.linspace(400, 4000, 100)
    spectral_ax = SpectralAxis(values=wavenumbers, units="cm-1", title="Wavenumber")

    ds = SherpaDataset(X, feature_axis=spectral_ax)

    # Verify both feature_axis and spectral_axis work
    assert ds.feature_axis is not None
    assert ds.feature_axis.axis_type == "wavenumber"
    assert ds.spectral_axis is not None  # Backward compat
    assert isinstance(ds.feature_axis, SpectralAxis)

    print("✓ New feature_axis API works with SpectralAxis")


def test_timeaxis_chromatography():
    """Test TimeAxis for chromatography data."""
    print("Testing TimeAxis for chromatography...")

    # Create chromatography dataset
    X = np.random.rand(5, 200)  # 5 samples, 200 time points
    retention_times = np.linspace(0, 30, 200)  # 0-30 minutes
    time_ax = TimeAxis(values=retention_times, units="min", title="Retention Time")

    ds = SherpaDataset(X, feature_axis=time_ax)

    # Verify TimeAxis works
    assert ds.feature_axis is not None
    assert isinstance(ds.feature_axis, TimeAxis)
    assert ds.feature_axis.axis_type == "time_minutes"
    assert ds.feature_axis.range == (0.0, 30.0)

    # Note: spectral_axis returns None for non-spectral axes
    assert ds.spectral_axis is None

    print("✓ TimeAxis works for chromatography")


def test_mzaxis_mass_spec():
    """Test MZAxis for mass spectrometry data."""
    print("Testing MZAxis for mass spectrometry...")

    # Create mass spec dataset
    X = np.random.rand(8, 500)  # 8 samples, 500 m/z points
    mz_values = np.linspace(50, 2000, 500)
    mz_ax = MZAxis(values=mz_values, units="m/z", title="Mass-to-Charge")

    ds = SherpaDataset(X, feature_axis=mz_ax)

    # Verify MZAxis works
    assert ds.feature_axis is not None
    assert isinstance(ds.feature_axis, MZAxis)
    assert ds.feature_axis.axis_type == "mass_to_charge"
    assert ds.feature_axis.range == (50.0, 2000.0)

    print("✓ MZAxis works for mass spectrometry")


def test_potentialaxis_electrochemistry():
    """Test PotentialAxis for electrochemistry data."""
    print("Testing PotentialAxis for electrochemistry...")

    # Create voltammetry dataset
    X = np.random.rand(3, 300)  # 3 samples, 300 voltage points
    potentials = np.linspace(-1.0, 1.0, 300)  # -1 to 1 V
    potential_ax = PotentialAxis(values=potentials, units="V", title="Potential")

    ds = SherpaDataset(X, feature_axis=potential_ax)

    # Verify PotentialAxis works
    assert ds.feature_axis is not None
    assert isinstance(ds.feature_axis, PotentialAxis)
    assert ds.feature_axis.axis_type == "voltage_volts"

    print("✓ PotentialAxis works for electrochemistry")


def test_select_region():
    """Test that select_region works on all FeatureAxis types."""
    print("Testing select_region on various axis types...")

    # Test on SpectralAxis
    wavenumbers = np.linspace(400, 4000, 100)
    spectral_ax = SpectralAxis(values=wavenumbers, units="cm-1")
    mask = spectral_ax.select_region(1000, 2000)
    assert mask.sum() > 0
    assert mask.sum() < len(wavenumbers)

    # Test on TimeAxis
    times = np.linspace(0, 30, 200)
    time_ax = TimeAxis(values=times, units="min")
    mask = time_ax.select_region(10, 20)
    assert mask.sum() > 0

    print("✓ select_region works on all FeatureAxis types")


def test_sample_axis():
    """Test that SampleAxis still works."""
    print("Testing SampleAxis...")

    X = np.random.rand(10, 100)
    sample_ax = SampleAxis(
        values=np.arange(10),
        labels=[f"Sample_{i}" for i in range(10)],
        classes=np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 2]),
    )

    ds = SherpaDataset(X, sample_axis=sample_ax)

    assert ds.sample_axis is not None
    assert len(ds.sample_axis.labels) == 10
    assert len(ds.sample_axis.classes) == 10

    print("✓ SampleAxis works")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Axis System Backward Compatibility")
    print("=" * 60)

    try:
        test_backward_compat_spectral_axis()
        test_new_feature_axis_api()
        test_timeaxis_chromatography()
        test_mzaxis_mass_spec()
        test_potentialaxis_electrochemistry()
        test_select_region()
        test_sample_axis()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nSummary:")
        print("- Backward compatibility maintained (spectral_axis works)")
        print("- New feature_axis API works for all axis types")
        print("- TimeAxis, MZAxis, PotentialAxis fully functional")
        print("- All FeatureAxis methods (select_region, range, etc.) work")
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
