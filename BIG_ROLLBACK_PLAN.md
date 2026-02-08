# Big Rollback Plan (BRB): Remove SpectralResult, Return to NDDataset

**Status**: PLANNING
**Created**: 2026-02-05
**Goal**: Remove SpectralResult wrapper entirely and return to NDDataset as the sole data type, with provenance/sample management handled via standardized `meta` dict conventions.

---

## Executive Summary

SpectralResult was designed to add processing history and API serialization on top of NDDataset. However:

1. **NDDataset already provides**: coordinate coupling, unit propagation, slicing with physical units, math operations, plotting
2. **SpectralResult adds overhead**: every node does double-conversion (ensure_spectral_result + ensure_nddataset)
3. **Open-source friction**: Contributors must learn a custom wrapper instead of using SpectroChemPy directly
4. **Real value is at API boundary**: The serialization logic belongs in a single `serialize_for_api()` function, not baked into every node

**Target Architecture**:
```
┌─────────────────────────────────────────────────────────────────┐
│                     CONTRIBUTOR INTERFACE                        │
│  - Work with NDDataset directly                                  │
│  - Use helper functions for sample management                    │
│  - SpectroChemPy methods work unchanged                          │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   meta DICT CONVENTIONS                          │
│  - processing_history: [...]  (provenance)                       │
│  - samples: {include_mask, classes, labels}  (PLS_Toolbox-like)  │
│  - spectral_technique, data_quantity  (auto-detected)            │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API BOUNDARY                                │
│  serialize_for_api(dataset) → JSON for frontend/LLM              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase -1: Cull Existing Redundancy

Before creating new helpers, identify and remove redundancies introduced during the SpectralResult migration. These are patterns that added complexity without proportional value.

### -1.1 Redundancies to Remove

| Redundancy | Location | Issue | Action |
|------------|----------|-------|--------|
| **Double conversion pattern** | All nodes | `ensure_spectral_result()` + `ensure_nddataset()` called on every input | Remove entirely - work with NDDataset directly |
| **ProcessingStep dataclass** | `spectral_result.py` | Redundant wrapper for a simple dict | Replace with plain dict schema |
| **Duplicate detection logic** | `SpectralResult.spectral_technique`, etc. | Detection logic duplicated from what could be standalone functions | Move to `meta_helpers.py` as standalone functions |
| **`_json` output keys** | `modeling.py` | Some nodes had both `scores` and `scores_json` outputs | Remove `*_json` keys - serialize once at API boundary |
| **`apply_to_2d_batch()` over-abstraction** | `preprocessing.py` | Wrapper function when SpectroChemPy methods already handle 2D | Evaluate per-node: many SCP methods work on 2D natively |
| **`wrap_nddataset()` / `unwrap_to_nddataset()`** | `spectral_result.py` | Convenience functions that encourage wrapper usage | Delete with SpectralResult |
| **Dual provenance tracking** | Nodes + SpectralResult | Some nodes added to both `meta` and `processing_history` | Single location: `meta["processing_history"]` |

### -1.2 apply_to_2d_batch() Analysis

**Current pattern** (in preprocessing.py):
```python
def apply_to_2d_batch(input_data, processing_func, **kwargs) -> NDDataset:
    """Apply a function to each row of 2D data."""
    if input_data.ndim == 2 and input_data.shape[0] > 1:
        for i in range(n_spectra):
            spectrum = input_data[i]
            processed = processing_func(spectrum, **kwargs)
            # ... stack results
```

**Problem**: Many SpectroChemPy methods already handle 2D data natively:
- `dataset.basc()` - works on 2D ✓
- `dataset.smooth()` - works on 2D ✓
- `dataset.deriv()` - works on 2D ✓
- `dataset.snv()` - works on 2D ✓

**Action**:
1. Audit which preprocessing methods actually need row-by-row processing
2. For those that don't, call SCP method directly on 2D data
3. Keep `apply_to_2d_batch()` only for truly 1D-only operations (e.g., some custom algorithms)

### -1.3 Simplified Node Pattern After Redundancy Removal

**BEFORE** (over-abstracted):
```python
async def execute(self, input_data) -> SpectralResult:
    input_sr = ensure_spectral_result(input_data)  # REDUNDANT
    input_ds = ensure_nddataset(input_data)        # REDUNDANT

    def apply_baseline(spectrum):
        corrected = spectrum.copy()
        corrected.basc(...)
        return corrected

    result_ds = apply_to_2d_batch(input_ds, apply_baseline)  # UNNECESSARY

    return build_spectral_result(...)  # REDUNDANT
