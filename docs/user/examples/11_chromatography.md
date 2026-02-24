# Chromatography Analysis with TimeAxis

This example demonstrates how to analyze chromatography data (HPLC, GC, IC, CE) using `TimeAxis` for retention time measurements.

## Overview

Chromatography data uses **retention time** as the feature axis instead of wavelength/wavenumber. SpectraSherpa's `TimeAxis` provides proper metadata and units for time-based measurements.

## Complete Example: HPLC Analysis

```python
import numpy as np
import matplotlib.pyplot as plt
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import TimeAxis

# ============================================================================
# 1. Generate Synthetic HPLC Data
# ============================================================================

def generate_hplc_peak(time, center, width, height):
    """Generate a Gaussian peak."""
    return height * np.exp(-((time - center) ** 2) / (2 * width ** 2))

# Time axis: 0-30 minutes with 0.05 min resolution
n_timepoints = 600
retention_times = np.linspace(0, 30, n_timepoints)

# Generate 10 HPLC chromatograms with 3 peaks each
n_samples = 10
hplc_data = np.zeros((n_samples, n_timepoints))

# Define peaks (retention time, width, height)
peak_positions = [
    (5.2, 0.3, 1.0),   # Peak 1
    (12.5, 0.4, 1.5),  # Peak 2
    (20.1, 0.5, 0.8)   # Peak 3
]

# Generate chromatograms with slight variations
np.random.seed(42)
for i in range(n_samples):
    for center, width, height in peak_positions:
        # Add random variation to peak parameters
        varied_center = center + np.random.normal(0, 0.1)
        varied_height = height * (1 + np.random.normal(0, 0.1))
        hplc_data[i, :] += generate_hplc_peak(retention_times, varied_center, width, varied_height)

    # Add baseline drift and noise
    baseline = 0.05 * np.sin(retention_times / 5) + 0.1
    noise = np.random.normal(0, 0.02, n_timepoints)
    hplc_data[i, :] += baseline + noise

# ============================================================================
# 2. Create SherpaDataset with TimeAxis
# ============================================================================

time_ax = TimeAxis(
    values=retention_times,
    units="min",
    title="Retention Time"
)

dataset = SherpaDataset(
    X=hplc_data,
    feature_axis=time_ax,  # Use TimeAxis instead of SpectralAxis
    title="HPLC Analysis - Pharmaceutical Samples",
    units="mAU"  # Milli-absorbance units
)

print(f"Dataset shape: {dataset.shape}")
print(f"Feature axis type: {dataset.get_feature_axis().axis_type}")
print(f"Retention time range: {time_ax.range} {time_ax.units}")

# ============================================================================
# 3. Data Exploration
# ============================================================================

# Plot all chromatograms
plt.figure(figsize=(12, 6))
for i in range(n_samples):
    plt.plot(retention_times, hplc_data[i, :], alpha=0.7, label=f"Sample {i+1}")

plt.xlabel(f"{time_ax.title} ({time_ax.units})")
plt.ylabel("Absorbance (mAU)")
plt.title("HPLC Chromatograms - All Samples")
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# Plot mean chromatogram with std
mean_chrom = np.mean(hplc_data, axis=0)
std_chrom = np.std(hplc_data, axis=0)

plt.figure(figsize=(12, 5))
plt.plot(retention_times, mean_chrom, 'b-', linewidth=2, label='Mean')
plt.fill_between(retention_times, mean_chrom - std_chrom, mean_chrom + std_chrom,
                 alpha=0.3, label='±1 SD')
plt.xlabel(f"{time_ax.title} ({time_ax.units})")
plt.ylabel("Absorbance (mAU)")
plt.title("Average HPLC Chromatogram")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 4. Region Selection (Peak Isolation)
# ============================================================================

# Select region around Peak 2 (12-13 min)
peak2_mask = time_ax.select_region(12.0, 13.0)
peak2_data = hplc_data[:, peak2_mask]
peak2_times = retention_times[peak2_mask]

print(f"\\nPeak 2 region:")
print(f"  Time range: {peak2_times[0]:.2f} - {peak2_times[-1]:.2f} min")
print(f"  Data shape: {peak2_data.shape}")
print(f"  Mean peak height: {np.mean(peak2_data.max(axis=1)):.3f} mAU")

# Plot Peak 2 region for all samples
plt.figure(figsize=(10, 5))
for i in range(n_samples):
    plt.plot(peak2_times, peak2_data[i, :], alpha=0.7)

plt.xlabel(f"{time_ax.title} ({time_ax.units})")
plt.ylabel("Absorbance (mAU)")
plt.title("Peak 2 Region (12-13 min) - All Samples")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 5. Preprocessing: Baseline Correction
# ============================================================================

from scipy.signal import savgol_filter

def baseline_als(y, lam=1e5, p=0.01, niter=10):
    """Asymmetric Least Squares baseline correction."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    L = len(y)
    D = sparse.diags([1, -2, 1], [0, -1, -2], shape=(L, L-2))
    w = np.ones(L)

    for i in range(niter):
        W = sparse.spdiags(w, 0, L, L)
        Z = W + lam * D.dot(D.transpose())
        z = spsolve(Z, w * y)
        w = p * (y > z) + (1 - p) * (y < z)

    return z

# Apply baseline correction to all chromatograms
hplc_corrected = np.zeros_like(hplc_data)
for i in range(n_samples):
    baseline = baseline_als(hplc_data[i, :])
    hplc_corrected[i, :] = hplc_data[i, :] - baseline

# Create corrected dataset
dataset_corrected = SherpaDataset(
    X=hplc_corrected,
    feature_axis=time_ax,  # TimeAxis is preserved
    title="HPLC Analysis - Baseline Corrected",
    units="mAU"
)

# Plot before/after
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

ax1.plot(retention_times, hplc_data[0, :], 'b-', label='Original')
ax1.set_ylabel("Absorbance (mAU)")
ax1.set_title("Before Baseline Correction")
ax1.legend()
ax1.grid(True, alpha=0.3)

ax2.plot(retention_times, hplc_corrected[0, :], 'r-', label='Corrected')
ax2.set_xlabel(f"{time_ax.title} ({time_ax.units})")
ax2.set_ylabel("Absorbance (mAU)")
ax2.set_title("After Baseline Correction")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# ============================================================================
# 6. Peak Detection and Integration
# ============================================================================

from scipy.signal import find_peaks

# Detect peaks in mean chromatogram
mean_corrected = np.mean(hplc_corrected, axis=0)
peaks, properties = find_peaks(mean_corrected, height=0.3, distance=50)

print(f"\\nDetected {len(peaks)} peaks:")
for i, peak_idx in enumerate(peaks):
    rt = retention_times[peak_idx]
    height = mean_corrected[peak_idx]
    print(f"  Peak {i+1}: RT = {rt:.2f} min, Height = {height:.3f} mAU")

# Plot detected peaks
plt.figure(figsize=(12, 5))
plt.plot(retention_times, mean_corrected, 'b-', linewidth=2, label='Mean Chromatogram')
plt.plot(retention_times[peaks], mean_corrected[peaks], 'ro', markersize=10, label='Detected Peaks')

for i, peak_idx in enumerate(peaks):
    plt.annotate(f'Peak {i+1}\\n{retention_times[peak_idx]:.1f} min',
                xy=(retention_times[peak_idx], mean_corrected[peak_idx]),
                xytext=(retention_times[peak_idx], mean_corrected[peak_idx] + 0.2),
                ha='center', fontsize=9,
                arrowprops=dict(arrowstyle='->', color='red'))

plt.xlabel(f"{time_ax.title} ({time_ax.units})")
plt.ylabel("Absorbance (mAU)")
plt.title("Peak Detection Results")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# Integrate peaks (Simpson's rule)
from scipy.integrate import simpson

peak_areas = []
for i in range(n_samples):
    sample_areas = []
    for peak_idx in peaks:
        # Define integration window (±0.5 min around peak)
        window_mask = time_ax.select_region(
            retention_times[peak_idx] - 0.5,
            retention_times[peak_idx] + 0.5
        )
        peak_region = hplc_corrected[i, window_mask]
        time_region = retention_times[window_mask]

        # Integrate
        area = simpson(y=peak_region, x=time_region)
        sample_areas.append(area)

    peak_areas.append(sample_areas)

peak_areas = np.array(peak_areas)

print(f"\\nPeak areas (mAU·min):")
print(f"  Mean ± SD for each peak:")
for i in range(len(peaks)):
    mean_area = np.mean(peak_areas[:, i])
    std_area = np.std(peak_areas[:, i])
    rsd = (std_area / mean_area) * 100
    print(f"  Peak {i+1}: {mean_area:.3f} ± {std_area:.3f} (RSD = {rsd:.1f}%)")

# ============================================================================
# 7. Results Summary
# ============================================================================

print(f"\\n{'='*60}")
print("HPLC ANALYSIS SUMMARY")
print(f"{'='*60}")
print(f"Dataset: {dataset_corrected.title}")
print(f"Number of samples: {dataset_corrected.shape[0]}")
print(f"Retention time range: {time_ax.range[0]:.1f} - {time_ax.range[1]:.1f} {time_ax.units}")
print(f"Resolution: {(retention_times[1] - retention_times[0]):.3f} {time_ax.units}")
print(f"Detected peaks: {len(peaks)}")
print(f"\\nPeak Information:")
for i, peak_idx in enumerate(peaks):
    print(f"  Peak {i+1}:")
    print(f"    Retention Time: {retention_times[peak_idx]:.2f} {time_ax.units}")
    print(f"    Mean Height: {mean_corrected[peak_idx]:.3f} mAU")
    print(f"    Mean Area: {np.mean(peak_areas[:, i]):.3f} mAU·min")
    print(f"    RSD: {(np.std(peak_areas[:, i]) / np.mean(peak_areas[:, i]) * 100):.1f}%")

print(f"{'='*60}")
```

