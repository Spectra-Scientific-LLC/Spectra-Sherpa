# Mass Spectrometry Analysis with MZAxis

This example demonstrates mass spectrometry data analysis using `MZAxis` for mass-to-charge ratio measurements.

## Complete Example: LC-MS Analysis

```python
import numpy as np
import matplotlib.pyplot as plt
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import MZAxis

# ============================================================================
# 1. Generate Synthetic LC-MS Data
# ============================================================================

# m/z axis: 50-500 m/z with 0.5 m/z resolution
n_mz_points = 900
mz_values = np.linspace(50, 500, n_mz_points)

# Generate 15 mass spectra with characteristic peaks
n_samples = 15
ms_data = np.zeros((n_samples, n_mz_points))

def add_peak(spectrum, mz_center, mz_axis, intensity, width=2.0):
    """Add a Gaussian peak to spectrum."""
    peak = intensity * np.exp(-((mz_axis - mz_center) ** 2) / (2 * width ** 2))
    return spectrum + peak

np.random.seed(42)
# Define characteristic peaks (m/z, intensity)
compound_peaks = [
    (78.0, 0.5),    # Fragment 1
    (149.0, 0.8),   # Fragment 2
    (256.0, 1.0),   # Molecular ion
    (372.0, 0.3),   # Adduct
]

for i in range(n_samples):
    for mz, intensity in compound_peaks:
        # Add variation to intensity
        varied_intensity = intensity * (1 + np.random.normal(0, 0.15))
        ms_data[i, :] = add_peak(ms_data[i, :], mz, mz_values, varied_intensity)

    # Add chemical noise
    noise_level = 0.02
    ms_data[i, :] += np.random.exponential(noise_level, n_mz_points)

# ============================================================================
# 2. Create SherpaDataset with MZAxis
# ============================================================================

mz_ax = MZAxis(
    values=mz_values,
    units="m/z",
    title="Mass-to-Charge Ratio"
)

dataset = SherpaDataset(
    X=ms_data,
    feature_axis=mz_ax,  # Use MZAxis instead of SpectralAxis
    title="LC-MS Analysis - Compound Identification",
    units="intensity"
)

print(f"Dataset shape: {dataset.shape}")
print(f"Feature axis type: {dataset.get_feature_axis().axis_type}")
print(f"m/z range: {mz_ax.range}")

# ============================================================================
# 3. Visualization
# ============================================================================

# Plot average mass spectrum
mean_spectrum = np.mean(ms_data, axis=0)
std_spectrum = np.std(ms_data, axis=0)

plt.figure(figsize=(12, 6))
plt.plot(mz_values, mean_spectrum, 'b-', linewidth=1.5, label='Mean Spectrum')
plt.fill_between(mz_values, mean_spectrum - std_spectrum,
                 mean_spectrum + std_spectrum, alpha=0.3, label='±1 SD')

plt.xlabel(f"{mz_ax.title} ({mz_ax.units})")
plt.ylabel("Intensity")
plt.title("Average Mass Spectrum")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 4. Peak Detection and Annotation
# ============================================================================

from scipy.signal import find_peaks

# Detect peaks in average spectrum
peaks, properties = find_peaks(mean_spectrum, height=0.15, distance=20)

print(f"\\nDetected {len(peaks)} peaks:")
peak_info = []
for peak_idx in peaks:
    mz = mz_values[peak_idx]
    intensity = mean_spectrum[peak_idx]
    peak_info.append((mz, intensity))
    print(f"  m/z = {mz:.1f}, Intensity = {intensity:.3f}")

# Plot with annotations
plt.figure(figsize=(14, 6))
plt.plot(mz_values, mean_spectrum, 'b-', linewidth=1.5)

# Mark detected peaks
for mz, intensity in peak_info:
    plt.plot(mz, intensity, 'ro', markersize=8)
    plt.annotate(f'{mz:.0f}',
                xy=(mz, intensity),
                xytext=(mz, intensity + 0.1),
                ha='center', fontsize=9,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

plt.xlabel(f"{mz_ax.title} ({mz_ax.units})")
plt.ylabel("Intensity")
plt.title("Mass Spectrum with Peak Annotation")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 5. Region Selection (Molecular Ion Region)
# ============================================================================

# Focus on molecular ion region (250-260 m/z)
molecular_ion_mask = mz_ax.select_region(250, 260)
molecular_ion_data = ms_data[:, molecular_ion_mask]
molecular_ion_mz = mz_values[molecular_ion_mask]

print(f"\\nMolecular Ion Region (250-260 m/z):")
print(f"  Data shape: {molecular_ion_data.shape}")
print(f"  Max intensity: {np.max(molecular_ion_data):.3f}")

plt.figure(figsize=(10, 5))
for i in range(min(5, n_samples)):  # Plot first 5 samples
    plt.plot(molecular_ion_mz, molecular_ion_data[i, :], alpha=0.7, label=f'Sample {i+1}')

plt.xlabel(f"{mz_ax.title} ({mz_ax.units})")
plt.ylabel("Intensity")
plt.title("Molecular Ion Region - Multiple Samples")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# ============================================================================
# 6. Isotope Pattern Analysis
# ============================================================================

# Calculate isotope ratios around main peak (256 m/z)
main_peak_idx = np.argmin(np.abs(mz_values - 256.0))
isotope_1_idx = np.argmin(np.abs(mz_values - 257.0))  # M+1
isotope_2_idx = np.argmin(np.abs(mz_values - 258.0))  # M+2

main_intensities = ms_data[:, main_peak_idx]
m1_intensities = ms_data[:, isotope_1_idx]
m2_intensities = ms_data[:, isotope_2_idx]

# Calculate ratios
m1_ratio = m1_intensities / main_intensities
m2_ratio = m2_intensities / main_intensities

print(f"\\nIsotope Pattern Analysis (m/z 256):")
print(f"  M+1/M ratio: {np.mean(m1_ratio):.3f} ± {np.std(m1_ratio):.3f}")
print(f"  M+2/M ratio: {np.mean(m2_ratio):.3f} ± {np.std(m2_ratio):.3f}")

# ============================================================================
# 7. Multivariate Analysis (PCA)
# ============================================================================

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# Standardize data
scaler = StandardScaler()
ms_scaled = scaler.fit_transform(ms_data)

# PCA
pca = PCA(n_components=3)
scores = pca.fit_transform(ms_scaled)
loadings = pca.components_

print(f"\\nPCA Results:")
print(f"  Explained variance: {pca.explained_variance_ratio_}")
print(f"  Cumulative variance: {np.cumsum(pca.explained_variance_ratio_)}")

# Plot scores
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

ax1.scatter(scores[:, 0], scores[:, 1], s=100, alpha=0.6, edgecolors='k')
ax1.set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]*100:.1f}%)')
ax1.set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]*100:.1f}%)')
ax1.set_title('PCA Scores Plot')
ax1.grid(True, alpha=0.3)

# Plot loadings for PC1
ax2.plot(mz_values, loadings[0, :], 'b-', linewidth=1.5)
ax2.set_xlabel(f"{mz_ax.title} ({mz_ax.units})")
ax2.set_ylabel('PC1 Loading')
ax2.set_title('PC1 Loadings (Important m/z values)')
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# ============================================================================
# 8. Summary Report
# ============================================================================

print(f"\\n{'='*60}")
print("LC-MS ANALYSIS SUMMARY")
print(f"{'='*60}")
print(f"Dataset: {dataset.title}")
print(f"Number of samples: {dataset.shape[0]}")
print(f"m/z range: {mz_ax.range[0]:.1f} - {mz_ax.range[1]:.1f} {mz_ax.units}")
print(f"Resolution: {(mz_values[1] - mz_values[0]):.2f} {mz_ax.units}")
print(f"Detected peaks: {len(peaks)}")
print(f"\\nMajor Peaks:")
for mz, intensity in sorted(peak_info, key=lambda x: x[1], reverse=True)[:5]:
    print(f"  m/z {mz:.1f}: {intensity:.3f}")
print(f"\\nPCA:")
print(f"  First 3 PCs explain {np.sum(pca.explained_variance_ratio_[:3])*100:.1f}% variance")
print(f"{'='*60}")
```