```

**AFTER** (minimal):
```python
async def execute(self, input_data: NDDataset) -> NDDataset:
    result = input_data.copy()
    result.basc(lamb=lam, asymmetry=p)  # SCP handles 2D natively
    add_processing_step(result, "baseline.als", {...})
    return result
```

**Lines of code**: 14 → 4 (71% reduction per node)

### -1.4 Serialization Redundancy

**Current** (in workflows.py):
```python
def serialize_result(obj):
    # Path 1: SpectralResult
    if isinstance(obj, SpectralResult):
        return obj.to_api_json(...)

    # Path 2: NDDataset (convert to SpectralResult first!)
    if isinstance(obj, NDDataset):
        sr = SpectralResult.from_nddataset(obj)  # REDUNDANT CONVERSION
        return sr.to_api_json(...)

    # Path 3: Dict with nested SpectralResult/NDDataset
    if isinstance(obj, dict):
        # ... recursively handle
```

**After**:
```python
def serialize_result(obj):
    # Single path for NDDataset
    if isinstance(obj, NDDataset):
        return serialize_for_api(obj)

    # ... other types
```

---

## Phase 0: Create New Helpers (BEFORE any rollback)

### 0.1 Replace compat.py with meta_helpers.py

**File**: `backend/app/services/dag/meta_helpers.py`

```python
"""
Meta dict conventions for NDDataset provenance and sample management.

This module standardizes how we store provenance and sample metadata in
NDDataset.meta, enabling PLS_Toolbox-like functionality without a wrapper class.

Meta Dict Schema:
    processing_history: List[Dict]  # Provenance chain
    samples: Dict                    # Sample management (classes, include/exclude)
    spectral_technique: str          # Auto-detected ("IR", "NIR", "Raman", "UV-Vis")
    data_quantity: str               # Auto-detected ("Absorbance", "Transmittance", etc.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import numpy as np

try:
    from spectrochempy import NDDataset
    HAS_NDDATASET = True
except ImportError:
    NDDataset = None
    HAS_NDDATASET = False


# =============================================================================
# Processing History (Provenance)
# =============================================================================

def add_processing_step(
    dataset: NDDataset,
    operation: str,
    parameters: Dict[str, Any],
    node_id: Optional[str] = None,
    input_shape: Optional[tuple] = None,
) -> None:
    """
    Record a processing step in dataset.meta["processing_history"].

    Mutates the dataset in place. If processing_history doesn't exist, creates it.

    Args:
        dataset: NDDataset to add history to
        operation: Name of the operation (e.g., "baseline.als", "smooth.savgol")
        parameters: Dict of parameters used
        node_id: Optional DAG node ID
        input_shape: Shape before processing (defaults to current shape)

    Example:
        >>> dataset = scp.read("spectrum.spa")
        >>> dataset.basc(lamb=1e5, asymmetry=0.001)
        >>> add_processing_step(dataset, "baseline.als", {"lam": 1e5, "p": 0.001})
    """
    if not hasattr(dataset, 'meta') or dataset.meta is None:
        dataset.meta = {}

    if "processing_history" not in dataset.meta:
        dataset.meta["processing_history"] = []

    step = {
        "operation": operation,
        "parameters": parameters,
        "timestamp": datetime.utcnow().isoformat(),
        "node_id": node_id,
        "input_shape": list(input_shape) if input_shape else list(dataset.shape),
        "output_shape": list(dataset.shape),
    }

    dataset.meta["processing_history"].append(step)


def get_processing_history(dataset: NDDataset) -> List[Dict[str, Any]]:
    """
    Get processing history from dataset.meta.

    Returns:
        List of processing step dicts, or empty list if none
    """
    if not hasattr(dataset, 'meta') or not dataset.meta:
        return []
    return dataset.meta.get("processing_history", [])


def clear_processing_history(dataset: NDDataset) -> None:
    """Clear processing history (useful for creating derived datasets)."""
    if hasattr(dataset, 'meta') and dataset.meta:
        dataset.meta["processing_history"] = []


# =============================================================================
# Sample Management (PLS_Toolbox-like Include/Exclude + Classes)
# =============================================================================

def ensure_samples_meta(dataset: NDDataset) -> Dict[str, Any]:
    """
    Ensure dataset.meta["samples"] exists with proper structure.

    Structure:
        samples:
            include_mask: np.ndarray[bool]  # True = included, False = excluded
            classes: np.ndarray[str|int]    # Class labels per sample
            labels: List[str]               # Sample names/identifiers
    """
    if not hasattr(dataset, 'meta') or dataset.meta is None:
        dataset.meta = {}

    if "samples" not in dataset.meta:
        n_samples = dataset.shape[0] if dataset.ndim == 2 else 1
        dataset.meta["samples"] = {
            "include_mask": np.ones(n_samples, dtype=bool),
            "classes": np.array([""] * n_samples, dtype=object),
            "labels": [f"Sample_{i+1}" for i in range(n_samples)],
        }

    return dataset.meta["samples"]


def exclude_samples(
    dataset: NDDataset,
    indices: Union[int, List[int], np.ndarray],
    reason: Optional[str] = None,
) -> None:
    """
    Mark samples as excluded (soft delete, keeps data but sets include_mask=False).

    This is the PLS_Toolbox approach: data is never deleted, just flagged.
    Use get_included_data() to get only included samples.

    Args:
        dataset: NDDataset with 2D data
        indices: Sample index(es) to exclude
        reason: Optional reason for exclusion (stored in meta)

    Example:
        >>> exclude_samples(dataset, [0, 5, 10], reason="Outliers from PCA")
        >>> included = get_included_data(dataset)  # Returns data without excluded
    """
    samples = ensure_samples_meta(dataset)

    if isinstance(indices, int):
        indices = [indices]
    indices = np.asarray(indices)

    samples["include_mask"][indices] = False

    # Track exclusion reasons
    if reason:
        if "exclusion_reasons" not in samples:
            samples["exclusion_reasons"] = {}
        for idx in indices:
            samples["exclusion_reasons"][int(idx)] = reason


def include_samples(
    dataset: NDDataset,
    indices: Union[int, List[int], np.ndarray, None] = None,
) -> None:
    """
    Mark samples as included. If indices=None, includes all samples.

    Args:
        dataset: NDDataset with 2D data
        indices: Sample index(es) to include, or None for all
    """
    samples = ensure_samples_meta(dataset)

    if indices is None:
        samples["include_mask"][:] = True
        samples.pop("exclusion_reasons", None)
    else:
        if isinstance(indices, int):
            indices = [indices]
        indices = np.asarray(indices)
        samples["include_mask"][indices] = True


def get_included_data(dataset: NDDataset) -> NDDataset:
    """
    Return a view/copy of dataset with only included samples.

    This is the workhorse function: preprocessing nodes should call this
    before operations if they want to respect the include/exclude mask.

    Returns:
        NDDataset with only included samples
    """
    if dataset.ndim != 2:
        return dataset  # 1D data has no samples to exclude

    samples = ensure_samples_meta(dataset)
    mask = samples["include_mask"]

    if np.all(mask):
        return dataset  # All included, no copy needed

    return dataset[mask]


def get_include_mask(dataset: NDDataset) -> np.ndarray:
    """Get the include/exclude mask as a boolean array."""
    samples = ensure_samples_meta(dataset)
    return samples["include_mask"].copy()


def set_class(
    dataset: NDDataset,
    indices: Union[int, List[int], np.ndarray],
    class_label: Union[str, int],
) -> None:
    """
    Assign a class label to samples.

    Args:
        dataset: NDDataset with 2D data
        indices: Sample index(es) to assign class to
        class_label: Class label (string or integer)

    Example:
        >>> set_class(dataset, [0, 1, 2], "Control")
        >>> set_class(dataset, [3, 4, 5], "Treatment")
    """
    samples = ensure_samples_meta(dataset)

    if isinstance(indices, int):
        indices = [indices]
    indices = np.asarray(indices)

    samples["classes"][indices] = class_label


def get_classes(dataset: NDDataset) -> np.ndarray:
    """Get array of class labels for all samples."""
    samples = ensure_samples_meta(dataset)
    return samples["classes"].copy()


def filter_by_class(
    dataset: NDDataset,
    class_label: Union[str, int, List[Union[str, int]]],
) -> NDDataset:
    """
    Return dataset filtered to only samples with given class(es).

    Args:
        dataset: NDDataset with 2D data
        class_label: Class label(s) to filter by

    Returns:
        NDDataset with only matching samples
    """
    if dataset.ndim != 2:
        return dataset

    samples = ensure_samples_meta(dataset)
    classes = samples["classes"]

    if isinstance(class_label, (str, int)):
        class_label = [class_label]

    mask = np.isin(classes, class_label)
    return dataset[mask]


def set_sample_labels(dataset: NDDataset, labels: List[str]) -> None:
    """Set sample labels/names."""
    samples = ensure_samples_meta(dataset)
    if len(labels) != dataset.shape[0]:
        raise ValueError(f"Labels length ({len(labels)}) must match n_samples ({dataset.shape[0]})")
    samples["labels"] = list(labels)


def get_sample_labels(dataset: NDDataset) -> List[str]:
    """Get sample labels/names."""
    samples = ensure_samples_meta(dataset)
    return list(samples["labels"])


# =============================================================================
# Spectral Type Detection (moved from SpectralResult)
# =============================================================================

# Patterns for detection
_WAVENUMBER_UNITS = frozenset({"cm-1", "cm^-1", "cm⁻¹", "1/cm", "kayser"})
_WAVELENGTH_NM_UNITS = frozenset({"nm", "nanometer", "nanometers"})
_WAVELENGTH_UM_UNITS = frozenset({"um", "μm", "micron", "microns", "micrometer", "micrometers"})

_ABSORBANCE_PATTERNS = {"absorbance", "abs", "a", "optical density", "od"}
_TRANSMITTANCE_PATTERNS = {"transmittance", "trans", "t", "%t", "% transmittance"}
_REFLECTANCE_PATTERNS = {"reflectance", "refl", "r", "%r", "% reflectance"}


def detect_x_axis_type(dataset: NDDataset) -> Optional[str]:
    """
    Detect X-axis type from units.

    Returns:
        "wavenumber", "wavelength_nm", "wavelength_um", or None
    """
    if not hasattr(dataset, 'x') or dataset.x is None:
        return None

    units = str(dataset.x.units).lower().strip() if hasattr(dataset.x, 'units') else ""

    if units in _WAVENUMBER_UNITS or "cm" in units and "-1" in units:
        return "wavenumber"
    if units in _WAVELENGTH_NM_UNITS:
        return "wavelength_nm"
    if units in _WAVELENGTH_UM_UNITS:
        return "wavelength_um"

    return None


def detect_spectral_technique(dataset: NDDataset) -> Optional[str]:
    """
    Detect spectral technique from X-axis range and units.

    Returns:
        "IR", "NIR", "Raman", "UV-Vis", or None
    """
    if not hasattr(dataset, 'x') or dataset.x is None:
        return None

    # Check title for Raman indicator
    if hasattr(dataset, 'title') and dataset.title and "raman" in str(dataset.title).lower():
        return "Raman"

    axis_type = detect_x_axis_type(dataset)
    if axis_type is None:
        return None

    x_data = np.array(dataset.x.data)
    x_min, x_max = float(np.min(x_data)), float(np.max(x_data))

    if axis_type == "wavenumber":
        if x_min >= 100 and x_max <= 4000:
            # Check for Raman in units
            units_str = str(dataset.units).lower() if hasattr(dataset, 'units') else ""
            if "raman" in units_str or x_min < 400:
                return "Raman"
            return "IR"
        elif x_min >= 4000 and x_max <= 12500:
            return "NIR"
    elif axis_type == "wavelength_nm":
        if x_min >= 200 and x_max <= 800:
            return "UV-Vis"
        elif x_min >= 800 and x_max <= 2500:
            return "NIR"

    return None


def detect_data_quantity(dataset: NDDataset) -> Optional[str]:
    """
    Detect data quantity type from units.

    Returns:
        "Absorbance", "Transmittance", "Reflectance", "Intensity", or None
    """
    if not hasattr(dataset, 'units') or not dataset.units:
        return None

    units_lower = str(dataset.units).lower().strip()

    if units_lower in _ABSORBANCE_PATTERNS or "absorbance" in units_lower:
        return "Absorbance"
    if units_lower in _TRANSMITTANCE_PATTERNS or "transmittance" in units_lower:
        return "Transmittance"
    if units_lower in _REFLECTANCE_PATTERNS or "reflectance" in units_lower:
        return "Reflectance"
    if "intensity" in units_lower or "counts" in units_lower:
        return "Intensity"

    return None


def get_spectral_info(dataset: NDDataset) -> Dict[str, Any]:
    """
    Get comprehensive spectral information for a dataset.

    Returns:
        Dict with technique, data_quantity, x_axis_type, ranges, etc.
    """
    info = {
        "technique": detect_spectral_technique(dataset),
        "data_quantity": detect_data_quantity(dataset),
        "x_axis_type": detect_x_axis_type(dataset),
        "shape": tuple(dataset.shape),
        "n_samples": dataset.shape[0] if dataset.ndim == 2 else 1,
        "n_features": dataset.shape[-1],
    }

    if hasattr(dataset, 'x') and dataset.x is not None:
        x_data = np.array(dataset.x.data)
        info["x_range"] = (float(np.min(x_data)), float(np.max(x_data)))
        info["x_units"] = str(dataset.x.units) if hasattr(dataset.x, 'units') else None

    if hasattr(dataset, 'units'):
        info["data_units"] = str(dataset.units)

    return info
```

### 0.2 Create API Serialization Helper

**File**: `backend/app/services/dag/serialize.py`

```python
"""
Single source of truth for NDDataset → API JSON serialization.

