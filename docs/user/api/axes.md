# Axis Types API Reference

SpectraSherpa supports multiple analytical chemistry domains through a typed axis system. Each axis type represents a different kind of measurement dimension with domain-specific metadata and behavior.

## Overview

All axes inherit from `AxisInfo`, with feature-type axes (representing measured variables) inheriting from `FeatureAxis`:

```
AxisInfo (base)
├── FeatureAxis (base for all feature-type axes)
│   ├── SpectralAxis (wavelength/wavenumber)
│   ├── TimeAxis (retention time, elution time, kinetics)
│   ├── MZAxis (mass-to-charge ratio)
│   ├── PotentialAxis (voltage, electrochemistry)
│   └── FrequencyAxis (NMR, dielectric spectroscopy)
└── SampleAxis (observations/rows with metadata)
```

## Importing Axis Types

```python
from spectra_sherpa.app.lib.axes import (
    SpectralAxis,
    TimeAxis,
    MZAxis,
    PotentialAxis,
    FrequencyAxis,
    SampleAxis
)
```

---

## SpectralAxis

For spectroscopic measurements (IR, NIR, Raman, UV-Vis, Fluorescence).

### Constructor

```python
SpectralAxis(
    values: np.ndarray,      # Array of wavelength/wavenumber values
    units: str = "cm-1",     # "cm-1", "cm⁻¹", "nm", "µm", etc.
    title: str = None,       # Human-readable title (optional)
    labels: Any = None       # Optional labels for each value
)
```

### Properties

- **`axis_type`** → `str`: Returns `"wavenumber"`, `"wavelength_nm"`, or `"wavelength_um"` based on units
- **`range`** → `tuple[float, float]`: (min, max) of axis values
- **`length`** → `int`: Number of values
- **`units`** → `str`: Unit string
- **`title`** → `str`: Human-readable title

### Methods

- **`select_region(start, end)`** → `np.ndarray`: Boolean mask for values within [start, end]
- **`copy()`** → `SpectralAxis`: Deep copy of the axis

### Example: IR Spectroscopy

```python
import numpy as np
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

# Create wavenumber axis for IR spectrum
wavenumbers = np.linspace(400, 4000, 1000)
spectral_ax = SpectralAxis(
    values=wavenumbers,
    units="cm-1",
    title="Wavenumber"
)

# Create dataset
data = np.random.randn(10, 1000)  # 10 spectra
dataset = SherpaDataset(X=data, feature_axis=spectral_ax)

# Select region (e.g., C-H stretch region 2800-3000 cm⁻¹)
mask = spectral_ax.select_region(2800, 3000)
ch_region = data[:, mask]

print(f"Axis type: {spectral_ax.axis_type}")  # "wavenumber"
print(f"Range: {spectral_ax.range}")  # (400.0, 4000.0)
```

### Example: UV-Vis Spectroscopy

```python
# Create wavelength axis for UV-Vis spectrum
wavelengths = np.linspace(200, 800, 600)
spectral_ax = SpectralAxis(
    values=wavelengths,
    units="nm",
    title="Wavelength"
)

dataset = SherpaDataset(X=data, feature_axis=spectral_ax)
print(f"Axis type: {spectral_ax.axis_type}")  # "wavelength_nm"
```

---

## TimeAxis

For chromatography, kinetics, and time-resolved measurements.

### Constructor

```python
TimeAxis(
    values: np.ndarray,      # Array of time values
    units: str = "min",      # "min", "s", "ms", "hr"
    title: str = None,       # e.g., "Retention Time", "Reaction Time"
    labels: Any = None
)
```

### Properties

- **`axis_type`** → `str`: Returns `"time_minutes"`, `"time_seconds"`, `"time_milliseconds"`, or `"time_hours"`
- **`range`** → `tuple[float, float]`: (min, max) time values
- **`length`** → `int`: Number of time points
- **`units`** → `str`: Time unit

### Example: HPLC Chromatography

```python
from spectra_sherpa.app.lib.axes import TimeAxis

# Create retention time axis for HPLC
retention_times = np.linspace(0, 30, 600)  # 0-30 minutes
time_ax = TimeAxis(
    values=retention_times,
    units="min",
    title="Retention Time"
)

# HPLC data: 10 samples × 600 time points
hplc_data = np.random.randn(10, 600)
dataset = SherpaDataset(X=hplc_data, feature_axis=time_ax)

# Select peak region (e.g., 12-14 min)
mask = time_ax.select_region(12, 14)
peak_region = hplc_data[:, mask]

print(f"Axis type: {time_ax.axis_type}")  # "time_minutes"
```

### Example: Reaction Kinetics

