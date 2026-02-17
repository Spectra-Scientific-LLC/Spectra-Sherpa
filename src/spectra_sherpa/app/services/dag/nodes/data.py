"""
Data source nodes for loading spectral data.

These nodes handle loading data from experiments, files, or other sources.
All data source nodes attach SpectraMeta metadata for traceability.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
from spectra_sherpa.app.lib.scp_compat import (
    HAS_SCP,
    NDDataset,
    get_scp_datadirs,
    require_scp,
    resolve_scp_path,
    scp,
)
from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo, from_sklearn_bunch
from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

from ..node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history, safe_get_coord
from spectra_sherpa.app.models.spectra_meta import (
    SpectraMeta,
    SpeciesInfo,
    ConcentrationProfile,
    DataProvenance,
    AcquisitionParams,
    ExperimentalConditions,
    InstrumentInfo,
    SourceType,
    PhysicalState,
    ConcentrationUnit,
    set_spectra_meta,
    create_minimal_meta,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level utility functions
# =============================================================================


def is_index_column(data_column: np.ndarray) -> bool:
    """
    Detect if a column is a monotonic integer sequence (likely an index).

    Checks if the column:
    - Contains only integers (or floats that are whole numbers)
    - Is monotonically increasing
    - Has consistent step size of 1

    Args:
        data_column: 1D numpy array representing a column

    Returns:
        True if column appears to be an index, False otherwise
    """
    try:
        # Convert to numeric if not already
        col = np.array(data_column).flatten()

        # Check if all values are integers or whole numbers
        if not np.allclose(col, np.round(col)):
            return False

        col_int = np.round(col).astype(int)

        # Check if monotonically increasing
        if not np.all(np.diff(col_int) > 0):
            return False

        # Check if step size is consistently 1
        steps = np.diff(col_int)
        if not np.all(steps == 1):
            return False

        return True
    except (ValueError, TypeError):
        return False


def remove_index_columns(dataset: NDDataset) -> NDDataset:
    """
    Remove index columns from dataset if detected.

    Detects and removes columns that appear to be row indices
    (monotonic integer sequences with step=1).

    Args:
        dataset: Input NDDataset

    Returns:
        NDDataset with index columns removed (if any were found)
    """
    if not hasattr(dataset, 'data') or dataset.ndim != 2:
        return dataset

    data = np.array(dataset.data)
    n_rows, n_cols = data.shape

    # Check first column for index pattern
    if n_cols > 1:  # Only remove if there are other columns
        first_col = data[:, 0]
        if is_index_column(first_col):
            logger.debug(f"[DATA] Detected index column in first position (values: {first_col[0]:.0f}-{first_col[-1]:.0f}), removing from data")
            # Remove first column
            cleaned_data = data[:, 1:]

            # Create new dataset without the index column
            if isinstance(dataset, AnalysisDataset):
                cleaned_dataset = AnalysisDataset(
                    X=cleaned_data,
                    x_axis=dataset.x_axis.copy() if dataset.x_axis else None,
                    y_axis=dataset.y_axis.copy() if dataset.y_axis else None,
                    meta=dict(dataset.meta) if dataset.meta else {},
                    provenance=list(dataset.provenance),
                    backend=dataset.backend,
                    title=dataset.title,
                    units=dataset.units,
                )
                # Trim x-axis if it matched original column count
                if cleaned_dataset.x_axis and cleaned_dataset.x_axis.values is not None and len(cleaned_dataset.x_axis.values) == n_cols:
                    cleaned_dataset.x_axis = AxisInfo(
                        values=cleaned_dataset.x_axis.values[1:],
                        labels=cleaned_dataset.x_axis.labels[1:] if cleaned_dataset.x_axis.labels and len(cleaned_dataset.x_axis.labels) == n_cols else cleaned_dataset.x_axis.labels,
                        units=cleaned_dataset.x_axis.units,
                        title=cleaned_dataset.x_axis.title,
                    )
            elif HAS_SCP and isinstance(dataset, NDDataset):
                cleaned_dataset = scp.NDDataset(cleaned_data)

                # Preserve coordinate system if present
                ric_x_coord = safe_get_coord(dataset, 'x')
                if ric_x_coord is not None and len(ric_x_coord) == n_cols:
                    cleaned_dataset.x = ric_x_coord[1:].copy() if hasattr(ric_x_coord, '__getitem__') else ric_x_coord
                elif ric_x_coord is not None:
                    cleaned_dataset.x = ric_x_coord.copy()

                ric_y_coord = safe_get_coord(dataset, 'y')
                if ric_y_coord is not None:
                    cleaned_dataset.y = ric_y_coord.copy()

                # Preserve metadata
                if hasattr(dataset, 'meta') and dataset.meta:
                    cleaned_dataset.meta = dataset.meta.copy()

                if hasattr(dataset, 'title'):
                    cleaned_dataset.title = dataset.title

                if hasattr(dataset, 'units'):
                    cleaned_dataset.units = dataset.units
            else:
                # Plain ndarray fallback
                cleaned_dataset = AnalysisDataset(X=cleaned_data)

            return cleaned_dataset

    return dataset


def extract_dataset_from_result(result: Any, file_path: str) -> NDDataset:
    """
    Extract a single NDDataset from a file read result.

    Handles ScpObjectList which is returned by read_matlab() when .MAT files
    contain multiple variables (common for MCR-ALS datasets like als2004dataset.MAT).

    Strategy: Select the 2D dataset with the largest total size (rows * cols),
    which is typically the main spectral matrix D = C * S^T.

    Note: This function is only called from SCP file-loading paths.

    Args:
        result: The result from SpectroChemPy read operation
        file_path: Path to the file being read (for error messages)

    Returns:
        NDDataset: A single dataset extracted from the result
    """
    require_scp("File loading")

    # If already an NDDataset, return as-is
    if isinstance(result, NDDataset):
        return result

    # Handle ScpObjectList (list of datasets)
    if hasattr(result, '__iter__') and not isinstance(result, (str, bytes)):
        datasets = list(result)

        if len(datasets) == 0:
            raise ValueError(f"No datasets found in {file_path}")

        if len(datasets) == 1:
            return datasets[0]

        # Multiple datasets - find the best candidate
        # Prefer 2D datasets (spectral matrices) over 1D
        candidates_2d = [d for d in datasets if hasattr(d, 'shape') and len(d.shape) == 2]

        if candidates_2d:
            # Select largest 2D dataset by total elements
            best = max(candidates_2d, key=lambda d: np.prod(d.shape))
            logger.debug(f"MAT file contains {len(datasets)} items, selected shape {best.shape}")
            return best
        else:
            # No 2D candidates - select largest overall (encapsulate as NDDataset)
            best = max(datasets, key=lambda d: np.prod(getattr(d, 'shape', (0,))))
            logger.debug(f"MAT file contains {len(datasets)} items with no 2D arrays, selected largest dataset with shape {getattr(best, 'shape', 'unknown')}")
            return best

    # Ensure result is encapsulated as NDDataset for consistency
    if not isinstance(result, NDDataset):
        # Convert array-like objects to NDDataset
        try:
            if isinstance(result, np.ndarray):
                result = scp.NDDataset(result)
            elif hasattr(result, '__array__'):
                result = scp.NDDataset(np.array(result))
            else:
                # Last resort - try direct conversion
                result = scp.NDDataset(result)
        except Exception as e:
            raise TypeError(
                f"Cannot convert to NDDataset: {type(result).__name__}\n"
                f"File: {file_path}\n"
                f"Error: {str(e)}"
            ) from e
    return result


_SCP_KNOWN_DEFAULTS: dict[str, tuple[str, str]] = {
    # category: (relative_path, explicit reader name)
    "irdata": ("irdata/nh4y-activation.spg", "read_omnic"),
}


def _normalize_scp_read_output(result: Any) -> NDDataset | None:
    """Normalize SpectroChemPy reader outputs across versions."""
    if result is None:
        return None
    if isinstance(result, NDDataset):
        return result

    if isinstance(result, dict):
        for value in result.values():
            candidate = _normalize_scp_read_output(value)
            if candidate is not None:
                return candidate
        return None

    if isinstance(result, (list, tuple)):
        for item in result:
            candidate = _normalize_scp_read_output(item)
            if candidate is not None:
                return candidate
        return None

    # Some SCP objects are iterable but not list/tuple.
    if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
        try:
            for item in result:
                candidate = _normalize_scp_read_output(item)
                if candidate is not None:
                    return candidate
        except Exception:
            return None

    return None


def _try_load_scp_file(path: Path) -> NDDataset | None:
    """Load one SCP file with extension-aware reader selection."""
    from spectra_sherpa.app.core.config import get_reader_for_extension

    try:
        reader_name = get_reader_for_extension(path.suffix)
    except ValueError:
        return None

    dataset = None
    reader_fn = getattr(scp, reader_name, None)
    if callable(reader_fn):
        try:
            dataset = _normalize_scp_read_output(reader_fn(str(path)))
        except Exception:
            dataset = None

    # If the mapped reader is missing or couldn't parse, try generic read().
    if dataset is None and reader_name != "read":
        generic_reader = getattr(scp, "read", None)
        if callable(generic_reader):
            try:
                dataset = _normalize_scp_read_output(generic_reader(str(path)))
            except Exception:
                dataset = None

    if dataset is None:
        return None

    if path.suffix.lower() == ".csv":
        return remove_index_columns(dataset)

    return dataset


def _try_load_first_file(folder: Path) -> NDDataset | None:
    """Find the first readable file in a dataset folder (recursive)."""
    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith((".", "_")):
            continue
        dataset = _try_load_scp_file(file_path)
        if dataset is not None:
            return dataset
    return None


def extract_instrument_metadata(dataset: NDDataset, file_path: str) -> dict:
    """
    Extract and normalize instrument metadata from a loaded NDDataset.

    This is a wrapper around the metadata extraction service that provides
    format-specific extractors (OPUS, SPA, JCAMP, SPC) and a normalizer
    that maps raw keys to our SpectraMeta schema.

    The new architecture supports:
    - Bruker OPUS files: Comprehensive instrument/acquisition params
    - Thermo SPA/SPG files: Full metadata extraction
    - JCAMP-DX files: Standard header fields + vendor extensions
    - Galactic SPC files: Instrument metadata
    - Generic fallback for CSV, MAT, etc.

    Args:
        dataset: Loaded NDDataset with potential metadata
        file_path: Original file path (for format detection)

    Returns:
        Dict with normalized metadata fields ready for SpectraMeta:
        {
            "instrument_metadata": {...},   # -> InstrumentInfo
            "acquisition_params": {...},    # -> AcquisitionParams
            "experimental_conditions": {...}, # -> ExperimentalConditions
            "sample_info": {...},           # Sample-related fields
            "provenance": {...},            # -> DataProvenance + AuditInfo
            "raw_file_metadata": {...},     # Preserved but excluded from API
        }
    """
    try:
        # Use the new metadata extraction service
        from spectra_sherpa.app.services.metadata import extract_metadata
        return extract_metadata(dataset, file_path)
    except ImportError:
        # Fallback if metadata service not available (shouldn't happen)
        logger.warning("Metadata service not available, using minimal extraction")
        return _minimal_metadata_extraction(dataset, file_path)


def _minimal_metadata_extraction(dataset: NDDataset, file_path: str) -> dict:
    """
    Minimal fallback metadata extraction if the service is unavailable.

    This preserves basic functionality if there's an import error.
    SECURITY: Only stores filename, not full path, to prevent server path leakage.
    """
    metadata = {
        "provenance": {
            "original_file_format": os.path.splitext(file_path)[1].lower().lstrip("."),
            "original_filename": os.path.basename(file_path),
        }
    }

    # Extract x-axis info if available
    mme_x_coord = safe_get_coord(dataset, 'x')
    if mme_x_coord is not None:
        try:
            x_data = np.array(mme_x_coord.data) if hasattr(mme_x_coord, 'data') else np.array(mme_x_coord)
            if len(x_data) > 0:
                metadata["acquisition_params"] = {
                    "wavenumber_min": float(np.min(x_data)),
                    "wavenumber_max": float(np.max(x_data)),
                    "n_points": len(x_data),
                }
        except Exception:
            pass

    return metadata


# =============================================================================
# Data Source Nodes
# =============================================================================


@register_node
class DataSourceNode(Node):
    """
    Data Source node for loading spectral data.

    Loads spectral data from reference catalogs or direct files.
    """

    metadata = NodeMetadata(
        node_type="data.source",
        category="data",
        label="Data Source",
        description="Load spectral data from reference catalogs or direct files",
        parameters=[
            # PRIMARY SELECTION (Basic - Top of Inspector)
            NodeParameter(
                name="source",
                label="Source Type",
                param_type="select",
                default="spectrochempy",
                options=["spectrochempy", "sklearn", "eigenvector", "file"],
                description="Type of data source",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="example_dataset",
                label="Example Dataset",
                param_type="select",
                default="irdata",
                options=[
                    {"label": "IR Spectroscopy", "value": "irdata"},
                    {"label": "Raman Spectroscopy", "value": "ramandata"},
                    {"label": "NMR (Bruker TopSpin)", "value": "nmrdata"},
                    {"label": "Galactic SPC Files", "value": "galacticdata"},
                    {"label": "Agilent IR (AGIR)", "value": "agirdata"},
                    {"label": "MATLAB Datasets", "value": "matlabdata"},
                    {"label": "Mass Spectrometry", "value": "msdata"},
                ],
                description="SpectroChemPy example dataset category to load",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="sklearn_dataset",
                label="Sklearn Dataset",
                param_type="select",
                default="iris",
                options=[
                    {"label": "Iris (3 species, 4 features, 150 samples)", "value": "iris"},
                    {"label": "Wine (3 classes, 13 features, 178 samples)", "value": "wine"},
                    {"label": "Breast Cancer (2 classes, 30 features, 569 samples)", "value": "breast_cancer"},
                    {"label": "Digits (10 classes, 64 features, 1797 samples)", "value": "digits"},
                ],
                description="Scikit-learn dataset to load via SpectroChemPy (for testing PCA, classification, etc.)",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="eigenvector_dataset",
                label="Eigenvector Dataset",
                param_type="select",
                default="diesel_nir",
                options=[
                    {"label": v["label"], "value": k}
                    for k, v in DATASET_CATALOG.items()
                ],
                description="Eigenvector Research public dataset (bundled reference data with properties)",
                required=False,
                category="basic",
            ),
            # EXPERIMENT/FILE/LIBRARY OPTIONS (Advanced)
            NodeParameter(
                name="experiment_id",
                label="Experiment ID",
                param_type="number",
                default=None,
                description="ID of experiment to load data from",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="file_id",
                label="File ID",
                param_type="number",
                default=None,
                description="Specific file ID to load from experiment",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="stage",
                label="Data Stage",
                param_type="select",
                default="raw",
                options=["raw", "preprocessed", "synthetic"],
                description="Stage of data to load from experiment",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="library_id",
                label="Library Entry ID",
                param_type="number",
                default=None,
                description="ID of NIST library entry to load",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="file_path",
                label="File Path",
                param_type="text",
                default="",
                description="Path to data file (CSV, JDX, SPA, etc.)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="example_file",
                label="Example File",
                param_type="text",
                default="",
                description="Specific file within the selected dataset (e.g., 'CO@Mo_Al2O3.SPG'). Leave empty for default file.",
                required=False,
                category="advanced",
            ),
            # DATA MANIPULATION OPTIONS (Advanced)
            NodeParameter(
                name="transpose_on_load",
                label="Transpose on Load",
                param_type="boolean",
                default=False,
                description="Swap rows/columns if data is (n_wavenumbers, n_samples) instead of (n_samples, n_wavenumbers)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="sample_axis_title",
                label="Sample Axis Title (Override)",
                param_type="text",
                default="",
                description="Override sample axis (y-axis) title. Leave empty to use source title.",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="spectral_axis_title",
                label="Spectral Axis Title (Override)",
                param_type="text",
                default="",
                description="Override spectral axis (x-axis) title. Leave empty to use source title.",
                required=False,
                category="advanced",
            ),
        ],
        input_types=[],  # No inputs - this is a source node
        output_type="dict",  # Multi-output: dataset + optional target labels
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Loaded dataset",
            ),
            PortMetadata(
                name="target",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Target Labels",
                description="Class/target labels if available (e.g., sklearn datasets)",
            ),
        ],
    )

    async def execute(self, *args) -> Any:
        """
        Execute data loading.

        Returns:
            NDDataset containing the loaded spectral data
        """
        source = self.parameters.get("source", "spectrochempy")
        experiment_id = self.parameters.get("experiment_id")
        file_id = self.parameters.get("file_id")
        stage = self.parameters.get("stage", "raw")
        library_id = self.parameters.get("library_id")
        file_path = self.parameters.get("file_path", "")
        example_dataset = self.parameters.get("example_dataset", "irdata")
        example_file = self.parameters.get("example_file", "")
        sklearn_dataset = self.parameters.get("sklearn_dataset", "iris")

        # Load data based on source
        if source == "spectrochempy":
            require_scp("SpectroChemPy example dataset loading")
            # Single file loading only - use LoadGroupNode for multiple files
            if example_file and self._is_pattern(example_file):
                raise ValueError(
                    f"Pattern detected in example_file: '{example_file}'\n\n"
                    f"DataSourceNode is for loading single files only.\n"
                    f"For loading multiple files with patterns, use the LoadGroupNode instead:\n"
                    f"  - Drag 'Load Group' node from the node palette\n"
                    f"  - Set folder_path to the folder (e.g., 'irdata/carroucell_samp')\n"
                    f"  - Set pattern to your desired pattern (e.g., '*.spa', 'sample_*')\n\n"
                    f"LoadGroupNode provides additional features:\n"
                    f"  - Sort options (filename, numeric suffix, modification time)\n"
                    f"  - X-axis validation\n"
                    f"  - Recursive subdirectory scanning\n"
                    f"  - Custom group titles"
                )
            dataset = self._load_spectrochempy_example(example_dataset, example_file)
        elif source == "sklearn":
            dataset = self._load_sklearn_dataset(sklearn_dataset)
        elif source == "eigenvector":
            eigenvector_dataset = self.parameters.get("eigenvector_dataset", "diesel_nir")
            dataset = self._load_eigenvector_dataset(eigenvector_dataset)
        elif source == "experiment" and experiment_id:
            require_scp("Spectral file reading")
            dataset = await self._load_from_experiment(experiment_id, file_id, stage)
        elif source == "library" and library_id:
            require_scp("Spectral file reading")
            dataset = await self._load_from_library(library_id)
        elif source == "file" and file_path:
            require_scp("Spectral file reading")
            dataset = self._load_from_file(file_path)
        elif source == "synthetic":
            dataset = self._generate_synthetic()
        else:
            raise ValueError(
                "Invalid or incomplete data source configuration. "
                f"source={source!r}, experiment_id={experiment_id}, "
                f"library_id={library_id}, file_path={file_path!r}"
            )

        # ----- Non-NDDataset fast path (no SCP) -----
        # When data is a raw numpy array or AnalysisDataset, ensure uniform container.
        if not isinstance(dataset, NDDataset):
            target = None
            if source == "sklearn" and hasattr(self, "_sklearn_bunch"):
                dataset = from_sklearn_bunch(self._sklearn_bunch, name=sklearn_dataset)
                target = self._sklearn_bunch.target.tolist()
            elif source == "eigenvector" and hasattr(self, "_eigenvector_properties"):
                target = self._eigenvector_properties
                # _load_eigenvector_dataset already returns AnalysisDataset in no-SCP mode
                if not isinstance(dataset, AnalysisDataset):
                    dataset = AnalysisDataset(X=dataset, backend="numpy")
            elif isinstance(dataset, AnalysisDataset):
                pass  # Already wrapped (e.g., eigenvector no-SCP, synthetic)
            else:
                # Generic numpy array (e.g., synthetic no-SCP)
                dataset = AnalysisDataset(X=dataset, backend="numpy")
            # Apply axis config on AnalysisDataset too
            if isinstance(dataset, AnalysisDataset):
                dataset = self._apply_axis_config(dataset)

            # Initialize provenance with data.source step (matches NDDataset path)
            if isinstance(dataset, AnalysisDataset):
                add_processing_step(
                    dataset,
                    "data.source",
                    {
                        "source": source,
                        "sklearn_dataset": sklearn_dataset if source == "sklearn" else None,
                        "eigenvector_dataset": self.parameters.get("eigenvector_dataset") if source == "eigenvector" else None,
                    },
                    node_id=self.node_id,
                    input_shape=None,
                )

            return {"default": dataset, "target": target}

        # ----- NDDataset path (SCP available) -----
        # Apply axis configuration
        dataset = self._apply_axis_config(dataset)

        # Initialize or MERGE provenance tracking for the data pipeline
        # IMPORTANT: Preserve any existing provenance from the loaded file
        # (e.g., OPUS/JCAMP files may carry instrument metadata in dataset.meta)
        if not hasattr(dataset, 'meta') or dataset.meta is None:
            dataset.meta = {}

        # Create the data.source step
        source_step = {
            "operation": "data.source",
            "parameters": {
                "source": source,
                "example_dataset": example_dataset if source == "spectrochempy" else None,
                "sklearn_dataset": sklearn_dataset if source == "sklearn" else None,
                "eigenvector_dataset": self.parameters.get("eigenvector_dataset") if source == "eigenvector" else None,
                "experiment_id": experiment_id if source == "experiment" else None,
                "file_path": file_path if source == "file" else None,
            },
            "timestamp": datetime.utcnow().isoformat(),
            "node_id": self.node_id,
            "input_shape": None,  # No input for source node
            "output_shape": list(dataset.shape),
        }

        # MERGE with existing processing_history (don't overwrite!)
        try:
            existing_history = dataset.meta.get("processing_history", [])
            if existing_history:
                # Prepend source step to existing history (this load is the new origin)
                dataset.meta["processing_history"] = [source_step] + existing_history
            else:
                dataset.meta["processing_history"] = [source_step]
        except (TypeError, AttributeError):
            # Some dataset meta containers are immutable; replace with a mutable copy when possible.
            try:
                mutable_meta = dict(dataset.meta)
                existing_history = mutable_meta.get("processing_history", [])
                if existing_history:
                    mutable_meta["processing_history"] = [source_step] + existing_history
                else:
                    mutable_meta["processing_history"] = [source_step]
                dataset.meta = mutable_meta
            except Exception:
                logger.debug(
                    "Could not write processing_history to dataset.meta for %s",
                    getattr(dataset, "name", "<unknown>"),
                )

        # MERGE provenance summary - PRESERVE all existing fields from file metadata
        existing_provenance = dataset.meta.get("provenance", {})
        if not isinstance(existing_provenance, dict):
            existing_provenance = {}

        existing_operations = existing_provenance.get("operations", [])

        # Start with existing provenance to preserve all file-extracted fields
        # (operator, original_title, original_file_path, lab_name, etc.)
        merged_provenance = dict(existing_provenance)

        # CRITICAL: Preserve original_source_type if this is a re-load
        # Don't overwrite rich provenance (e.g., "opus" -> "experiment")
        original_source_type = (
            existing_provenance.get("original_source_type") or
            existing_provenance.get("source_type") or
            existing_provenance.get("original_source")
        )

        # Add/update processing-related fields - use .setdefault() to not overwrite existing
        # Only add current_source_type, preserve original_source_type chain
        merged_provenance["current_source_type"] = source
        if original_source_type:
            merged_provenance["original_source_type"] = original_source_type
        # Keep source_type for backwards compat but set to original if available
        merged_provenance["source_type"] = original_source_type or source
        merged_provenance["original_source"] = original_source_type or source
        merged_provenance["operations"] = ["data.source"] + existing_operations
        merged_provenance["last_modified"] = datetime.utcnow().isoformat()
        merged_provenance["last_operation"] = "data.source"

        dataset.meta["provenance"] = merged_provenance

        if source == "sklearn":
            target = self._extract_target_labels(dataset)
        elif source == "eigenvector" and hasattr(self, "_eigenvector_properties"):
            target = self._eigenvector_properties
        else:
            target = None

        # NOTE: data.source step is already recorded in processing_history
        # above (lines 589-612) via the manual merge.  Do NOT call
        # add_processing_step() here — that would create a duplicate entry.

        return {
            "default": dataset,
            "target": target,
        }

    def _extract_target_labels(self, dataset: NDDataset) -> Any:
        """
        Extract target labels from an NDDataset if present.

        Prefers y-axis labels over y-axis data.
        """
        etl_y_coord = safe_get_coord(dataset, 'y')
        if etl_y_coord is not None:
            if hasattr(etl_y_coord, "labels") and etl_y_coord.labels is not None:
                labels = etl_y_coord.labels
                if hasattr(labels, "tolist"):
                    return labels.tolist()
                return list(labels)
            if hasattr(etl_y_coord, "data") and etl_y_coord.data is not None:
                data = np.array(etl_y_coord.data)
                if data.size > 0:
                    return data.tolist()
        return None

    def _apply_axis_config(self, dataset):
        """
        Apply axis configuration: transpose and custom axis titles.

        Preserves original axis titles from source data unless explicitly overridden.
        Works with both NDDataset and AnalysisDataset.

        Args:
            dataset: Input dataset (NDDataset or AnalysisDataset)

        Returns:
            Configured dataset with correct axis orientation and titles
        """
        # Get parameters - empty string means "preserve source title"
        transpose_on_load = self.parameters.get("transpose_on_load", False)
        sample_axis_override = self.parameters.get("sample_axis_title", "").strip()
        spectral_axis_override = self.parameters.get("spectral_axis_title", "").strip()

        is_ads = isinstance(dataset, AnalysisDataset)

        # Transpose if requested (swap rows and columns)
        if transpose_on_load:
            if is_ads:
                dataset = AnalysisDataset(
                    X=dataset.X.T,
                    x_axis=dataset.y_axis,
                    y_axis=dataset.x_axis,
                    meta=dict(dataset.meta),
                    provenance=list(dataset.provenance),
                    backend=dataset.backend,
                    title=dataset.title,
                    units=dataset.units,
                )
            else:
                dataset = dataset.T
            logger.debug(f"[DATA] Transposed data to {dataset.shape[0]} samples × {dataset.shape[1]} features")

        if dataset.ndim >= 2:
            current_y = safe_get_coord(dataset, 'y')
            current_x = safe_get_coord(dataset, 'x')

            # Determine y-axis (sample) title
            if sample_axis_override:
                y_title = sample_axis_override
            elif current_y is not None and hasattr(current_y, 'title') and current_y.title:
                y_title = current_y.title
            else:
                y_title = "Sample"

            # Determine x-axis (spectral/feature) title
            if spectral_axis_override:
                x_title = spectral_axis_override
            elif current_x is not None and hasattr(current_x, 'title') and current_x.title:
                x_title = current_x.title
            else:
                x_title = "Feature"

            if is_ads:
                # AnalysisDataset: set AxisInfo directly
                if current_y is not None:
                    if current_y.title != y_title:
                        dataset.y_axis = AxisInfo(
                            values=current_y.values if hasattr(current_y, 'values') else current_y.data if hasattr(current_y, 'data') else None,
                            labels=current_y.labels if hasattr(current_y, 'labels') else None,
                            units=current_y.units if hasattr(current_y, 'units') else None,
                            title=y_title,
                        )
                else:
                    dataset.y_axis = AxisInfo(
                        values=np.arange(dataset.shape[0]),
                        title=y_title,
                    )

                if current_x is not None:
                    if current_x.title != x_title:
                        dataset.x_axis = AxisInfo(
                            values=current_x.values if hasattr(current_x, 'values') else current_x.data if hasattr(current_x, 'data') else None,
                            labels=current_x.labels if hasattr(current_x, 'labels') else None,
                            units=current_x.units if hasattr(current_x, 'units') else None,
                            title=x_title,
                        )
                else:
                    dataset.x_axis = AxisInfo(
                        values=np.arange(dataset.shape[1]),
                        title=x_title,
                    )
            else:
                # NDDataset: use SCP Coord + set_coordset
                if current_y is not None:
                    try:
                        if current_y.title != y_title:
                            current_y.title = y_title
                    except (AttributeError, TypeError):
                        pass
                else:
                    dataset.set_coordset(
                        y=scp.Coord(np.arange(dataset.shape[0]), title=y_title),
                        x=current_x
                    )
                    current_y = safe_get_coord(dataset, 'y')

                if current_x is not None:
                    try:
                        if current_x.title != x_title:
                            current_x.title = x_title
                    except (AttributeError, TypeError):
                        pass
                else:
                    dataset.set_coordset(
                        y=current_y,
                        x=scp.Coord(np.arange(dataset.shape[1]), title=x_title)
                    )

        elif dataset.ndim == 1:
            # For 1D data, only x-axis
            aac_1d_x_coord = safe_get_coord(dataset, 'x')
            if spectral_axis_override:
                x_title = spectral_axis_override
            elif aac_1d_x_coord is not None and hasattr(aac_1d_x_coord, 'title') and aac_1d_x_coord.title:
                x_title = aac_1d_x_coord.title
            else:
                x_title = "Feature"

            if is_ads:
                if aac_1d_x_coord is not None:
                    if aac_1d_x_coord.title != x_title:
                        dataset.x_axis = AxisInfo(
                            values=aac_1d_x_coord.values if hasattr(aac_1d_x_coord, 'values') else aac_1d_x_coord.data if hasattr(aac_1d_x_coord, 'data') else None,
                            title=x_title,
                        )
                else:
                    dataset.x_axis = AxisInfo(
                        values=np.arange(dataset.shape[0]),
                        title=x_title,
                    )
            else:
                if aac_1d_x_coord is not None:
                    if aac_1d_x_coord.title != x_title:
                        aac_1d_x_coord.title = x_title
                else:
                    dataset.set_coordset(
                        x=scp.Coord(np.arange(dataset.shape[0]), title=x_title)
                    )

        return dataset

    def _load_sklearn_dataset(self, dataset_name: str):
        """
        Load a scikit-learn benchmark dataset.

        When SpectroChemPy is available, uses its wrappers which return
        NDDataset objects with rich metadata.  When absent, loads directly
        from scikit-learn and returns a numpy array.

        Args:
            dataset_name: Name of sklearn dataset (iris, wine, breast_cancer, digits)

        Returns:
            NDDataset (with SCP) or numpy array (without SCP)

        Raises:
            ValueError: If dataset_name is not supported
        """
        from sklearn import datasets as sk_datasets

        _loaders = {
            "iris": sk_datasets.load_iris,
            "wine": sk_datasets.load_wine,
            "breast_cancer": sk_datasets.load_breast_cancer,
            "digits": sk_datasets.load_digits,
        }

        if dataset_name not in _loaders:
            raise ValueError(
                f"Unsupported sklearn dataset: {dataset_name}\n"
                f"Supported datasets: {', '.join(_loaders)}"
            )

        if HAS_SCP:
            # Rich path: SpectroChemPy wrappers return NDDataset with metadata
            logger.debug("[DATA] Loading sklearn dataset via SpectroChemPy: %s", dataset_name)
            try:
                scp_loader = getattr(scp, f"load_{dataset_name}", None)
                if scp_loader is None:
                    raise AttributeError(f"scp.load_{dataset_name} not found")
                dataset = scp_loader()
                if dataset is None:
                    raise ValueError(f"SpectroChemPy returned None for {dataset_name}")
                logger.debug("[DATA] Loaded %s: %s", dataset_name, dataset.shape)
                return dataset
            except (AttributeError, Exception) as e:
                logger.warning(
                    "[DATA] SCP loader failed for %s, falling back to sklearn: %s",
                    dataset_name, e,
                )
                # Fall through to direct sklearn path

        # Direct sklearn path — no SCP required
        logger.debug("[DATA] Loading sklearn dataset directly: %s", dataset_name)
        bunch = _loaders[dataset_name]()
        # Store target on the instance so _extract_target_labels_sklearn can get it
        self._sklearn_bunch = bunch
        logger.debug(
            "[DATA] Loaded %s: %d samples × %d features",
            dataset_name, bunch.data.shape[0], bunch.data.shape[1],
        )
        return bunch.data  # numpy array

    def _load_eigenvector_dataset(self, dataset_name: str):
        """
        Load an Eigenvector Research public benchmark dataset.

        When SpectroChemPy is available, wraps in NDDataset with wavelength
        Coord axes. Otherwise returns raw numpy array.

        Args:
            dataset_name: Name from DATASET_CATALOG (diesel_nir, corn_m5, etc.)

        Returns:
            NDDataset (with SCP) or numpy array (without SCP)
        """
        from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset

        result = load_eigenvector_dataset(dataset_name)
        spectra = result["spectra"]
        properties = result["properties"]
        wavelengths = result["wavelengths"]
        catalog = result["catalog_entry"]

        # Store properties for the target output port
        if properties is not None:
            self._eigenvector_properties = {
                "data": properties.tolist(),
                "columns": result.get("prop_names") or [],
            }

        if HAS_SCP:
            # Rich path: wrap in NDDataset with wavelength Coord
            x_title = catalog.get("x_title", "Channel")
            x_units = catalog.get("x_units")

            if wavelengths is not None and len(wavelengths) == spectra.shape[1]:
                x_coord = scp.Coord(
                    wavelengths,
                    title=x_title,
                    units=x_units if x_units else None,
                )
            else:
                x_coord = scp.Coord(
                    np.arange(spectra.shape[1]),
                    title=x_title,
                )

            y_coord = scp.Coord(
                np.arange(spectra.shape[0]),
                title="Sample",
            )

            dataset = scp.NDDataset(spectra, coordset=[y_coord, x_coord])
            dataset.name = catalog.get("label", dataset_name)
            dataset.description = catalog.get("description", "")

            logger.debug(
                "[DATA] Loaded Eigenvector %s via SCP: %s (%s)",
                dataset_name, dataset.shape, catalog.get("technique", ""),
            )
            return dataset

        # No-SCP path: return AnalysisDataset with proper axes
        x_title = catalog.get("x_title", "Channel")
        x_units = catalog.get("x_units")
        x_values = wavelengths if wavelengths is not None and len(wavelengths) == spectra.shape[1] else np.arange(spectra.shape[1])

        dataset = AnalysisDataset(
            X=spectra,
            x_axis=AxisInfo(values=x_values, title=x_title, units=x_units),
            y_axis=AxisInfo(values=np.arange(spectra.shape[0]), title="Sample"),
            backend="numpy",
            title=catalog.get("label", dataset_name),
        )
        logger.debug(
            "[DATA] Loaded Eigenvector %s: %d samples × %d features",
            dataset_name, spectra.shape[0], spectra.shape[1],
        )
        return dataset

    def _load_spectrochempy_example(self, example_name: str, example_file: str = "") -> NDDataset:
        """Load a SpectroChemPy example dataset from discovered testdata folders."""
        require_scp("SpectroChemPy example datasets")

        # If a specific file is requested, load it directly.
        if example_file:
            full_file_path = f"{example_name}/{example_file}" if "/" not in example_file else example_file
            return self._load_spectrochempy_custom_file(full_file_path)

        # Try known, verified defaults first.
        if example_name in _SCP_KNOWN_DEFAULTS:
            rel_path, reader_name = _SCP_KNOWN_DEFAULTS[example_name]
            resolved = resolve_scp_path(rel_path)
            if resolved is not None:
                reader_fn = getattr(scp, reader_name, None)
                if callable(reader_fn):
                    try:
                        dataset = _normalize_scp_read_output(reader_fn(str(resolved)))
                    except Exception:
                        dataset = None
                    if dataset is not None:
                        return dataset

        # Generic fallback: first loadable file in dataset folder.
        for datadir in get_scp_datadirs():
            folder = datadir / example_name
            if not folder.exists() or not folder.is_dir():
                continue
            dataset = _try_load_first_file(folder)
            if dataset is not None:
                return dataset

        raise ValueError(
            f"No loadable files found for '{example_name}'.\n"
            "Ensure SpectroChemPy data is downloaded:\n"
            "  python -c \"from spectra_sherpa.app.lib.scp_compat import download_testdata; download_testdata()\""
        )

    def _load_spectrochempy_custom_file(self, file_path: str) -> NDDataset:
        """
        Load a custom file from the SpectroChemPy data directory.

        Args:
            file_path: Path relative to spectrochempy datadir (e.g., "irdata/CO@Mo_Al2O3.SPG")

        Returns:
            NDDataset loaded from the specified file
        """
        requested_path = Path(file_path).expanduser()
        candidate_paths = []

        if requested_path.is_absolute():
            candidate_paths.append(requested_path)
        else:
            candidate_paths.extend(datadir / file_path for datadir in get_scp_datadirs())

        full_path = next((path for path in candidate_paths if path.exists()), None)
        if full_path is None:
            attempted = "\n".join(f"  - {path}" for path in candidate_paths)
            raise ValueError(
                f"File not found: {file_path}\n"
                f"Attempted paths:\n{attempted}\n"
                "Please verify the file exists in the SpectroChemPy data directory."
            )

        try:
            # For directories (Bruker NMR format), read the directory
            if full_path.is_dir():
                dataset = _normalize_scp_read_output(scp.read(str(full_path)))
                if dataset is None:
                    raise ValueError(f"scp.read() returned no NDDataset for directory: {file_path}")
                logger.debug(f"Loaded NMR dataset from directory: {file_path}")
                dataset.title = file_path.replace("/", " / ")
                return dataset

            # Use centralized reader mapping for file extensions
            from spectra_sherpa.app.core.config import get_reader_for_extension

            ext = full_path.suffix
            reader_name = get_reader_for_extension(ext)
            reader_method = getattr(scp, reader_name)

            dataset = _normalize_scp_read_output(reader_method(str(full_path)))
            if dataset is None and reader_name != "read":
                dataset = _normalize_scp_read_output(scp.read(str(full_path)))
            logger.debug(f"Loaded {ext} dataset using {reader_name}: {file_path}")

            # Post-processing for specific formats
            if ext.lower() == ".csv":
                dataset = remove_index_columns(dataset)

            if dataset is None:
                raise ValueError(f"Reader {reader_name} returned no NDDataset for {file_path}")

            # Set a meaningful title
            dataset.title = file_path.replace("/", " / ")

            return dataset

        except Exception as e:
            raise ValueError(
                f"Failed to load {file_path}: {str(e)}\n"
                f"File type: {full_path.suffix}\n"
                f"Full path: {full_path}"
            ) from e

    def _is_pattern(self, file_path: str) -> bool:
        """
        Detect if file_path contains wildcards or indicates folder loading.

        Patterns include:
        - Wildcards: * or ?
        - Folder indicator: trailing /
        - Example: "irdata/*.spa", "irdata/sample_*", "irdata/"

        Args:
            file_path: Path string to check

        Returns:
            True if pattern detected, False otherwise
        """
        return '*' in file_path or '?' in file_path or file_path.endswith('/')

    def _load_spectrochempy_group(self, example_dataset: str, pattern: str) -> NDDataset:
        """
        Load multiple files from SpectroChemPy example dataset using pattern.

        This method provides smart pattern matching for the DataSourceNode,
        enabling users to load groups of files without using LoadGroupNode directly.

        Supported patterns:
        - "irdata/" - Load all files from irdata folder
        - "irdata/*.spa" - Load all .spa files from irdata
        - "irdata/sample_*" - Load all files matching sample_*

        Args:
            example_dataset: Dataset name (e.g., "irdata", "galacticdata")
            pattern: Pattern string (e.g., "/*.spa", "/sample_*", "/")

        Returns:
            NDDataset with all matching files concatenated along sample axis
        """
        import re

        # Parse pattern to extract folder and glob pattern
        if pattern.endswith('/'):
            # Folder indicator: load all files from specified folder
            # Remove trailing slash and use as folder path
            folder_path = pattern.rstrip('/')
            glob_pattern = '*'
        elif '/' in pattern:
            # Pattern with subfolder: "irdata/subfolder/*.spa"
            parts = pattern.rsplit('/', 1)
            folder_path = parts[0] if parts[0] else example_dataset
            glob_pattern = parts[1] if len(parts) > 1 else '*'
        else:
            # Just a pattern: "*.spa" - apply to example_dataset
            folder_path = example_dataset
            glob_pattern = pattern

        logger.debug(f"[DATA] Pattern detected: folder={folder_path}, pattern={glob_pattern}")

        # Resolve folder path across configured SCP datadirs.
        candidate_paths = [datadir / folder_path for datadir in get_scp_datadirs()]

        folder = next((p for p in candidate_paths if p.exists()), None)

        if folder is None:
            attempted = "\n".join(f"  - {p}" for p in candidate_paths)
            raise ValueError(
                f"Folder not found: {folder_path}\n"
                f"Attempted paths:\n{attempted}\n"
                f"Please verify the folder exists in the SpectroChemPy data directory."
            )

        # Find all matching files (case-insensitive)
        # Use case-insensitive matching to handle both .spa and .SPA extensions
        import fnmatch

        # Get all files in folder (non-recursive for DataSourceNode)
        all_files = list(folder.iterdir())

        # Filter with case-insensitive matching
        files = []
        for f in all_files:
            # Skip directories, hidden files, and system files
            if not f.is_file() or f.name.startswith(('.', '__')):
                continue

            # Case-insensitive pattern matching
            if '*' in glob_pattern or '?' in glob_pattern:
                # Wildcard pattern - use fnmatch
                if fnmatch.fnmatch(f.name.lower(), glob_pattern.lower()):
                    files.append(f)
            else:
                # Exact match - case-insensitive
                if f.name.lower() == glob_pattern.lower():
                    files.append(f)

        if not files:
            raise ValueError(
                f"No files found matching pattern '{glob_pattern}' in {folder}\n"
                f"(Case-insensitive search performed)\n"
                f"Please verify the pattern matches existing files."
            )

        logger.debug(f"[DATA] Found {len(files)} files matching pattern '{glob_pattern}'")

        # Sort alphabetically
        files.sort(key=lambda f: f.name.lower())

        # Load all files using centralized reader
        datasets = []
        file_names = []

        for i, file_path in enumerate(files, 1):
            try:
                logger.debug(f"[DATA] Loading {i}/{len(files)}: {file_path.name}")

                # Use centralized reader
                from spectra_sherpa.app.core.config import get_reader_for_extension

                ext = file_path.suffix
                reader_name = get_reader_for_extension(ext)
                reader_method = getattr(scp, reader_name)

                dataset = reader_method(str(file_path))

                if dataset is None:
                    raise ValueError(f"Reader {reader_name} returned None for {file_path.name}")

                # Post-processing
                if ext.lower() == ".csv":
                    dataset = remove_index_columns(dataset)
                elif ext.lower() == ".mat":
                    dataset = extract_dataset_from_result(dataset, str(file_path))
                    dataset = remove_index_columns(dataset)

                dataset.title = file_path.stem
                datasets.append(dataset)
                file_names.append(file_path.name)

            except Exception as e:
                # Fail-fast: stop on first error
                error_msg = (
                    f"❌ Failed to load file {i}/{len(files)}: {file_path.name}\n"
                    f"Error: {str(e)}\n\n"
                    f"Stopped loading remaining files (fail-fast policy).\n"
                    f"Successfully loaded: {len(datasets)}/{len(files)} files"
                )
                raise ValueError(error_msg) from e

        # Validate x-axes match (strict validation)
        if len(datasets) > 1:
            self._validate_group_axes(datasets, file_names)

        # Custom concatenation to avoid SpectroChemPy's unit compatibility issues
        # Concatenate numpy arrays directly and create new NDDataset
        try:
            # Extract data arrays and squeeze out singleton dimensions
            data_arrays = [np.squeeze(np.array(ds.data)) for ds in datasets]

            # Ensure all arrays are at least 1D (in case of scalar data)
            data_arrays = [arr if arr.ndim > 0 else np.array([arr]) for arr in data_arrays]

            # Ensure all arrays are 2D (n_spectra, n_wavenumbers)
            # This handles both single-spectrum files (1D) and multi-spectrum files (2D)
            data_arrays_2d = []
            for i, arr in enumerate(data_arrays):
                if arr.ndim == 1:
                    # Single spectrum: reshape to (1, n_wavenumbers)
                    data_arrays_2d.append(arr.reshape(1, -1))
                elif arr.ndim == 2:
                    # Multi-spectrum: keep as is (n_spectra, n_wavenumbers)
                    data_arrays_2d.append(arr)
                else:
                    raise ValueError(
                        f"Unexpected array dimensionality in file {i+1}: shape {arr.shape}. "
                        f"Expected 1D or 2D array."
                    )

            # Concatenate along sample axis (axis=0) to get 2D (total_spectra, n_wavenumbers)
            concatenated_data = np.concatenate(data_arrays_2d, axis=0)

            # Generate y-axis labels accounting for multi-spectrum files
            y_labels = []
            for i, (arr, file_name) in enumerate(zip(data_arrays_2d, file_names)):
                # Use .name instead of .stem to preserve OPUS-style extensions (.0000, .0001, etc.)
                # For files like "test.0000", Path.stem would give "test" but Path.name gives "test.0000"
                file_label = Path(file_name).name
                n_spectra = arr.shape[0]
                if n_spectra == 1:
                    # Single spectrum: use file name
                    y_labels.append(file_label)
                else:
                    # Multi-spectrum: add spectrum index
                    for j in range(n_spectra):
                        y_labels.append(f"{file_label}_{j+1}")

            total_spectra = concatenated_data.shape[0]
            logger.debug(f"[DATA] Concatenated {len(datasets)} files ({total_spectra} spectra) into shape {concatenated_data.shape}")

            # Create new NDDataset with stacked data
            concatenated = scp.NDDataset(concatenated_data)

            # Copy x-axis from reference (all validated to be identical)
            lsg_ref_x_coord = safe_get_coord(datasets[0], 'x')
            if lsg_ref_x_coord is not None:
                concatenated.x = lsg_ref_x_coord.copy()

            # Set units from reference if available
            if hasattr(datasets[0], 'units') and datasets[0].units is not None:
                concatenated.units = datasets[0].units

        except Exception as e:
            raise ValueError(
                f"Failed to concatenate datasets.\n"
                f"Error: {str(e)}\n"
                f"All files loaded successfully but concatenation failed."
            ) from e

        # Set title and y-axis labels
        concatenated.title = f"{folder.name} ({len(datasets)} files, {total_spectra} spectra)"

        lsg_cat_y_coord = safe_get_coord(concatenated, 'y')
        if lsg_cat_y_coord is not None:
            lsg_cat_y_coord.title = "Sample"
            lsg_cat_y_coord.labels = y_labels
        else:
            lsg_cat_x_coord = safe_get_coord(concatenated, 'x')
            concatenated.set_coordset(
                y=scp.Coord(
                    np.arange(len(y_labels)),
                    title="Sample",
                    labels=y_labels
                ),
                x=lsg_cat_x_coord
            )

        return concatenated

    def _validate_group_axes(self, datasets: list[NDDataset], file_names: list[str]) -> None:
        """
        Validate that all datasets have identical x-axes for concatenation.

        Args:
            datasets: List of loaded datasets
            file_names: List of file names (for error messages)

        Raises:
            ValueError: If x-axes don't match
        """
        if len(datasets) < 2:
            return

        reference = datasets[0]
        reference_name = file_names[0]

        vga_ref_x_coord = safe_get_coord(reference, 'x')
        if vga_ref_x_coord is None:
            raise ValueError(
                f"Reference file '{reference_name}' has no x-axis.\n"
                f"Cannot validate axes for group loading."
            )

        reference_x = np.array(vga_ref_x_coord.data)

        for i, (dataset, file_name) in enumerate(zip(datasets[1:], file_names[1:]), 2):
            vga_ds_x_coord = safe_get_coord(dataset, 'x')
            if vga_ds_x_coord is None:
                raise ValueError(
                    f"File {i}/{len(datasets)}: '{file_name}' has no x-axis.\n"
                    f"All files must have x-axis coordinates for group loading."
                )

            dataset_x = np.array(vga_ds_x_coord.data)

            if dataset_x.shape != reference_x.shape:
                raise ValueError(
                    f"X-axis mismatch:\n"
                    f"File {i}: '{file_name}' has {len(dataset_x)} points\n"
                    f"Reference: '{reference_name}' has {len(reference_x)} points\n"
                    f"All files must have identical x-axes for group loading."
                )

            if not np.allclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12):
                mismatch_idx = np.where(~np.isclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12))[0][0]
                raise ValueError(
                    f"X-axis values mismatch at index {mismatch_idx}:\n"
                    f"  {reference_name}: {reference_x[mismatch_idx]:.6f}\n"
                    f"  {file_name}: {dataset_x[mismatch_idx]:.6f}\n"
                    f"All files must have identical x-axis values."
                )

        logger.debug(f"[DATA] X-axis validation passed for {len(datasets)} files")

    def _generate_ftir_synthetic(self) -> NDDataset:
        """Generate realistic FTIR-like synthetic data."""
        n_samples = 55  # Typical activation series
        n_wavenumbers = 5549  # High resolution

        # FTIR wavenumber range
        wavenumbers = np.linspace(6000, 650, n_wavenumbers)

        spectra = np.zeros((n_samples, n_wavenumbers))

        # Simulate NH4Y zeolite activation (decreasing NH4+ peaks with temperature)
        for i in range(n_samples):
            temp_factor = i / n_samples  # 0 to 1 as temperature increases
            base = 0.2 + np.random.rand() * 0.05
            noise = np.random.randn(n_wavenumbers) * 0.005

            # OH stretching region (3000-3800 cm-1) - increases with activation
            oh_peak = (0.3 + temp_factor * 0.5) * np.exp(-((wavenumbers - 3650) ** 2) / (2 * 80 ** 2))
            oh_peak2 = (0.2 + temp_factor * 0.3) * np.exp(-((wavenumbers - 3550) ** 2) / (2 * 100 ** 2))

            # NH4+ peaks (1400-1500 cm-1) - decreases with activation
            nh4_peak = (0.6 - temp_factor * 0.5) * np.exp(-((wavenumbers - 1450) ** 2) / (2 * 40 ** 2))

            # Si-O-Si framework (1000-1200 cm-1) - relatively constant
            sio_peak = 0.8 * np.exp(-((wavenumbers - 1050) ** 2) / (2 * 100 ** 2))

            # Water bending (1640 cm-1) - decreases with activation
            h2o_peak = (0.3 - temp_factor * 0.25) * np.exp(-((wavenumbers - 1640) ** 2) / (2 * 30 ** 2))

            spectra[i] = base + oh_peak + oh_peak2 + nh4_peak + sio_peak + h2o_peak + noise

        dataset = scp.NDDataset(spectra)
        dataset.set_coordset(
            y=scp.Coord(np.linspace(25, 300, n_samples), title="Temperature", units="degC"),
            x=scp.Coord(wavenumbers, title="Wavenumber", units="cm^-1"),
        )
        dataset.title = "NH4Y Zeolite Activation (Synthetic)"
        dataset.units = "absorbance"

        # Attach metadata
        meta = SpectraMeta(
            species=[
                SpeciesInfo(name="NH4Y Zeolite", state=PhysicalState.SOLID),
            ],
            conditions=ExperimentalConditions(
                temperature_c=25.0,  # Initial temperature
            ),
            acquisition=AcquisitionParams(
                resolution_cm=4.0,
                wavenumber_min=650.0,
                wavenumber_max=6000.0,
                n_points=n_wavenumbers,
            ),
            provenance=DataProvenance(
                source_type=SourceType.SYNTHETIC,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            is_ground_truth=True,
            processing_steps=["synthetic_generation"],
            custom={
                "synthetic_params": {
                    "type": "ftir_activation",
                    "n_samples": n_samples,
                    "temp_range_c": [25, 300],
                }
            },
        )
        set_spectra_meta(dataset, meta)

        return dataset

    def _generate_raman_synthetic(self) -> NDDataset:
        """Generate Raman-like synthetic data."""
        n_samples = 30
        n_wavenumbers = 1024

        # Raman shift range (typical)
        wavenumbers = np.linspace(100, 3200, n_wavenumbers)

        spectra = np.zeros((n_samples, n_wavenumbers))

        for i in range(n_samples):
            concentration = (i + 1) / n_samples
            noise = np.random.randn(n_wavenumbers) * 50

            # Simulate some typical Raman peaks
            peak1 = concentration * 1000 * np.exp(-((wavenumbers - 1000) ** 2) / (2 * 20 ** 2))
            peak2 = concentration * 800 * np.exp(-((wavenumbers - 1600) ** 2) / (2 * 30 ** 2))
            peak3 = concentration * 500 * np.exp(-((wavenumbers - 2900) ** 2) / (2 * 50 ** 2))

            spectra[i] = 100 + peak1 + peak2 + peak3 + noise

        dataset = scp.NDDataset(spectra)
        dataset.set_coordset(
            y=scp.Coord(np.arange(n_samples), title="Sample"),
            x=scp.Coord(wavenumbers, title="Raman Shift", units="cm^-1"),
        )
        dataset.title = "Raman Spectra (Synthetic)"
        dataset.units = "counts"

        # Attach metadata
        meta = SpectraMeta(
            acquisition=AcquisitionParams(
                wavenumber_min=100.0,
                wavenumber_max=3200.0,
                n_points=n_wavenumbers,
            ),
            provenance=DataProvenance(
                source_type=SourceType.SYNTHETIC,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            is_ground_truth=True,
            processing_steps=["synthetic_generation"],
            custom={
                "synthetic_params": {
                    "type": "raman_concentration_series",
                    "n_samples": n_samples,
                }
            },
        )
        set_spectra_meta(dataset, meta)

        return dataset

    async def _load_from_experiment(
        self, experiment_id: int, file_id: int | None = None, stage: str = "raw"
    ) -> NDDataset:
        """
        Load data from an experiment in the database.

        Args:
            experiment_id: ID of the experiment
            file_id: Specific file ID to load (if None, loads first file of the stage)
            stage: Data stage (raw, preprocessed, synthetic)
        """
        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.experiment_file import ExperimentFile
        from sqlalchemy import select

        async with async_session() as session:
            # Find experiment files for the specified stage
            query = select(ExperimentFile).where(
                ExperimentFile.experiment_id == experiment_id,
                ExperimentFile.stage == stage
            ).order_by(ExperimentFile.created_at)  # Deterministic ordering

            # If specific file_id is provided, filter by it
            if file_id is not None:
                query = query.where(ExperimentFile.id == file_id)

            result = await session.execute(query)
            files = result.scalars().all()

            if not files:
                raise ValueError(
                    f"No {stage} files found for experiment {experiment_id}. "
                    f"Please upload spectral data files to this experiment before loading."
                )

            # Load the first matching file (or the specific file if file_id was provided)
            file = files[0]

            # Build absolute path: file_path already includes stage subdirectory (e.g., "raw/filename.csv")
            exp_dir = f"exp_{str(experiment_id).zfill(3)}"
            full_path = settings.data_dir / "experiments" / exp_dir / file.file_path

            if not full_path.exists():
                raise FileNotFoundError(
                    f"File not found: {full_path}. "
                    f"File record exists in database but file is missing on disk."
                )

            return self._load_from_file(str(full_path))

    async def _load_from_library(self, library_id: int) -> NDDataset:
        """
        Load data from NIST library entry.

        Args:
            library_id: ID of the NIST library entry
        """
        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.nist_library import NistLibrary
        from sqlalchemy import select

        async with async_session() as session:
            # Find library entry
            query = select(NistLibrary).where(NistLibrary.id == library_id)
            result = await session.execute(query)
            library_entry = result.scalar_one_or_none()

            if not library_entry:
                raise ValueError(f"NIST library entry {library_id} not found in database.")

            # Build path to library file (file_path already includes "nist_library/" prefix)
            full_path = settings.data_dir / library_entry.file_path

            if not full_path.exists():
                raise FileNotFoundError(
                    f"Library file not found: {full_path}. "
                    f"File record exists in database but file is missing on disk."
                )

            return self._load_from_file(str(full_path))

    def _load_from_file(self, file_path: str) -> NDDataset:
        """
        Load data from a file with intelligent index column detection.

        Also extracts and normalizes instrument metadata from file headers
        (OPUS, JCAMP-DX, SPC, etc.) into SpectraMeta format.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"File not found: {file_path}. "
                f"Please verify the file exists and the path is correct."
            )

        ext = os.path.splitext(file_path)[1]

        try:
            # Use centralized reader mapping
            from spectra_sherpa.app.core.config import get_reader_for_extension

            reader_name = get_reader_for_extension(ext)
            reader_method = getattr(scp, reader_name)
            dataset = reader_method(file_path)

            # Post-processing for specific formats
            if ext.lower() == ".mat":
                dataset = extract_dataset_from_result(dataset, file_path)
                dataset = remove_index_columns(dataset)
            elif ext.lower() == ".csv":
                dataset = remove_index_columns(dataset)

            # CRITICAL: Extract and normalize instrument metadata from file headers
            # This preserves OPUS/JCAMP/SPC header info in our SpectraMeta schema
            # The new metadata service returns normalized fields matching SpectraMeta
            extracted_meta = extract_instrument_metadata(dataset, file_path)

            # Store extracted metadata in dataset.meta for provenance
            if not hasattr(dataset, 'meta') or dataset.meta is None:
                dataset.meta = {}

            # Use the normalizer's merge function to preserve existing values
            # and never overwrite blindly
            try:
                from spectra_sherpa.app.services.metadata.normalizer import MetadataNormalizer
                normalizer = MetadataNormalizer()
                dataset.meta = normalizer.merge_with_existing(extracted_meta, dataset.meta)
            except ImportError:
                # Fallback: manual merge (shouldn't happen in normal operation)
                # New structure uses: instrument_metadata, acquisition_params,
                # experimental_conditions, sample_info, provenance, raw_file_metadata
                for key in ["instrument_metadata", "acquisition_params",
                           "experimental_conditions", "sample_info", "provenance"]:
                    if extracted_meta.get(key):
                        if key not in dataset.meta:
                            dataset.meta[key] = {}
                        # Only add new fields, don't overwrite existing
                        for field, value in extracted_meta[key].items():
                            if field not in dataset.meta[key]:
                                dataset.meta[key][field] = value

                # Raw file metadata preserved for debugging (excluded from API by default)
                if extracted_meta.get("raw_file_metadata"):
                    if "raw_file_metadata" not in dataset.meta:
                        dataset.meta["raw_file_metadata"] = {}
                    dataset.meta["raw_file_metadata"].update(extracted_meta["raw_file_metadata"])

            return dataset

        except Exception as e:
            raise ValueError(
                f"Failed to load spectral data from {file_path}: {str(e)}. "
                f"File format: {ext or 'unknown'}. "
                f"Please verify the file is a valid spectral data file."
            ) from e

    def _generate_synthetic(self):
        """Generate synthetic spectral data for testing.

        Returns NDDataset when SCP is available, numpy array otherwise.
        """
        n_samples = 50
        n_wavenumbers = 1000

        # Wavenumber axis (4000 to 400 cm-1)
        wavenumbers = np.linspace(4000, 400, n_wavenumbers)

        # Generate synthetic spectra with some peaks
        spectra = np.zeros((n_samples, n_wavenumbers))
        for i in range(n_samples):
            base = np.random.rand() * 0.1
            noise = np.random.randn(n_wavenumbers) * 0.01

            for peak_pos in [3400, 2900, 1700, 1500, 1000]:
                peak_height = np.random.rand() * 0.5 + 0.2
                peak_width = np.random.rand() * 50 + 30
                peak = peak_height * np.exp(-((wavenumbers - peak_pos) ** 2) / (2 * peak_width ** 2))
                spectra[i] += peak

            spectra[i] += base + noise

        if not HAS_SCP:
            return AnalysisDataset(
                X=spectra,
                x_axis=AxisInfo(values=wavenumbers, title="Wavenumber", units="cm^-1"),
                y_axis=AxisInfo(values=np.arange(n_samples), title="Sample"),
                backend="numpy",
                title="Synthetic Spectra",
                units="absorbance",
            )

        # Create NDDataset with rich metadata
        dataset = scp.NDDataset(spectra)
        dataset.set_coordset(
            y=scp.Coord(np.arange(n_samples), title="Sample"),
            x=scp.Coord(wavenumbers, title="Wavenumber", units="cm^-1"),
        )
        dataset.title = "Synthetic Spectra"
        dataset.units = "absorbance"

        meta = SpectraMeta(
            acquisition=AcquisitionParams(
                wavenumber_min=400.0,
                wavenumber_max=4000.0,
                n_points=n_wavenumbers,
            ),
            provenance=DataProvenance(
                source_type=SourceType.SYNTHETIC,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            is_ground_truth=True,
            processing_steps=["synthetic_generation"],
            custom={
                "synthetic_params": {
                    "type": "generic_ftir",
                    "n_samples": n_samples,
                    "peak_positions_cm": [3400, 2900, 1700, 1500, 1000],
                }
            },
        )
        set_spectra_meta(dataset, meta)

        return dataset


# ============================================================================
# SPECIALIZED DATA SOURCE NODES
# These are individual nodes for specific data sources in the unified workflow
# ============================================================================


@register_node
class FileLoadNode(Node):
    """
    File Load node for loading spectral data from experiment files.

    This is a specialized node for the unified workflow that loads data
    from files stored in experiments.
    """

    metadata = NodeMetadata(
        node_type="data.file_load",
        category="data",
        label="File Load",
        description="Load spectral data from experiment files",
        parameters=[
            NodeParameter(
                name="experiment_id",
                label="Experiment ID",
                param_type="number",
                default=None,
                description="Experiment containing the file",
                required=True,
            ),
            NodeParameter(
                name="file_id",
                label="File ID",
                param_type="number",
                default=None,
                description="Specific file to load",
                required=True,
            ),
            NodeParameter(
                name="stage",
                label="Stage",
                param_type="select",
                default="raw",
                options=["raw", "preprocessed", "synthetic"],
                description="Data processing stage",
                required=False,
            ),
        ],
        input_types=[],
        output_type="NDDataset",
    )

    async def execute(self, *args) -> Any:
        """Load data from a specific experiment file."""
        require_scp("File loading")
        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.experiment_file import ExperimentFile
        from sqlalchemy import select

        experiment_id = self.parameters.get("experiment_id")
        file_id = self.parameters.get("file_id")
        stage = self.parameters.get("stage", "raw")

        if not experiment_id or not file_id:
            raise ValueError("Both experiment_id and file_id are required")

        try:
            async with async_session() as session:
                query = select(ExperimentFile).where(
                    ExperimentFile.experiment_id == experiment_id,
                    ExperimentFile.id == file_id,
                    ExperimentFile.stage == stage,
                )
                result = await session.execute(query)
                file_record = result.scalar_one_or_none()

                if not file_record:
                    raise ValueError(
                        f"File {file_id} not found in experiment {experiment_id} for stage '{stage}'. "
                        f"The file may exist in a different stage (raw/preprocessed/synthetic)."
                    )

                # Build full file path (file_path already includes stage subdirectory)
                exp_dir = f"exp_{str(experiment_id).zfill(3)}"
                full_path = settings.data_dir / "experiments" / exp_dir / file_record.file_path

                dataset = self._load_file(str(full_path))

                # Attach metadata
                meta = SpectraMeta(
                    provenance=DataProvenance(
                        source_type=SourceType.EXPERIMENT,
                        experiment_id=experiment_id,
                        file_id=file_id,
                        original_file_path=str(file_record.file_path),
                        original_file_format=os.path.splitext(file_record.file_path)[1].lower().lstrip("."),
                        created_datetime=datetime.utcnow().isoformat(),
                    ),
                    processing_steps=["load"] if stage == "raw" else ["load", stage],
                )
                set_spectra_meta(dataset, meta)

                # Record provenance in dataset.meta
                add_processing_step(
                    dataset,
                    "data.file_load",
                    {
                        "experiment_id": experiment_id,
                        "file_id": file_id,
                        "stage": stage,
                    },
                    node_id=self.node_id,
                )
                return dataset
        except Exception as e:
            raise ValueError(f"Error loading file: {e}")

    def _load_file(self, file_path: str) -> NDDataset:
        """Load data from a file using SpectroChemPy with index column detection."""

        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1]

        try:
            # Use centralized reader mapping
            from spectra_sherpa.app.core.config import get_reader_for_extension

            reader_name = get_reader_for_extension(ext)
            reader_method = getattr(scp, reader_name)
            dataset = reader_method(file_path)

            # Fail explicitly if reader returns None (no silent fallbacks)
            if dataset is None:
                raise ValueError(f"Reader {reader_name} returned None for {file_path}")

            # Post-processing for specific formats
            if ext.lower() == ".mat":
                dataset = extract_dataset_from_result(dataset, file_path)
                dataset = remove_index_columns(dataset)
            elif ext.lower() == ".csv":
                dataset = remove_index_columns(dataset)

            return dataset

        except Exception as e:
            raise ValueError(
                f"Failed to load file {file_path}: {str(e)}. "
                f"File format: {ext or 'unknown'}. "
                f"Please verify the file is valid and readable."
            ) from e


