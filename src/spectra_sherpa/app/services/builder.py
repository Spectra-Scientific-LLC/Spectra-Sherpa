"""
Builder service for spectral data processing.

Provides preprocessing, blending, and curve generation services.
Uses NDDataset as the primary data type throughout.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, List, Dict, Optional, TYPE_CHECKING

import numpy as np

from app.core.config import settings
from app.services.cache import build_preprocessing_settings, load_preprocessed_spectrum, register_settings
from app.services.experiments import resolve_data_path

from app.lib.blending import BlendSettings, blend_datasets
from app.lib.curves import curve_segments, initial_curve_points, generate_concentration_curve
from app.lib.io import load_spectrum
from app.lib.spectral.dataset import create_spectral_dataset, SpectralUnit
from app.lib.preprocessing import preprocess_pipeline

if TYPE_CHECKING:
    from app.lib.scp_compat import NDDataset


def _dataset_to_payload(dataset: "NDDataset") -> Dict[str, Any]:
    """
    Convert NDDataset to a JSON-serializable payload dict.

    Parameters
    ----------
    dataset : NDDataset
        SpectroChemPy dataset

    Returns
    -------
    dict
        JSON-serializable payload with all metadata preserved
    """
    # Extract wavenumbers
    # NOTE: NDDataset.__getattr__ raises KeyError (not AttributeError) for missing coords
    try:
        x_coord = dataset.x
    except (KeyError, AttributeError):
        x_coord = None
    if x_coord is not None:
        wavenumber = np.asarray(x_coord.data, dtype=float)
    else:
        wavenumber = np.arange(dataset.shape[-1], dtype=float)

    # Extract absorbance
    absorbance = np.asarray(dataset.data, dtype=float)
    if absorbance.ndim > 1:
        absorbance = absorbance.flatten()

    # Extract metadata
    meta = dict(dataset.meta) if hasattr(dataset, "meta") and dataset.meta else {}
    calibration = meta.get("calibration", {})

    # Build payload
    payload: Dict[str, Any] = {
        "label": dataset.title if hasattr(dataset, "title") and dataset.title else "UNKNOWN",
        "file_path": meta.get("source_file"),
        "wavenumber": wavenumber.tolist(),
        "absorbance": absorbance.tolist(),
        "source": meta.get("source_type", "csv"),
        "model_type": calibration.get("model_type"),
        "model_at_wavenumber": calibration.get("model_at_wavenumber"),
        "slope": calibration.get("slope"),
        "intercept": calibration.get("intercept"),
        "s": calibration.get("s"),
        "p": calibration.get("p"),
        "c": calibration.get("c"),
        "reference_concentration": calibration.get("reference_concentration"),
        "concentration_mode": calibration.get("concentration_mode"),
        "x_label": meta.get("x_label"),
        "x_unit": meta.get("x_unit"),
        "pathlength_m": meta.get("pathlength_m"),
    }

    # Include additional metadata if present
    if "chemometrics" in meta:
        payload["chemometrics"] = meta["chemometrics"]
    if "provenance" in meta:
        payload["provenance"] = meta["provenance"]
    if "spectral_resolution" in meta:
        payload["spectral_resolution"] = meta["spectral_resolution"]

    return payload


class BuilderService:
    def __init__(self) -> None:
        self.max_spectra = settings.max_spectra_per_job
        self.max_wavenumbers = settings.max_wavenumbers

    def preprocess(
        self, spectra: list[dict[str, Any]], settings_dict: dict[str, Any]
    ) -> tuple[list[Any], dict | None]:
        """
        Preprocess spectra according to settings.

        Parameters
        ----------
        spectra : list[dict]
            List of spectrum payloads
        settings_dict : dict
            Preprocessing settings

        Returns
        -------
        tuple[list[NDDataset], dict | None]
            Processed spectra as NDDataset and metadata.
            The returned spectra can be passed directly to to_payload().
        """
        if len(spectra) > self.max_spectra:
            raise ValueError("Too many spectra in request")

        preprocess_settings = build_preprocessing_settings(settings_dict)
        settings_hash = register_settings(settings_dict)

        # Special case: single file path without wavenumber data
        if len(spectra) == 1 and spectra[0].get("file_path") and not spectra[0].get("wavenumber"):
            datasets = self._load_datasets_from_file(spectra[0])

            # For single-spectrum files, use caching
            if len(datasets) == 1:
                source_file = datasets[0].meta.get("source_file")
                if source_file:
                    file_mtime = Path(source_file).stat().st_mtime
                    cached_data, metadata = load_preprocessed_spectrum(
                        source_file, file_mtime, settings_hash
                    )
                    return [cached_data], metadata

            # For multi-spectrum files (like MAT), process all datasets
            if len(datasets) > self.max_spectra:
                raise ValueError(
                    f"File contains {len(datasets)} spectra, which exceeds the maximum limit of {self.max_spectra}. "
                    f"Consider splitting the file or increasing MAX_SPECTRA_PER_JOB in your environment."
                )
            self._validate_wavenumbers_ds(datasets)
            processed, metadata = self._preprocess_datasets(datasets, preprocess_settings)
            return processed, metadata

        datasets = [self._dataset_from_payload(item) for item in spectra]
        self._validate_wavenumbers_ds(datasets)
        processed, metadata = self._preprocess_datasets(datasets, preprocess_settings)
        return processed, metadata

    def generate_concentrations(
        self,
        curve_specs: list[dict[str, Any]],
        n_points: int = 100,
        time_min: float = 0.0,
        time_max: float = 1.0,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """
        Generate concentration curves for multiple species.

        This is the concentration generation step, separate from spectral synthesis.
        Returns only concentration arrays and time axis - no spectral computation.

        Parameters
        ----------
        curve_specs : list[dict]
            List of curve specifications, each with:
            - label: species identifier
            - curve_type: sigmoid, gaussian, linear, exponential, step, constant, catmull_rom
            - max_concentration: peak concentration value
            - center: center position for sigmoid/gaussian (0-1)
            - width: width parameter for sigmoid/gaussian/exponential
            - control_points: for catmull_rom curves
        n_points : int
            Number of time points to generate
        time_min : float
            Start time
        time_max : float
            End time

        Returns
        -------
        tuple[np.ndarray, dict[str, np.ndarray]]
            Time axis and concentration arrays for each species
        """
        times = np.linspace(time_min, time_max, n_points)
        concentrations: dict[str, np.ndarray] = {}

        for spec in curve_specs:
            label = spec.get("label", f"Species_{len(concentrations) + 1}")
            curve_type = spec.get("curve_type", "constant")
            max_conc = spec.get("max_concentration", 1.0)
            center = spec.get("center", 0.5)
            width = spec.get("width", 0.1)
            control_points = spec.get("control_points")

            concentrations[label] = generate_concentration_curve(
                curve_type=curve_type,
                n_points=n_points,
                max_concentration=max_conc,
                center=center,
                width=width,
                control_points=control_points,
            )

        return times, concentrations

    def synthesize_spectra(
        self,
        species: list[dict[str, Any]],
        concentrations: dict[str, list[float]],
        settings_dict: dict[str, Any],
        pathlength_m: float | None = None,
    ) -> "NDDataset":
        """
        Synthesize blended spectra from species and concentration profiles.

        This is the spectral synthesis step - consumes pre-generated concentrations
        and produces an NDDataset of absorbance values.

        Parameters
        ----------
        species : list[dict]
            List of species spectrum payloads with calibration models
        concentrations : dict[str, list[float]]
            Concentration values for each species over time (from generate_concentrations)
        settings_dict : dict
            Synthesis settings (system saturation, etc.)
        pathlength_m : float, optional
            Pathlength for concentration mode conversion

        Returns
        -------
        NDDataset
            Synthesized mixture spectra with ground truth in metadata
        """
        if len(species) > self.max_spectra:
            raise ValueError("Too many species in request")

        # Work with NDDataset directly
        datasets = [self._dataset_from_payload(item) for item in species]
        self._validate_wavenumbers_ds(datasets)

        blend_settings = self._build_blend_settings(settings_dict)
        concentration_arrays = {
            label: np.array(values, dtype=float)
            for label, values in concentrations.items()
        }

        return blend_datasets(
            datasets,
            concentration_arrays,
            blend_settings,
            pathlength_m=pathlength_m,
        )

    def blend(
        self,
        species: list[dict[str, Any]],
        concentration_timeseries: dict[str, list[float]],
        settings_dict: dict[str, Any],
        pathlength_m: float | None = None,
    ) -> "NDDataset":
        """
        DEPRECATED: Use synthesize_spectra() instead.

        Blend multiple species according to concentration timeseries.
        This method is preserved for backward compatibility.
        """
        import warnings
        warnings.warn(
            "blend() is deprecated, use synthesize_spectra() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.synthesize_spectra(
            species=species,
            concentrations=concentration_timeseries,
            settings_dict=settings_dict,
            pathlength_m=pathlength_m,
        )

    def generate_curves(self, count: int) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        """
        Generate Catmull-Rom curve control points and segments.

        Parameters
        ----------
        count : int
            Number of control points

        Returns
        -------
        tuple[list[dict], list[dict]]
            Control points and curve segments
        """
        points = initial_curve_points(count)
        segments = curve_segments(points)
        return points, segments

    def to_payload(self, data: "NDDataset") -> dict[str, Any]:
        """
        Convert an NDDataset to a JSON-serializable payload.

        Parameters
        ----------
        data : NDDataset
            Spectrum data to convert

        Returns
        -------
        dict
            JSON-serializable representation with all metadata preserved
        """
        return _dataset_to_payload(data)

    def _build_blend_settings(self, settings_dict: dict[str, Any]) -> BlendSettings:
        """Build BlendSettings from a dictionary."""
        allowed = {field.name for field in fields(BlendSettings)}
        filtered = {key: value for key, value in settings_dict.items() if key in allowed}
        return BlendSettings(**filtered)

    def _preprocess_datasets(
        self,
        datasets: List["NDDataset"],
        preprocess_settings: Any,
    ) -> tuple[List["NDDataset"], Optional[Dict]]:
        """
        Preprocess datasets using the preprocessing pipeline.

        Returns NDDataset directly to preserve all metadata.
        """
        # Process all datasets at once
        processed_datasets, _golden_grid = preprocess_pipeline(datasets, preprocess_settings)

        # Build metadata
        metadata = {
            "preprocessing": {
                "align_wavenumbers": preprocess_settings.align_wavenumbers,
                "alignment_method": preprocess_settings.alignment_method,
                "cosmic_ray_removal": preprocess_settings.remove_cosmic_rays,
                "smoothing": preprocess_settings.apply_smoothing,
                "range_limit": preprocess_settings.clip_range,
            }
        }

        return processed_datasets, metadata

    def _dataset_from_payload(self, payload: dict[str, Any]) -> "NDDataset":
        """Create an NDDataset from a payload dictionary."""
        if payload.get("wavenumber") is None or payload.get("absorbance") is None:
            return self._load_dataset_from_file(payload)

        wavenumber = np.array(payload["wavenumber"], dtype=float)
        absorbance = np.array(payload["absorbance"], dtype=float)

        if wavenumber.size == 0 or absorbance.size == 0:
            raise ValueError("Spectrum arrays cannot be empty")
        if wavenumber.size != absorbance.size:
            raise ValueError("Wavenumber and absorbance length mismatch")

        file_path = payload.get("file_path")
        resolved_path = self._resolve_payload_path(file_path) if file_path else None

        # Create NDDataset directly
        dataset = create_spectral_dataset(
            data=absorbance,
            wavenumbers=wavenumber,
            units=SpectralUnit.ABSORBANCE,
            title=payload.get("label") or "UNKNOWN",
        )

        # Add metadata
        dataset.meta["source_file"] = str(resolved_path) if resolved_path else None
        dataset.meta["source_type"] = payload.get("source", "csv")

        # Add calibration metadata if present
        if payload.get("model_type"):
            calibration = {
                "model_type": payload["model_type"],
                "concentration_mode": payload.get("concentration_mode"),
            }

            if payload.get("reference_concentration") is not None:
                calibration["reference_concentration"] = payload["reference_concentration"]

            if payload.get("slope") is not None:
                calibration["slope"] = payload["slope"]
            if payload.get("intercept") is not None:
                calibration["intercept"] = payload["intercept"]
            if payload.get("s") is not None:
                calibration["s"] = payload["s"]
            if payload.get("p") is not None:
                calibration["p"] = payload["p"]
            if payload.get("c") is not None:
                calibration["c"] = payload["c"]
            if payload.get("model_at_wavenumber") is not None:
                calibration["model_at_wavenumber"] = payload["model_at_wavenumber"]

            dataset.meta["calibration"] = calibration

        # Add additional metadata
        if payload.get("x_label"):
            dataset.meta["x_label"] = payload["x_label"]
        if payload.get("x_unit"):
            dataset.meta["x_unit"] = payload["x_unit"]
        if payload.get("pathlength_m") is not None:
            dataset.meta["pathlength_m"] = payload["pathlength_m"]

        return dataset

    def _load_dataset_from_file(self, payload: dict[str, Any]) -> "NDDataset":
        """Load a single dataset from a file (takes first if multiple exist)."""
        datasets = self._load_datasets_from_file(payload)
        return datasets[0]

    def _load_datasets_from_file(self, payload: dict[str, Any]) -> List["NDDataset"]:
        """Load all datasets from a file (supports multi-spectrum files)."""
        file_path = payload.get("file_path")
        if not file_path:
            raise ValueError("file_path is required when spectra arrays are missing")

        resolved = self._resolve_payload_path(file_path)

        # Use load_spectrum function (returns NDDataset)
        dataset = load_spectrum(resolved)

        # Handle stacked datasets (multiple spectra)
        datasets: List["NDDataset"] = []
        if dataset.ndim == 2 and dataset.shape[0] > 1:
            try:
                x_coord = dataset.x
            except (KeyError, AttributeError):
                x_coord = None
            wavenumber = x_coord.data if x_coord is not None else np.arange(dataset.shape[1])

            for i in range(dataset.shape[0]):
                label = f"{dataset.title}_{i + 1}" if dataset.title else f"Spectrum_{i + 1}"
                try:
                    y_coord = dataset.y
                except (KeyError, AttributeError):
                    y_coord = None
                if y_coord is not None and i < len(y_coord.data):
                    label = str(y_coord.data[i])

                # Create individual NDDataset for each spectrum
                ds = create_spectral_dataset(
                    data=dataset.data[i, :].copy(),
                    wavenumbers=wavenumber.copy(),
                    units=SpectralUnit.ABSORBANCE,
                    title=label,
                )
                ds.meta["source_file"] = str(resolved)
                ds.meta["source_type"] = dataset.meta.get("source_type", "csv") if hasattr(dataset, "meta") else "csv"
                datasets.append(ds)
        else:
            # Single spectrum - use the loaded dataset directly
            dataset.meta["source_file"] = str(resolved)
            datasets = [dataset]

        if not datasets:
            raise ValueError("No spectra found at file path")

        # Apply label prefix if provided
        if payload.get("label") and len(datasets) > 1:
            base_label = payload["label"]
            for i, ds in enumerate(datasets):
                ds.title = f"{base_label}_{i + 1}"
        elif payload.get("label"):
            datasets[0].title = payload["label"]

        return datasets

    def _resolve_payload_path(self, file_path: str) -> Path:
        """Resolve a file path from a payload."""
        path = Path(file_path)
        if not path.is_absolute():
            path = resolve_data_path(file_path)
        path = path.resolve()
        if not path.is_relative_to(settings.data_dir):
            raise ValueError("File path must be within data directory")
        return path

    def _validate_wavenumbers_ds(self, datasets: List["NDDataset"]) -> None:
        """Validate wavenumber array sizes for NDDataset list."""
        for ds in datasets:
            try:
                x_coord = ds.x
            except (KeyError, AttributeError):
                x_coord = None
            wavenumber_size = x_coord.size if x_coord is not None else ds.shape[-1]
            if wavenumber_size > self.max_wavenumbers:
                raise ValueError("Spectrum exceeds max wavenumbers limit")
