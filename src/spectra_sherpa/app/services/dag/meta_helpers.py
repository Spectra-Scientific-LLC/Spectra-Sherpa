"""
Meta dict conventions for SherpaDataset provenance and sample management.

This module standardizes how we store provenance and sample metadata in
dataset.meta, enabling PLS_Toolbox-like functionality without a wrapper class.

Meta Dict Schema:
    processing_history: List[Dict]  # Provenance chain
    samples: Dict                    # Sample management (classes, include/exclude)

Usage in nodes:
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

    async def execute(self, input_data: SherpaDataset) -> SherpaDataset:
        result = input_data.copy()
        add_processing_step(result, "baseline.als", {"lam": 1e5})
        return result
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import Provenance, SherpaDataset

HAS_NDDATASET = HAS_SCP


# =============================================================================
# Safe Coordinate Access
# =============================================================================


def safe_get_coord(dataset, coord_name: str):
    """Safely get a coordinate from NDDataset.

    SpectroChemPy's NDDataset.__getattr__ raises KeyError (not AttributeError)
    when a coordinate name like 'x' or 'y' is not in the coordset.  Python's
    built-in hasattr() only catches AttributeError, so
    ``hasattr(dataset, 'x')`` propagates the KeyError.  Use this helper
    instead of hasattr for coordinate access.
    """
    try:
        return getattr(dataset, coord_name)
    except (KeyError, AttributeError):
        return None


# =============================================================================
# Processing History (Provenance)
# =============================================================================


def add_processing_step(
    dataset: Any,
    operation: str,
    parameters: Dict[str, Any],
    node_id: Optional[str] = None,
    input_shape: Optional[tuple] = None,
    state_effects: Optional[List[str]] = None,
) -> None:
    """
    Record a processing step in dataset provenance / meta["processing_history"].

    Mutates the dataset in place.

    Args:
        dataset: SherpaDataset, NDDataset, or compatible dataset to add history to
        operation: Name of the operation (e.g., "baseline.als", "smooth.savgol")
        parameters: Dict of parameters used
        node_id: Optional DAG node ID
        input_shape: Shape before processing (defaults to current shape)
        state_effects: List of effect tags (e.g., ["baseline_corrected", "normalized"])

    Example:
        >>> add_processing_step(dataset, "baseline.als", {"lam": 1e5, "p": 0.001},
        ...                     state_effects=["baseline_corrected"])
    """
    if isinstance(dataset, SherpaDataset):
        in_shape = tuple(input_shape) if input_shape else tuple(dataset.shape)
        dataset.provenance.append(
            op_id=operation,
            parameters=parameters,
            node_id=node_id,
            input_shape=in_shape,
            output_shape=tuple(dataset.shape),
            state_effects=state_effects or [],
        )
        return

    if not hasattr(dataset, "meta") or dataset.meta is None:
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

    # Sync to provenance list if legacy dataset
    # NOTE: Cannot use hasattr() here — NDDataset.__getattr__ raises KeyError
    # (not AttributeError) for unknown attributes, which hasattr doesn't catch.
    # Guard: skip if provenance IS the same list object (legacy datasets may link
    # them in __init__ via setdefault) to avoid double-appending.
    try:
        prov = dataset.provenance
        if isinstance(prov, list) and prov is not dataset.meta.get("processing_history"):
            prov.append(step)
    except (KeyError, AttributeError):
        pass


def get_processing_history(dataset: Any) -> List[Dict[str, Any]]:
    """
    Get processing history from dataset.meta.

    Returns:
        List of processing step dicts, or empty list if none
    """
    if isinstance(dataset, SherpaDataset):
        return dataset.provenance.to_list()

    if not hasattr(dataset, "meta") or not dataset.meta:
        return []
    return dataset.meta.get("processing_history", [])


def copy_processing_history(source: Any, target: Any) -> None:
    """
    Copy processing history from source to target dataset.

    For legacy datasets, also syncs the .provenance attribute so that
    meta["processing_history"] and provenance stay in lockstep.

    Args:
        source: Dataset to copy history from
        target: Dataset to copy history to
    """
    history = get_processing_history(source)
    copied = [step.copy() if isinstance(step, dict) else dict(step) for step in history]

    if isinstance(target, SherpaDataset):
        target.provenance = Provenance.from_list(copied)
        return

    if not hasattr(target, "meta") or target.meta is None:
        target.meta = {}

    target.meta["processing_history"] = copied

    # Keep legacy dataset .provenance in sync (it may be a separate list
    # after meta["processing_history"] was replaced above).
    try:
        prov = target.provenance
        if isinstance(prov, list) and prov is not copied:
            prov.clear()
            prov.extend(copied)
            # Re-link so they're the same object going forward
            target.meta["processing_history"] = prov
    except (KeyError, AttributeError):
        pass


def clear_processing_history(dataset: Any) -> None:
    """Clear processing history (useful for creating derived datasets)."""
    if isinstance(dataset, SherpaDataset):
        dataset.provenance = Provenance()
        return

    if hasattr(dataset, "meta") and dataset.meta:
        dataset.meta["processing_history"] = []
    # Sync legacy dataset .provenance
    try:
        prov = dataset.provenance
        if isinstance(prov, list):
            prov.clear()
    except (KeyError, AttributeError):
        pass


# =============================================================================
# Sample Management (PLS_Toolbox-like Include/Exclude + Classes)
# =============================================================================


def ensure_samples_meta(dataset: Any) -> Dict[str, Any]:
    """
    Ensure dataset.meta["samples"] exists with proper structure.

    Structure:
        samples:
            include_mask: np.ndarray[bool]  # True = included, False = excluded
            classes: np.ndarray[str|int]    # Class labels per sample
            labels: List[str]               # Sample names/identifiers
    """
    if not hasattr(dataset, "meta") or dataset.meta is None:
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
    dataset: Any,
    indices: Union[int, List[int], np.ndarray],
    reason: Optional[str] = None,
) -> None:
    """
    Mark samples as excluded (soft delete, keeps data but sets include_mask=False).

    This is the PLS_Toolbox approach: data is never deleted, just flagged.
    Use get_included_data() to get only included samples.

    Args:
        dataset: Dataset with 2D data
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
    dataset: Any,
    indices: Union[int, List[int], np.ndarray, None] = None,
) -> None:
    """
    Mark samples as included. If indices=None, includes all samples.

    Args:
        dataset: Dataset with 2D data
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


def get_included_data(dataset: Any) -> Any:
    """
    Return a view/copy of dataset with only included samples.

    This is the workhorse function: preprocessing nodes should call this
    before operations if they want to respect the include/exclude mask.

    Returns:
        Dataset with only included samples
    """
    if dataset.ndim != 2:
        return dataset  # 1D data has no samples to exclude

    samples = ensure_samples_meta(dataset)
    mask = samples["include_mask"]

    if np.all(mask):
        return dataset  # All included, no copy needed

    return dataset[mask]


def get_include_mask(dataset: Any) -> np.ndarray:
    """Get the include/exclude mask as a boolean array."""
    samples = ensure_samples_meta(dataset)
    return samples["include_mask"].copy()


def set_class(
    dataset: Any,
    indices: Union[int, List[int], np.ndarray],
    class_label: Union[str, int],
) -> None:
    """
    Assign a class label to samples.

    Args:
        dataset: Dataset with 2D data
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