This replaces SpectralResult.to_api_json() with a standalone function.
Called ONLY at API boundary (in routes/workflows.py).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
import numpy as np

try:
    from spectrochempy import NDDataset
    HAS_NDDATASET = True
except ImportError:
    NDDataset = None
    HAS_NDDATASET = False

from .meta_helpers import (
    get_processing_history,
    detect_spectral_technique,
    detect_data_quantity,
    detect_x_axis_type,
    get_spectral_info,
)


def serialize_for_api(
    dataset: NDDataset,
    sanitize_paths: bool = False,
) -> Dict[str, Any]:
    """
    Serialize NDDataset to API-compatible JSON format.

    This is the SINGLE SOURCE OF TRUTH for serialization.
    Called only at API boundary, not inside nodes.

    Args:
        dataset: NDDataset to serialize
        sanitize_paths: If True, strip file paths to basenames

    Returns:
        Dict ready for JSON response
    """
    result = {
        "type": "NDDataset",
        "shape": list(dataset.shape),
        "data": np.asarray(dataset.data).tolist(),
        "n_samples": dataset.shape[0] if dataset.ndim == 2 else 1,
        "n_features": dataset.shape[-1],
        "metadata": {},
    }

    # X-axis
    if hasattr(dataset, 'x') and dataset.x is not None:
        x_data = np.array(dataset.x.data).tolist()
        x_title = str(dataset.x.title) if hasattr(dataset.x, 'title') and dataset.x.title else "Feature"
        x_units = str(dataset.x.units) if hasattr(dataset.x, 'units') and str(dataset.x.units) != "dimensionless" else ""

        result["x_axis"] = {
            "title": x_title,
            "units": x_units,
            "data": x_data,
        }
        result["metadata"]["wavenumbers"] = x_data
        result["metadata"]["x_title"] = x_title
        result["metadata"]["x_units"] = x_units

    # Spectral detection
    technique = detect_spectral_technique(dataset)
    data_quantity = detect_data_quantity(dataset)
    is_spectra = technique is not None

    result["metadata"]["data_type"] = "spectra" if is_spectra else "generic"
    result["metadata"]["is_spectra"] = is_spectra
    result["metadata"]["spectral_technique"] = technique
    result["metadata"]["data_quantity"] = data_quantity

    # Y-axis (sample labels)
    if hasattr(dataset, 'y') and dataset.y is not None:
        y_title = str(dataset.y.title) if hasattr(dataset.y, 'title') else "Sample"
        result["y_axis"] = {
            "title": y_title,
            "units": "",
            "data": np.array(dataset.y.data).tolist(),
        }

    # Data units
    if hasattr(dataset, 'units') and dataset.units:
        result["metadata"]["value_units"] = str(dataset.units)

    # Processing history from meta
    history = get_processing_history(dataset)
    if history:
        result["metadata"]["processing_history"] = history
        result["metadata"]["provenance"] = {
            "operations": [step.get("operation", "unknown") for step in history],
            "last_modified": history[-1].get("timestamp") if history else None,
        }

    # Include all other meta fields
    if hasattr(dataset, 'meta') and dataset.meta:
        PATH_FIELDS = {"original_file_path", "original_source", "background_file"}

        for key, value in dataset.meta.items():
            if key in ("processing_history", "samples"):
                continue  # Already handled or internal
            if sanitize_paths and key in PATH_FIELDS and isinstance(value, str):
                value = os.path.basename(value)
            if key not in result["metadata"]:
                result["metadata"][key] = value

    # Title
    result["title"] = str(dataset.title) if hasattr(dataset, 'title') and dataset.title else (
        "Spectra" if is_spectra else "Data"
    )

    return result
