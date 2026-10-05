"""Minimal, lazy adapter for the three retained SpectroChemPy algorithms.

The canonical scientific transport is :class:`SherpaDataset`.  This module
creates temporary matrix-only SpectroChemPy datasets solely for EFA, MCR-ALS,
and SIMPLISMA execution.  It deliberately provides no reverse conversion,
coordinate inference, file discovery, downloader, or generic round-trip API.
"""

from __future__ import annotations

import threading
from importlib import import_module
from types import ModuleType
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.fitted_state import EFAExtract, MCRExtract, SIMPLISMAExtract
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

_ALLOWED_OPERATIONS = frozenset({"model.efa", "model.mcr_als", "model.simplisma"})
_DISALLOWED_BACKGROUND_TARGETS = frozenset(
    {
        "spectrochempy.application.check_update.check_update",
        "spectrochempy.application.testdata.download_full_testdata_directory",
    }
)
_REQUIRED_RUNTIME_SYMBOLS = ("NDDataset", "EFA", "MCRALS", "SIMPLISMA")
_IMPORT_LOCK = threading.Lock()


def _import_local_only_runtime() -> ModuleType:
    """Import SCP without its unrelated update/test-data background threads.

    SpectroChemPy 0.8.1 starts an update check and test-data download from its
    package initializer. Sherpa uses only matrix algorithms, so those two exact
    background services are outside this adapter's authority. Suppress only
    those pinned-runtime targets during first import, while allowing any other
    thread to start normally, and restore the process thread hook immediately.
    """

    with _IMPORT_LOCK:
        original_start = threading.Thread.start

        def local_only_start(thread: threading.Thread) -> None:
            target = getattr(thread, "_target", None)
            target_id = (
                f"{getattr(target, '__module__', '')}.{getattr(target, '__qualname__', '')}"
                if target is not None
                else ""
            )
            if target_id in _DISALLOWED_BACKGROUND_TARGETS:
                return
            original_start(thread)

        threading.Thread.start = local_only_start
        try:
            # Always resolve through the protected section. A prior plain
            # ``import spectrochempy`` creates only SCP's lazy top-level module;
            # returning it directly would defer application initialization and
            # its background services until after this guard was restored.
            module = import_module("spectrochempy")
            # SCP exposes a lazy top-level API: importing the package alone does
            # not initialize the application that owns the two background
            # services. Resolve the complete, exact adapter surface while the
            # local-only start policy is active so later scientific execution
            # cannot trigger those services after this boundary is restored.
            for symbol in _REQUIRED_RUNTIME_SYMBOLS:
                getattr(module, symbol)
            return module
        finally:
            threading.Thread.start = original_start


def require_spectrochempy(operation_id: str) -> ModuleType:
    """Load SpectroChemPy lazily for one exact retained operation."""

    if operation_id not in _ALLOWED_OPERATIONS:
        raise ValueError(f"SpectroChemPy is not an authority for operation {operation_id!r}")
    try:
        return _import_local_only_runtime()
    except ImportError as exc:
        raise ImportError(
            f"{operation_id} requires SpectroChemPy. "
            "Install the optional adapter with: pip install 'spectra-sherpa[scp]'"
        ) from exc


