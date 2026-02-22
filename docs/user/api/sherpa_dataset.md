# SherpaDataset API Reference

`SherpaDataset` is the core data container for SpectraSherpa workflows. It stores measurement data along with rich metadata including axis information, provenance tracking, quality metrics, and domain context.

## Overview

`SherpaDataset` is designed for:
- **Multi-domain analytics**: Supports spectroscopy, chromatography, mass spectrometry, electrochemistry, and more
- **Metadata preservation**: Axes, units, provenance, and quality metrics propagate through workflows
- **AI-friendliness**: Structured metadata for LLM exploration and MCP tools
- **Type safety**: Pydantic validation for all fields

## Importing

```python
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.axes import SpectralAxis, TimeAxis, MZAxis, SampleAxis
```

---

## Constructor

```python
SherpaDataset(
    X: np.ndarray,                  # Data matrix (2D float64)
    feature_axis: FeatureAxis = None,        # Spectral, Time, MZ, Potential, etc.
    spectral_axis: SpectralAxis = None,     # Alias for feature_axis (backward compat)
    sample_axis: SampleAxis = None,          # Sample metadata
    target: np.ndarray = None,               # Target values for modeling
    target_context: TargetContext = None,    # Target metadata
    domain: DomainContext = None,            # Analytical technique info
    provenance: Provenance = None,           # Processing history
    quality: QualityMetrics = None,          # Quality assessment
    backend: str = "numpy",                  # Origin ("numpy", "scp", "sklearn")
    title: str = None,                       # Dataset title
    units: str = None,                       # Data units
    extra: dict = None                       # Additional metadata
)
```

### Parameters

- **X**: 2D numpy array (n_samples × n_features) containing measurement data
- **feature_axis**: Axis for columns (e.g., SpectralAxis, TimeAxis, MZAxis)
- **spectral_axis**: Backward-compatible alias for feature_axis (spectroscopy workflows)
- **sample_axis**: Axis for rows with per-sample metadata and class labels
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

#### `get_feature_axis()` → `FeatureAxis | None`

**Generic accessor** that returns the feature axis regardless of type (SpectralAxis, TimeAxis, MZAxis, etc.).

```python
# Works with any axis type
feature_ax = dataset.get_feature_axis()

if feature_ax is not None:
    print(f"Axis type: {feature_ax.axis_type}")
    print(f"Range: {feature_ax.range}")
    print(f"Units: {feature_ax.units}")
```

**Use this** when writing domain-agnostic code or when working with multi-domain datasets.

#### `spectral_axis` → `SpectralAxis | None`

**Legacy accessor** for spectroscopy workflows. Returns SpectralAxis if present, None otherwise.

```python
# Backward compatible for spectroscopy
spec_ax = dataset.spectral_axis
if spec_ax is not None:
    wavenumbers = spec_ax.data
```

**Note**: For new code, prefer `get_feature_axis()` for flexibility.

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
    spectral_axis=spectral_ax,  # or feature_axis=spectral_ax
    title="IR Spectra",
    units="absorbance"
)

print(f"Shape: {dataset.shape}")
print(f"Feature axis type: {dataset.get_feature_axis().axis_type}")
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

print(f"Feature axis: {dataset.get_feature_axis().axis_type}")  # "time_minutes"
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
    spectral_axis=spectral_ax,
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
    spectral_axis=spectral_ax,
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
    spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1"),
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

### Example 5: Time-Resolved Spectroscopy (2D)

```python
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis

# Time-resolved data: 100 time points × 1000 wavelengths
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
print(f"Feature axis: {dataset.get_feature_axis().axis_type}")  # "wavenumber"
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

## Common Patterns

### Checking Axis Types

```python
from spectra_sherpa.app.lib.axes import TimeAxis, SpectralAxis, MZAxis

feature_ax = dataset.get_feature_axis()

if isinstance(feature_ax, SpectralAxis):
    print("Spectroscopy data")
elif isinstance(feature_ax, TimeAxis):
    print("Chromatography or kinetics data")
elif isinstance(feature_ax, MZAxis):
    print("Mass spectrometry data")
```

### Region Selection

```python
# Select spectral region
feature_ax = dataset.get_feature_axis()
if feature_ax is not None:
    mask = feature_ax.select_region(2800, 3000)  # C-H stretch region
    ch_region_data = dataset.data[:, mask]
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

    # Use generic accessors
    feature_ax = dataset.get_feature_axis()
    obs_ax = dataset.get_observation_axis()

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

For hyphenated techniques (e.g., LC-MS: time × m/z):

```python
from spectra_sherpa.app.lib.axes import TimeAxis, MZAxis

# LC-MS: 50 time points × 1000 m/z values
time_values = np.linspace(0, 30, 50)      # Retention time
mz_values = np.linspace(50, 500, 1000)    # m/z range
data = np.random.randn(50, 1000)

# Create axes
time_ax = TimeAxis(values=time_values, units="min", title="Retention Time")
mz_ax = MZAxis(values=mz_values, units="m/z", title="m/z")

# Create dataset
dataset = SherpaDataset(X=data, feature_axis=mz_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()

# Now we have: TimeAxis (rows) × MZAxis (columns)
print(f"Observation: {dataset.get_observation_axis().axis_type}")  # "time_minutes"
print(f"Feature: {dataset.get_feature_axis().axis_type}")  # "mass_to_charge"
```

---

## See Also

- [Axis Types API Reference](axes.md) - Details on all axis types
- [Chromatography Example](../examples/11_chromatography.md) - HPLC workflow
- [Mass Spectrometry Example](../examples/12_mass_spectrometry.md) - LC-MS workflow
- [Electrochemistry Example](../examples/13_electrochemistry.md) - CV workflow
- [Architecture Guide](../../dev/architecture.md) - Deep dive into design decisions
