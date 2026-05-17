# SherpaDataset API Reference

`SherpaDataset` is the core data container for SpectraSherpa workflows. It stores measurement data along with rich metadata including axis information, provenance tracking, quality metrics, and domain context.

## Overview

`SherpaDataset` is designed for:
- **Multi-domain analytics**: Supports spectroscopy, chromatography, mass spectrometry, electrochemistry, and more
- **Metadata preservation**: Axes, units, provenance, and quality metrics propagate through workflows
- **AI-friendliness**: Structured metadata for LLM exploration and MCP tools
- **Type safety**: Pydantic validation for all fields

### Preferred Access Pattern

For new code and plugins, use one idiomatic path:

- Data array: `dataset.data`
- Feature axis: `dataset.feature_axis`
- Sample axis: `dataset.sample_axis` (for sample-based datasets)
- Metadata dict: `dataset.meta`

Compatibility accessors (`X`, `get_observation_axis()`, `axis()`, `set_extra()/get_extra()`) are still supported and documented for advanced or legacy workflows.

## Importing

```python
from spectra_sherpa.sdk import SherpaDataset, SpectralAxis, TimeAxis, MZAxis, SampleAxis
```

---

## Constructor

```python
SherpaDataset(
    X: np.ndarray,                           # Data matrix (nD float64; dim 0=samples, dim -1=features)
    feature_axis: FeatureAxis = None,        # Spectral, Time, MZ, Potential, etc.
    sample_axis: SampleAxis = None,          # Sample metadata
    axes: dict[int, AxisInfo] = None,        # Inner dimension axes (e.g., {1: TimeAxis(...)})
    target: np.ndarray = None,               # Target values for modeling
    target_context: TargetContext = None,     # Target metadata
    domain: DomainContext = None,             # Analytical technique info
    provenance: Provenance = None,            # Processing history
    quality: QualityMetrics = None,           # Quality assessment
    backend: str = "numpy",                  # Origin ("numpy", "scp", "sklearn")
    title: str = None,                       # Dataset title
    units: str = None,                       # Data units
    extra: dict = None                       # Additional metadata
)
```

### Parameters

- **X**: nD numpy array containing measurement data. Dimension 0 is always samples, dimension -1 is always features. For standard spectroscopy this is (n_samples, n_features); for hyperspectral/time-resolved data additional inner dimensions are supported (e.g., n_samples × n_time × n_wavelengths). 1D input is automatically reshaped to (1, n_features).
- **feature_axis**: Axis for the last dimension (e.g., SpectralAxis, TimeAxis, MZAxis). Must match `X.shape[-1]`.
- **sample_axis**: Axis for the first dimension with per-sample metadata and class labels. Must match `X.shape[0]`.
- **axes**: Dictionary mapping dimension indices to `AxisInfo` objects for inner dimensions (dims 1 through n-2). For example, `{1: TimeAxis(...)}` for a 3D time-resolved dataset. Each axis length must match the corresponding `X.shape[dim]`.
- **target**: 1D array of target values for supervised learning (optional)
- **backend**: Tag indicating data origin ("numpy", "scp", "sklearn")

---

## Core Properties

### Data Access

#### `data`
Returns the raw data matrix as numpy array.

```python
dataset = SherpaDataset(X=np.random.randn(10, 1000))
print(dataset.data.shape)  # (10, 1000)
```

#### `shape`
Tuple of (n_samples, n_features).

```python
print(dataset.shape)  # (10, 1000)
```

#### `backend`
String indicating data origin.

```python
print(dataset.backend)  # "numpy"
```

---

### Axis Access

#### `feature_axis` → `FeatureAxis | None`

**Generic accessor** that returns the feature axis regardless of type (SpectralAxis, TimeAxis, MZAxis, etc.).

```python
# Works with any axis type
feature_ax = dataset.feature_axis

if feature_ax is not None:
    print(f"Axis type: {feature_ax.axis_type}")
    print(f"Range: {feature_ax.range}")
    print(f"Units: {feature_ax.units}")
```