```

---

## Phase 1: Rollback Node Files

### 1.1 Rollback Pattern

**BEFORE** (current SpectralResult pattern):
```python
from app.models.spectral_result import SpectralResult
from app.services.dag.compat import ensure_spectral_result, ensure_nddataset, build_spectral_result

async def execute(self, input_data) -> SpectralResult:
    input_sr = ensure_spectral_result(input_data)
    input_ds = ensure_nddataset(input_data)

    # ... process ...

    return build_spectral_result(
        values=np.array(result_ds.data),
        source=input_sr,
        operation="baseline.als",
        parameters={"lam": lam, "p": p},
        node_id=self.node_id,
        input_shape=input_ds.shape,
    )
```

**AFTER** (NDDataset-only pattern):
```python
from app.services.dag.meta_helpers import add_processing_step

async def execute(self, input_data: NDDataset) -> NDDataset:
    # Process directly (make copy to preserve input)
    result = input_data.copy()
    result.basc(lamb=lam, asymmetry=p)

    # Record provenance
    add_processing_step(result, "baseline.als", {"lam": lam, "p": p}, node_id=self.node_id)

    return result
```

### 1.2 Files to Modify (in order)

| File | Node Count | Notes |
|------|------------|-------|
| `preprocessing.py` | 19 nodes | Highest priority - most nodes |
| `data.py` | 6 nodes | Data source nodes |
| `blend.py` | 3 nodes | Merge/concatenate nodes |
| `custom.py` | 8 nodes | Custom Python, NBS ratio, etc. |
| `time_series.py` | 2 nodes | Time series analysis |
| `output.py` | 6 nodes | Export/save nodes |
| `modeling.py` | 8+ nodes | PCA, PLS, MCR-ALS, etc. |
| `classification.py` | 3 nodes | Classification nodes |
| `diagnostics.py` | 2 nodes | Diagnostic nodes |

### 1.3 Detailed Changes for preprocessing.py

Each preprocessing node needs:

1. Remove SpectralResult import
2. Remove compat.py imports
3. Add meta_helpers import
4. Change return type annotation from `SpectralResult` to `NDDataset`
5. Replace `ensure_spectral_result()`/`ensure_nddataset()` with direct processing
6. Replace `build_spectral_result()` with `add_processing_step()`

**Example: BaselineALSNode**

```python
# BEFORE:
async def execute(self, input_data) -> SpectralResult:
    input_sr = ensure_spectral_result(input_data)
    input_ds = ensure_nddataset(input_data)
    lam = self.parameters.get("lam", 1e5)
    p = self.parameters.get("p", 0.001)

    def apply_baseline(spectrum: NDDataset) -> NDDataset:
        corrected = spectrum.copy()
        corrected.basc(lamb=lam, asymmetry=p)
        return corrected

    result_ds = apply_to_2d_batch(input_ds, apply_baseline)

    return build_spectral_result(
        values=np.array(result_ds.data),
        source=input_sr,
        operation="baseline.als",
        parameters={"lam": lam, "p": p},
        node_id=self.node_id,
        input_shape=input_ds.shape,
    )