@register_node
class NISTLibraryNode(Node):
    """
    NIST Library node for loading reference spectra.

    Loads spectra from the local NIST library database.
    """

    metadata = NodeMetadata(
        node_type="data.nist_library",
        category="data",
        label="NIST Library",
        description="Load reference spectra from NIST library",
        parameters=[
            NodeParameter(
                name="library_id",
                label="Library Entry ID",
                param_type="number",
                default=None,
                description="ID of the NIST library entry",
                required=True,
            ),
            NodeParameter(
                name="compound_name",
                label="Compound Name",
                param_type="text",
                default="",
                description="Name of the compound (for display)",
                required=False,
            ),
        ],
        input_types=[],
        output_type="NDDataset",
        requires_scp=True,
    )

    async def execute(self, *args) -> Any:
        """Load spectrum from NIST library."""
        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.nist_library import NistLibrary
        from sqlalchemy import select

        library_id = self.parameters.get("library_id")

        if not library_id:
            raise ValueError("library_id is required")

        try:
            async with async_session() as session:
                query = select(NistLibrary).where(NistLibrary.id == library_id)
                result = await session.execute(query)
                entry = result.scalar_one_or_none()

                if not entry:
                    raise ValueError(f"Library entry {library_id} not found")

                # Build path to library file (file_path already includes "nist_library/" prefix)
                file_path = settings.data_dir / entry.file_path

                dataset = scp.read_jcamp(str(file_path))
                dataset.title = entry.compound_name

                # Parse physical state from JCAMP-DX if available
                state = PhysicalState.UNKNOWN
                state_str = getattr(entry, "state", None)
                if state_str:
                    state_lower = state_str.lower()
                    if "gas" in state_lower:
                        state = PhysicalState.GAS
                    elif "liquid" in state_lower:
                        state = PhysicalState.LIQUID
                    elif "solid" in state_lower:
                        state = PhysicalState.SOLID

                # Create species info from database entry
                species_info = SpeciesInfo(
                    name=entry.compound_name,
                    cas_number=getattr(entry, "cas_number", None),
                    molecular_formula=getattr(entry, "molecular_formula", None),
                    molecular_weight=getattr(entry, "molecular_weight", None),
                    state=state,
                    nist_id=getattr(entry, "nist_id", None),
                )

                # Attach metadata
                meta = SpectraMeta(
                    species=[species_info],
                    provenance=DataProvenance(
                        source_type=SourceType.NIST,
                        nist_id=getattr(entry, "nist_id", None),
                        original_file_path=str(entry.file_path),
                        original_file_format="jdx",
                        created_datetime=datetime.utcnow().isoformat(),
                    ),
                    processing_steps=["nist_library_load"],
                )
                set_spectra_meta(dataset, meta)

                # Record provenance in dataset.meta
                add_processing_step(
                    dataset,
                    "data.nist_library",
                    {
                        "library_id": library_id,
                        "compound_name": entry.compound_name,
                        "nist_id": getattr(entry, "nist_id", None),
                    },
                    node_id=self.node_id,
                )
                return dataset
        except Exception as e:
            raise ValueError(f"Error loading NIST library entry: {e}")