**Use this** when writing domain-agnostic code or when working with multi-domain datasets.

#### `get_observation_axis()` → `AxisInfo | None`

**Generic accessor** for the observation/sample dimension. Returns SampleAxis, TimeAxis, or any other axis type present in the sample dimension.

```python
obs_ax = dataset.get_observation_axis()

from spectra_sherpa.app.lib.axes import TimeAxis, SampleAxis

if isinstance(obs_ax, TimeAxis):
    print("Time-resolved data")
    print(f"Time range: {obs_ax.range}")
elif isinstance(obs_ax, SampleAxis):
    print("Sample-based data")
    print(f"Number of samples: {obs_ax.length}")
```

#### `sample_axis` → `SampleAxis | None`

**Accessor** for SampleAxis (returns None if observation axis is a different type like TimeAxis).

```python
sample_ax = dataset.sample_axis
if sample_ax is not None:
    print(f"Classes: {sample_ax.classes}")
```

#### `axis(dim: int)` → `AxisInfo | None`

**Direct access** to axis by dimension index.

```python
# Access by dimension
feature_ax = dataset.axis(-1)  # Last dimension (columns)
obs_ax = dataset.axis(0)       # First dimension (rows)
```

---

### Dimensionality

`SherpaDataset` supports 2D and n-dimensional data with a fixed layout:

| Dimension | Role | Accessor | Example |
|-----------|------|----------|---------|
| **dim 0** (first) | Samples / observations | `sample_axis`, `get_observation_axis()` | 20 experiments |
| **dim 1..n-2** (middle) | Inner dimensions | `axis(dim)`, `inner_axes` | 100 time points |
| **dim -1** (last) | Features / measurements | `feature_axis` | 1000 wavelengths |

1D input is automatically reshaped to `(1, n_features)`.

#### `ndim`
Number of dimensions.

```python
print(dataset.ndim)  # 2 for standard, 3 for time-resolved, etc.
```

#### `n_samples`
First dimension size: `X.shape[0]`.

#### `n_features`
Last dimension size: `X.shape[-1]`.

#### `inner_shape`
Shape of middle dimensions. Empty tuple `()` for standard 2D data.

```python
# 3D dataset: (20, 100, 1000)
print(dataset.inner_shape)  # (100,)
```

#### `inner_axes` → `dict[int, AxisInfo]`
Axes for inner dimensions only (excludes sample and feature).

```python
for dim, ax in dataset.inner_axes.items():
    print(f"Dim {dim}: {ax.axis_type}, {ax.length} points")
```

#### `dim_role(dim: int)` → `str`
Returns the semantic role of a dimension: `"sample"`, `"feature"`, or `"inner"`.

```python
dataset.dim_role(0)   # "sample"
dataset.dim_role(1)   # "inner"
dataset.dim_role(-1)  # "feature"
```

---

### Metadata

#### `domain` → `DomainContext`

Contains analytical technique and sample information.

```python
print(f"Technique: {dataset.domain.technique}")           # "FTIR", "HPLC", "LC-MS", etc.
print(f"Sample type: {dataset.domain.sample_type}")       # "pharmaceutical", "food", etc.
print(f"Measurement mode: {dataset.domain.measurement_mode}")  # "transmission", "ATR", etc.
print(f"Inferred: {dataset.domain.inferred}")             # Auto-detected domain info
```

#### `provenance` → `Provenance`

Processing history with append-only log of operations.

```python
# Check processing history
for entry in dataset.provenance.history:
    print(f"Operation: {entry.operation}")
    print(f"Timestamp: {entry.timestamp}")
    print(f"Parameters: {entry.parameters}")
    print(f"State effects: {entry.state_effects}")
```

#### `quality` → `QualityMetrics`

Quality assessment and SNR information.

