"""DataSourceNode — primary data source for loading spectral data.

Registered as ``data.source``.  Handles SpectroChemPy examples, sklearn
datasets, Eigenvector benchmarks, experiment files, library entries,
and synthetic generation.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn as from_sklearn_bunch
from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
from spectra_sherpa.app.lib.scp_compat import (
    HAS_SCP,
    NDDataset,
    from_nddataset,
    get_scp_datadirs,
    require_scp,
    resolve_scp_path,
    scp,
)
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.models.spectra_meta import (
    AcquisitionParams,
    DataProvenance,
    ExperimentalConditions,
    PhysicalState,
    SourceType,
    SpeciesInfo,
    SpectraMeta,
    set_spectra_meta,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, safe_get_coord

from ...io_contracts import coerce_to_sherpa
from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._utils import (
    _SCP_KNOWN_DEFAULTS,
    _normalize_scp_read_output,
    _try_load_first_file,
    extract_dataset_from_result,
    extract_instrument_metadata,
    remove_index_columns,
)

logger = logging.getLogger(__name__)


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
                options=[{"label": v["label"], "value": k} for k, v in DATASET_CATALOG.items()],
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
                description=(
                    "Specific file within the selected dataset"
                    " (e.g., 'CO@Mo_Al2O3.SPG'). Leave empty for default file."
                ),
                required=False,
                category="advanced",
            ),
            # DATA MANIPULATION OPTIONS (Advanced)
            NodeParameter(
                name="transpose_on_load",
                label="Transpose on Load",
                param_type="boolean",
                default=False,
                description=(
                    "Swap rows/columns if data is (n_wavenumbers, n_samples)" " instead of (n_samples, n_wavenumbers)"
                ),
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
        input_ports=[],
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
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values",
                description="Target/property values if available (1D or 2D for multi-response)",
            ),
        ],
    )

    async def execute(self, *args) -> Any:
        """
        Execute data loading.

        Returns:
            dict with "default" (SherpaDataset) and "target" (optional labels)
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

        # ----- Normalize to SherpaDataset -----
        # Convert NDDataset to SherpaDataset immediately so all downstream
        # code has a single type to work with.  NDDataset meta/provenance is
        # preserved losslessly by from_nddataset().
        if isinstance(dataset, NDDataset):
            # Apply axis config while still NDDataset (SCP Coord operations)
            dataset = self._apply_axis_config(dataset)
            # Preserve any existing meta before conversion
            if not hasattr(dataset, "meta") or dataset.meta is None:
                dataset.meta = {}
            # Merge provenance summary from file metadata (OPUS, JCAMP, etc.)
            existing_provenance = dataset.meta.get("provenance", {})
            if isinstance(existing_provenance, dict):
                existing_operations = existing_provenance.get("operations", [])
                merged_provenance = dict(existing_provenance)
                original_source_type = (
                    existing_provenance.get("original_source_type")
                    or existing_provenance.get("source_type")
                    or existing_provenance.get("original_source")
                )
                merged_provenance["current_source_type"] = source
                if original_source_type:
                    merged_provenance["original_source_type"] = original_source_type
                merged_provenance["source_type"] = original_source_type or source
                merged_provenance["original_source"] = original_source_type or source
                merged_provenance["operations"] = ["data.source"] + existing_operations
                merged_provenance["last_modified"] = datetime.utcnow().isoformat()
                merged_provenance["last_operation"] = "data.source"
                dataset.meta["provenance"] = merged_provenance
            # Extract target before conversion (needs SCP Coord access)
            if source == "sklearn":
                target = self._extract_target_labels(dataset)
            elif source == "eigenvector" and hasattr(self, "_eigenvector_properties"):
                target = self._eigenvector_properties
            else:
                target = None
            # Convert NDDataset -> SherpaDataset (lossless)
            dataset = from_nddataset(dataset)
        else:
            # Non-NDDataset path (no SCP, or already SherpaDataset)
            target = None
            if source == "sklearn" and hasattr(self, "_sklearn_bunch"):
                dataset = from_sklearn_bunch(self._sklearn_bunch, name=sklearn_dataset)
                # from_sklearn_bunch already embeds target + target_context
            elif source == "eigenvector" and hasattr(self, "_eigenvector_properties"):
                target = self._eigenvector_properties
            dataset = coerce_to_sherpa(dataset, input_name="dataset", allow_array=True)
            dataset = self._apply_axis_config(dataset)

        # Enrich asserted domain + promoted metadata after all conversions.
        dataset = self._apply_domain_context_hints(
            dataset,
            source=source,
            sklearn_dataset=sklearn_dataset,
            eigenvector_dataset=self.parameters.get("eigenvector_dataset"),
        )

        # ----- Embed target into dataset (self-describing data) -----
        if target is not None and dataset.target is None:
            target_arr = np.asarray(target) if not isinstance(target, np.ndarray) else target
            dataset.target = target_arr
            if source == "eigenvector":
                prop_names = getattr(self, "_eigenvector_target_names", [])
                dataset.target_context = TargetContext(
                    target_type="continuous",
                    target_names=prop_names or None,
                )
            elif source == "sklearn":
                # SCP path: infer target context from extracted values
                n_unique = len(np.unique(target_arr))
                is_categorical = n_unique <= 30 and (
                    np.issubdtype(target_arr.dtype, np.integer)
                    or np.issubdtype(target_arr.dtype, np.str_)
                    or target_arr.dtype.kind == "U"
                )
                if is_categorical:
                    dataset.target_context = TargetContext(
                        target_type="categorical",
                        target_name=sklearn_dataset or None,
                        n_classes=n_unique,
                    )
                else:
                    dataset.target_context = TargetContext(
                        target_type="continuous",
                        target_name=sklearn_dataset or None,
                    )

        # ----- Unified provenance (always SherpaDataset from here) -----
        add_processing_step(
            dataset,
            "data.source",
            {
                "source": source,
                "example_dataset": example_dataset if source == "spectrochempy" else None,
                "sklearn_dataset": sklearn_dataset if source == "sklearn" else None,
                "eigenvector_dataset": self.parameters.get("eigenvector_dataset") if source == "eigenvector" else None,
                "experiment_id": experiment_id if source == "experiment" else None,
                "file_path": file_path if source == "file" else None,
            },
            node_id=self.node_id,
            input_shape=None,
        )

        return {
            "default": dataset,
            "target": dataset.target,  # Derived from embedded — one source of truth
        }

    def _apply_domain_context_hints(
        self,
        dataset: SherpaDataset,
        *,
        source: str,
        sklearn_dataset: str,
        eigenvector_dataset: str | None,
    ) -> SherpaDataset:
        """Apply authoritative source hints and promote metadata into domain context."""
        domain = dataset.domain.model_copy(deep=True)

        # Source-level asserted domain (authoritative).
        if source == "eigenvector":
            catalog = DATASET_CATALOG.get(eigenvector_dataset or "", {})
            technique = catalog.get("technique")
            if technique:
                domain.technique = str(technique)
            x_units = catalog.get("x_units")
            if x_units and not domain.expected_units:
                domain.expected_units = str(x_units)
        elif source == "sklearn":
            domain.technique = "generic"
            if sklearn_dataset:
                domain.sample_type = sklearn_dataset

        # Promote extracted instrument/sample metadata from the metadata dict.
        meta = dataset.meta if isinstance(dataset.meta, dict) else {}
        instrument_metadata = meta.get("scp.instrument_metadata") or meta.get("instrument_metadata")
        sample_info = meta.get("scp.sample_info") or meta.get("sample_info")

        if isinstance(instrument_metadata, dict):
            instrument = self._format_instrument_name(instrument_metadata)
            if instrument and not domain.instrument:
                domain.instrument = instrument

        if isinstance(sample_info, dict):
            raw_mode = (
                sample_info.get("sampling_technique")
                or sample_info.get("measurement_mode")
                or sample_info.get("accessory")
            )
            mode = self._normalize_measurement_mode(raw_mode)
            if mode and not domain.measurement_mode:
                domain.measurement_mode = mode

        dataset.domain = domain
        return dataset

    @staticmethod
    def _format_instrument_name(instrument_metadata: dict[str, Any]) -> str | None:
        """Build a compact instrument name from normalized metadata fields."""
        manufacturer = instrument_metadata.get("manufacturer")
        model = instrument_metadata.get("model")
        raw = instrument_metadata.get("manufacturer_model_raw")

        parts = [str(p).strip() for p in (manufacturer, model) if p]
        if parts:
            return " ".join(parts)
        if raw:
            return str(raw).strip()
        return None

    @staticmethod
    def _normalize_measurement_mode(raw_mode: Any) -> str | None:
        """Normalize extracted sampling mode into DomainContext values."""
        if raw_mode is None:
            return None
        value = str(raw_mode).strip()
        if not value:
            return None
        lowered = value.lower()

        if "atr" in lowered:
            return "ATR"
        if "trans" in lowered:
            return "transmission"
        if "refl" in lowered or "drift" in lowered or "diffuse" in lowered:
            return "reflectance"
        return value

    def _extract_target_labels(self, dataset: NDDataset) -> Any:
        """
        Extract target labels from an NDDataset if present.

        Called **before** the NDDataset-to-SherpaDataset conversion so that
        SCP Coord label access is still available.  Prefers y-axis labels
        over y-axis numeric data.
        """
        etl_y_coord = safe_get_coord(dataset, "y")
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
        Works with both NDDataset and SherpaDataset.

        Args:
            dataset: Input dataset (NDDataset or SherpaDataset)

        Returns:
            Configured dataset with correct axis orientation and titles
        """
        # Get parameters - empty string means "preserve source title"
        transpose_on_load = self.parameters.get("transpose_on_load", False)
        sample_axis_override = self.parameters.get("sample_axis_title", "").strip()
        spectral_axis_override = self.parameters.get("spectral_axis_title", "").strip()

        is_sherpa = isinstance(dataset, SherpaDataset)

        # Transpose if requested (swap rows and columns)
        if transpose_on_load:
            if is_sherpa:
                dataset = SherpaDataset(
                    X=dataset.data.T,
                    feature_axis=dataset.sample_axis.copy() if dataset.sample_axis is not None else None,
                    sample_axis=dataset.feature_axis.copy() if dataset.feature_axis is not None else None,
                    target=None,  # row count changes on transpose; drop target unless explicitly re-bound
                    target_context=dataset.target_context.model_copy(deep=True),
                    domain=dataset.domain.model_copy(deep=True),
                    provenance=dataset.provenance.copy(),
                    quality=dataset.quality.model_copy(deep=True),
                    backend=dataset.backend,
                    title=dataset.title,
                    units=dataset.units,
                    extra=dict(dataset.meta),
                )
            else:
                dataset = dataset.T
            logger.debug(f"[DATA] Transposed data to {dataset.shape[0]} samples x {dataset.shape[1]} features")

        if dataset.ndim >= 2:
            if is_sherpa:
                current_y = dataset.sample_axis
                current_x = dataset.feature_axis
            else:
                current_y = safe_get_coord(dataset, "y")
                current_x = safe_get_coord(dataset, "x")

            # Determine y-axis (sample) title
            if sample_axis_override:
                y_title = sample_axis_override
            elif current_y is not None and hasattr(current_y, "title") and current_y.title:
                y_title = current_y.title
            else:
                y_title = "Sample"

            # Determine x-axis (spectral/feature) title
            if spectral_axis_override:
                x_title = spectral_axis_override
            elif current_x is not None and hasattr(current_x, "title") and current_x.title:
                x_title = current_x.title
            else:
                x_title = "Feature"

            if is_sherpa:
                if current_y is not None:
                    if current_y.title != y_title:
                        new_y = current_y.copy()
                        new_y.title = y_title
                        dataset.sample_axis = new_y
                else:
                    dataset.sample_axis = SampleAxis(values=np.arange(dataset.shape[0], dtype=float), title=y_title)

                if current_x is not None:
                    if current_x.title != x_title:
                        new_x = current_x.copy()
                        new_x.title = x_title
                        dataset.feature_axis = new_x
                else:
                    dataset.feature_axis = SpectralAxis(values=np.arange(dataset.shape[1], dtype=float), title=x_title)
            else:
                # NDDataset: use SCP Coord + set_coordset
                if current_y is not None:
                    try:
                        if current_y.title != y_title:
                            current_y.title = y_title
                    except (AttributeError, TypeError):
                        pass
                else:
                    dataset.set_coordset(y=scp.Coord(np.arange(dataset.shape[0]), title=y_title), x=current_x)
                    current_y = safe_get_coord(dataset, "y")

                if current_x is not None:
                    try:
                        if current_x.title != x_title:
                            current_x.title = x_title
                    except (AttributeError, TypeError):
                        pass
                else:
                    dataset.set_coordset(y=current_y, x=scp.Coord(np.arange(dataset.shape[1]), title=x_title))

        elif dataset.ndim == 1:
            # For 1D data, only x-axis
            if is_sherpa:
                aac_1d_x_coord = dataset.feature_axis
            else:
                aac_1d_x_coord = safe_get_coord(dataset, "x")
            if spectral_axis_override:
                x_title = spectral_axis_override
            elif aac_1d_x_coord is not None and hasattr(aac_1d_x_coord, "title") and aac_1d_x_coord.title:
                x_title = aac_1d_x_coord.title
            else:
                x_title = "Feature"

            if is_sherpa:
                if aac_1d_x_coord is not None:
                    if aac_1d_x_coord.title != x_title:
                        new_x = aac_1d_x_coord.copy()
                        new_x.title = x_title
                        dataset.feature_axis = new_x
                else:
                    dataset.feature_axis = SpectralAxis(values=np.arange(dataset.shape[0], dtype=float), title=x_title)
            else:
                if aac_1d_x_coord is not None:
                    if aac_1d_x_coord.title != x_title:
                        aac_1d_x_coord.title = x_title
                else:
                    dataset.set_coordset(x=scp.Coord(np.arange(dataset.shape[0]), title=x_title))

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
                f"Unsupported sklearn dataset: {dataset_name}\n" f"Supported datasets: {', '.join(_loaders)}"
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
                    dataset_name,
                    e,
                )
                # Fall through to direct sklearn path

        # Direct sklearn path -- no SCP required
        logger.debug("[DATA] Loading sklearn dataset directly: %s", dataset_name)
        bunch = _loaders[dataset_name]()
        # Store target on the instance so _extract_target_labels_sklearn can get it
        self._sklearn_bunch = bunch
        logger.debug(
            "[DATA] Loaded %s: %d samples x %d features",
            dataset_name,
            bunch.data.shape[0],
            bunch.data.shape[1],
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

        # Store properties for the target output port (as numpy array)
        if properties is not None:
            self._eigenvector_properties = np.asarray(properties, dtype=np.float64)
            self._eigenvector_target_names = result.get("prop_names") or []

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
                dataset_name,
                dataset.shape,
                catalog.get("technique", ""),
            )
            return dataset

        # No-SCP path: return SherpaDataset with proper axes
        x_title = catalog.get("x_title", "Channel")
        x_units = catalog.get("x_units")
        x_values = (
            wavelengths
            if wavelengths is not None and len(wavelengths) == spectra.shape[1]
            else np.arange(spectra.shape[1])
        )

        dataset = SherpaDataset(
            X=spectra,
            feature_axis=SpectralAxis(values=x_values, title=x_title, units=x_units),
            sample_axis=SampleAxis(values=np.arange(spectra.shape[0]), title="Sample"),
            domain=DomainContext(
                technique=catalog.get("technique"),
                expected_units=catalog.get("x_units"),
            ),
            backend="numpy",
            title=catalog.get("label", dataset_name),
        )
        logger.debug(
            "[DATA] Loaded Eigenvector %s: %d samples x %d features",
            dataset_name,
            spectra.shape[0],
            spectra.shape[1],
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
            '  python -c "from spectra_sherpa.app.lib.scp_compat import download_testdata; download_testdata()"'
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
                f"Failed to load {file_path}: {str(e)}\n" f"File type: {full_path.suffix}\n" f"Full path: {full_path}"
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
        return "*" in file_path or "?" in file_path or file_path.endswith("/")

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

        # Parse pattern to extract folder and glob pattern
        if pattern.endswith("/"):
            # Folder indicator: load all files from specified folder
            # Remove trailing slash and use as folder path
            folder_path = pattern.rstrip("/")
            glob_pattern = "*"
        elif "/" in pattern:
            # Pattern with subfolder: "irdata/subfolder/*.spa"
            parts = pattern.rsplit("/", 1)
            folder_path = parts[0] if parts[0] else example_dataset
            glob_pattern = parts[1] if len(parts) > 1 else "*"
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
            if not f.is_file() or f.name.startswith((".", "__")):
                continue

            # Case-insensitive pattern matching
            if "*" in glob_pattern or "?" in glob_pattern:
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
                    f"Failed to load file {i}/{len(files)}: {file_path.name}\n"
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
            logger.debug(
                f"[DATA] Concatenated {len(datasets)} files "
                f"({total_spectra} spectra) into shape {concatenated_data.shape}"
            )

            # Create new NDDataset with stacked data
            concatenated = scp.NDDataset(concatenated_data)

            # Copy x-axis from reference (all validated to be identical)
            lsg_ref_x_coord = safe_get_coord(datasets[0], "x")
            if lsg_ref_x_coord is not None:
                concatenated.x = lsg_ref_x_coord.copy()

            # Set units from reference if available
            if hasattr(datasets[0], "units") and datasets[0].units is not None:
                concatenated.units = datasets[0].units

        except Exception as e:
            raise ValueError(
                f"Failed to concatenate datasets.\n"
                f"Error: {str(e)}\n"
                f"All files loaded successfully but concatenation failed."
            ) from e

        # Set title and y-axis labels
        concatenated.title = f"{folder.name} ({len(datasets)} files, {total_spectra} spectra)"

        lsg_cat_y_coord = safe_get_coord(concatenated, "y")
        if lsg_cat_y_coord is not None:
            lsg_cat_y_coord.title = "Sample"
            lsg_cat_y_coord.labels = y_labels
        else:
            lsg_cat_x_coord = safe_get_coord(concatenated, "x")
            concatenated.set_coordset(
                y=scp.Coord(np.arange(len(y_labels)), title="Sample", labels=y_labels), x=lsg_cat_x_coord
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

        vga_ref_x_coord = safe_get_coord(reference, "x")
        if vga_ref_x_coord is None:
            raise ValueError(
                f"Reference file '{reference_name}' has no x-axis.\n" f"Cannot validate axes for group loading."
            )

        reference_x = np.array(vga_ref_x_coord.data)

        for i, (dataset, file_name) in enumerate(zip(datasets[1:], file_names[1:]), 2):
            vga_ds_x_coord = safe_get_coord(dataset, "x")
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
            oh_peak = (0.3 + temp_factor * 0.5) * np.exp(-((wavenumbers - 3650) ** 2) / (2 * 80**2))
            oh_peak2 = (0.2 + temp_factor * 0.3) * np.exp(-((wavenumbers - 3550) ** 2) / (2 * 100**2))

            # NH4+ peaks (1400-1500 cm-1) - decreases with activation
            nh4_peak = (0.6 - temp_factor * 0.5) * np.exp(-((wavenumbers - 1450) ** 2) / (2 * 40**2))

            # Si-O-Si framework (1000-1200 cm-1) - relatively constant
            sio_peak = 0.8 * np.exp(-((wavenumbers - 1050) ** 2) / (2 * 100**2))

            # Water bending (1640 cm-1) - decreases with activation
            h2o_peak = (0.3 - temp_factor * 0.25) * np.exp(-((wavenumbers - 1640) ** 2) / (2 * 30**2))

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
            peak1 = concentration * 1000 * np.exp(-((wavenumbers - 1000) ** 2) / (2 * 20**2))
            peak2 = concentration * 800 * np.exp(-((wavenumbers - 1600) ** 2) / (2 * 30**2))
            peak3 = concentration * 500 * np.exp(-((wavenumbers - 2900) ** 2) / (2 * 50**2))

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
        from sqlalchemy import select

        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.experiment_file import ExperimentFile

        async with async_session() as session:
            # Find experiment files for the specified stage
            query = (
                select(ExperimentFile)
                .where(ExperimentFile.experiment_id == experiment_id, ExperimentFile.stage == stage)
                .order_by(ExperimentFile.created_at)
            )  # Deterministic ordering

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
                    f"File not found: {full_path}. " f"File record exists in database but file is missing on disk."
                )

            return self._load_from_file(str(full_path))

    async def _load_from_library(self, library_id: int) -> NDDataset:
        """
        Load data from NIST library entry.

        Args:
            library_id: ID of the NIST library entry
        """
        from sqlalchemy import select

        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.nist_library import NistLibrary

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
                f"File not found: {file_path}. " f"Please verify the file exists and the path is correct."
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
            if not hasattr(dataset, "meta") or dataset.meta is None:
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
                for key in [
                    "instrument_metadata",
                    "acquisition_params",
                    "experimental_conditions",
                    "sample_info",
                    "provenance",
                ]:
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
                peak = peak_height * np.exp(-((wavenumbers - peak_pos) ** 2) / (2 * peak_width**2))
                spectra[i] += peak

            spectra[i] += base + noise

        if not HAS_SCP:
            return SherpaDataset(
                X=spectra,
                feature_axis=SpectralAxis(values=wavenumbers, title="Wavenumber", units="cm^-1"),
                sample_axis=SampleAxis(values=np.arange(n_samples), title="Sample"),
                domain=DomainContext(
                    technique="IR",
                    data_quantity="Absorbance",
                    expected_units="cm^-1",
                ),
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
