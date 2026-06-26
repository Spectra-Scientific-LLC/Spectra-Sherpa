"""Specialized data loader nodes for experiment files and file groups.

Contains:
- ``FileLoadNode`` (``data.file_load``)
- ``MyDatasetNode`` (``data.my_dataset``)
- ``LoadGroupNode`` (``data.load_group``)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.scp_compat import (
    NDDataset,
    from_nddataset,
    get_scp_datadirs,
    scp,
)
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.models.spectra_meta import (
    DataProvenance,
    SourceType,
    SpectraMeta,
    set_spectra_meta,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, safe_get_coord
from spectra_sherpa.app.services.prepared_data import (
    apply_dataset_prepared_data_overrides,
    load_prepared_data_overrides,
    merge_prepared_data_overrides,
)

from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._utils import extract_dataset_from_result, remove_index_columns

logger = logging.getLogger(__name__)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class _LoadedDataset:
    dataset: Any
    file_name: str
    file_path: str | None = None
    embedded_target_names: list[str] | None = None
    embedded_target_data: np.ndarray | None = None
    embedded_target_units: str | None = None
    ground_truth_spectra: np.ndarray | None = None
    ground_truth_spectra_names: list[str] | None = None
    ground_truth_spectra_units: list[str] | str | None = None
    ground_truth_spectra_x: np.ndarray | None = None
    ground_truth_spectra_x_title: str | None = None
    ground_truth_spectra_x_units: str | None = None


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
        input_ports=[],
        output_type="NDDataset",
    )

    async def execute(self, *args) -> Any:
        """Load data from a specific experiment file."""
        from sqlalchemy import select

        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.experiment_file import ExperimentFile

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
                # Convert to SherpaDataset for uniform DAG contract
                return from_nddataset(dataset) if isinstance(dataset, NDDataset) else dataset
        except Exception as e:
            raise ValueError(f"Error loading file: {e}")

    def _load_file(self, file_path: str) -> Any:
        """Load data from a file using SpectroChemPy with index column detection."""

        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            from spectra_sherpa.app.lib.io import load_csv_as_sherpa

            return load_csv_as_sherpa(file_path)
        if ext == ".npz":
            from spectra_sherpa.app.services.synthesis import is_synthetic_npz

            if is_synthetic_npz(file_path):
                return _load_synthesis_npz_as_nddataset(file_path)
        if ext in {".jdx", ".dx", ".npy", ".npz"}:
            from spectra_sherpa.app.lib.io import load_open_spectral_file_as_sherpa

            open_dataset = load_open_spectral_file_as_sherpa(file_path)
            if open_dataset is not None:
                return open_dataset

        try:
            from spectra_sherpa.app.lib.data_formats import ensure_reader_available

            ensure_reader_available(ext)
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
class MyDatasetNode(Node):
    """
    My Dataset node -- loads ALL files from a user dataset (experiment) created
    on the Data tab and concatenates them into a single NDDataset.
    """

    metadata = NodeMetadata(
        node_type="data.my_dataset",
        category="data",
        label="My Dataset",
        description="Load all files from your dataset collection",
        parameters=[
            NodeParameter(
                name="dataset_id",
                label="Dataset",
                param_type="number",
                default=None,
                description="Dataset (experiment) to load",
                required=True,
            ),
            NodeParameter(
                name="target_mode",
                label="Target Mode",
                param_type="select",
                default="dataset_default",
                options=[
                    {"label": "Use My Dataset default", "value": "dataset_default"},
                    {"label": "Single property", "value": "single"},
                    {"label": "Multi-target complete-case", "value": "multi"},
                ],
                description="How this workflow sheet interprets multi-property reference values.",
                required=False,
            ),
            NodeParameter(
                name="selected_target",
                label="Target Property",
                param_type="text",
                default=None,
                description="Property name used when Target Mode is Single property.",
                required=False,
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Spectral data (all compatible files stacked)",
            ),
            PortMetadata(
                name="target",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Properties",
                description="Property / target data if available (1D or 2D for multi-response)",
            ),
        ],
    )

    async def execute(self, *args) -> Any:
        """Load all files, group by compatible x-axis, stack each group."""
        from sqlalchemy import select as sa_select

        from spectra_sherpa.app.core.config import settings
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.experiment import Experiment
        from spectra_sherpa.app.models.experiment_file import ExperimentFile as EF

        dataset_id = self.parameters.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id is required")

        async with async_session() as session:
            exp_result = await session.execute(sa_select(Experiment).where(Experiment.id == dataset_id))
            experiment = exp_result.scalar_one_or_none()
            if not experiment:
                raise ValueError(f"Dataset {dataset_id} not found.")
            exp_name = experiment.name

            query = (
                sa_select(EF)
                .where(
                    EF.experiment_id == dataset_id,
                    EF.stage == "raw",
                )
                .order_by(EF.id)
            )
            result = await session.execute(query)
            file_records = list(result.scalars().all())
            if not file_records:
                synthetic_query = (
                    sa_select(EF)
                    .where(
                        EF.experiment_id == dataset_id,
                        EF.stage == "synthetic",
                    )
                    .order_by(EF.id)
                )
                result = await session.execute(synthetic_query)
                file_records = list(result.scalars().all())

        if not file_records:
            raise ValueError(f"No files found in dataset '{exp_name}'.")

        exp_dir = f"exp_{str(dataset_id).zfill(3)}"
        base_dir = settings.data_dir / "experiments" / exp_dir

        # Load each file
        loaded: list[_LoadedDataset] = []
        for rec in file_records:
            full_path = base_dir / rec.file_path
            try:
                loaded.append(self._load_file(str(full_path), file_name=rec.file_path))
            except Exception as e:
                logger.warning(f"[MY_DATASET] Skipping {rec.file_path}: {e}")

        if not loaded:
            raise ValueError(f"All files in dataset '{exp_name}' failed to load.")

        if all(isinstance(item.dataset, SherpaDataset) and item.dataset.data_role == "X_features" for item in loaded):
            feature_dataset = self._concatenate_feature_tables(loaded, exp_name)
            feature_dataset = self._apply_loaded_overrides(feature_dataset, loaded)
            feature_dataset = self._apply_node_target_selection(feature_dataset)
            add_processing_step(
                feature_dataset,
                "data.my_dataset",
                self._processing_parameters(dataset_id=dataset_id, file_count=len(loaded), dataset=feature_dataset),
                node_id=self.node_id,
            )
            return {"default": feature_dataset, "target": feature_dataset.target}

        # Group files by compatible x-axis
        groups = self._group_by_x_axis(loaded)

        # Pick the group with the most x-axis points as "spectra",
        # remaining groups become "properties" / target
        groups.sort(key=lambda g: self._x_length(g[0].dataset), reverse=True)
        spectra_group = groups[0]
        prop_groups = groups[1:]
        embedded_target = self._combine_embedded_targets(spectra_group)

        # Stack spectra
        s_datasets = [item.dataset for item in spectra_group]
        s_names = [item.file_name for item in spectra_group]
        s_datasets, s_names = list(s_datasets), list(s_names)
        spectra = self._concatenate(s_datasets, s_names) if len(s_datasets) > 1 else s_datasets[0]
        spectra.title = f"{exp_name} ({len(s_datasets)} file{'s' if len(s_datasets) != 1 else ''})"

        meta = SpectraMeta(
            provenance=DataProvenance(
                source_type=SourceType.EXPERIMENT,
                experiment_id=dataset_id,
                original_file_path=", ".join(s_names),
                created_datetime=datetime.utcnow().isoformat(),
            ),
            processing_steps=["load"],
        )
        set_spectra_meta(spectra, meta)
        add_processing_step(
            spectra,
            "data.my_dataset",
            {"dataset_id": dataset_id, "file_count": len(loaded)},
            node_id=self.node_id,
        )

        # Stack properties (if any)
        target: Optional[Any] = None
        if prop_groups:
            all_props = []
            all_pnames = []
            for grp in prop_groups:
                for item in grp:
                    all_props.append(item.dataset)
                    all_pnames.append(item.file_name)
            target = self._concatenate(all_props, all_pnames) if len(all_props) > 1 else all_props[0]
            target.title = f"{exp_name} properties"
            logger.debug(
                f"[MY_DATASET] Loaded {len(s_names)} spectral + " f"{len(all_pnames)} property files from '{exp_name}'"
            )

        # Convert to SherpaDataset for uniform DAG contract
        spectra_out = from_nddataset(spectra) if isinstance(spectra, NDDataset) else spectra
        target_out = from_nddataset(target) if isinstance(target, NDDataset) else target
        spectra_out = self._apply_loaded_overrides(spectra_out, spectra_group)
        self._attach_ground_truth_spectra(spectra_out, spectra_group)

        # Embed target into default output for single-wire use (parity with DataSourceNode)
        # Priority 1: CSV property columns embedded alongside the spectra
        if embedded_target is not None:
            embedded_target_data, embedded_target_names, embedded_target_units = embedded_target
            spectra_out.target = embedded_target_data
            spectra_out.target_context = TargetContext(
                target_type="continuous",
                target_name="synthetic concentration" if embedded_target_units == "ppm" else None,
                target_names=embedded_target_names,
                target_units=embedded_target_units,
            )
            if target_out is None:
                from spectra_sherpa.app.lib.axes import FeatureAxis

                target_out = SherpaDataset(
                    X=embedded_target_data,
                    feature_axis=FeatureAxis(
                        labels=embedded_target_names,
                        title="Concentration" if embedded_target_units == "ppm" else "Property",
                        units=embedded_target_units,
                    ),
                    sample_axis=spectra_out.sample_axis,
                    title=(
                        f"{exp_name} synthetic concentrations"
                        if embedded_target_units == "ppm"
                        else f"{exp_name} properties"
                    ),
                )
        # Priority 2: Multi-file property groups
        elif target_out is not None:
            self._validate_target_alignment(spectra_out, target_out, exp_name)
            target_data = np.asarray(target_out.data, dtype=np.float64)
            spectra_out.target = target_data
            t_names = None
            fa = getattr(target_out, "feature_axis", None)
            if fa is not None and getattr(fa, "labels", None):
                t_names = list(fa.labels)
            spectra_out.target_context = TargetContext(
                target_type="continuous",
                target_names=t_names,
            )

        spectra_out = self._apply_loaded_overrides(spectra_out, spectra_group)
        spectra_out = self._apply_node_target_selection(spectra_out)
        processing_history = getattr(spectra_out, "processing_history", None)
        if processing_history:
            latest_step = processing_history[-1]
            if latest_step.operation == "data.my_dataset":
                latest_step.parameters.update(
                    self._processing_parameters(dataset_id=dataset_id, file_count=len(loaded), dataset=spectra_out)
                )
        return {"default": spectra_out, "target": target_out}

    def _processing_parameters(self, *, dataset_id: int, file_count: int, dataset: SherpaDataset) -> dict[str, Any]:
        params: dict[str, Any] = {"dataset_id": dataset_id, "file_count": file_count}
        tc = getattr(dataset, "target_context", None)
        if tc is not None and getattr(tc, "selected_target", None):
            params["target_mode"] = "single"
            params["selected_target"] = tc.selected_target
        elif self.parameters.get("target_mode") == "multi":
            params["target_mode"] = "multi"
        return params

    def _apply_node_target_selection(self, dataset: SherpaDataset) -> SherpaDataset:
        target_mode = str(self.parameters.get("target_mode") or "dataset_default")
        if target_mode in {"", "dataset_default", "auto"}:
            return dataset

        tc = dataset.target_context
        if target_mode == "multi":
            dataset.target_context = tc.model_copy(update={"selected_target": None})
            dataset.meta["target_mode"] = "multi"
            dataset.meta.pop("selected_target", None)
            return dataset

        if target_mode != "single":
            raise ValueError(f"Unsupported target mode for My Dataset: {target_mode}")

        names = [str(name) for name in (tc.target_names or [])]
        selected = str(self.parameters.get("selected_target") or "").strip()
        if not selected and names:
            selected = names[0]
        if not selected:
            raise ValueError(
                "This My Dataset node is set to Single property, but the selected dataset has no target names."
            )
        if names and selected not in names:
            available = ", ".join(names)
            raise ValueError(
                f"This My Dataset node selects target '{selected}', but the dataset target properties are: {available}."
            )
        dataset.target_context = tc.model_copy(update={"selected_target": selected})
        dataset.meta["target_mode"] = "single"
        dataset.meta["selected_target"] = selected
        return dataset

    @staticmethod
    def _sample_labels(dataset: Any) -> list[str] | None:
        axis = getattr(dataset, "sample_axis", None)
        if axis is not None and getattr(axis, "labels", None):
            return [str(item) for item in axis.labels]
        if not isinstance(dataset, SherpaDataset):
            coord = safe_get_coord(dataset, "y")
            labels = getattr(coord, "labels", None) if coord is not None else None
            if labels:
                return [str(item) for item in labels]
        return None

    def _validate_target_alignment(self, spectra: SherpaDataset, target: Any, exp_name: str) -> None:
        spectra_rows = int(np.asarray(spectra.data).shape[0])
        target_data = np.asarray(target.data)
        target_rows = int(target_data.shape[0]) if target_data.ndim > 0 else 1
        if spectra_rows != target_rows:
            raise ValueError(
                f"Cannot attach reference values for '{exp_name}': spectra have {spectra_rows} sample rows "
                f"but the target/property file has {target_rows} rows."
            )

        spectra_labels = self._sample_labels(spectra)
        target_labels = self._sample_labels(target)
        if spectra_labels and target_labels and spectra_labels != target_labels:
            mismatch = next(
                (
                    i
                    for i, (spectra_label, target_label) in enumerate(zip(spectra_labels, target_labels))
                    if spectra_label != target_label
                ),
                0,
            )
            raise ValueError(
                f"Cannot attach reference values for '{exp_name}': sample labels differ at row {mismatch + 1} "
                f"({spectra_labels[mismatch]!r} vs {target_labels[mismatch]!r}). "
                "Use matching sample IDs or embed the reference values in the spectral file."
            )

        if spectra_labels and not target_labels:
            warning = (
                "Reference values came from a separate property file without sample labels; rows were attached "
                "by file order. Verify the property file order matches the spectra before trusting calibration metrics."
            )
            logger.warning("[MY_DATASET] %s", warning)
            spectra.meta.setdefault("warnings", []).append(warning)

    @staticmethod
    def _attach_ground_truth_spectra(dataset: SherpaDataset, loaded: list[_LoadedDataset]) -> None:
        candidates = [item for item in loaded if item.ground_truth_spectra is not None]
        if not candidates:
            return
        if len(candidates) > 1:
            logger.debug("Skipping synthetic ground-truth spectra attachment for multi-file stack.")
            return

        item = candidates[0]
        spectra = np.asarray(item.ground_truth_spectra, dtype=np.float64)
        if spectra.ndim != 2 or spectra.size == 0:
            return
        if spectra.shape[1] != dataset.n_features:
            logger.debug(
                "Skipping synthetic ground-truth spectra attachment: S has %s features but dataset has %s.",
                spectra.shape[1],
                dataset.n_features,
            )
            return

        dataset.set_extra("ground_truth.spectra", spectra.tolist())
        dataset.set_extra("ground_truth.spectra_names", item.ground_truth_spectra_names or [])
        dataset.set_extra("ground_truth.spectra_units", item.ground_truth_spectra_units)
        if item.ground_truth_spectra_x is not None:
            dataset.set_extra("ground_truth.spectra_x", np.asarray(item.ground_truth_spectra_x, dtype=float).tolist())
        if item.ground_truth_spectra_x_title is not None:
            dataset.set_extra("ground_truth.spectra_x_title", item.ground_truth_spectra_x_title)
        if item.ground_truth_spectra_x_units is not None:
            dataset.set_extra("ground_truth.spectra_x_units", item.ground_truth_spectra_x_units)

    @staticmethod
    def _apply_loaded_overrides(dataset: SherpaDataset, loaded: list[_LoadedDataset]) -> SherpaDataset:
        overrides = [
            load_prepared_data_overrides(file_path=str(Path(item.file_path).resolve()))
            for item in loaded
            if item.file_path
        ]
        if not overrides:
            return dataset
        merged = merge_prepared_data_overrides(overrides)
        if merged.is_empty():
            return dataset
        return apply_dataset_prepared_data_overrides(dataset, merged)

    @staticmethod
    def _x_length(ds: NDDataset) -> int:
        """Return number of x-axis points (0 if no x-axis).

        Operates on raw NDDataset instances loaded by ``_load_file()``
        before the SherpaDataset conversion step.
        """
        if isinstance(ds, SherpaDataset):
            axis = ds.feature_axis
            return int(axis.length) if axis is not None else int(ds.shape[-1])
        coord = safe_get_coord(ds, "x")
        return len(np.array(coord.data)) if coord is not None else 0

    def _group_by_x_axis(self, loaded: list[_LoadedDataset]) -> list[list[_LoadedDataset]]:
        """Group loaded datasets by compatible x-axis.

        Two datasets are compatible if they have the same number of x points
        and (when both have numeric x) the values match within tolerance.
        Datasets without an x-axis form their own group.
        """
        groups: list[list[_LoadedDataset]] = []
        group_keys: list[tuple[int, np.ndarray | None]] = []  # (length, x_values)

        for item in loaded:
            ds = item.dataset
            if isinstance(ds, SherpaDataset):
                axis = ds.get_feature_axis()
                values = getattr(axis, "values", None) if axis is not None else None
                x = np.asarray(values, dtype=float) if values is not None else None
                length = int(ds.shape[-1])
            else:
                coord = safe_get_coord(ds, "x")
                if coord is not None:
                    x = np.array(coord.data)
                    length = len(x)
                else:
                    x = None
                    length = 0

            matched = False
            for i, (glen, gx) in enumerate(group_keys):
                if length != glen:
                    continue
                if x is None and gx is None:
                    groups[i].append(item)
                    matched = True
                    break
                if x is not None and gx is not None and np.allclose(x, gx, rtol=1e-9, atol=1e-12):
                    groups[i].append(item)
                    matched = True
                    break

            if not matched:
                groups.append([item])
                group_keys.append((length, x))

        return groups

    def _validate_axes(self, datasets: list[NDDataset], file_names: list[str]) -> None:
        """Reject datasets whose x-axes differ."""
        if len(datasets) < 2:
            return
        ref = datasets[0]
        ref_x = self._feature_values(ref)
        if ref_x is None:
            return  # no x-axis to compare

        for i, (ds, fname) in enumerate(zip(datasets[1:], file_names[1:]), 2):
            ds_x = self._feature_values(ds)
            if ds_x is None:
                raise ValueError(f"Cannot merge: '{fname}' has no x-axis but " f"'{file_names[0]}' does.")
            if ds_x.shape != ref_x.shape:
                raise ValueError(
                    f"Cannot merge: x-axis length mismatch.\n"
                    f"  '{file_names[0]}': {len(ref_x)} points\n"
                    f"  '{fname}': {len(ds_x)} points\n"
                    f"All files in the dataset must share the same x-axis."
                )
            if not np.allclose(ds_x, ref_x, rtol=1e-9, atol=1e-12):
                idx = int(np.where(~np.isclose(ds_x, ref_x, rtol=1e-9, atol=1e-12))[0][0])
                raise ValueError(
                    f"Cannot merge: x-axis values differ at index {idx}.\n"
                    f"  '{file_names[0]}': {ref_x[idx]:.6f}\n"
                    f"  '{fname}': {ds_x[idx]:.6f}\n"
                    f"All files in the dataset must share the same x-axis."
                )

    @staticmethod
    def _feature_values(ds: Any) -> np.ndarray | None:
        if isinstance(ds, SherpaDataset):
            axis = ds.get_feature_axis()
            values = getattr(axis, "values", None) if axis is not None else None
            return np.asarray(values, dtype=float) if values is not None else None
        coord = safe_get_coord(ds, "x")
        return np.asarray(coord.data, dtype=float) if coord is not None else None

    def _concatenate(self, datasets: list[NDDataset], file_names: list[str]) -> NDDataset:
        """Validate x-axes match then concatenate along the sample axis."""
        self._validate_axes(datasets, file_names)
        data_arrays = [np.squeeze(np.array(ds.data)) for ds in datasets]
        data_arrays = [arr if arr.ndim > 0 else np.array([arr]) for arr in data_arrays]

        data_arrays_2d = []
        for i, arr in enumerate(data_arrays):
            if arr.ndim == 1:
                data_arrays_2d.append(arr.reshape(1, -1))
            elif arr.ndim == 2:
                data_arrays_2d.append(arr)
            else:
                raise ValueError(f"Unexpected dimensionality in file '{file_names[i]}': shape {arr.shape}")

        concatenated_data = np.concatenate(data_arrays_2d, axis=0)

        y_labels = []
        for ds, arr, fname in zip(datasets, data_arrays_2d, file_names):
            label = Path(fname).name
            n = arr.shape[0]
            source_labels: list[str] = []
            if isinstance(ds, SherpaDataset) and ds.sample_axis is not None and ds.sample_axis.labels:
                source_labels = [str(item) for item in ds.sample_axis.labels]
            if len(source_labels) == n:
                y_labels.extend(
                    clean_sample_labels(
                        source_labels,
                        n,
                        fallback_prefix=label if n == 1 else "Sample",
                        source_name=label,
                    )
                )
            elif n == 1:
                y_labels.append(label)
            else:
                y_labels.extend(clean_sample_labels(None, n, fallback_prefix="Sample"))

        if all(isinstance(ds, SherpaDataset) for ds in datasets):
            first = datasets[0]
            assert isinstance(first, SherpaDataset)
            feature_axis = first.get_feature_axis()
            sample_axis = SampleAxis(labels=y_labels, title="Sample")
            target_chunks = [
                np.asarray(ds.target) for ds in datasets if isinstance(ds, SherpaDataset) and ds.target is not None
            ]
            target = None
            if target_chunks and sum(chunk.shape[0] for chunk in target_chunks) == concatenated_data.shape[0]:
                target = np.concatenate(target_chunks, axis=0)
            return SherpaDataset(
                X=concatenated_data,
                feature_axis=feature_axis,
                sample_axis=sample_axis,
                target=target,
                target_context=first.target_context.model_copy(deep=True) if target is not None else None,
                domain=first.domain.model_copy(deep=True),
                backend=first.backend,
                title="Stacked Dataset",
                units=first.units,
                data_role=first.data_role,
            )

        merged = scp.NDDataset(concatenated_data)

        ref_x = safe_get_coord(datasets[0], "x")
        if ref_x is not None:
            merged.x = ref_x.copy()

        if hasattr(datasets[0], "units") and datasets[0].units is not None:
            merged.units = datasets[0].units

        cat_y = safe_get_coord(merged, "y")
        if cat_y is not None:
            cat_y.title = "Sample"
            cat_y.labels = y_labels
        else:
            cat_x = safe_get_coord(merged, "x")
            merged.set_coordset(
                y=scp.Coord(
                    np.arange(len(y_labels)),
                    title="Sample",
                    labels=y_labels,
                ),
                x=cat_x,
            )

        return merged

    @staticmethod
    def _sample_count(ds: NDDataset) -> int:
        data = np.asarray(ds.data)
        if data.ndim == 0:
            return 1
        if data.ndim == 1:
            return 1
        return int(data.shape[0])

    def _combine_embedded_targets(
        self, loaded: list[_LoadedDataset]
    ) -> tuple[np.ndarray, list[str], str | None] | None:
        """Concatenate embedded property blocks from the spectra group in file order."""
        target_names: list[str] | None = None
        target_units: str | None = None
        target_chunks: list[np.ndarray] = []
        saw_embedded_target = False

        for item in loaded:
            target_data = item.embedded_target_data
            if target_data is None:
                if saw_embedded_target:
                    raise ValueError(
                        f"Embedded property columns are missing for "
                        f"'{item.file_name}' while other spectral "
                        f"files have them."
                    )
                continue

            saw_embedded_target = True
            names = item.embedded_target_names or []
            if target_names is None:
                target_names = list(names)
            elif list(names) != target_names:
                raise ValueError(
                    f"Embedded property columns in '{item.file_name}' do not match the other spectral files."
                )
            if target_units is None:
                target_units = item.embedded_target_units
            elif item.embedded_target_units and item.embedded_target_units != target_units:
                raise ValueError(
                    f"Embedded property units in '{item.file_name}' do not match the other spectral files."
                )

            if target_data.shape[0] != self._sample_count(item.dataset):
                raise ValueError(
                    f"Embedded property row count mismatch in '{item.file_name}': "
                    f"{target_data.shape[0]} target rows for {self._sample_count(item.dataset)} spectra."
                )

            target_chunks.append(target_data)

        if not target_chunks:
            return None

        return np.concatenate(target_chunks, axis=0), target_names or [], target_units

    def _load_file(self, file_path: str, *, file_name: str | None = None) -> _LoadedDataset:
        """Load data from a file, with pandas fallback for CSVs that SCP can't read."""
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        resolved_file_name = file_name or Path(file_path).name
        if ext == ".csv":
            dataset, embedded_target_names, embedded_target_data = self._load_csv_pandas(file_path)
            return _LoadedDataset(
                dataset=dataset,
                file_name=resolved_file_name,
                file_path=file_path,
                embedded_target_names=embedded_target_names,
                embedded_target_data=embedded_target_data,
            )
        if ext == ".npz":
            from spectra_sherpa.app.services.synthesis import is_synthetic_npz

            if is_synthetic_npz(file_path):
                return _load_synthesis_npz_as_loaded_dataset(file_path, file_name=resolved_file_name)

        # Try SpectroChemPy first
        try:
            from spectra_sherpa.app.core.config import get_reader_for_extension

            reader_name = get_reader_for_extension(ext)
            reader_method = getattr(scp, reader_name)
            dataset = reader_method(file_path)

            if dataset is not None:
                if ext == ".mat":
                    dataset = extract_dataset_from_result(dataset, file_path)
                    dataset = remove_index_columns(dataset)
                return _LoadedDataset(dataset=dataset, file_name=resolved_file_name, file_path=file_path)
        except Exception:
            pass  # fall through to pandas fallback

        raise ValueError(f"Failed to load {file_path} (format: {ext or 'unknown'})")

    def _load_csv_pandas(self, file_path: str) -> tuple[Any, list[str] | None, np.ndarray | None]:
        """Load a CSV via pandas -- handles headers, mixed types, etc.

        Splits columns by whether the *header name* parses as a float:
        - Float-named columns -> spectral data, header values become x-axis
        - String-named columns -> label / ID columns (first used as y-labels)
        """
        from spectra_sherpa.app.lib.io import load_csv_as_sherpa

        dataset = load_csv_as_sherpa(file_path)
        if isinstance(dataset, SherpaDataset) and dataset.get_extra("csv.layout") == "axis_column_conditions":
            return dataset, None, None
        if isinstance(dataset, SherpaDataset) and dataset.data_role == "X_features":
            names = None
            if dataset.target_context is not None:
                if dataset.target_context.target_names:
                    names = dataset.target_context.target_names
                elif dataset.target_context.target_name:
                    names = [dataset.target_context.target_name]
            return dataset, names, dataset.target

        df = pd.read_csv(file_path)
        # Partition columns: float-named headers vs string-named headers
        spectral_cols: list[str] = []
        x_vals: list[float] = []
        label_cols: list[str] = []
        for col in df.columns:
            try:
                x_vals.append(float(col))
                spectral_cols.append(col)
            except (ValueError, TypeError):
                label_cols.append(col)

        if not spectral_cols:
            # No float-named columns -- fall back to all numeric columns
            numeric_df = df.select_dtypes(include="number")
            if numeric_df.empty:
                raise ValueError(f"No numeric columns in {file_path}")
            data = numeric_df.values.astype(np.float64)
            dataset = scp.NDDataset(data)
            dataset.title = Path(file_path).stem
            return dataset, None, None

        data = df[spectral_cols].values.astype(np.float64)
        dataset = scp.NDDataset(data)
        dataset.title = Path(file_path).stem

        # Set x-axis from column header values and y-axis for samples
        y_labels = df[label_cols[0]].astype(str).tolist() if label_cols else None
        dataset.set_coordset(
            y=scp.Coord(
                np.arange(data.shape[0]),
                title="Sample",
                labels=y_labels,
            ),
            x=scp.Coord(
                np.array(x_vals),
                title="Feature",
            ),
        )

        # Detect string-named numeric columns as reference properties
        # (mirrors io.py load_csv_as_sherpa logic)
        prop_label_cols = label_cols[1:] if y_labels is not None else label_cols
        if prop_label_cols:
            prop_cols = [c for c in prop_label_cols if pd.api.types.is_numeric_dtype(df[c])]
            if prop_cols:
                return dataset, prop_cols, df[prop_cols].values.astype(np.float64)

        return dataset, None, None

    def _concatenate_feature_tables(self, loaded: list[_LoadedDataset], exp_name: str) -> SherpaDataset:
        """Stack compatible X_features tables while preserving embedded targets."""
        first = loaded[0].dataset
        assert isinstance(first, SherpaDataset)
        first_axis = first.feature_axis
        first_labels = list(first_axis.labels or []) if first_axis is not None else []
        chunks: list[np.ndarray] = []
        targets: list[np.ndarray] = []
        sample_labels: list[str] = []

        for item in loaded:
            ds = item.dataset
            if not isinstance(ds, SherpaDataset):
                raise ValueError(f"Cannot merge feature table with spectral file '{item.file_name}'.")
            axis = ds.feature_axis
            labels = list(axis.labels or []) if axis is not None else []
            if first_labels and labels and labels != first_labels:
                raise ValueError(f"Feature columns in '{item.file_name}' do not match the first feature-table file.")
            data = np.asarray(ds.data, dtype=np.float64)
            chunks.append(data if data.ndim == 2 else data.reshape(1, -1))
            if ds.target is not None:
                targets.append(np.asarray(ds.target))
            n = chunks[-1].shape[0]
            source_axis = ds.sample_axis
            source_labels = list(source_axis.labels or []) if source_axis is not None else []
            sample_labels.extend(
                clean_sample_labels(
                    source_labels if len(source_labels) == n else None,
                    n,
                    fallback_prefix=item.file_name if n == 1 else "Sample",
                    source_name=item.file_name,
                )
            )

        X = np.vstack(chunks)
        target = np.concatenate(targets, axis=0) if targets and sum(len(t) for t in targets) == X.shape[0] else None
        target_context = (
            first.target_context.model_copy(deep=True) if target is not None and first.target_context else None
        )
        return SherpaDataset(
            X=X,
            feature_axis=FeatureAxis(
                values=np.arange(X.shape[1], dtype=float),
                labels=first_labels or None,
                title=getattr(first_axis, "title", None) or "Feature",
            ),
            sample_axis=SampleAxis(labels=sample_labels, title="Sample"),
            target=target,
            target_context=target_context,
            domain=first.domain.model_copy(deep=True),
            backend="pandas",
            title=f"{exp_name} ({len(loaded)} feature file{'s' if len(loaded) != 1 else ''})",
            data_role="X_features",
        )