```python
print(f"SNR: {dataset.quality.snr}")
print(f"SNR method: {dataset.quality.snr_method}")

# Check evaluations (e.g., from cross-validation)
for scope, evaluation in dataset.quality.evaluations.items():
    print(f"Scope: {scope}")
    print(f"Metrics: {evaluation.metrics}")
```

#### `target_context` → `TargetContext`

Metadata for target variable (for supervised learning).

```python
if dataset.target is not None:
    print(f"Target type: {dataset.target_context.target_type}")  # "continuous", "categorical"
    print(f"Class names: {dataset.target_context.class_names}")
```

---

## Creating Datasets

### Example 1: Basic Spectroscopy Dataset

```python
import numpy as np
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import SpectralAxis

# Generate data
n_samples = 20
n_wavelengths = 1000
data = np.random.randn(n_samples, n_wavelengths)

# Create spectral axis
wavenumbers = np.linspace(400, 4000, n_wavelengths)
spectral_ax = SpectralAxis(
    values=wavenumbers,
    units="cm-1",
    title="Wavenumber"
)

# Create dataset
dataset = SherpaDataset(
    X=data,
    feature_axis=spectral_ax,
    title="IR Spectra",
    units="absorbance"
)

print(f"Shape: {dataset.shape}")
print(f"Feature axis type: {dataset.feature_axis.axis_type}")
```

### Example 2: HPLC Chromatography

```python
from spectra_sherpa.app.lib.axes import TimeAxis

# HPLC data: 15 samples × 600 time points
retention_times = np.linspace(0, 30, 600)  # 0-30 minutes
hplc_data = np.random.randn(15, 600)

# Create time axis
time_ax = TimeAxis(
    values=retention_times,
    units="min",
    title="Retention Time"
)

# Create dataset
dataset = SherpaDataset(
    X=hplc_data,
    feature_axis=time_ax,  # Use TimeAxis, not SpectralAxis
    title="HPLC Chromatograms",
    units="mAU"
)

print(f"Feature axis: {dataset.feature_axis.axis_type}")  # "time_minutes"
```

### Example 3: Classification Dataset with Sample Metadata

```python
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis

# Data with class assignments
class_assignments = np.array([0, 0, 0, 1, 1, 1, 1, 0, 0, 1])  # Binary classification (0 or 1)
data = np.random.randn(10, 1000)

# Create sample axis with class assignments
sample_ax = SampleAxis(
    classes=class_assignments,  # Full array of assignments (one per sample)
    labels=["P001", "P002", "P003", "P004", "P005", "P006", "P007", "P008", "P009", "P010"],  # Sample IDs
    title="Patient Samples"
)

# Create spectral axis
spectral_ax = SpectralAxis(
    values=np.linspace(400, 4000, 1000),
    units="cm-1"
)

# Create dataset
dataset = SherpaDataset(
    X=data,
    feature_axis=spectral_ax,
    sample_axis=sample_ax,
    title="Tissue Analysis"
)

# Access class assignments
print(f"Class assignments: {dataset.sample_axis.classes}")  # [0, 0, 0, 1, 1, 1, 1, 0, 0, 1]
print(f"Unique classes: {np.unique(dataset.sample_axis.classes)}")  # [0, 1]

# Note: To store class names like ["Healthy", "Diseased"], use target_context or sample_table
from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

dataset_with_names = SherpaDataset(
    X=data,
    feature_axis=spectral_ax,
    sample_axis=sample_ax,
    target=class_assignments,
    target_context=TargetContext(
        target_type="categorical",
        class_names=["Healthy", "Diseased"]
    ),
    title="Tissue Analysis"
)

print(f"Class names: {dataset_with_names.target_context.class_names}")  # ["Healthy", "Diseased"]
```

### Example 4: Regression Dataset with Target Values