```python
# Time-resolved spectroscopy: reaction monitoring
reaction_times = np.linspace(0, 3600, 100)  # 0-3600 seconds
time_ax = TimeAxis(
    values=reaction_times,
    units="s",
    title="Reaction Time"
)

# Data: 100 time points × 1000 wavelengths
kinetic_data = np.random.randn(100, 1000)
spectral_ax = SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1")

# TimeAxis goes in observation dimension (rows)
dataset = SherpaDataset(X=kinetic_data, feature_axis=spectral_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()

print(f"Observation axis: {dataset.get_observation_axis().axis_type}")  # "time_seconds"
print(f"Feature axis: {dataset.get_feature_axis().axis_type}")  # "wavenumber"
```

---

## MZAxis

For mass spectrometry (LC-MS, GC-MS, MALDI-TOF, ICP-MS).

### Constructor

```python
MZAxis(
    values: np.ndarray,      # Array of m/z values
    units: str = "m/z",      # "m/z", "Da", "amu"
    title: str = None,       # e.g., "Mass-to-Charge Ratio"
    labels: Any = None
)
```

### Properties

- **`axis_type`** → `str`: Returns `"mass_to_charge"`
- **`range`** → `tuple[float, float]`: (min, max) m/z values
- **`length`** → `int`: Number of m/z points

### Example: LC-MS

```python
from spectra_sherpa.app.lib.axes import MZAxis

# Create m/z axis for LC-MS
mz_values = np.linspace(50, 500, 1000)  # 50-500 m/z
mz_ax = MZAxis(
    values=mz_values,
    units="m/z",
    title="Mass-to-Charge Ratio"
)

# LC-MS data: 20 samples × 1000 m/z points
lcms_data = np.random.randn(20, 1000)
dataset = SherpaDataset(X=lcms_data, feature_axis=mz_ax)

# Select protein mass range (e.g., 400-500 m/z)
mask = mz_ax.select_region(400, 500)
protein_region = lcms_data[:, mask]

print(f"Axis type: {mz_ax.axis_type}")  # "mass_to_charge"
```

---

## PotentialAxis

For electrochemistry (CV, DPV, SWV, LSV, CA, EIS).

### Constructor

```python
PotentialAxis(
    values: np.ndarray,      # Array of voltage values
    units: str = "V",        # "V" (volts), "mV" (millivolts)
    title: str = None,       # e.g., "Potential", "Applied Voltage"
    labels: Any = None
)
```

### Properties

- **`axis_type`** → `str`: Returns `"voltage_volts"` or `"voltage_millivolts"`
- **`range`** → `tuple[float, float]`: (min, max) voltage values
- **`length`** → `int`: Number of voltage points

### Example: Cyclic Voltammetry

```python
from spectra_sherpa.app.lib.axes import PotentialAxis

# Create potential axis for cyclic voltammetry
potentials = np.linspace(-2.0, 2.0, 400)  # -2V to +2V
pot_ax = PotentialAxis(
    values=potentials,
    units="V",
    title="Potential"
)

# CV data: 5 cycles × 400 potential points
cv_data = np.random.randn(5, 400)
dataset = SherpaDataset(X=cv_data, feature_axis=pot_ax)

# Select oxidation peak region (e.g., 0.4-0.6 V)
mask = pot_ax.select_region(0.4, 0.6)
oxidation_peak = cv_data[:, mask]

print(f"Axis type: {pot_ax.axis_type}")  # "voltage_volts"
```

---

## FrequencyAxis

For NMR spectroscopy and dielectric measurements.

### Constructor

```python
FrequencyAxis(
    values: np.ndarray,      # Array of frequency values
    units: str = "MHz",      # "Hz", "MHz", "GHz", "ppm"
    title: str = None,       # e.g., "Frequency", "Chemical Shift"
    labels: Any = None
)
```

### Properties

- **`axis_type`** → `str`: Returns `"frequency_hz"`, `"frequency_mhz"`, `"frequency_ghz"`, or `"chemical_shift"`
- **`range`** → `tuple[float, float]`: (min, max) frequency values

### Example: ¹H NMR

```python
from spectra_sherpa.app.lib.axes import FrequencyAxis

# Create chemical shift axis for NMR
chemical_shifts = np.linspace(0, 12, 2048)  # 0-12 ppm
freq_ax = FrequencyAxis(
    values=chemical_shifts,
    units="ppm",
    title="Chemical Shift"
)

# NMR data: 10 samples × 2048 points
nmr_data = np.random.randn(10, 2048)
dataset = SherpaDataset(X=nmr_data, feature_axis=freq_ax)

print(f"Axis type: {freq_ax.axis_type}")  # "chemical_shift"
```

---

## SampleAxis

For observation/sample dimension with per-sample metadata.

### Constructor