def _load_synthesis_npz_as_nddataset(file_path: str) -> NDDataset:
    from spectra_sherpa.app.services.synthesis import load_synthetic_npz

    payload = load_synthetic_npz(file_path)
    return _synthesis_npz_payload_to_nddataset(file_path, payload)


def _load_synthesis_npz_as_loaded_dataset(file_path: str, *, file_name: str | None = None) -> _LoadedDataset:
    from spectra_sherpa.app.services.synthesis import load_synthetic_npz

    payload = load_synthetic_npz(file_path)
    target_names = _synthesis_target_names(payload)
    ground_truth = _synthesis_ground_truth(payload)
    return _LoadedDataset(
        dataset=_synthesis_npz_payload_to_nddataset(file_path, payload),
        file_name=file_name or Path(file_path).name,
        file_path=file_path,
        embedded_target_names=target_names,
        embedded_target_data=np.asarray(payload["C"], dtype=np.float64),
        embedded_target_units=_optional_text(payload.get("concentration_units")),
        ground_truth_spectra=np.asarray(payload["S"], dtype=np.float64),
        ground_truth_spectra_names=target_names,
        ground_truth_spectra_units=ground_truth.get("S_units"),
        ground_truth_spectra_x=np.asarray(payload["wavenumber"], dtype=np.float64),
        ground_truth_spectra_x_title=_optional_text(payload.get("metadata", {}).get("x_title")),
        ground_truth_spectra_x_units=_optional_text(payload.get("feature_units")),
    )