```python
# Calibration dataset with concentration targets
concentrations = np.array([0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
spectra = np.random.randn(6, 1000)

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

dataset = SherpaDataset(
    X=spectra,
    feature_axis=SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1"),
    target=concentrations,
    target_context=TargetContext(
        target_type="continuous",
        target_name="Concentration",
        target_units="mg/mL"
    ),
    title="Calibration Set"
)

print(f"Target: {dataset.target}")  # [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
```

### Example 5: Time-Resolved Spectroscopy — Single Experiment (2D)

A single reaction monitored over time. Each row is a time point, not an independent sample.
The observation axis (dim 0) is repurposed as time — there are no separate "samples".

```python
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis

# Single experiment: 100 time points × 1000 wavelengths
reaction_times = np.linspace(0, 3600, 100)  # 0-3600 seconds
wavenumbers = np.linspace(400, 4000, 1000)
data = np.random.randn(100, 1000)

# Create axes
time_ax = TimeAxis(values=reaction_times, units="s", title="Reaction Time")
spectral_ax = SpectralAxis(values=wavenumbers, units="cm-1")

# Create dataset with time in observation dimension
dataset = SherpaDataset(X=data, feature_axis=spectral_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()

print(f"Observation axis: {dataset.get_observation_axis().axis_type}")  # "time_seconds"
print(f"Feature axis: {dataset.feature_axis.axis_type}")  # "wavenumber"
```

### Example 6: Time-Resolved Spectroscopy — Multiple Experiments (3D)

Multiple experiments, each with time-resolved spectra. This requires a 3D array
with an inner time dimension between samples and features.

```python
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis, SampleAxis

# 20 experiments × 100 time points × 1000 wavelengths
data = np.random.randn(20, 100, 1000)

sample_ax = SampleAxis(labels=[f"run_{i}" for i in range(20)])
time_ax = TimeAxis(values=np.linspace(0, 3600, 100), units="s", title="Reaction Time")
spectral_ax = SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1")

dataset = SherpaDataset(
    X=data,
    feature_axis=spectral_ax,
    sample_axis=sample_ax,
    axes={1: time_ax},          # inner dimension
)

print(f"Shape: {dataset.shape}")            # (20, 100, 1000)
print(f"Inner shape: {dataset.inner_shape}")  # (100,)
print(f"Sample axis: {dataset.sample_axis.labels[:3]}")  # ['run_0', 'run_1', 'run_2']
print(f"Time axis: {dataset.axis(1).axis_type}")          # "time_seconds"
print(f"Feature axis: {dataset.feature_axis.axis_type}")  # "wavenumber"
```

---

## Working with Provenance

Provenance tracks the processing history automatically.

```python
# Check if dataset has been baseline corrected
has_baseline = any(
    "baseline_corrected" in entry.state_effects
    for entry in dataset.provenance.history
)

# Add manual provenance entry (use append with keyword arguments)
dataset.provenance.append(
    op_id="manual_outlier_removal",
    parameters={"indices": [2, 7]},
    state_effects=["outliers_removed"]
)

# Access provenance history
for entry in dataset.provenance.history:
    print(f"Operation: {entry.op_id}")
    print(f"Parameters: {entry.parameters}")
    print(f"Timestamp: {entry.timestamp}")
    print(f"State effects: {entry.state_effects}")

# Export provenance
provenance_dict = dataset.provenance.to_dict()
```

---

## Working with Quality Metrics