def get_classes(dataset: Any) -> np.ndarray:
    """Get array of class labels for all samples."""
    samples = ensure_samples_meta(dataset)
    return samples["classes"].copy()


def filter_by_class(
    dataset: Any,
    class_label: Union[str, int, List[Union[str, int]]],
) -> Any:
    """
    Return dataset filtered to only samples with given class(es).

    Args:
        dataset: Dataset with 2D data
        class_label: Class label(s) to filter by

    Returns:
        Dataset with only matching samples
    """
    if dataset.ndim != 2:
        return dataset

    samples = ensure_samples_meta(dataset)
    classes = samples["classes"]

    if isinstance(class_label, (str, int)):
        class_label = [class_label]

    mask = np.isin(classes, class_label)
    return dataset[mask]


def set_sample_labels(dataset: Any, labels: List[str]) -> None:
    """Set sample labels/names."""
    samples = ensure_samples_meta(dataset)
    if len(labels) != dataset.shape[0]:
        raise ValueError(f"Labels length ({len(labels)}) must match n_samples ({dataset.shape[0]})")
    samples["labels"] = list(labels)


def get_sample_labels(dataset: Any) -> List[str]:
    """Get sample labels/names."""
    samples = ensure_samples_meta(dataset)
    return list(samples["labels"])


# =============================================================================
# Spectral Type Detection
# =============================================================================

# Patterns for detection
_WAVENUMBER_UNITS = frozenset({"cm-1", "cm^-1", "cm⁻¹", "1/cm", "kayser"})
_WAVELENGTH_NM_UNITS = frozenset({"nm", "nanometer", "nanometers"})
_WAVELENGTH_UM_UNITS = frozenset({"um", "μm", "micron", "microns", "micrometer", "micrometers"})

