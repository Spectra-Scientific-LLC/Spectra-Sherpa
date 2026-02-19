"""
Galactic SPC file metadata extractor.

SPC is a binary spectral data format originally developed by Galactic Industries
(now part of Thermo Fisher). It's widely supported across various spectrometer
vendors and spectral processing software.

Key SPC metadata areas:
- File header: Data type, date, resolution, source
- Log block: Extended ASCII metadata (instrument details, comments)
- Sub-file headers: Per-spectrum metadata in multi-spectrum files

Reference: Galactic SPC file format specification
"""

from __future__ import annotations

from typing import Any, Dict

from ..extractor_base import BaseMetadataExtractor


class SPCExtractor(BaseMetadataExtractor):
    """
    Extractor for Galactic SPC files.

    SPC is a legacy but widely supported format. Metadata is stored in
    a binary header with an optional ASCII log block for extended info.
    SpectroChemPy extracts available metadata into dataset.meta.
    """

    extensions = [".spc"]

    # SPC header and log block field mappings
    INSTRUMENT_KEYS = {
        "manufacturer_model": ["fexper", "source", "instrument", "spectrometer"],
        "technique": ["fexper", "experiment type", "technique"],
        "x_units": ["fxtype", "x units", "x-axis units"],
        "y_units": ["fytype", "y units", "y-axis units"],
    }

    ACQUISITION_KEYS = {
        "n_scans": ["scans", "number of scans", "fnsub"],
        "resolution_cm": ["resolution", "fres", "spectral resolution"],
        "acquisition_datetime": ["fdate", "date", "timestamp"],
        "first_x": ["ffirst", "first x"],
        "last_x": ["flast", "last x"],
        "n_points": ["fnpts", "npoints", "number of points"],
        "experiment_type": ["fexper"],
    }

    SAMPLE_KEYS = {
        "sample_name": ["fmemo", "memo", "sample name", "cmnt", "comment"],
        "source_file": ["fsource", "source", "source file"],
        "concentration": ["fconcs", "concentrations"],
        "z_value": ["fz", "z value", "z axis"],
    }

    PROVENANCE_KEYS = {
        "original_title": ["fmemo", "memo", "title"],
        "comment": ["fcmnt", "cmnt", "comment", "log text"],
        "spc_version": ["fversn", "version"],
        "log_text": ["flogtext", "log"],
    }

    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from SPC file.

        SPC has limited but standardized metadata structure.
        """
        meta = self._get_meta(dataset)

        result = {
            "instrument": self._extract_instrument(meta),
            "acquisition": self._extract_acquisition(meta, dataset),
            "conditions": {},  # SPC typically doesn't have condition info
            "sample": self._extract_sample(meta),
            "provenance": self._extract_provenance(meta),
            "extra": self._extract_extra(meta),
        }

        return result

    def _extract_instrument(self, meta: dict) -> dict:
        """Extract instrument-related metadata."""
        instrument = {}

        for field, keys in self.INSTRUMENT_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                instrument[field] = self._clean_value(value)

        # Decode experiment type from fexper code if present
        if "technique" in instrument:
            technique = instrument["technique"]
            decoded = self._decode_experiment_type(technique)
            if decoded:
                instrument["technique_name"] = decoded

        return instrument

    def _extract_acquisition(self, meta: dict, dataset: Any) -> dict:
        """Extract acquisition parameters."""
        acquisition = {}

        for field, keys in self.ACQUISITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in ["n_scans", "n_points"]:
                    acquisition[field] = self._to_int(value)
                elif field in ["resolution_cm", "first_x", "last_x"]:
                    acquisition[field] = self._to_float(value)
                else:
                    acquisition[field] = self._clean_value(value)

        # Calculate spectral range
        if "first_x" in acquisition and "last_x" in acquisition:
            first_x = acquisition.get("first_x")
            last_x = acquisition.get("last_x")
            if first_x is not None and last_x is not None:
                acquisition["wavenumber_min"] = min(first_x, last_x)
                acquisition["wavenumber_max"] = max(first_x, last_x)

        # Also get from x-axis
        x_info = self._extract_x_axis_info(dataset)
        if x_info:
            for key, value in x_info.items():
                if key not in acquisition:
                    acquisition[key] = value

        return acquisition

    def _extract_sample(self, meta: dict) -> dict:
        """Extract sample-related metadata."""
        sample = {}

        for field, keys in self.SAMPLE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field == "z_value":
                    sample[field] = self._to_float(value)
                else:
                    sample[field] = self._clean_value(value)

        return sample

    def _extract_provenance(self, meta: dict) -> dict:
        """Extract provenance metadata."""
        provenance = {}

        for field, keys in self.PROVENANCE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                provenance[field] = self._clean_value(value)

        # Parse log text if present for additional info
        if "log_text" in provenance:
            log_info = self._parse_log_text(provenance["log_text"])
            provenance.update(log_info)

        return provenance

    def _extract_extra(self, meta: dict) -> dict:
        """Extract unrecognized metadata."""
        recognized = set()
        for key_map in [self.INSTRUMENT_KEYS, self.ACQUISITION_KEYS, self.SAMPLE_KEYS, self.PROVENANCE_KEYS]:
            for keys in key_map.values():
                recognized.update(k.lower() for k in keys)

        recognized.update(["processing_history", "provenance", "spectra", "_"])

        extra = {}
        for key, value in meta.items():
            if key.lower() not in recognized and not key.startswith("_"):
                if value is not None and value != "":
                    extra[key] = self._clean_value(value)

        return extra

    def _decode_experiment_type(self, fexper: Any) -> str | None:
        """
        Decode SPC experiment type code.

        SPC uses numeric codes for experiment types.
        """
        # Common SPC experiment type codes
        experiment_types = {
            0: "General SPC",
            1: "Gas Chromatogram",
            2: "General Chromatogram",
            3: "HPLC Chromatogram",
            4: "FT-IR Spectrum",
            5: "NIR Spectrum",
            6: "UV-VIS Spectrum",
            7: "X-ray Diffraction",
            8: "Mass Spectrum",
            9: "NMR Spectrum",
            10: "Raman Spectrum",
            11: "Fluorescence Spectrum",
            12: "Atomic Spectrum",
            13: "Chromatography Diode Array",
        }

        try:
            code = int(fexper)
            return experiment_types.get(code)
        except (ValueError, TypeError):
            # May already be a string description
            return str(fexper) if fexper else None

    def _parse_log_text(self, log_text: str) -> dict:
        """
        Parse SPC log text block for additional metadata.

        Log text is free-form ASCII but often contains key=value pairs.
        """
        info = {}
        if not log_text:
            return info

        lines = str(log_text).split("\n")
        for line in lines:
            line = line.strip()
            if "=" in line:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower().replace(" ", "_")
                    value = parts[1].strip()
                    if key and value:
                        info[f"log_{key}"] = value

        return info

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

        return value

    def _to_int(self, value: Any) -> int | None:
        """Safely convert to int."""
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None

    def _to_float(self, value: Any) -> float | None:
        """Safely convert to float."""
        try:
            val_str = str(value).split()[0]
            return float(val_str)
        except (ValueError, TypeError, IndexError):
            return None
