"""
Generic fallback metadata extractor.

This extractor handles formats without specific extractors (CSV, MAT, TXT, etc.)
and provides best-effort metadata extraction from common keys.
"""

from __future__ import annotations

from typing import Any, Dict

from ..extractor_base import BaseMetadataExtractor


class GenericExtractor(BaseMetadataExtractor):
    """
    Generic fallback extractor for unsupported or simple formats.

    Used for CSV, MAT, TXT, and other formats that may have minimal or
    non-standardized metadata. Extracts common fields by pattern matching.
    """

    # Handles all other extensions as fallback
    extensions = [".csv", ".txt", ".mat", ".npy", ".npz"]

    # Common metadata key patterns (case-insensitive matching)
    COMMON_INSTRUMENT_KEYS = [
        "instrument", "spectrometer", "manufacturer", "model", "detector",
        "source", "beamsplitter", "serial", "hardware"
    ]

    COMMON_ACQUISITION_KEYS = [
        "scans", "resolution", "date", "time", "datetime", "timestamp",
        "velocity", "apodization", "aperture", "gain", "points"
    ]

    COMMON_SAMPLE_KEYS = [
        "sample", "name", "title", "id", "description", "concentration",
        "pathlength", "cell", "preparation"
    ]

    COMMON_PROVENANCE_KEYS = [
        "operator", "user", "owner", "author", "lab", "organization",
        "comment", "note", "remarks"
    ]

    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata using generic pattern matching.

        Performs best-effort extraction from common key patterns.
        """
        meta = self._get_meta(dataset)

        result = {
            "instrument": self._extract_by_patterns(meta, self.COMMON_INSTRUMENT_KEYS),
            "acquisition": self._extract_acquisition(meta, dataset),
            "conditions": {},
            "sample": self._extract_by_patterns(meta, self.COMMON_SAMPLE_KEYS),
            "provenance": self._extract_by_patterns(meta, self.COMMON_PROVENANCE_KEYS),
            "extra": self._extract_extra(meta),
        }

        return result

    def _extract_by_patterns(self, meta: dict, patterns: list[str]) -> dict:
        """
        Extract metadata using fuzzy key matching.

        Matches any key containing a pattern word.
        """
        extracted = {}

        for key, value in meta.items():
            if value is None or value == "":
                continue

            key_lower = key.lower()
            for pattern in patterns:
                if pattern in key_lower:
                    # Normalize the key name
                    normalized_key = self._normalize_key(key)
                    extracted[normalized_key] = self._clean_value(value)
                    break

        return extracted

    def _extract_acquisition(self, meta: dict, dataset: Any) -> dict:
        """Extract acquisition parameters with x-axis info."""
        acquisition = self._extract_by_patterns(meta, self.COMMON_ACQUISITION_KEYS)

        # Add x-axis info
        x_info = self._extract_x_axis_info(dataset)
        if x_info:
            acquisition.update(x_info)

        return acquisition

    def _extract_extra(self, meta: dict) -> dict:
        """
        Collect all remaining unrecognized metadata.

        For generic files, we preserve more metadata since we don't know
        what might be important.
        """
        all_patterns = (
            self.COMMON_INSTRUMENT_KEYS +
            self.COMMON_ACQUISITION_KEYS +
            self.COMMON_SAMPLE_KEYS +
            self.COMMON_PROVENANCE_KEYS
        )

        extra = {}
        for key, value in meta.items():
            if value is None or value == "" or key.startswith("_"):
                continue

            key_lower = key.lower()

            # Check if matched by any pattern
            is_recognized = False
            for pattern in all_patterns:
                if pattern in key_lower:
                    is_recognized = True
                    break

            if not is_recognized and key_lower not in ["processing_history", "provenance", "spectra"]:
                extra[key] = self._clean_value(value)

        return extra

    def _normalize_key(self, key: str) -> str:
        """
        Normalize a metadata key to snake_case.

        E.g., "Sample Name" -> "sample_name"
             "DATE-TIME" -> "date_time"
        """
        # Replace common separators with underscore
        normalized = key.lower()
        for char in [" ", "-", ".", "/"]:
            normalized = normalized.replace(char, "_")

        # Remove leading/trailing underscores and collapse multiple
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        normalized = normalized.strip("_")

        return normalized

    def _clean_value(self, value: Any) -> Any:
        """Clean and convert a metadata value."""
        if value is None:
            return None

        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="replace").strip()
            except Exception:
                return str(value)

        if hasattr(value, "item"):
            return value.item()

        if isinstance(value, str):
            return value.strip()

        # Handle numpy arrays
        if hasattr(value, "tolist"):
            try:
                return value.tolist()
            except Exception:
                pass

        return value