```python
from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult

# Check SNR
if dataset.quality.snr is not None:
    print(f"Signal-to-noise ratio: {dataset.quality.snr:.2f}")

# Add evaluation results (e.g., from PCA)
pca_evaluation = EvaluationResult(
    evaluation_id="pca_scores",
    model_type="PCA",
    n_components=3,
    r2=0.85  # Explained variance as R²
)
dataset.quality.add_evaluation(pca_evaluation)

# Add cross-validation results
cv_evaluation = EvaluationResult(
    evaluation_id="cross_validation",
    model_type="LDA",
    fold=1,
    accuracy=0.92
)
dataset.quality.add_evaluation(cv_evaluation)

# Access evaluations (list of EvaluationResult)
for eval_result in dataset.quality.evaluations:
    print(f"Evaluation: {eval_result.evaluation_id}")
    print(f"Model: {eval_result.model_type}")
    if eval_result.r2 is not None:
        print(f"R²: {eval_result.r2:.3f}")
    if eval_result.accuracy is not None:
        print(f"Accuracy: {eval_result.accuracy:.3f}")

# Get latest evaluation
latest = dataset.quality.latest
if latest:
    print(f"Latest evaluation: {latest.evaluation_id}")
    print(f"Model type: {latest.model_type}")

# Get specific evaluation by ID (convenience method - NEW!)
pca_eval = dataset.quality.get_evaluation("pca_scores")
if pca_eval:
    print(f"PCA R²: {pca_eval.r2}")
    print(f"Components: {pca_eval.n_components}")

# Alternative: manual search through evaluations list (old way)
pca_evals = [e for e in dataset.quality.evaluations if e.evaluation_id == "pca_scores"]
if pca_evals:
    print(f"PCA R²: {pca_evals[0].r2}")
```

---

## Serialization

### to_dict() / from_dict()

```python
# Serialize to dictionary
data_dict = dataset.to_dict()

# Restore from dictionary
restored = SherpaDataset.from_dict(data_dict)

# Save to JSON (with NaN handling)
import json
with open("dataset.json", "w") as f:
    json.dump(data_dict, f)
```

---

## Slicing & Indexing

Slicing a `SherpaDataset` returns a **new** `SherpaDataset` with axes, provenance, domain, and quality preserved. Scalar integer indices are converted to length-1 slices so the result always has the same `ndim` as the original.

### Sample selection (dim 0)

```python
# Boolean mask
mask = np.array([True, False, True, ...])
subset = dataset[mask]              # keeps only True samples

# Single sample (stays nD — dim 0 becomes length 1)
one = dataset[5]                    # shape: (1, ..., n_features)

# Slice
first_ten = dataset[0:10]
every_other = dataset[::2]

# Fancy index
picked = dataset[[0, 3, 7]]
```

### Feature selection (dim -1)

For **2D** data, use two-element indexing:

```python
region = dataset[:, 200:800]        # shape: (n_samples, 600)
```

For **nD** data, a two-element tuple is treated as `(sample_key, feature_key)` shorthand — inner dimensions pass through unchanged:

```python
# 3D dataset: (20, 100, 1000)
region = dataset[:, 200:800]        # shape: (20, 100, 600)
```

### Full nD indexing

When the tuple length equals `ndim`, every dimension is sliced independently (including inner axes):

```python
# 3D dataset: (20, 100, 1000) — samples × time × wavelengths
subset = dataset[0:5, 10:50, 200:800]   # shape: (5, 40, 600)
```

Inner axes are sliced along with the data:

```python
# The time axis on the result only contains time points 10–49
print(subset.axis(1).length)  # 40
```

---

## Region Selection by Physical Values

One of the main benefits of `SherpaDataset` over plain numpy arrays: you can slice by **physical values** (wavenumbers, seconds, m/z) instead of integer indices.

All `FeatureAxis` subclasses (`SpectralAxis`, `TimeAxis`, `MZAxis`, `PotentialAxis`, `FrequencyAxis`) provide:

- **`select_region(start, end)`** → `np.ndarray[bool]` — boolean mask for values within [start, end] (inclusive, order-independent)
- **`get_region_indices(start, end)`** → `np.ndarray[int]` — integer indices instead of a mask

These work regardless of sampling resolution, spacing uniformity, or axis ordering.

### Feature axis (dim -1)

