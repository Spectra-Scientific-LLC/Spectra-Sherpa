"""Core utilities for modeling nodes.

This module provides reusable helper functions for creating and manipulating
SherpaDataset instances with proper axis/coordinate preservation. These utilities
are used extensively across modeling nodes (PCA, PLS, MCR, etc.) and are exposed
as public API for custom node developers.

**Public API:**
- `make_safe_coord()` - Convert various coordinate formats to AxisInfo
- `create_spectral_dataset()` - Build SherpaDataset with coordinate preservation
- `is_sequential_numeric()` - Detect sequential vs categorical numeric data
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    AxisInfo,
    FeatureAxis,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)

from ...io_contracts import to_numpy_1d, to_numpy_2d

__all__ = [
    "make_safe_coord",
    "create_spectral_dataset",
    "is_sequential_numeric",
    "unwrap_data",
    "to_numpy_2d_any",
    "to_numpy_1d_any",
]


# ── Data conversion helpers ─────────────────────────────────────────
# Previously duplicated across all split node files.


def unwrap_data(value: Any) -> Any:
    """Safely unwrap dataset-like .data while avoiding ndarray memoryview traps."""
    if isinstance(value, SherpaDataset):
        return value.data
    if hasattr(value, "data") and not isinstance(value, np.ndarray):
        return value.data
    return value


def to_numpy_2d_any(value: Any, *, name: str, dtype: Any = np.float64) -> np.ndarray:
    """Convert dataset-like values to a strict 2D numpy array."""
    return to_numpy_2d(unwrap_data(value), name=name, dtype=dtype)


def to_numpy_1d_any(value: Any, *, name: str, dtype: Any = np.float64) -> np.ndarray:
    """Convert dataset-like values to a strict 1D numpy array."""
    return to_numpy_1d(unwrap_data(value), name=name, dtype=dtype)


def make_safe_coord(values: Any, title: Optional[str] = None) -> Any:
    """Build axis metadata safely for numeric and categorical values.

    Converts various coordinate formats (AxisInfo, Coord-like objects, numeric arrays,
    categorical arrays) into a standardized AxisInfo object. This enables downstream
    nodes to work without requiring SpectroChemPy.

    **Usage in Custom Nodes:**
    ```python
    from spectra_sherpa.app.services.dag.nodes.modeling import make_safe_coord

    # Convert wavenumber array to axis
    x_axis = make_safe_coord(wavenumbers, title="Wavenumber")

    # Convert sample labels to axis
    y_axis = make_safe_coord(["Sample_A", "Sample_B", "Sample_C"], title="Samples")

    # Pass through existing AxisInfo (creates copy)
    preserved_axis = make_safe_coord(existing_axis, title="New Title")
    ```

    Args:
        values: Coordinate values to convert. Can be:
            - AxisInfo: Copied and optionally retitled
            - Coord-like object: Converted to AxisInfo
            - Numeric array: Creates AxisInfo with numeric values
            - String/categorical array: Creates AxisInfo with labels + numeric index
            - None: Returns None
        title: Optional title for the axis (overrides existing title if provided)

    Returns:
        AxisInfo object with standardized coordinate representation, or None if input is None

    Example:
        >>> # Numeric coordinates (e.g., wavenumbers)
        >>> wavenumbers = np.linspace(400, 4000, 1000)
        >>> axis = make_safe_coord(wavenumbers, title="Wavenumber")
        >>> axis.values.shape  # (1000,)
        >>> axis.title  # "Wavenumber"

        >>> # Categorical coordinates (e.g., sample names)
        >>> samples = ["Control_1", "Control_2", "Treatment_1", "Treatment_2"]
        >>> axis = make_safe_coord(samples, title="Sample ID")
        >>> axis.labels  # ["Control_1", "Control_2", "Treatment_1", "Treatment_2"]
        >>> axis.values  # [0.0, 1.0, 2.0, 3.0]  (numeric index)
    """
    if values is None:
        return None

    # Already an AxisInfo — copy and optionally set title
    if isinstance(values, AxisInfo):
        coord = values.copy()
        if title and not coord.title:
            coord.title = title
        return coord

    # Coord-like object (NDDataset coordinate from SpectroChemPy) — convert to AxisInfo
    if hasattr(values, "data") and hasattr(values, "copy"):
        labels = None
        raw_labels = getattr(values, "labels", None)
        if raw_labels is not None:
            try:
                if hasattr(raw_labels, "tolist"):
                    flat = raw_labels.tolist()
                else:
                    flat = list(raw_labels)
                if isinstance(flat, list):
                    labels = [str(v) for v in flat]
                else:
                    labels = [str(flat)]
            except Exception:
                labels = None
        return AxisInfo(
            values=np.asarray(values.data) if values.data is not None else None,
            units=str(values.units) if hasattr(values, "units") and values.units else None,
            title=title or (str(values.title) if hasattr(values, "title") and values.title else None),
            labels=labels,
        )

    # Try numeric array
    arr = np.asarray(values)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if np.issubdtype(arr.dtype, np.number):
        return AxisInfo(values=arr, title=title)

    # String / categorical — store as labels with numeric index
    labels_str = [str(v) for v in arr.reshape(-1).tolist()]
    return AxisInfo(
        values=np.arange(len(labels_str), dtype=float),
        labels=labels_str,
        title=title,
    )


def create_spectral_dataset(
    data: np.ndarray,
    x_coord: Optional[Any] = None,
    y_coord: Optional[Any] = None,
    units: Optional[str] = None,
    title: Optional[str] = None,
    meta: Optional[dict] = None,
    data_role: Optional[str] = None,
) -> SherpaDataset:
    """Create a SherpaDataset with proper coordinate preservation.

    This ensures that spectral data always carries its coordinate system,
    enabling "smart array" behavior where slicing data also slices coordinates.

    **Usage in Custom Nodes:**
    ```python
    from spectra_sherpa.app.services.dag.nodes.modeling import create_spectral_dataset

    # Create dataset with wavenumber axis
    output_data = create_spectral_dataset(
        data=scores_matrix,
        x_coord=pc_labels,  # ["PC1", "PC2", "PC3"]
        y_coord=sample_ids,  # ["S001", "S002", ...]
        units="score",
        title="PCA Scores",
        meta={"explained_variance": [0.45, 0.30, 0.15]}
    )
    ```

    Args:
        data: The spectral data array (1D or 2D)
        x_coord: X-axis (feature) coordinate — AxisInfo, Coord, or array-like
        y_coord: Y-axis (sample) coordinate — AxisInfo, Coord, or array-like
        units: Data-value units (e.g., "absorbance", "score", "loading")
        title: Dataset title
        meta: Metadata dictionary to attach to dataset.meta
        data_role: Optional canonical role. Use ``X_features`` for latent
            score/embedding outputs that should not be treated as ordered spectra.

    Returns:
        SherpaDataset with coordinates properly attached

    Example:
        >>> # Create PCA scores dataset
        >>> scores = np.random.randn(20, 3)  # 20 samples × 3 components
        >>> pc_axis = ["PC1", "PC2", "PC3"]
        >>> sample_axis = [f"Sample_{i+1}" for i in range(20)]
        >>>
        >>> scores_ds = create_spectral_dataset(
        ...     data=scores,
        ...     x_coord=pc_axis,
        ...     y_coord=sample_axis,
        ...     units="score",
        ...     title="PCA Scores"
        ... )
        >>> scores_ds.shape  # (20, 3)
        >>> scores_ds.feature_axis.labels  # ["PC1", "PC2", "PC3"]
    """
    x_axis_info = make_safe_coord(x_coord) if x_coord is not None else None
    y_axis_info = make_safe_coord(y_coord) if y_coord is not None else None

    output_data_role = data_role
    feature_axis = None
    if x_axis_info is not None:
        if isinstance(x_axis_info, SpectralAxis):
            feature_axis = x_axis_info
        elif isinstance(x_axis_info, FeatureAxis):
            feature_axis = x_axis_info
            output_data_role = output_data_role or "X_features"
        elif output_data_role == "X_features":
            feature_axis = FeatureAxis(
                values=x_axis_info.values,
                labels=x_axis_info.labels,
                units=x_axis_info.units,
                title=x_axis_info.title,
            )
        else:
            feature_axis = SpectralAxis(
                values=x_axis_info.values,
                labels=x_axis_info.labels,
                units=x_axis_info.units,
                title=x_axis_info.title,
            )

    sample_axis = None
    if y_axis_info is not None:
        if isinstance(y_axis_info, SampleAxis):
            sample_axis = y_axis_info
        else:
            sample_axis = SampleAxis(
                values=y_axis_info.values,
                labels=y_axis_info.labels,
                units=y_axis_info.units,
                title=y_axis_info.title,
            )

    return SherpaDataset(
        X=data,
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        units=units,
        title=title,
        extra=meta.copy() if meta is not None else None,
        data_role=output_data_role,
    )


def ensure_orientation(
    data: np.ndarray,
    *,
    expected_rows: int,
    expected_cols: int,
    name: str = "matrix",
) -> np.ndarray:
    """Ensure a 2D array has shape (expected_rows, expected_cols), transposing if needed.

    Handles SCP version differences where loadings/scores may arrive in
    either orientation.  If both dimensions match (square case), returns
    data unchanged.

    Raises:
        ValueError: If neither orientation matches the expected shape.
    """
    if data.ndim != 2:
        raise ValueError(f"{name}: expected 2D, got {data.ndim}D")
    if data.shape == (expected_rows, expected_cols):
        return data
    if data.shape == (expected_cols, expected_rows):
        return data.T
    raise ValueError(f"{name}: shape {data.shape} cannot be oriented to ({expected_rows}, {expected_cols})")


def is_sequential_numeric(values: list) -> bool:
    """Check if numeric values are sequential (e.g., time series, temperature series).

    Sequential data should NOT be treated as categorical. This function detects
    if numeric values form an arithmetic sequence (constant difference between values),
    which indicates they represent a continuous variable rather than discrete categories.

    **Usage in Custom Nodes:**
    ```python
    from spectra_sherpa.app.services.dag.nodes.modeling import is_sequential_numeric

    # Detect if temperature values are sequential
    temps = [20.0, 25.0, 30.0, 35.0, 40.0]
    if is_sequential_numeric(temps):
        # Treat as continuous axis (e.g., for plotting)
        axis_type = "continuous"
    else:
        # Treat as categorical labels
        axis_type = "categorical"
    ```

    Args:
        values: List of numeric values (already converted to hashable types)

    Returns:
        True if values appear to be a sequential series (arithmetic progression),
        False otherwise

    Example:
        >>> # Sequential data (constant difference)
        >>> temps = [20, 25, 30, 35, 40]  # Diff = 5
        >>> is_sequential_numeric(temps)  # True

        >>> # Non-sequential data (irregular differences)
        >>> categories = [1, 2, 5, 10, 100]
        >>> is_sequential_numeric(categories)  # False

        >>> # Categorical labels (numeric but not sequential)
        >>> sample_ids = [101, 203, 305, 407]
        >>> is_sequential_numeric(sample_ids)  # False (irregular diff)

    Note:
        - Requires at least 3 values to detect sequence
        - Allows 1% tolerance for floating-point errors
        - Returns False if any value is non-numeric
    """
    try:
        # Convert to numeric array
        numeric_values = []
        for v in values:
            if isinstance(v, (int, float, np.integer, np.floating)):
                numeric_values.append(float(v))
            else:
                # If any value is not numeric, not sequential
                return False

        if len(numeric_values) < 3:
            # Need at least 3 values to detect sequence
            return False

        # Check if values form an arithmetic sequence (constant difference)
        diffs = np.diff(sorted(set(numeric_values)))

        # If all differences are the same (within tolerance), it's sequential
        if len(diffs) > 0:
            mean_diff = np.mean(diffs)
            # Allow 1% tolerance for floating point errors
            tolerance = max(abs(mean_diff) * 0.01, 1e-10)
            return bool(np.all(np.abs(diffs - mean_diff) < tolerance))

        return False
    except (TypeError, ValueError):
        return False