def _synthesis_npz_payload_to_nddataset(file_path: str, payload: dict[str, Any]) -> NDDataset:
    data = np.asarray(payload["X"], dtype=np.float64)
    embedded_meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    dataset = scp.NDDataset(data)
    dataset.title = str(embedded_meta.get("title") or Path(file_path).stem)
    value_units = _optional_text(embedded_meta.get("value_units")) or _optional_text(payload.get("units"))
    if value_units is not None:
        dataset.units = value_units
    labels = payload.get("sample_labels") or [f"sample_{i + 1:03d}" for i in range(data.shape[0])]
    dataset.set_coordset(
        y=scp.Coord(np.arange(data.shape[0]), title=_optional_text(embedded_meta.get("y_title")), labels=labels),
        x=scp.Coord(
            np.asarray(payload["wavenumber"], dtype=np.float64),
            title=_optional_text(embedded_meta.get("x_title")),
            units=_optional_text(embedded_meta.get("x_units")) or _optional_text(payload.get("feature_units")),
        ),
    )
    dataset.meta["data_role"] = embedded_meta.get("data_role") or "X_spectra"
    if embedded_meta.get("data_quantity") is not None:
        dataset.meta["data_quantity"] = embedded_meta["data_quantity"]
    if value_units is not None:
        dataset.meta["value_units"] = value_units
        dataset.meta["value_units_label"] = value_units
    dataset.meta["is_time_series"] = bool(embedded_meta.get("is_time_series", False))
    meta = SpectraMeta(
        provenance=DataProvenance(
            source_type=SourceType.SYNTHETIC,
            original_file_path=str(file_path),
            original_file_format="npz",
            created_datetime=datetime.utcnow().isoformat(),
        ),
        processing_steps=["load", "synthetic"],
        custom={
            "synthesis_recipe": payload.get("recipe_json"),
            "synthesis_ground_truth": payload.get("ground_truth_json"),
        },
    )
    set_spectra_meta(dataset, meta)
    return dataset