```python
spectral_ax = dataset.feature_axis

# Select the C-H stretch region by wavenumber
mask = spectral_ax.select_region(2800, 3000)   # boolean mask over wavelengths

# 2D: slice features directly
ch_region = dataset[:, mask]                    # shape: (n_samples, n_selected)

# 3D: two-element shorthand — inner dims pass through
ch_region = dataset[:, mask]                    # shape: (n_samples, n_time, n_selected)
```

### Inner axis (e.g., time at dim 1)

```python
time_ax = dataset.axis(1)                       # TimeAxis on inner dimension

# Select 10–20 minute window
time_mask = time_ax.select_region(600, 1200)    # 600–1200 seconds
```

### Combining both axes

Use full nD indexing (tuple length == `ndim`) to slice by physical range on multiple axes simultaneously:

```python
# 3D dataset: (20 samples, 100 time points, 1000 wavelengths)
spectral_ax = dataset.feature_axis
time_ax = dataset.axis(1)

spectral_mask = spectral_ax.select_region(1000, 2000)  # 1000–2000 cm⁻¹
time_mask = time_ax.select_region(600, 1200)            # 600–1200 seconds

# Slice both at once — all samples, time window, spectral window
subset = dataset[:, time_mask, spectral_mask]
# shape: (20, n_time_selected, n_spectral_selected)

# The axes on the result are trimmed automatically
print(subset.feature_axis.range)   # (1000.x, 2000.x)
print(subset.axis(1).range)              # (600.x, 1200.x)
```

---

## Computing Statistics

`SherpaDataset` stores data as a numpy array accessible via `.data` (or `.X`). Use standard numpy operations for statistics — axis indices follow the same layout as the dataset dimensions.

### 2D data: (n_samples, n_features)

```python
# Mean spectrum across all samples
mean_spectrum = dataset.data.mean(axis=0)           # shape: (n_features,)

# Per-sample total intensity
total_per_sample = dataset.data.sum(axis=-1)        # shape: (n_samples,)

# Standard deviation across samples at each feature
std_spectrum = dataset.data.std(axis=0)             # shape: (n_features,)
```

### 3D data: (n_samples, n_time, n_features)

```python
# Mean spectrum per sample (average over time)
mean_over_time = dataset.data.mean(axis=1)          # shape: (n_samples, n_features)

# Time profile per sample (average over wavelengths)
time_profiles = dataset.data.mean(axis=-1)          # shape: (n_samples, n_time)

# Global mean spectrum (average over both samples and time)
global_mean = dataset.data.mean(axis=(0, 1))        # shape: (n_features,)

# Variance across samples at each (time, wavelength) pair
sample_var = dataset.data.var(axis=0)               # shape: (n_time, n_features)
```

### Using axis values as coordinates

Axis metadata provides the physical x-values for plotting and analysis:

```python
feature_ax = dataset.feature_axis

# Plot mean spectrum with physical x-axis
import matplotlib.pyplot as plt
plt.plot(feature_ax.values, dataset.data.mean(axis=0))
plt.xlabel(f"{feature_ax.title} ({feature_ax.units})")
plt.ylabel(dataset.units or "Intensity")
```

### Pandas analogy

| Concept | Pandas | SherpaDataset |
|---------|--------|---------------|
| Raw data | `df.values` | `dataset.data` |
| Column labels | `df.columns` | `dataset.feature_axis.values` |
| Row labels | `df.index` | `dataset.sample_axis` (or `dataset.get_observation_axis()` for non-sample dim-0 axes) |
| Extra dimension | `MultiIndex` | `dataset.axis(1)` (inner axes via `axes=` param) |
| Slice rows | `df.iloc[0:3]` | `dataset[0:3]` |
| Slice columns | `df.iloc[:, 0:3]` | `dataset[:, 0:3]` |
| Stats | `df.mean(axis=0)` | `dataset.data.mean(axis=0)` |
| Physical range | `df.loc[:, 1000:2000]` | `dataset[:, feature_ax.select_region(1000, 2000)]` |

---

## Common Patterns

### Checking Axis Types

