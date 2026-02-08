"""
Caching utilities for spectral data processing.

Provides preprocessing settings management and spectrum caching.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from app.lib.io import load_spectrum
from app.lib.preprocessing import preprocess_pipeline, PreprocessingSettings

_SETTINGS_REGISTRY: dict[str, dict[str, Any]] = {}

# Field name mapping: frontend/legacy names → new PreprocessingSettings names
_FIELD_MAP = {
    "align_wavenumbers": "align_wavenumbers",
    "wavenumber_alignment_method": "alignment_method",
    "wavenumber_merge_tolerance": "merge_tolerance",
    "apply_cosmic_ray_removal": "remove_cosmic_rays",
    "cosmic_ray_window": "cosmic_ray_window",
    "cosmic_ray_zscore": "cosmic_ray_zscore",
    "apply_savgol": "apply_smoothing",
    "savgol_window": "smoothing_window",
    "savgol_polyorder": "smoothing_polyorder",
    "apply_range_limit": "clip_range",
    "min_wavenumber": "min_wavenumber",
    "max_wavenumber": "max_wavenumber",
}


def register_settings(settings: dict[str, Any]) -> str:
    """
    Register preprocessing settings and return a hash key.

    Parameters
    ----------
    settings : dict
        Preprocessing settings dictionary

    Returns
    -------
    str
        SHA256 hash of the settings (for cache key)
    """
    payload = json.dumps(settings, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    _SETTINGS_REGISTRY[digest] = settings
    return digest


def build_preprocessing_settings(settings: dict[str, Any]) -> PreprocessingSettings:
    """
    Build PreprocessingSettings from a frontend/legacy dictionary.

    Handles field name mapping from legacy names to new names.

    Parameters
    ----------
    settings : dict
        Settings dictionary (may use legacy field names)

    Returns
    -------
    PreprocessingSettings
        Validated preprocessing settings
    """
    mapped = {}
    for old_name, new_name in _FIELD_MAP.items():
        if old_name in settings:
            mapped[new_name] = settings[old_name]
        elif new_name in settings:
            mapped[new_name] = settings[new_name]
    return PreprocessingSettings(**mapped)


@lru_cache(maxsize=128)
def load_preprocessed_spectrum(
    file_path: str, file_mtime: float, settings_hash: str
) -> tuple[Any, dict | None]:
    """
    Load and preprocess a spectrum with caching.

    Parameters
    ----------
    file_path : str
        Path to the spectrum file
    file_mtime : float
        File modification time (for cache invalidation)
    settings_hash : str
        Hash of preprocessing settings

    Returns
    -------
    tuple[Any, dict | None]
        Processed NDDataset and metadata.
    """
    _ = file_mtime  # Used for cache key only

    raw_settings = _SETTINGS_REGISTRY.get(settings_hash)
    if raw_settings is None:
        raise ValueError("Unknown preprocessing settings hash")

    # Load spectrum
    dataset = load_spectrum(file_path)

    # Build settings with field name mapping
    settings = build_preprocessing_settings(raw_settings)

    # Process dataset
    processed_list, _golden_grid = preprocess_pipeline([dataset], settings)
    processed_dataset = processed_list[0]

    # Build metadata
    metadata = {
        "preprocessing": {
            "align_wavenumbers": settings.align_wavenumbers,
            "alignment_method": settings.alignment_method,
            "cosmic_ray_removal": settings.remove_cosmic_rays,
            "smoothing": settings.apply_smoothing,
            "range_limit": settings.clip_range,
        }
    }

    return processed_dataset, metadata