# AFTER:
async def execute(self, input_data: NDDataset) -> NDDataset:
    lam = self.parameters.get("lam", 1e5)
    p = self.parameters.get("p", 0.001)

    def apply_baseline(spectrum: NDDataset) -> NDDataset:
        corrected = spectrum.copy()
        corrected.basc(lamb=lam, asymmetry=p)
        return corrected

    result = apply_to_2d_batch(input_data, apply_baseline)
    add_processing_step(result, "baseline.als", {"lam": lam, "p": p}, node_id=self.node_id)

    return result
```

---

## Phase 2: Update Executor

### 2.1 executor.py Changes

1. Remove SpectralResult import:
```python
# REMOVE:
try:
    from app.models.spectral_result import SpectralResult
    HAS_SPECTRAL_RESULT = True
except ImportError:
    SpectralResult = None
    HAS_SPECTRAL_RESULT = False
```

2. Simplify `_validate_port_type()` - remove SpectralResult handling

3. Keep NDDataset-only validation

---

## Phase 3: Update API Serialization

### 3.1 workflows.py Changes

Replace current `serialize_result()` function:

```python
# BEFORE (current):
from app.models.spectral_result import SpectralResult

def serialize_result(obj: Any) -> Any:
    if isinstance(obj, SpectralResult):
        return obj.to_api_json(...)
    if HAS_NDDATASET and isinstance(obj, NDDataset):
        spectral_result = SpectralResult.from_nddataset(obj)
        return spectral_result.to_api_json(...)
    # ... rest