```python
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis, MZAxis

feature_ax = dataset.feature_axis

if isinstance(feature_ax, SpectralAxis):
    print("Spectroscopy data")
elif isinstance(feature_ax, TimeAxis):
    print("Chromatography or kinetics data")
elif isinstance(feature_ax, MZAxis):
    print("Mass spectrometry data")
```

### Excluding Outliers

```python
if dataset.sample_axis is not None:
    # Exclude outlier samples
    dataset.sample_axis.exclude([2, 7], reason="High noise")

    # Get included data only
    mask = dataset.sample_axis.include_mask
    clean_data = dataset.data[mask, :]
```

### Domain-Agnostic Code

```python
def process_dataset(dataset: SherpaDataset) -> SherpaDataset:
    """Works with any domain (spectroscopy, chromatography, MS, etc.)"""

    # Preferred accessors
    feature_ax = dataset.feature_axis
    obs_ax = dataset.sample_axis or dataset.get_observation_axis()

    if feature_ax is not None:
        print(f"Feature axis: {feature_ax.axis_type}")
        print(f"Range: {feature_ax.range}")

    if obs_ax is not None:
        print(f"Observation axis type: {type(obs_ax).__name__}")

    # Process data...
    processed_data = dataset.data * 2.0

    # Create output dataset preserving metadata
    from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like
    return build_dataset_like(processed_data, dataset)
```

---

## Advanced: Multi-Domain Datasets

### Single-run hyphenated technique (2D)

For a single LC-MS run, time is the observation axis and m/z is the feature axis:

```python
from spectra_sherpa.app.lib.axes import TimeAxis, MZAxis

# Single LC-MS run: 50 time points × 1000 m/z values
time_values = np.linspace(0, 30, 50)      # Retention time
mz_values = np.linspace(50, 500, 1000)    # m/z range
data = np.random.randn(50, 1000)

time_ax = TimeAxis(values=time_values, units="min", title="Retention Time")
mz_ax = MZAxis(values=mz_values, units="m/z", title="m/z")

dataset = SherpaDataset(X=data, feature_axis=mz_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()

# TimeAxis (rows) × MZAxis (columns)
print(f"Observation: {dataset.get_observation_axis().axis_type}")  # "time_minutes"
print(f"Feature: {dataset.feature_axis.axis_type}")  # "mass_to_charge"
```

### Multiple-run hyphenated technique (3D)

For multiple LC-MS runs, use a 3D array with time as an inner dimension:

```python
from spectra_sherpa.app.lib.axes import TimeAxis, MZAxis, SampleAxis

# 10 LC-MS runs × 50 time points × 1000 m/z values
data = np.random.randn(10, 50, 1000)

sample_ax = SampleAxis(labels=[f"sample_{i}" for i in range(10)])
time_ax = TimeAxis(values=np.linspace(0, 30, 50), units="min", title="Retention Time")
mz_ax = MZAxis(values=np.linspace(50, 500, 1000), units="m/z")

dataset = SherpaDataset(
    X=data,
    feature_axis=mz_ax,
    sample_axis=sample_ax,
    axes={1: time_ax},      # time as inner dimension
)

# Slice by physical values on both axes
time_mask = dataset.axis(1).select_region(5, 15)       # 5–15 min retention window
mz_mask = dataset.feature_axis.select_region(100, 300)  # 100–300 m/z

subset = dataset[:, time_mask, mz_mask]
print(f"Subset shape: {subset.shape}")  # (10, n_time_selected, n_mz_selected)
```

---

## See Also

- [Axis Types API Reference](axes.md) - Details on all axis types
- [Chromatography Example](../examples/11_chromatography.md) - HPLC workflow
- [Mass Spectrometry Example](../examples/12_mass_spectrometry.md) - LC-MS workflow
- [Electrochemistry Example](../examples/13_electrochemistry.md) - CV workflow
- [Architecture Guide](../../dev/architecture.md) - Deep dive into design decisions