def _finite_matrix(value: Any, *, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional matrix")
    if not matrix.size:
        raise ValueError(f"{name} must not be empty")
    finite = np.isfinite(matrix)
    if not finite.all():
        missing_count = int(np.count_nonzero(~finite))
        # Scientist-facing rows are one-based. Bound the diagnostic so a large
        # malformed matrix cannot turn one refusal into an enormous response.
        affected_rows = np.flatnonzero(np.any(~finite, axis=1)) + 1
        shown_rows = affected_rows[:12].tolist()
        remaining_rows = int(max(0, affected_rows.size - len(shown_rows)))
        row_text = ", ".join(str(row) for row in shown_rows)
        if remaining_rows:
            row_text += f", and {remaining_rows} more"
        noun = "value" if missing_count == 1 else "values"
        if name == "SherpaDataset.X":
            row_label = "sample row(s)"
            remediation = (
                "Repair the source or use Prepare Samples to exclude the affected rows "
                "before fitting a scientific model; do not infer replacement values implicitly."
            )
        else:
            row_label = "matrix row(s)"
            remediation = (
                "Provide a complete finite matrix before execution; " "do not infer replacement values implicitly."
            )
        raise ValueError(
            f"{name} contains {missing_count} missing or non-finite {noun} " f"in {row_label} {row_text}. {remediation}"
        )
    return np.ascontiguousarray(matrix)


def to_spectrochempy_dataset(dataset: SherpaDataset, *, operation_id: str) -> Any:
    """Project one native dataset to a temporary matrix-only SCP dataset."""

    if not isinstance(dataset, SherpaDataset):
        raise TypeError("SpectroChemPy adaptation requires a SherpaDataset")
    scp = require_spectrochempy(operation_id)
    return scp.NDDataset(_finite_matrix(dataset.X, name="SherpaDataset.X"))


def spectrochempy_dataset_from_array(array: Any, *, operation_id: str) -> Any:
    """Create the temporary SCP matrix used for MCR-ALS initialization."""

    scp = require_spectrochempy(operation_id)
    return scp.NDDataset(_finite_matrix(array, name="MCR-ALS initial concentrations"))


def _external_array(value: Any, *, name: str) -> np.ndarray:
    """Project one optional-runtime value into an owned NumPy array."""

    if value is None:
        raise ValueError(f"{name} is missing")
    raw = value.data if hasattr(value, "data") and not isinstance(value, np.ndarray) else value
    return np.asarray(raw)


def _external_matrix(value: Any, *, name: str) -> np.ndarray:
    array = _external_array(value, name=name)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2:
        raise ValueError(f"{name} must be one- or two-dimensional")
    return np.asarray(array, dtype=np.float64)


def extract_efa_state(model: Any) -> EFAExtract:
    """Close an EFA runtime object into native diagnostic arrays."""

    forward = _external_matrix(getattr(model, "f_ev", None), name="EFA forward eigenvalues")
    backward = _external_matrix(getattr(model, "b_ev", None), name="EFA backward eigenvalues")
    return EFAExtract(
        forward_ev=forward,
        backward_ev=backward,
        n_components=int(model.n_components),
    )


def extract_mcr_state(model: Any, *, concentration_solver: str) -> MCRExtract:
    """Close an MCR-ALS runtime object into native fitted state."""

    concentrations = _external_matrix(getattr(model, "C", None), name="MCR concentrations")
    spectra = _external_matrix(getattr(model, "St", None), name="MCR component spectra")
    return MCRExtract(
        C=concentrations,
        St=spectra,
        n_components=concentrations.shape[1],
        concentration_solver=concentration_solver,
    )


def extract_simplisma_state(model: Any) -> SIMPLISMAExtract:
    """Close a SIMPLISMA runtime object into native fitted state."""

    concentrations = _external_matrix(getattr(model, "C", None), name="SIMPLISMA concentrations")
    spectra = _external_matrix(getattr(model, "St", None), name="SIMPLISMA component spectra")
    n_components = concentrations.shape[1]
    purities = None
    if getattr(model, "purities", None) is not None:
        purities = np.asarray(_external_array(model.purities, name="SIMPLISMA purities"), dtype=np.float64).reshape(-1)
    elif getattr(model, "Pt", None) is not None:
        purity_spectra = _external_matrix(model.Pt, name="SIMPLISMA purity spectra")
        if purity_spectra.shape[0] != n_components:
            raise ValueError("SIMPLISMA purity spectra do not match the resolved component count")
        purities = np.max(purity_spectra, axis=1)
    return SIMPLISMAExtract(
        C=concentrations,
        St=spectra,
        purities=purities,
        n_components=n_components,
    )


__all__ = (
    "extract_efa_state",
    "extract_mcr_state",
    "extract_simplisma_state",
    "require_spectrochempy",
    "spectrochempy_dataset_from_array",
    "to_spectrochempy_dataset",
)