# AFTER (new):
from app.services.dag.serialize import serialize_for_api

def serialize_result(obj: Any) -> Any:
    # NDDataset - use standalone serializer
    if HAS_NDDATASET and isinstance(obj, NDDataset):
        return serialize_for_api(obj, sanitize_paths=settings.sanitize_paths)

    # Model objects - placeholder
    if _is_model_object(obj):
        return {"__model_placeholder__": type(obj).__name__, ...}

    # numpy arrays
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # Dicts - recursive
    if isinstance(obj, dict):
        return {k: serialize_result(v) for k, v in obj.items() if k != "_internal"}

    # Lists - recursive
    if isinstance(obj, list):
        return [serialize_result(item) for item in obj]

    # numpy scalars
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()

    return obj
```

---

## Phase 4: Remove SpectralResult

### 4.1 Files to Delete

| File | Reason |
|------|--------|
| `backend/app/models/spectral_result.py` | No longer needed |
| `backend/app/services/dag/compat.py` | Replaced by meta_helpers.py |

### 4.2 Update Imports

Search and remove these imports from all files:
```python
from app.models.spectral_result import SpectralResult, ProcessingStep
from app.services.dag.compat import ensure_spectral_result, ensure_nddataset, build_spectral_result
```

### 4.3 Update __init__.py Files

**backend/app/models/__init__.py**: Remove SpectralResult export if present

**backend/app/services/dag/__init__.py**: No changes needed (already clean)

---

## Phase 5: Update Documentation

### 5.1 CLAUDE.md Changes

Update the "Primary data container" line:
```markdown
# BEFORE:
- Primary data container: `SpectralResult` (`app/models/spectral_result.py`) — wraps SpectroChemPy `NDDataset` with coordinate coupling, processing history (`ProcessingStep`), spectral technique detection, and API serialization (`to_api_json()`)
- Foundation data type: `NDDataset` (SpectroChemPy) — the raw array+coordinates layer inside `SpectralResult`