def _synthesis_target_names(payload: dict[str, Any]) -> list[str]:
    ground_truth = _synthesis_ground_truth(payload)
    names = ground_truth.get("component_names")
    if isinstance(names, list) and names:
        return [str(name) for name in names]

    c = np.asarray(payload["C"])
    return [f"component_{index + 1}" for index in range(c.shape[1] if c.ndim == 2 else 1)]


def _synthesis_ground_truth(payload: dict[str, Any]) -> dict[str, Any]:
    raw_ground_truth = payload.get("ground_truth_json")
    if raw_ground_truth:
        try:
            parsed = json.loads(str(raw_ground_truth))
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            logger.debug("Could not parse synthesis ground-truth metadata", exc_info=True)
    return {}


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
                description=(
                    "How to order files before concatenation"
                    " (filename=alphabetical, numeric_suffix=extract numbers"
                    " from filename, modified_time=file modification timestamp)"
                ),
                required=False,
            ),
            NodeParameter(
                name="validate_axes",
                label="Validate X-Axes Match",
                param_type="boolean",
                default=True,
                description=(
                    "Require all files to have identical x-axes (wavenumbers)."
                    " Recommended: True for strict validation."
                ),
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
        input_ports=[],
        output_type="NDDataset",
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.NDDataset.html",
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

            folder = next((p for p in candidate_paths if p.exists()), None)  # type: ignore[assignment]

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
            for item in folder.rglob("*"):
                if item.is_file():
                    all_files.append(item)
        else:
            # Only immediate directory
            all_files = [f for f in folder.iterdir() if f.is_file()]

        # Filter with case-insensitive matching
        files = []
        for f in all_files:
            # Skip hidden files and system files
            if f.name.startswith((".", "__")):
                continue

            # Case-insensitive pattern matching
            # For recursive patterns, compare relative path; otherwise just filename
            if recursive and "/" in pattern:
                # Pattern includes path (e.g., "subfolder/*.spa")
                # Compare relative path from folder root
                try:
                    rel_path = f.relative_to(folder)
                    match_str = str(rel_path).replace("\\", "/")  # Normalize path separators
                except ValueError:
                    continue
            else:
                # Simple pattern - just match filename
                match_str = f.name

            # Apply case-insensitive matching
            if "*" in pattern or "?" in pattern:
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
                match = re.search(r"(\d+)", file_path.stem)
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
                    f"Failed to load file {i}/{len(files)}: {file_path.name}\n"
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
            logger.debug(
                f"[LOAD_GROUP] Concatenated {len(datasets)} files "
                f"({total_spectra} spectra) into shape {concatenated_data.shape}"
            )

            # Create new NDDataset with stacked data
            concatenated = scp.NDDataset(concatenated_data)

            # Copy x-axis from reference (all validated to be identical)
            lgn_ref_x_coord = safe_get_coord(datasets[0], "x")
            if lgn_ref_x_coord is not None:
                concatenated.x = lgn_ref_x_coord.copy()

            # Set units from reference if available
            if hasattr(datasets[0], "units") and datasets[0].units is not None:
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
        lgn_cat_y_coord = safe_get_coord(concatenated, "y")
        if lgn_cat_y_coord is not None:
            lgn_cat_y_coord.title = "Sample"
            # Set labels to spectrum names (accounting for multi-spectrum files)
            lgn_cat_y_coord.labels = y_labels
        else:
            # Create y-axis with spectrum names
            lgn_cat_x_coord = safe_get_coord(concatenated, "x")
            concatenated.set_coordset(
                y=scp.Coord(np.arange(len(y_labels)), title="Sample", labels=y_labels), x=lgn_cat_x_coord
            )

        # Attach rich metadata (SECURITY: only folder name, not full path)
        folder_name = folder.name if hasattr(folder, "name") else os.path.basename(str(folder))
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
        # Convert to SherpaDataset for uniform DAG contract
        return from_nddataset(concatenated)

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
                f"Failed to load {file_path.name}: {str(e)}\n" f"File type: {ext}\n" f"Full path: {file_path}"
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
        vam_ref_x_coord = safe_get_coord(reference, "x")
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
            vam_ds_x_coord = safe_get_coord(dataset, "x")
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
                    f"X-axis validation failed:\n"
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
                    f"X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has different x-axis values\n"
                    f"Reference: '{reference_name}'\n\n"
                    f"First mismatch at index {mismatch_idx}:\n"
                    f"  {reference_name}: {reference_x[mismatch_idx]:.6f}\n"
                    f"  {file_name}: {dataset_x[mismatch_idx]:.6f}\n\n"
                    f"All spectra must have identical wavenumber axes for concatenation.\n"
                    f"Consider reprocessing files to ensure consistent spectral range and resolution."
                )

        logger.debug(
            f"[LOAD_GROUP] X-axis validation passed: All {len(datasets)} spectra "
            f"have identical x-axes ({len(reference_x)} points)"
        )