## Key Concepts

### 1. MZAxis for m/z Values

```python
mz_ax = MZAxis(
    values=mz_values,
    units="m/z",  # Also supports "Da", "amu"
    title="Mass-to-Charge Ratio"
)
```

### 2. Compound Identification

Mass spectrometry is used for:
- Molecular weight determination (molecular ion peak)
- Fragmentation pattern analysis
- Isotope pattern matching
- Quantification via peak area

### 3. Region Selection for Specific m/z

```python
# Select region of interest
mask = mz_ax.select_region(250, 260)
region_data = spectrum[mask]
```

### 4. Workflow Integration

SpectraSherpa nodes automatically handle `MZAxis`:
- **PlotNode**: Labels axis as "m/z" not "Index"
- **SmoothNode**: Smoothing along m/z dimension
- **NMFNode**: Component extraction from mass spec data
- **Peak Detection**: Finds m/z values of interest

## Advanced: LC-MS 2D Data

For LC-MS with both time and m/z dimensions:

```python
from spectra_sherpa.app.lib.axes import TimeAxis, MZAxis

# 2D LC-MS: 50 time points × 900 m/z points
time_values = np.linspace(0, 30, 50)  # Retention time
mz_values = np.linspace(50, 500, 900)  # m/z

time_ax = TimeAxis(values=time_values, units="min")
mz_ax = MZAxis(values=mz_values, units="m/z")

# Create dataset with both axes
lcms_2d = np.random.randn(50, 900)
dataset = SherpaDataset(X=lcms_2d, feature_axis=mz_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()

print(f"Observation axis: {dataset.get_observation_axis().axis_type}")  # time_minutes
print(f"Feature axis: {dataset.get_feature_axis().axis_type}")  # mass_to_charge
```

## See Also

- [MZAxis API Reference](../api/axes.md#mzaxis)
- [SherpaDataset API Reference](../api/sherpa_dataset.md)
- [Chromatography Example](11_chromatography.md) - TimeAxis tutorial