# AFTER:
- Primary data container: `NDDataset` (SpectroChemPy) — unified format with coordinate coupling, units, and metadata
- Provenance tracking: `meta_helpers.py` — standardized `meta` dict conventions for processing history and sample management
- API serialization: `serialize_for_api()` — single function at API boundary
```

### 5.2 Other Documentation

Check and update:
- `INFORMATION_ARCHITECTURE.md` (if exists)
- `workflow.md` (if exists)
- Any docstrings referencing SpectralResult

---

## Phase 6: Testing

### 6.1 Test Updates

1. Update any tests that import/use SpectralResult
2. Verify processing history is captured in `dataset.meta["processing_history"]`
3. Verify API responses still have same structure
4. Run full workflow execution tests

### 6.2 Verification Checklist

- [ ] All nodes return NDDataset
- [ ] Processing history is in `meta["processing_history"]`
- [ ] API responses maintain same JSON structure
- [ ] Sample management helpers work (include/exclude/classes)
- [ ] Spectral detection works from NDDataset directly
- [ ] No remaining SpectralResult imports

---

## Execution Order

1. **Phase 0**: Create `meta_helpers.py` and `serialize.py` (NEW FILES)
2. **Phase 1**: Rollback nodes one file at a time (preprocessing → data → blend → ...)
3. **Phase 2**: Update executor.py
4. **Phase 3**: Update workflows.py serialize_result()
5. **Phase 4**: Delete SpectralResult and compat.py
6. **Phase 5**: Update documentation
7. **Phase 6**: Run tests

---

## Risk Mitigation

1. **Parallel development**: New helpers (Phase 0) can coexist with old code
2. **Incremental rollback**: One node file at a time, test after each
3. **API contract preserved**: `serialize_for_api()` outputs same JSON structure
4. **No data loss**: Processing history preserved in `meta` dict

---

## Rollback (if needed)

If this rollback causes issues, we can revert to SpectralResult by:
1. Restore `spectral_result.py` from git
2. Restore `compat.py` from git
3. Revert node files to use SpectralResult pattern

Since nothing is released, this is a clean cut with no backwards compatibility concerns.

---

## Complexity Reduction Summary

### Lines of Code Removed

| File | Before | After | Reduction |
|------|--------|-------|-----------|
| `spectral_result.py` | ~1460 lines | 0 (deleted) | **-1460** |
| `compat.py` | ~130 lines | 0 (deleted) | **-130** |
| Node execute() methods | ~14 lines/node × 50 nodes | ~4 lines/node | **-500** |
| `workflows.py` serialize_result() | ~140 lines | ~50 lines | **-90** |
| **Total** | | | **~2180 lines** |

### New Code Added

| File | Lines | Purpose |
|------|-------|---------|
| `meta_helpers.py` | ~200 | Provenance + sample management (reusable) |
| `serialize.py` | ~80 | API serialization (single location) |
| **Total** | **~280** | |

### Net Reduction: **~1900 lines** (87% reduction in wrapper code)

### Conceptual Simplification

| Concept | Before | After |
|---------|--------|-------|
| Data type for nodes | SpectralResult + NDDataset | NDDataset only |
| Conversion functions | 3 (ensure_sr, ensure_ds, build_sr) | 1 (add_processing_step) |
| Serialization paths | 2 (SpectralResult, NDDataset→SpectralResult) | 1 (NDDataset) |
| Provenance locations | 2 (SpectralResult.processing_history, meta) | 1 (meta) |
| Classes to learn | ProcessingStep, SpectralResult, NDDataset | NDDataset only |

### Contributor Experience

**Before**:
> "To add a preprocessing node, import SpectralResult and 3 helper functions, call ensure_spectral_result and ensure_nddataset on input, process with NDDataset, then call build_spectral_result with 7 parameters..."

**After**:
> "To add a preprocessing node, copy the input, call the SpectroChemPy method, and add_processing_step(). Done."
