"""
Bruker OPUS file metadata extractor.

OPUS files store extensive metadata in parameter blocks. SpectroChemPy extracts
these into dataset.meta and/or dataset.params. This extractor normalizes the
Bruker-specific keys to our intermediate format.

Key OPUS parameter blocks:
- Acquisition Parameters (AB): Scans, resolution, velocity, etc.
- Optical Parameters (OPT): Detector, source, beamsplitter, aperture
- Instrument Status (INS): Instrument model, serial number
- Sample Parameters (SNM): Sample name, concentration, preparation
- Data Parameters (DAT): Date, time, operator
- History (HIS): Processing history from OPUS software

Reference: Bruker OPUS User Guide (parameter block documentation)
"""

from __future__ import annotations

from typing import Any, Dict

from ..extractor_base import BaseMetadataExtractor


class OPUSExtractor(BaseMetadataExtractor):
    """
    Extractor for Bruker OPUS binary files (.0, .1, .2, etc. and extensionless).

    OPUS files are the native format for Bruker FTIR spectrometers (Vertex, Tensor,
    Alpha, Invenio, etc.) and contain comprehensive instrument metadata.
    """

    # OPUS files can have numeric extensions (.0, .1, .0000, etc.) or .opus
    # The registry will also check for numeric patterns dynamically
    extensions = [
        ".0",
        ".1",
        ".2",
        ".3",
        ".4",
        ".5",
        ".6",
        ".7",
        ".8",
        ".9",
        ".opus",  # Explicit .opus extension
    ]

    @classmethod
    def handles_extension(cls, ext: str) -> bool:
        """
        Check if this extractor handles a given extension.

        OPUS files can have:
        - Single digit: .0, .1, .2, etc.
        - Multi-digit: .0000, .0001, .00001, etc.
        - Explicit: .opus
        """
        ext_lower = ext.lower()
        if not ext_lower.startswith("."):
            ext_lower = "." + ext_lower

        # Check explicit extensions
        if ext_lower in cls.extensions:
            return True

        # Check for numeric-only extensions (any length)
        ext_stripped = ext_lower.lstrip(".")
        if ext_stripped.isdigit():
            return True

        return False

    # OPUS parameter key mappings
    # Format: (possible_keys, target_field)
    INSTRUMENT_KEYS = {
        "manufacturer_model": ["INS", "Instrument", "Spectrometer", "HWS"],
        "serial_number": ["SNR", "Serial Number", "SN", "ISN"],
        "detector_type": ["DTC", "Detector", "DET", "DTY"],
        "detector_cooling": ["DCO", "Detector Cooling"],
        "source_type": ["SRC", "Source", "SOU"],
        "beamsplitter": ["BMS", "Beamsplitter", "BSM"],
        "firmware_version": ["FWV", "Firmware", "SWV", "Software Version"],
    }

    ACQUISITION_KEYS = {
        "n_scans": ["NSS", "Number of Scans", "Scans", "NS", "NSR"],
        "n_background_scans": ["NSB", "Background Scans", "NBS"],
        "resolution_cm": ["RES", "Resolution", "Spectral Resolution"],
        "scan_velocity_khz": ["VEL", "Scanner Velocity", "Velocity", "VEL.V"],
        "apodization": ["APF", "Apodization", "Apodization Function"],
        "zero_fill_factor": ["ZFF", "Zero Fill Factor", "Zero Fill", "ZF"],
        "phase_correction": ["PHC", "Phase Correction", "Phase Correction Mode"],
        "phase_resolution": ["PHR", "Phase Resolution"],
        "gain": ["GN", "Gain", "GAI", "ADG", "Amplifier Gain"],
        "aperture_mm": ["APT", "Aperture", "Aperture Setting"],
        "acquisition_datetime": ["DAT", "Date", "TIM", "Time", "DT"],
        "acquisition_duration_s": ["DUR", "Duration", "Measurement Time"],
        "high_frequency_limit": ["HFL", "High Frequency Limit"],
        "low_frequency_limit": ["LFL", "Low Frequency Limit"],
        "laser_wavenumber": ["LWN", "Laser Wavenumber"],
    }

    CONDITION_KEYS = {
        "temperature_c": ["TMP", "Temperature", "Sample Temperature", "STC"],
        "pressure_mbar": ["PRS", "Pressure", "Sample Pressure", "Press"],
        "humidity_percent": ["HUM", "Humidity", "RH"],
        "purge_gas": ["PUR", "Purge", "Purge Gas"],
        "purge_time_min": ["PUT", "Purge Time"],
        "co2_level": ["CO2", "CO2 Level"],
        "h2o_level": ["H2O", "H2O Level", "Water Vapor"],
    }

    SAMPLE_KEYS = {
        "sample_name": ["SNM", "Sample Name", "Sample", "SNA"],
        "sample_id": ["SID", "Sample ID", "Sample Number"],
        "sample_form": ["SFM", "Sample Form"],
        "concentration": ["CNM", "Concentration", "CON"],
        "pathlength": ["PTH", "Pathlength", "Path Length", "OPL"],
        "cell_type": ["CEL", "Cell", "Cell Type", "SCT"],
        "atr_crystal": ["ATR", "ATR Crystal", "Crystal"],
        "atr_angle": ["ANG", "Angle", "Incident Angle"],
    }

    PROVENANCE_KEYS = {
        "operator": ["OPE", "Operator", "User", "USR"],
        "experiment_title": ["EXP", "Experiment", "Experiment Name"],
        "original_title": ["TIT", "Title", "Name", "Sample Description"],
        "comment": ["CMT", "Comment", "COM", "Note"],
        "lab_name": ["LAB", "Laboratory", "Lab"],
        "organization": ["ORG", "Organization", "Company"],
    }

    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from OPUS file stored in dataset.meta/params.

        OPUS files have comprehensive metadata - we extract all available fields.
        """
        meta = self._get_meta(dataset)

        result = {
            "instrument": self._extract_instrument(meta),
            "acquisition": self._extract_acquisition(meta, dataset),
            "conditions": self._extract_conditions(meta),
            "sample": self._extract_sample(meta),
            "provenance": self._extract_provenance(meta),
            "extra": self._extract_extra(meta),
        }

        return result

    def _extract_instrument(self, meta: dict) -> dict:
        """Extract instrument-related metadata."""
        instrument: dict[str, Any] = {}

        for field, keys in self.INSTRUMENT_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                instrument[field] = self._clean_value(value)

        # Parse manufacturer from combined string if needed
        if "manufacturer_model" in instrument:
            combined = instrument["manufacturer_model"]
            parsed = self._parse_manufacturer_model(combined)
            instrument.update(parsed)

        return instrument

    def _extract_acquisition(self, meta: dict, dataset: Any) -> dict:
        """Extract acquisition parameters."""
        acquisition: dict[str, Any] = {}

        for field, keys in self.ACQUISITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                # Type conversion for numeric fields
                if field in ["n_scans", "n_background_scans", "zero_fill_factor"]:
                    acquisition[field] = self._to_int(value)
                elif field in [
                    "resolution_cm",
                    "scan_velocity_khz",
                    "phase_resolution",
                    "aperture_mm",
                    "acquisition_duration_s",
                    "high_frequency_limit",
                    "low_frequency_limit",
                    "laser_wavenumber",
                ]:
                    acquisition[field] = self._to_float(value)
                else:
                    acquisition[field] = self._clean_value(value)

        # Add spectral range from x-axis
        x_info = self._extract_x_axis_info(dataset)
        if x_info:
            acquisition.update(x_info)

        return acquisition

    def _extract_conditions(self, meta: dict) -> dict:
        """Extract experimental conditions."""
        conditions: dict[str, Any] = {}

        for field, keys in self.CONDITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in [
                    "temperature_c",
                    "pressure_mbar",
                    "humidity_percent",
                    "purge_time_min",
                    "co2_level",
                    "h2o_level",
                ]:
                    conditions[field] = self._to_float(value)
                else:
                    conditions[field] = self._clean_value(value)

        return conditions

    def _extract_sample(self, meta: dict) -> dict:
        """Extract sample-related metadata."""
        sample: dict[str, Any] = {}

        for field, keys in self.SAMPLE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in ["concentration", "pathlength", "atr_angle"]:
                    sample[field] = self._to_float(value)
                else:
                    sample[field] = self._clean_value(value)

        return sample

    def _extract_provenance(self, meta: dict) -> dict:
        """Extract provenance/audit metadata."""
        provenance: dict[str, Any] = {}

        for field, keys in self.PROVENANCE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                provenance[field] = self._clean_value(value)

        return provenance

    def _extract_extra(self, meta: dict) -> dict:
        """
        Extract unrecognized metadata keys for debugging.

        These are stored but excluded from API responses by default.
        """
        # Collect all recognized keys
        recognized: set[str] = set()
        for key_map in [
            self.INSTRUMENT_KEYS,
            self.ACQUISITION_KEYS,
            self.CONDITION_KEYS,
            self.SAMPLE_KEYS,
            self.PROVENANCE_KEYS,
        ]:
            for keys in key_map.values():
                recognized.update(k.lower() for k in keys)

        # Also exclude internal SpectroChemPy keys
        recognized.update(["processing_history", "provenance", "spectra", "_"])

        extra: dict[str, Any] = {}
        for key, value in meta.items():
            if key.lower() not in recognized and not key.startswith("_"):
                if value is not None and value != "":
                    extra[key] = self._clean_value(value)

        return extra

    def _parse_manufacturer_model(self, combined: str) -> dict:
        """
        Parse manufacturer and model from a combined string.

        E.g., "Bruker Vertex 70v" -> {"manufacturer": "Bruker", "model": "Vertex 70v"}
        """
        result: dict[str, Any] = {}
        combined_str = str(combined)

        known_manufacturers = {
            "Bruker": ["Bruker", "BRUKER"],
            "Thermo": ["Thermo", "THERMO", "Thermo Scientific", "Thermo Fisher"],
            "Agilent": ["Agilent", "AGILENT"],
            "PerkinElmer": ["PerkinElmer", "Perkin Elmer", "PERKINELMER", "PE"],
            "JASCO": ["JASCO", "Jasco"],
            "Nicolet": ["Nicolet", "NICOLET"],  # Now part of Thermo
            "Shimadzu": ["Shimadzu", "SHIMADZU"],
            "Varian": ["Varian", "VARIAN"],  # Now part of Agilent
            "Bio-Rad": ["Bio-Rad", "BIO-RAD", "Biorad"],
        }

        for canonical, variants in known_manufacturers.items():
            for variant in variants:
                if variant.lower() in combined_str.lower():
                    result["manufacturer"] = canonical
                    # Extract model by removing manufacturer
                    model = combined_str
                    for v in variants:
                        model = model.replace(v, "").replace(v.lower(), "")
                    result["model"] = model.strip()
                    break
            if result:
                break

        return result

    def _clean_value(self, value: Any) -> Any:
        """Clean and convert a metadata value."""
        if value is None:
            return None

        # Convert bytes to string
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="replace").strip()
            except Exception:
                return str(value)

        # Convert numpy types
        if hasattr(value, "item"):
            return value.item()

        # Strip strings
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
            # Handle strings with units like "4.0 cm-1"
            val_str = str(value).split()[0]  # Take first part before space
            return float(val_str)
        except (ValueError, TypeError, IndexError):
            return None