_ABSORBANCE_PATTERNS = {"absorbance", "abs", "a", "optical density", "od"}
_TRANSMITTANCE_PATTERNS = {"transmittance", "trans", "t", "%t", "% transmittance"}
_REFLECTANCE_PATTERNS = {"reflectance", "refl", "r", "%r", "% reflectance"}


def detect_x_axis_type(dataset: Any) -> Optional[str]:
    """
    Detect X-axis type from units.

    Returns:
        "wavenumber", "wavelength_nm", "wavelength_um", or None
    """
    # SherpaDataset: use spectral_axis directly
    if isinstance(dataset, SherpaDataset):
        sa = dataset.spectral_axis
        if sa is None:
            return None
        return sa.axis_type

    # NDDataset: SpectroChemPy's __getattr__ raises KeyError (not AttributeError)
    # when a coordinate name like 'x' is not found.
    try:
        x_coord = dataset.x
    except (KeyError, AttributeError):
        return None
    if x_coord is None:
        return None

    units = str(x_coord.units).lower().strip() if hasattr(x_coord, "units") else ""

    if units in _WAVENUMBER_UNITS or ("cm" in units and "-1" in units):
        return "wavenumber"
    if units in _WAVELENGTH_NM_UNITS:
        return "wavelength_nm"
    if units in _WAVELENGTH_UM_UNITS:
        return "wavelength_um"

    return None


def detect_spectral_technique(dataset: Any) -> Optional[str]:
    """
    Detect spectral technique from X-axis range and units.

    Returns:
        "IR", "NIR", "Raman", "UV-Vis", or None
    """
    # SherpaDataset: check authoritative domain first, then infer from spectral axis
    if isinstance(dataset, SherpaDataset):
        if dataset.domain.technique is not None:
            return dataset.domain.technique
        sa = dataset.spectral_axis
        if sa is None:
            return None
        if dataset.title and "raman" in dataset.title.lower():
            return "Raman"
        axis_type = sa.axis_type
        if axis_type is None or sa.range is None:
            return None
        x_min, x_max = sa.range
        return _technique_from_range(axis_type, x_min, x_max, (dataset.units or "").lower())

    # NDDataset path
    try:
        x_coord = dataset.x
    except (KeyError, AttributeError):
        return None
    if x_coord is None:
        return None

    # Check title for Raman indicator
    if hasattr(dataset, "title") and dataset.title and "raman" in str(dataset.title).lower():
        return "Raman"

    axis_type = detect_x_axis_type(dataset)
    if axis_type is None:
        return None

    x_data = np.array(x_coord.data)
    x_min, x_max = float(np.min(x_data)), float(np.max(x_data))
    units_str = str(dataset.units).lower() if hasattr(dataset, "units") else ""
    return _technique_from_range(axis_type, x_min, x_max, units_str)


def _technique_from_range(
    axis_type: str, x_min: float, x_max: float, units_str: str
) -> Optional[str]:
    """Map axis type + range to spectral technique."""
    if axis_type == "wavenumber":
        if x_min >= 100 and x_max <= 4000:
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


def detect_data_quantity(dataset: Any) -> Optional[str]:
    """
    Detect data quantity type from units.

    Returns:
        "Absorbance", "Transmittance", "Reflectance", "Intensity", or None
    """
    # SherpaDataset: check authoritative domain first
    if isinstance(dataset, SherpaDataset) and dataset.domain.data_quantity is not None:
        return dataset.domain.data_quantity

    if not hasattr(dataset, "units") or not dataset.units:
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


def get_spectral_info(dataset: Any) -> Dict[str, Any]:
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

    # SherpaDataset: use spectral_axis directly
    if isinstance(dataset, SherpaDataset):
        sa = dataset.spectral_axis
        if sa is not None and sa.range is not None:
            info["x_range"] = sa.range
            info["x_units"] = sa.units
        if dataset.units:
            info["data_units"] = str(dataset.units)
        return info

    # NDDataset path
    try:
        x_coord = dataset.x
    except (KeyError, AttributeError):
        x_coord = None
    if x_coord is not None:
        x_data = np.array(x_coord.data)
        info["x_range"] = (float(np.min(x_data)), float(np.max(x_data)))
        info["x_units"] = str(x_coord.units) if hasattr(x_coord, "units") else None

    if hasattr(dataset, "units"):
        info["data_units"] = str(dataset.units)

    return info