@register_node
class SyntheticCurveNode(Node):
    """
    Synthetic Curve node for generating concentration timeseries.

    Generates synthetic concentration curves for blending operations.
    """

    metadata = NodeMetadata(
        node_type="data.synthetic_curve",
        category="data",
        label="Synthetic Curve",
        description="Generate synthetic concentration curves",
        parameters=[
            NodeParameter(
                name="curve_type",
                label="Curve Type",
                param_type="select",
                default="sigmoid",
                options=["sigmoid", "gaussian", "linear", "exponential", "step"],
                description="Type of concentration curve",
                required=True,
            ),
            NodeParameter(
                name="n_points",
                label="Number of Points",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                description="Number of time points",
                required=True,
            ),
            NodeParameter(
                name="max_concentration",
                label="Max Concentration",
                param_type="number",
                default=1.0,
                min_value=0.0,
                max_value=100.0,
                description="Maximum concentration value",
                required=True,
            ),
            NodeParameter(
                name="center",
                label="Center Position",
                param_type="number",
                default=0.5,
                min_value=0.0,
                max_value=1.0,
                step=0.1,
                description="Center of sigmoid/gaussian (0-1)",
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Width",
                param_type="number",
                default=0.1,
                min_value=0.01,
                max_value=1.0,
                step=0.01,
                description="Width of sigmoid/gaussian",
                required=False,
            ),
        ],
        input_types=[],
        output_type="NDDataset",
    )

    async def execute(self, *args) -> Any:
        """Generate synthetic concentration curve."""
        curve_type = self.parameters.get("curve_type", "sigmoid")
        n_points = int(self.parameters.get("n_points", 100))
        max_conc = self.parameters.get("max_concentration", 1.0)
        center = self.parameters.get("center", 0.5)
        width = self.parameters.get("width", 0.1)

        t = np.linspace(0, 1, n_points)

        if curve_type == "sigmoid":
            curve = max_conc / (1 + np.exp(-(t - center) / width))
        elif curve_type == "gaussian":
            curve = max_conc * np.exp(-((t - center) ** 2) / (2 * width ** 2))
        elif curve_type == "linear":
            curve = max_conc * t
        elif curve_type == "exponential":
            curve = max_conc * (1 - np.exp(-t / width))
        elif curve_type == "step":
            curve = np.where(t >= center, max_conc, 0.0)
        else:
            curve = np.ones(n_points) * max_conc

        if HAS_SCP:
            dataset = scp.NDDataset(curve)
            dataset.set_coordset(
                x=scp.Coord(t * n_points, title="Time", units="s"),
            )
            dataset.title = f"Concentration ({curve_type})"
            dataset.units = "mol/L"
        else:
            dataset = AnalysisDataset(
                X=curve.reshape(1, -1),
                x_axis=AxisInfo(values=t * n_points, title="Time", units="s"),
                backend="numpy",
                title=f"Concentration ({curve_type})",
                units="mol/L",
            )

        # Attach metadata with concentration profile
        concentration_profile = ConcentrationProfile(
            species_index=0,
            species_name="Synthetic Species",
            curve_type=curve_type,
            values=curve.tolist(),
            max_concentration=max_conc,
            min_concentration=float(curve.min()),
            center=center,
            width=width,
            unit=ConcentrationUnit.MOL_L,
        )

        meta = SpectraMeta(
            concentrations=[concentration_profile],
            provenance=DataProvenance(
                source_type=SourceType.SYNTHETIC,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            is_ground_truth=True,
            processing_steps=["synthetic_curve_generation"],
            custom={
                "curve_params": {
                    "curve_type": curve_type,
                    "n_points": n_points,
                    "max_concentration": max_conc,
                    "center": center,
                    "width": width,
                }
            },
        )
        set_spectra_meta(dataset, meta)

        # Record provenance in dataset.meta
        add_processing_step(
            dataset,
            "data.synthetic_curve",
            {
                "curve_type": curve_type,
                "n_points": n_points,
                "max_concentration": max_conc,
                "center": center,
                "width": width,
            },
            node_id=self.node_id,
        )
        return dataset


@register_node
class LoadGroupNode(Node):
    """
    Load Group node for loading multiple spectral files from a folder.

    Loads all matching files from a folder and concatenates them along the sample axis,
    creating a single NDDataset with multiple spectra. Useful for:
    - Time-series measurements (multiple time points)
    - Multi-sample studies (different samples)
    - Batch processing (entire folder of spectra)
    - Comparative studies (control vs treatment groups)

    Features:
    - Mixed format support (uses centralized reader mapping)
    - Strict x-axis validation (ensures all spectra have identical wavenumbers)
    - Fail-fast error handling (stops on first error, no silent failures)
    - Multiple sorting options (alphabetical, numeric suffix, modification time)
    - Rich metadata tracking (source folder, file list, concatenation info)
    """

    metadata = NodeMetadata(
        node_type="data.load_group",
        category="data",
        label="Load Group",
        description="Load multiple spectral files from a folder as a grouped dataset",
        parameters=[
            NodeParameter(
                name="folder_path",
                label="Folder Path",
                param_type="text",
                default="",
                description="Path to folder containing spectral files (absolute or relative to SpectroChemPy datadir)",
                required=True,
            ),
            NodeParameter(
                name="pattern",
                label="File Pattern",
                param_type="text",
                default="*.spa",
                description="Glob pattern to filter files (e.g., '*.spa', '*.csv', '*', 'sample_*.spg')",
                required=False,
            ),
            NodeParameter(
                name="recursive",
                label="Include Subdirectories",
                param_type="boolean",
                default=False,
                description="Scan subdirectories recursively",
                required=False,
            ),
            NodeParameter(
                name="sort_by",
                label="Sort Files By",
                param_type="select",
                options=["filename", "numeric_suffix", "modified_time"],
                default="filename",
                description="How to order files before concatenation (filename=alphabetical, numeric_suffix=extract numbers from filename, modified_time=file modification timestamp)",
                required=False,
            ),
            NodeParameter(
                name="validate_axes",
                label="Validate X-Axes Match",
                param_type="boolean",
                default=True,
                description="Require all files to have identical x-axes (wavenumbers). Recommended: True for strict validation.",
                required=False,
            ),
            NodeParameter(
                name="group_title",
                label="Group Title",
                param_type="text",
                default="",
                description="Title for the grouped dataset (auto-generated from folder name if empty)",
                required=False,
            ),
        ],
        input_types=[],  # No inputs - this is a source node
        output_type="NDDataset",
        requires_scp=True,
    )

    async def execute(self, *args) -> Any:
        """
        Execute group loading: load all matching files and concatenate.

        Returns:
            NDDataset containing all spectra concatenated along sample axis (y-axis)
        """
        import re

        folder_path = self.parameters.get("folder_path", "")
        pattern = self.parameters.get("pattern", "*.spa")
        recursive = self.parameters.get("recursive", False)
        sort_by = self.parameters.get("sort_by", "filename")
        validate_axes = self.parameters.get("validate_axes", True)
        group_title = self.parameters.get("group_title", "")

        if not folder_path:
            raise ValueError("folder_path is required. Please specify a folder containing spectral files.")

        # Resolve folder path (absolute or relative to SpectroChemPy datadir)
        folder = Path(folder_path).expanduser()

        if not folder.is_absolute():
            # Try relative to SpectroChemPy datadir
            candidate_paths = [datadir / folder_path for datadir in get_scp_datadirs()]

            folder = next((p for p in candidate_paths if p.exists()), None)

            if folder is None:
                attempted = "\n".join(f"  - {p}" for p in candidate_paths)
                raise ValueError(
                    f"Folder not found: {folder_path}\n"
                    f"Attempted paths:\n{attempted}\n"
                    f"Please provide an absolute path or a path relative to SpectroChemPy datadir."
                )

        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder}")

        if not folder.is_dir():
            raise ValueError(f"Path is not a directory: {folder}")

        # Find all matching files (case-insensitive)
        # Use case-insensitive matching to handle both .spa and .SPA extensions
        import fnmatch

        # Get all files (recursively if requested)
        if recursive:
            # Walk directory tree recursively
            all_files = []
            for item in folder.rglob('*'):
                if item.is_file():
                    all_files.append(item)
        else:
            # Only immediate directory
            all_files = [f for f in folder.iterdir() if f.is_file()]

        # Filter with case-insensitive matching
        files = []
        for f in all_files:
            # Skip hidden files and system files
            if f.name.startswith(('.', '__')):
                continue

            # Case-insensitive pattern matching
            # For recursive patterns, compare relative path; otherwise just filename
            if recursive and '/' in pattern:
                # Pattern includes path (e.g., "subfolder/*.spa")
                # Compare relative path from folder root
                try:
                    rel_path = f.relative_to(folder)
                    match_str = str(rel_path).replace('\\', '/')  # Normalize path separators
                except ValueError:
                    continue
            else:
                # Simple pattern - just match filename
                match_str = f.name

            # Apply case-insensitive matching
            if '*' in pattern or '?' in pattern:
                # Wildcard pattern - use fnmatch
                if fnmatch.fnmatch(match_str.lower(), pattern.lower()):
                    files.append(f)
            else:
                # Exact match - case-insensitive
                if match_str.lower() == pattern.lower():
                    files.append(f)

        if not files:
            raise ValueError(
                f"No files found matching pattern '{pattern}' in {folder}\n"
                f"Recursive: {recursive}\n"
                f"(Case-insensitive search performed)\n"
                f"Please verify the folder contains spectral files and the pattern is correct."
            )

        logger.debug(f"[LOAD_GROUP] Found {len(files)} files matching '{pattern}' in {folder}")

        # Sort files according to sort_by parameter
        if sort_by == "numeric_suffix":
            # Extract numeric suffix from filename (e.g., "sample_001.spa" -> 1)
            def extract_number(file_path: Path) -> int:
                match = re.search(r'(\d+)', file_path.stem)
                return int(match.group(1)) if match else 0

            files.sort(key=extract_number)
            logger.debug("[LOAD_GROUP] Sorted by numeric suffix")

        elif sort_by == "modified_time":
            # Sort by file modification time (oldest first)
            files.sort(key=lambda f: f.stat().st_mtime)
            logger.debug("[LOAD_GROUP] Sorted by modification time")

        else:  # sort_by == "filename" (default)
            # Sort alphabetically by filename
            files.sort(key=lambda f: f.name.lower())
            logger.debug("[LOAD_GROUP] Sorted alphabetically")

        # Load all files (FAIL-FAST: stop on first error)
        datasets = []
        file_names = []
        errors_encountered = []

        for i, file_path in enumerate(files, 1):
            try:
                logger.debug(f"[LOAD_GROUP] Loading {i}/{len(files)}: {file_path.name}")

                # Load using centralized reader (supports mixed formats)
                dataset = self._load_single_file(file_path)

                if dataset is None:
                    # FAIL-FAST: No fallbacks allowed
                    raise ValueError(f"Reader returned None for {file_path.name}")

                datasets.append(dataset)
                file_names.append(file_path.name)

            except Exception as e:
                # FAIL-FAST: Stop immediately on first error
                error_msg = (
                    f"❌ Failed to load file {i}/{len(files)}: {file_path.name}\n"
                    f"Error: {str(e)}\n\n"
                    f"FAIL-FAST policy: Stopped loading remaining files.\n"
                    f"Successfully loaded: {len(datasets)}/{len(files)} files\n"
                    f"Failed file: {file_path}\n\n"
                    f"Fix the error in this file before proceeding."
                )
                raise ValueError(error_msg) from e

        logger.debug(f"[LOAD_GROUP] Successfully loaded all {len(datasets)} files")

        # Validate x-axes match (strict validation if enabled)
        if validate_axes and len(datasets) > 1:
            self._validate_axes_match(datasets, file_names)

        # Custom concatenation to avoid SpectroChemPy's unit compatibility issues
        # Concatenate numpy arrays directly and create new NDDataset
        try:
            # Extract data arrays and squeeze out singleton dimensions
            data_arrays = [np.squeeze(np.array(ds.data)) for ds in datasets]

            # Ensure all arrays are at least 1D (in case of scalar data)
            data_arrays = [arr if arr.ndim > 0 else np.array([arr]) for arr in data_arrays]

            # Ensure all arrays are 2D (n_spectra, n_wavenumbers)
            # This handles both single-spectrum files (1D) and multi-spectrum files (2D)
            data_arrays_2d = []
            for i, arr in enumerate(data_arrays):
                if arr.ndim == 1:
                    # Single spectrum: reshape to (1, n_wavenumbers)
                    data_arrays_2d.append(arr.reshape(1, -1))
                elif arr.ndim == 2:
                    # Multi-spectrum: keep as is (n_spectra, n_wavenumbers)
                    data_arrays_2d.append(arr)
                else:
                    raise ValueError(
                        f"Unexpected array dimensionality in file {i+1} ({file_names[i]}): shape {arr.shape}. "
                        f"Expected 1D or 2D array."
                    )

            # Concatenate along sample axis (axis=0) to get 2D (total_spectra, n_wavenumbers)
            concatenated_data = np.concatenate(data_arrays_2d, axis=0)

            # Generate y-axis labels accounting for multi-spectrum files
            y_labels = []
            for i, (arr, file_name) in enumerate(zip(data_arrays_2d, file_names)):
                # Use .name instead of .stem to preserve OPUS-style extensions (.0000, .0001, etc.)
                # For files like "test.0000", Path.stem would give "test" but Path.name gives "test.0000"
                file_label = Path(file_name).name
                n_spectra = arr.shape[0]
                if n_spectra == 1:
                    # Single spectrum: use file name
                    y_labels.append(file_label)
                else:
                    # Multi-spectrum: add spectrum index
                    for j in range(n_spectra):
                        y_labels.append(f"{file_label}_{j+1}")

            total_spectra = concatenated_data.shape[0]
            logger.debug(f"[LOAD_GROUP] Concatenated {len(datasets)} files ({total_spectra} spectra) into shape {concatenated_data.shape}")

            # Create new NDDataset with stacked data
            concatenated = scp.NDDataset(concatenated_data)

            # Copy x-axis from reference (all validated to be identical)
            lgn_ref_x_coord = safe_get_coord(datasets[0], 'x')
            if lgn_ref_x_coord is not None:
                concatenated.x = lgn_ref_x_coord.copy()

            # Set units from reference if available
            if hasattr(datasets[0], 'units') and datasets[0].units is not None:
                concatenated.units = datasets[0].units

        except Exception as e:
            raise ValueError(
                f"Failed to concatenate datasets along sample axis.\n"
                f"Error: {str(e)}\n"
                f"All files loaded successfully but concatenation failed.\n"
                f"This may indicate incompatible data shapes or axes."
            ) from e

        # Set meaningful title
        if group_title:
            concatenated.title = group_title
        else:
            concatenated.title = f"{folder.name} ({len(datasets)} files, {total_spectra} spectra)"

        # Update y-axis with file names
        lgn_cat_y_coord = safe_get_coord(concatenated, 'y')
        if lgn_cat_y_coord is not None:
            lgn_cat_y_coord.title = "Sample"
            # Set labels to spectrum names (accounting for multi-spectrum files)
            lgn_cat_y_coord.labels = y_labels
        else:
            # Create y-axis with spectrum names
            lgn_cat_x_coord = safe_get_coord(concatenated, 'x')
            concatenated.set_coordset(
                y=scp.Coord(
                    np.arange(len(y_labels)),
                    title="Sample",
                    labels=y_labels
                ),
                x=lgn_cat_x_coord
            )

        # Attach rich metadata (SECURITY: only folder name, not full path)
        folder_name = folder.name if hasattr(folder, 'name') else os.path.basename(str(folder))
        meta = SpectraMeta(
            provenance=DataProvenance(
                source_type=SourceType.EXPERIMENT,  # Closest match for file group
                original_file_path=folder_name,  # Only folder name, sanitized in to_api_json()
                created_datetime=datetime.utcnow().isoformat(),
            ),
            processing_steps=["load_group"],
            custom={
                "group_load_params": {
                    "folder_name": folder_name,  # Only folder name, not full path
                    "pattern": pattern,
                    "recursive": recursive,
                    "sort_by": sort_by,
                    "validate_axes": validate_axes,
                    "n_files": len(files),
                    "file_names": file_names,  # File names only, should not contain paths
                }
            },
        )
        set_spectra_meta(concatenated, meta)

        logger.debug(f"[LOAD_GROUP] Group loaded successfully: {concatenated.title}")

        # Record provenance in dataset.meta
        add_processing_step(
            concatenated,
            "data.load_group",
            {
                "folder_path": folder_name,
                "pattern": pattern,
                "recursive": recursive,
                "sort_by": sort_by,
                "validate_axes": validate_axes,
                "n_files": len(files),
            },
            node_id=self.node_id,
        )
        return concatenated

    def _load_single_file(self, file_path: Path) -> NDDataset:
        """
        Load a single spectral file using centralized reader mapping.

        Args:
            file_path: Path to file

        Returns:
            NDDataset loaded from file

        Raises:
            ValueError: If file cannot be loaded
        """
        from spectra_sherpa.app.core.config import get_reader_for_extension

        ext = file_path.suffix

        try:
            # Use centralized reader mapping (supports mixed formats)
            reader_name = get_reader_for_extension(ext)
            reader_method = getattr(scp, reader_name)

            dataset = reader_method(str(file_path))

            # FAIL-FAST: No fallbacks allowed
            if dataset is None:
                raise ValueError(f"Reader {reader_name} returned None")

            # Post-processing for specific formats
            if ext.lower() == ".csv":
                dataset = remove_index_columns(dataset)
            elif ext.lower() == ".mat":
                dataset = extract_dataset_from_result(dataset, str(file_path))
                dataset = remove_index_columns(dataset)

            # Set title to filename for tracking
            dataset.title = file_path.stem

            return dataset

        except Exception as e:
            raise ValueError(
                f"Failed to load {file_path.name}: {str(e)}\n"
                f"File type: {ext}\n"
                f"Full path: {file_path}"
            ) from e

    def _validate_axes_match(self, datasets: list[NDDataset], file_names: list[str]) -> None:
        """
        Validate that all datasets have identical x-axes (wavenumbers).

        STRICT VALIDATION: Raises error if any mismatch is found.

        Args:
            datasets: List of loaded datasets
            file_names: List of file names (for error messages)

        Raises:
            ValueError: If x-axes don't match across all files
        """
        if len(datasets) < 2:
            return  # Nothing to validate

        reference = datasets[0]
        reference_name = file_names[0]

        # Check if reference has x-axis
        vam_ref_x_coord = safe_get_coord(reference, 'x')
        if vam_ref_x_coord is None:
            raise ValueError(
                f"Reference file '{reference_name}' has no x-axis (wavenumbers).\n"
                f"All files must have x-axis coordinates for validation."
            )

        reference_x = np.array(vam_ref_x_coord.data)
        reference_shape = reference_x.shape

        # Compare all other datasets to reference
        for i, (dataset, file_name) in enumerate(zip(datasets[1:], file_names[1:]), 2):
            # Check if dataset has x-axis
            vam_ds_x_coord = safe_get_coord(dataset, 'x')
            if vam_ds_x_coord is None:
                raise ValueError(
                    f"X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has no x-axis.\n"
                    f"Reference: '{reference_name}' has x-axis with {len(reference_x)} points.\n\n"
                    f"All files must have x-axis coordinates (wavenumbers) for concatenation.\n"
                    f"Disable 'Validate X-Axes Match' parameter to skip this check (not recommended)."
                )

            dataset_x = np.array(vam_ds_x_coord.data)

            # Check shape match
            if dataset_x.shape != reference_shape:
                raise ValueError(
                    f"❌ X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has {len(dataset_x)} points\n"
                    f"Reference: '{reference_name}' has {len(reference_x)} points\n\n"
                    f"All spectra must have the same x-axis (wavenumber range) for concatenation.\n"
                    f"Consider interpolating or cropping spectra to match before loading as a group."
                )

            # Check values match (with tolerance for floating-point precision)
            if not np.allclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12):
                # Find first mismatch for detailed error message
                mismatch_idx = np.where(~np.isclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12))[0][0]

                raise ValueError(
                    f"❌ X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has different x-axis values\n"
                    f"Reference: '{reference_name}'\n\n"
                    f"First mismatch at index {mismatch_idx}:\n"
                    f"  {reference_name}: {reference_x[mismatch_idx]:.6f}\n"
                    f"  {file_name}: {dataset_x[mismatch_idx]:.6f}\n\n"
                    f"All spectra must have identical wavenumber axes for concatenation.\n"
                    f"Consider reprocessing files to ensure consistent spectral range and resolution."
                )

        logger.debug(f"[LOAD_GROUP] X-axis validation passed: All {len(datasets)} spectra have identical x-axes ({len(reference_x)} points)")


