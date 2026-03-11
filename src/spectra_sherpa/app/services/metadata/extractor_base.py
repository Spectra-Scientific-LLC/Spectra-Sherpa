"""
Base class and registry for format-specific metadata extractors.

Each file format (OPUS, SPA, JCAMP, SPC) has unique metadata storage conventions.
This module provides a registry pattern to select the appropriate extractor
based on file extension, ensuring extensibility for future formats.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type

import numpy as np


class BaseMetadataExtractor(ABC):
    """
    Abstract base class for format-specific metadata extractors.

    Each subclass implements extraction logic for a specific file format,
    returning raw metadata in a standardized intermediate format before
    normalization to SpectraMeta.

    The intermediate format uses these top-level keys:
    - instrument: dict - Raw instrument info (manufacturer, model, detector, etc.)
    - acquisition: dict - Raw acquisition params (resolution, scans, datetime, etc.)
    - conditions: dict - Environmental conditions (temperature, pressure, etc.)
    - sample: dict - Sample info (name, preparation, etc.)
    - provenance: dict - File origin info (operator, title, etc.)
    - extra: dict - Any unrecognized keys for debugging
    """

    # File extensions this extractor handles (e.g., [".spa", ".spg"])
    extensions: list[str] = []

    @abstractmethod
    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract raw metadata from a loaded dataset.

        Args:
            dataset: Loaded NDDataset (or similar) with raw metadata
            file_path: Path to the original file

        Returns:
            Dict with raw metadata organized by category:
            {
                "instrument": {...},
                "acquisition": {...},
                "conditions": {...},
                "sample": {...},
                "provenance": {...},
                "extra": {...}
            }
        """
        pass

    def _get_meta(self, dataset: Any) -> dict:
        """
        Safely get metadata dict from a dataset.

        SpectroChemPy may store metadata in dataset.meta or dataset.params
        depending on the format. This helper checks both.
        """
        meta: dict[str, Any] = {}

        # Primary: dataset.meta
        if hasattr(dataset, "meta") and dataset.meta:
            if isinstance(dataset.meta, dict):
                meta.update(dataset.meta)
            elif hasattr(dataset.meta, "items"):
                meta.update(dict(dataset.meta.items()))

        # Secondary: dataset.params (OPUS files use this)
        if hasattr(dataset, "params") and dataset.params:
            if isinstance(dataset.params, dict):
                meta.update(dataset.params)
            elif hasattr(dataset.params, "items"):
                meta.update(dict(dataset.params.items()))

        return meta

    def _safe_get(self, meta: dict, keys: list[str], default: Any = None) -> Any:
        """
        Safely get a value from metadata using multiple possible keys.

        Args:
            meta: Metadata dictionary
            keys: List of possible keys to try (case-insensitive)
            default: Default value if not found

        Returns:
            First matching value or default
        """
        # Normalize keys to lowercase for comparison
        normalized_meta = {k.lower(): v for k, v in meta.items()}

        for key in keys:
            key_lower = key.lower()
            if key_lower in normalized_meta:
                value = normalized_meta[key_lower]
                if value is not None and value != "":
                    return value

        return default

    def _extract_x_axis_info(self, dataset: Any) -> dict:
        """
        Extract spectral range info from dataset x-axis.

        Returns dict with wavenumber_min, wavenumber_max, n_points.
        """
        info: dict[str, Any] = {}

        try:
            x_coord = dataset.x
        except (KeyError, AttributeError):
            x_coord = None

        if x_coord is None:
            return info

        try:
            x_data = np.array(x_coord.data) if hasattr(x_coord, "data") else np.array(x_coord)
            if len(x_data) > 0:
                info["wavenumber_min"] = float(np.min(x_data))
                info["wavenumber_max"] = float(np.max(x_data))
                info["n_points"] = len(x_data)

                # Try to get units from x-axis
                if hasattr(x_coord, "units") and x_coord.units:
                    info["x_units"] = str(x_coord.units)
        except (ValueError, TypeError):
            pass

        return info


class ExtractorRegistry:
    """
    Registry for format-specific metadata extractors.

    Provides automatic selection of the appropriate extractor based on
    file extension.
    """

    def __init__(self):
        self._extractors: Dict[str, Type[BaseMetadataExtractor]] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register all built-in extractors."""
        # Import extractors here to avoid circular imports
        from .extractors.generic import GenericExtractor
        from .extractors.jcamp import JCAMPExtractor
        from .extractors.opus import OPUSExtractor
        from .extractors.spa import SPAExtractor
        from .extractors.spc import SPCExtractor

        self.register(OPUSExtractor)
        self.register(SPAExtractor)
        self.register(JCAMPExtractor)
        self.register(SPCExtractor)
        self.register(GenericExtractor)  # Fallback

    def register(self, extractor_cls: Type[BaseMetadataExtractor]):
        """
        Register an extractor class for its declared extensions.

        Args:
            extractor_cls: Extractor class with 'extensions' attribute
        """
        for ext in extractor_cls.extensions:
            ext_lower = ext.lower()
            if not ext_lower.startswith("."):
                ext_lower = "." + ext_lower
            self._extractors[ext_lower] = extractor_cls

    def get_extractor(self, file_path: str) -> Optional[BaseMetadataExtractor]:
        """
        Get the appropriate extractor for a file.

        Args:
            file_path: Path to the file

        Returns:
            Extractor instance or None if no specific extractor found
        """
        ext = os.path.splitext(file_path)[1].lower()

        # Direct extension match
        if ext in self._extractors:
            return self._extractors[ext]()

        # Check for dynamic extension handling (e.g., OPUS numeric extensions)
        # OPUS files can have extensions like .0000, .00001, etc.
        ext_stripped = ext.lstrip(".")
        if ext_stripped.isdigit():
            # Use OPUS extractor for any numeric extension
            from .extractors.opus import OPUSExtractor

            return OPUSExtractor()

        # Check if any extractor class has a handles_extension method
        for extractor_cls in set(self._extractors.values()):
            if hasattr(extractor_cls, "handles_extension"):
                if extractor_cls.handles_extension(ext):
                    return extractor_cls()

        return None

    def get_supported_extensions(self) -> list[str]:
        """Return list of all supported file extensions."""
        return list(self._extractors.keys())