```python
SampleAxis(
    values: np.ndarray = None,     # Optional sample identifiers
    labels: list[str] = None,      # Text labels for samples (optional)
    title: str = None,
    units: str = None,
    classes: np.ndarray = None,    # Class assignments for each sample (e.g., [0, 0, 1, 1])
    include_mask: np.ndarray = None,  # Boolean mask of included samples
    exclusion_reasons: list[str | None] = None,  # Exclusion reason per sample
    sample_table: dict = None      # Additional metadata (concentration, batch, etc.)
)
```

### Properties

- **`length`** → `int`: Number of samples
- **`classes`** → `np.ndarray | None`: Class assignment for each sample (must match length)
- **`n_included`** → `int`: Number of non-excluded samples
- **`include_mask`** → `np.ndarray | None`: Boolean mask of included samples
- **`exclusion_reasons`** → `list[str | None] | None`: List of exclusion reasons (one per sample, None if included)

### Methods

- **`exclude(indices, reason)`**: Exclude samples from analysis
- **`include(indices)`**: Re-include previously excluded samples
- **`get_column(name)`**: Get metadata column from sample_table
- **`set_column(name, values)`**: Set metadata column

### Example: Classification Dataset

```python
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis

# Create sample axis with class assignments
# classes: array of class assignments (one per sample)
sample_ax = SampleAxis(
    classes=np.array([0, 0, 0, 1, 1, 1, 1, 0, 0, 1]),  # Binary class assignments
    labels=["S001", "S002", "S003", "S004", "S005", "S006", "S007", "S008", "S009", "S010"],  # Sample IDs
    title="Samples"
)

# Spectral data: 10 samples × 1000 wavenumbers
data = np.random.randn(10, 1000)
spectral_ax = SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1")

dataset = SherpaDataset(
    X=data,
    feature_axis=spectral_ax,
    sample_axis=sample_ax
)

# Access class information
unique_classes = np.unique(sample_ax.classes)  # [0, 1]
print(f"Class assignments: {sample_ax.classes}")  # [0, 0, 0, 1, 1, 1, 1, 0, 0, 1]

# Exclude outliers
sample_ax.exclude([2, 7], reason="Outlier detected")
print(f"Included samples: {sample_ax.n_included}")  # 8

# Check exclusion reasons (list with None for included samples)
print(f"Sample 2 reason: {sample_ax.exclusion_reasons[2]}")  # "Outlier detected"
print(f"Sample 0 reason: {sample_ax.exclusion_reasons[0]}")  # None
```

### Example: Sample Metadata

```python
# Create sample axis with metadata table
sample_ax = SampleAxis(
    values=np.array(["S001", "S002", "S003", "S004", "S005"]),
    sample_table={
        "concentration": [0.5, 1.0, 1.5, 2.0, 2.5],
        "batch": ["A", "A", "B", "B", "A"],
        "operator": ["John", "Jane", "John", "Jane", "John"]
    }
)

# Access metadata
concentrations = sample_ax.get_column("concentration")
print(concentrations)  # [0.5, 1.0, 1.5, 2.0, 2.5]
```

---

## Common Patterns

### Generic Accessors

Use `dataset.get_feature_axis()` and `dataset.get_observation_axis()` to work with any axis type:

```python
# Works with SpectralAxis, TimeAxis, MZAxis, etc.
feature_ax = dataset.get_feature_axis()

if feature_ax is not None:
    print(f"Feature axis type: {feature_ax.axis_type}")
    print(f"Range: {feature_ax.range}")
    print(f"Units: {feature_ax.units}")
```

### Creating Multi-Domain Datasets

```python
# Time-resolved spectroscopy: TimeAxis (rows) × SpectralAxis (columns)
time_ax = TimeAxis(values=np.linspace(0, 60, 100), units="min")
spec_ax = SpectralAxis(values=np.linspace(400, 4000, 1000), units="cm-1")

data = np.random.randn(100, 1000)
dataset = SherpaDataset(X=data, feature_axis=spec_ax)
dataset._axes[dataset._SAMPLE_DIM] = time_ax.copy()
```

### Accessing Feature Axes

Use the generic `get_feature_axis()` accessor, which works with any axis type:

```python
dataset = SherpaDataset(X=data, feature_axis=spectral_ax)
feature_ax = dataset.get_feature_axis()  # Returns SpectralAxis
print(feature_ax.axis_type)              # "wavenumber"
```

---

## See Also

- [SherpaDataset API Reference](sherpa_dataset.md) - Core dataset container
- [Chromatography Example](../examples/11_chromatography.md) - TimeAxis tutorial
- [Mass Spectrometry Example](../examples/12_mass_spectrometry.md) - MZAxis tutorial
- [Electrochemistry Example](../examples/13_electrochemistry.md) - PotentialAxis tutorial