## Key Concepts

### 1. TimeAxis for Retention Time

```python
time_ax = TimeAxis(
    values=retention_times,
    units="min",  # Can be "min", "s", "ms", "hr"
    title="Retention Time"
)
```

The `TimeAxis` provides:
- Automatic `axis_type` detection (`"time_minutes"`, `"time_seconds"`, etc.)
- Unit-aware operations
- Proper metadata for visualization

### 2. Region Selection

```python
# Select time window
mask = time_ax.select_region(12.0, 13.0)  # 12-13 minutes
peak_data = chromatogram[mask]
```

This is equivalent to manual masking but more readable and maintains units.

### 3. Metadata Preservation

When processing data through workflows, the `TimeAxis` is automatically preserved:

```python
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like

# Processed data maintains TimeAxis
processed_data = baseline_correction(dataset.data)
output_dataset = build_dataset_like(processed_data, dataset)

# TimeAxis is still there!
assert isinstance(output_dataset.get_feature_axis(), TimeAxis)
```

## Workflow Node Integration

When using SpectraSherpa's workflow builder, nodes automatically handle `TimeAxis`:

- **PlotNode**: X-axis labeled "Retention Time (min)" instead of "Index"
- **SmoothNode**: Savitzky-Golay smoothing works correctly
- **BaselineNode**: ALS baseline correction preserves time axis
- **PeakFindingNode**: Peak detection with retention time output
- **IntegrationNode**: Peak area calculation with time-based windows

## Advanced: Multi-Wavelength HPLC (2D Data)

For DAD (Diode Array Detection) HPLC with multiple wavelengths:

```python
from spectra_sherpa.app.lib.axes import SpectralAxis

# 3D data: samples × time × wavelength
n_samples = 10
n_timepoints = 600
n_wavelengths = 50

time_values = np.linspace(0, 30, n_timepoints)
wavelengths = np.linspace(200, 400, n_wavelengths)  # UV range

# SherpaDataset supports nD arrays natively — no reshaping required.
# Shape: (n_samples, n_timepoints, n_wavelengths)
```

## See Also

- [TimeAxis API Reference](../api/axes.md#timeaxis) - Full TimeAxis documentation
- [SherpaDataset API Reference](../api/sherpa_dataset.md) - Core dataset container
- [Mass Spectrometry Example](12_mass_spectrometry.md) - MZAxis tutorial
- [Preprocessing: Baseline Correction](05_preprocessing_baseline.md) - Baseline methods