@register_node
class TrainTestSplitNode(Node):
    """
    Split dataset into training and test sets.

    Enables proper ML workflow with separate train/test evaluation.
    Supports random, stratified, and grouped splitting strategies.

    Multi-output node with 4 output ports:
    - X_train: Training feature data
    - X_test: Test feature data
    - y_train: Training targets (if y provided)
    - y_test: Test targets (if y provided)
    """

    metadata = NodeMetadata(
        node_type="data.train_test_split",
        category="data",
        label="Train/Test Split",
        description="Split data into training and test sets with optional stratification",
        parameters=[
            NodeParameter(
                name="test_size",
                label="Test Size",
                param_type="number",
                default=0.2,
                min_value=0.01,
                max_value=0.99,
                step=0.05,
                description="Fraction of data to use for testing (0.2 = 20%)",
                required=True,
            ),
            NodeParameter(
                name="split_method",
                label="Split Method",
                param_type="select",
                options=["random", "stratified", "sequential"],
                default="random",
                description="How to split the data",
                required=True,
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                description="Seed for reproducible random splits",
                required=False,
            ),
            NodeParameter(
                name="shuffle",
                label="Shuffle",
                param_type="boolean",
                default=True,
                description="Shuffle data before splitting (for random method)",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Full dataset to split into train/test",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Target Values (optional)",
                description="Target array for stratified splitting",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_train",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Training Data",
                description="Training subset of input data",
            ),
            PortMetadata(
                name="X_test",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Test Data",
                description="Test subset of input data",
            ),
            PortMetadata(
                name="y_train",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Training Targets",
                description="Training subset of targets",
            ),
            PortMetadata(
                name="y_test",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Test Targets",
                description="Test subset of targets",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",  # Returns dict with multiple outputs
    )
    
    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Split data into train and test sets.

        Args:
            X: Input dataset (NDDataset or SpectralResult)
            y: Optional target array for stratification
            **kwargs: Additional inputs (ignored)

        Returns:
            dict with keys: X_train, X_test, y_train (if y provided), y_test (if y provided)
        """
        test_size = self.parameters.get("test_size", 0.2)
        split_method = self.parameters.get("split_method", "random")
        random_seed = self.parameters.get("random_seed", 42)
        shuffle = self.parameters.get("shuffle", True)

        # Convert NDDataset to numpy array
        if hasattr(X, "data"):
            X_array = np.array(X.data)
        else:
            X_array = np.array(X)
        
        n_samples = X_array.shape[0]
        n_test = int(n_samples * test_size)
        n_train = n_samples - n_test
        
        if n_test < 1 or n_train < 1:
            raise ValueError(
                f"Test size {test_size} results in {n_test} test samples. "
                f"Need at least 1 train and 1 test sample."
            )
        
        # Generate indices
        if split_method == "sequential":
            # Sequential split (first N for train, rest for test)
            train_idx = np.arange(n_train)
            test_idx = np.arange(n_train, n_samples)
            
        elif split_method == "stratified" and y is not None:
            # Stratified split (preserve class proportions)
            from sklearn.model_selection import train_test_split
            
            y_array = np.array(y) if not isinstance(y, np.ndarray) else y
            indices = np.arange(n_samples)
            
            train_idx, test_idx = train_test_split(
                indices,
                test_size=test_size,
                random_state=random_seed,
                stratify=y_array,
                shuffle=shuffle,
            )
            
        else:
            # Random split
            indices = np.arange(n_samples)
            if shuffle:
                rng = np.random.RandomState(random_seed)
                rng.shuffle(indices)
            
            train_idx = indices[:n_train]
            test_idx = indices[n_train:]
        
        # Split data
        X_train_array = X_array[train_idx]
        X_test_array = X_array[test_idx]
        
        # Wrap split arrays as AnalysisDataset (no SCP dependency)
        X_train = AnalysisDataset(X=X_train_array)
        X_test = AnalysisDataset(X=X_test_array)

        # Copy coordinate system if present
        tts_x_coord = safe_get_coord(X, 'x')
        if tts_x_coord is not None:
            X_train.x = tts_x_coord.copy()
            X_test.x = tts_x_coord.copy()

        # Copy y-axis labels for selected samples
        tts_y_coord = safe_get_coord(X, 'y')
        if tts_y_coord is not None:
            X_train.y = tts_y_coord[train_idx].copy() if len(tts_y_coord) > 1 else tts_y_coord.copy()
            X_test.y = tts_y_coord[test_idx].copy() if len(tts_y_coord) > 1 else tts_y_coord.copy()
        
        # Copy metadata
        if hasattr(X, "meta") and X.meta:
            X_train.meta = X.meta.copy()
            X_test.meta = X.meta.copy()

        # Record provenance in dataset.meta
        add_processing_step(
            X_train,
            "data.train_test_split",
            {
                "split": "train",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        add_processing_step(
            X_test,
            "data.train_test_split",
            {
                "split": "test",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        # Build result dict
        result = {
            "X_train": X_train,
            "X_test": X_test,
        }

        # Split targets if provided (keep arrays as-is)
        if y is not None:
            y_array = np.array(y) if not isinstance(y, np.ndarray) else y
            result["y_train"] = y_array[train_idx]
            result["y_test"] = y_array[test_idx]

        logger.debug(f"Train/Test Split: {n_train} train, {n_test} test samples ({test_size*100:.0f}% test)")

        return result
