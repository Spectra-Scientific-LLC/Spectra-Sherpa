"""Port-type and spectral-unit validation for the DAG executor."""

from __future__ import annotations

import warnings
from typing import Any, Callable, List, Optional

from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

from .meta_helpers import safe_get_coord

HAS_NDDATASET = HAS_SCP

# SpectralResult removed - using NDDataset-only
HAS_SPECTRAL_RESULT = False
SpectralResult = None

# Import unit validation from app/lib
try:
    from spectra_sherpa.app.lib.spectral.validators import validate_and_normalize_units

    HAS_UNIT_VALIDATION = True
except ImportError:
    validate_and_normalize_units: Optional[Callable[[list[Any], str], list[Any]]] = None  # type: ignore[no-redef]
    HAS_UNIT_VALIDATION = False


def _is_dataset(obj: Any) -> bool:
    """Check if obj is a dataset (SherpaDataset primary; also catches legacy types)."""
    if isinstance(obj, SherpaDataset):
        return True
    if HAS_SCP and isinstance(obj, NDDataset):
        return True
    return False


def _category_from_type_ref(type_ref: str) -> str:
    """Derive the visual category from a type_ref URI.

    Resolves through the loaded type registry when available, otherwise
    falls back to ``"dataset"``.  ``Any`` ports skip validation entirely.
    """
    if "Any" in type_ref:
        return "any"  # Not in type_checks → validation skipped
    try:
        from spectra_sherpa.app.types import type_registry

        td = type_registry.resolve(type_ref)
        return td.category
    except Exception:
        return "dataset"


def _validate_spectral_units(
    datasets: List[Any],
    operation: str,
) -> List[Any]:
    """
    Validate and normalize spectral units across multiple datasets.

    Uses the "warning + auto-convert" policy: if incompatible units are
    detected (e.g., mixing Absorbance and Transmittance), logs a warning
    and auto-converts all datasets to Absorbance.

    Args:
        datasets: List of NDDataset objects to validate
        operation: Name of the operation (for warning messages)

    Returns:
        List of datasets with compatible units (possibly auto-converted)
    """
    if not HAS_UNIT_VALIDATION or not HAS_NDDATASET:
        return datasets

    # Filter to only NDDataset objects (unit validation is SCP-specific)
    nddatasets = [d for d in datasets if HAS_NDDATASET and isinstance(d, NDDataset)]
    if len(nddatasets) < 2:
        return datasets

    # Validate and normalize units
    normalized = validate_and_normalize_units(nddatasets, operation)

    # Replace in original list
    result = []
    norm_idx = 0
    for d in datasets:
        if HAS_NDDATASET and isinstance(d, NDDataset):
            result.append(normalized[norm_idx])
            norm_idx += 1
        else:
            result.append(d)

    return result


def _validate_port_type(
    data: Any,
    expected_type: str,
    port_name: str,
    source_node_id: str,
    target_node_id: str,
    strict: bool = False,
) -> None:
    """
    Validate that data matches the expected port type.

    Port types:
    - "dataset": Expects NDDataset (SpectroChemPy smart array)
    - "array": Expects list, tuple, or numpy array
    - "model": Expects fitted model object
    - "target": Expects array-like (concentrations, labels)
    - "config": Expects dict

    Args:
        data: The data to validate
        expected_type: The expected port type
        port_name: Name of the port for error messages
        source_node_id: ID of the node providing the data
        target_node_id: ID of the node receiving the data
        strict: If True, raise error on mismatch. If False, warn only.

    Raises:
        TypeError: If strict=True and type doesn't match
    """
    import numpy as np

    type_checks = {
        "dataset": lambda d: _is_dataset(d),
        "array": lambda d: isinstance(d, (list, tuple, np.ndarray)) or _is_dataset(d),
        "model": lambda d: hasattr(d, "fit") or hasattr(d, "transform") or hasattr(d, "predict"),
        "target": lambda d: isinstance(d, (list, tuple, np.ndarray, dict)) or _is_dataset(d),
        "config": lambda d: isinstance(d, dict),
    }

    # Skip validation for unknown types
    if expected_type not in type_checks:
        return

    # Check type
    is_valid = type_checks[expected_type](data)

    if not is_valid:
        actual_type = type(data).__name__
        msg = (
            f"Port type mismatch: '{port_name}' on node '{target_node_id}' "
            f"expects '{expected_type}' but received '{actual_type}' from node '{source_node_id}'. "
        )

        if expected_type == "dataset":
            msg += (
                "Upstream node should return SherpaDataset with coordinates attached, "
                "not raw arrays. This ensures X-axis (wavenumbers) stays coupled with data."
            )

        if strict:
            raise TypeError(msg)
        else:
            warnings.warn(msg, UserWarning, stacklevel=3)

    # Additional coordinate validation for datasets
    # This catches mismatched axes that could cause cryptic errors downstream
    if is_valid and expected_type == "dataset" and _is_dataset(data):
        coord_issues = []

        try:
            # Check X-axis (spectral dimension) exists and matches data shape.
            # Coordinate internals can occasionally be malformed (e.g., coord.data is None),
            # so this validation must never raise and block execution.
            x_coord = safe_get_coord(data, "x")
            data_shape = tuple(data.shape) if hasattr(data, "shape") else ()
            data_spectral_dim = data_shape[-1] if len(data_shape) > 0 else 0

            if x_coord is not None:
                x_len = None
                try:
                    x_data = getattr(x_coord, "data")
                except Exception:
                    x_data = None

                if x_data is not None:
                    try:
                        x_len = len(x_data)
                    except Exception:
                        try:
                            x_arr = np.asarray(x_data)
                            x_len = int(x_arr.shape[0]) if x_arr.ndim > 0 else 1
                        except Exception:
                            x_len = None

                if x_len is None:
                    try:
                        x_len = len(x_coord)
                    except Exception:
                        x_len = None

                if x_len is None:
                    coord_issues.append("X-axis coordinates exist but length could not be determined")
                elif data_spectral_dim > 0 and x_len != data_spectral_dim:
                    coord_issues.append(
                        f"X-axis length ({x_len}) doesn't match spectral dimension ({data_spectral_dim})"
                    )
            elif data_spectral_dim > 1:
                # Missing X-axis on multi-point data is a warning
                coord_issues.append("No X-axis coordinates defined (wavenumbers will be unavailable for display)")

            # Check for NaN in data (best effort; ignore non-numeric payloads)
            try:
                data_values = getattr(data, "data", None)
                if data_values is not None and np.any(np.isnan(np.asarray(data_values, dtype=float))):
                    coord_issues.append("Data contains NaN values")
            except Exception:
                pass
        except Exception as coord_err:
            warnings.warn(
                f"Data integrity validation failed on '{port_name}' from node '{source_node_id}': {coord_err}",
                UserWarning,
                stacklevel=3,
            )

        # Warn about coordinate issues (don't block execution)
        for issue in coord_issues:
            warnings.warn(
                f"Data integrity warning on '{port_name}' from node '{source_node_id}': {issue}",
                UserWarning,
                stacklevel=3,
            )
