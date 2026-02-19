"""
Thermo/Nicolet SPA/SPG file metadata extractor.

SPA (Single spectrum) and SPG (Spectral Group) files are native formats for
Thermo/Nicolet FTIR spectrometers (iS50, Nexus, Magna, Summit, etc.).
SpectroChemPy extracts metadata into dataset.meta.

Key Thermo SPA metadata blocks:
- Instrument Info: Spectrometer model, serial number, detector, source
- Collection Parameters: Resolution, scans, date/time, aperture
- Sample Info: Sample name, description, comments
- Processing History: Corrections, background info

Reference: OMNIC/Nicolet file format documentation
"""

from __future__ import annotations

from typing import Any, Dict

from ..extractor_base import BaseMetadataExtractor


class SPAExtractor(BaseMetadataExtractor):
    """
    Extractor for Thermo/Nicolet SPA and SPG files.

    SPA files contain single spectra; SPG files contain spectral groups
    (e.g., kinetic series, spatial mapping). Both use similar metadata
    conventions inherited from OMNIC software.
    """

    extensions = [".spa", ".spg"]

    # Thermo/OMNIC parameter key mappings
    INSTRUMENT_KEYS = {
        "manufacturer_model": ["Spectrometer", "Instrument", "Bench"],
        "serial_number": ["Serial Number", "Serial", "SN", "Bench Serial"],
        "detector_type": ["Detector", "Det Type", "Detector Type"],
        "detector_cooling": ["Detector Cooling", "MCT Cooling"],
        "source_type": ["Source", "IR Source"],
        "beamsplitter": ["Beamsplitter", "Beam Splitter", "BS"],
        "software_version": ["Software Version", "OMNIC Version", "Version"],
    }

    ACQUISITION_KEYS = {
        "n_scans": ["Number of Scans", "Scans", "Num Scans", "Co-additions"],
        "n_background_scans": ["Background Scans", "Bg Scans", "Background Num Scans"],
        "resolution_cm": ["Resolution", "Spectral Resolution", "Res"],
        "apodization": ["Apodization", "Apod Function", "Apodization Function"],
        "zero_fill_factor": ["Zero Fill", "Zero Filling", "ZFF"],
        "gain": ["Gain", "Detector Gain", "Signal Gain"],
        "aperture_mm": ["Aperture", "Beam Aperture", "Aperture Setting"],
        "acquisition_datetime": ["Collection Date", "Date", "Date/Time", "Timestamp"],
        "scan_speed": ["Scan Speed", "Mirror Velocity", "Velocity"],
        "high_frequency": ["High Limit", "High Frequency", "Frequency High"],
        "low_frequency": ["Low Limit", "Low Frequency", "Frequency Low"],
        "sample_spacing": ["Data Spacing", "Sample Spacing", "Point Spacing"],
    }

    CONDITION_KEYS = {
        "temperature_c": ["Temperature", "Sample Temp", "Cell Temperature"],
        "pressure_mbar": ["Pressure", "Sample Pressure", "Cell Pressure"],
        "humidity_percent": ["Humidity", "RH", "Relative Humidity"],
        "purge_status": ["Purge Status", "Purge", "N2 Purge"],
        "bench_temp": ["Bench Temperature", "Optical Bench Temp"],
    }

    SAMPLE_KEYS = {
        "sample_name": ["Sample Name", "Sample", "Sample ID", "Title"],
        "sample_description": ["Description", "Sample Description", "Comment"],
        "sample_form": ["Sample Form", "Form", "Physical State"],
        "accessory": ["Accessory", "Sampling Accessory", "ATR Accessory"],
        "atr_crystal": ["Crystal", "ATR Crystal", "IRE Material"],
        "atr_bounces": ["Number of Bounces", "Reflections", "N Bounces"],
        "pathlength": ["Path Length", "Pathlength", "Cell Pathlength"],
        "background_file": ["Background", "Background File", "Bg File"],
    }

    PROVENANCE_KEYS = {
        "operator": ["Operator", "User", "User Name", "Analyst"],
        "experiment_name": ["Experiment", "Experiment Name"],
        "original_title": ["Title", "Spectrum Title", "Name"],
        "comment": ["Comment", "Comments", "Notes"],
        "lab_name": ["Lab", "Laboratory", "Location"],
        "department": ["Department", "Dept"],
    }

    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from SPA/SPG file.

        Thermo files have good metadata support but with different key naming
        conventions than OPUS files.
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
        instrument = {}

        for field, keys in self.INSTRUMENT_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                instrument[field] = self._clean_value(value)

        # Thermo spectrometers are the manufacturer
        if "manufacturer_model" in instrument:
            model = instrument["manufacturer_model"]
            # Check if it's a Thermo/Nicolet model
            if not any(m in str(model).lower() for m in ["thermo", "nicolet"]):
                # Prepend manufacturer
                instrument["manufacturer"] = "Thermo Scientific"
            else:
                # Parse from combined string
                instrument.update(self._parse_manufacturer_model(model))
        else:
            instrument["manufacturer"] = "Thermo Scientific"

        return instrument

    def _extract_acquisition(self, meta: dict, dataset: Any) -> dict:
        """Extract acquisition parameters."""
        acquisition = {}

        for field, keys in self.ACQUISITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                # Type conversion for numeric fields
                if field in ["n_scans", "n_background_scans", "zero_fill_factor"]:
                    acquisition[field] = self._to_int(value)
                elif field in ["resolution_cm", "aperture_mm", "high_frequency", "low_frequency", "sample_spacing"]:
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
        conditions = {}

        for field, keys in self.CONDITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in ["temperature_c", "pressure_mbar", "humidity_percent", "bench_temp"]:
                    conditions[field] = self._to_float(value)
                else:
                    conditions[field] = self._clean_value(value)

        return conditions

    def _extract_sample(self, meta: dict) -> dict:
        """Extract sample-related metadata."""
        sample = {}

        for field, keys in self.SAMPLE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in ["pathlength", "atr_bounces"]:
                    if field == "atr_bounces":
                        sample[field] = self._to_int(value)
                    else:
                        sample[field] = self._to_float(value)
                else:
                    sample[field] = self._clean_value(value)

        return sample

    def _extract_provenance(self, meta: dict) -> dict:
        """Extract provenance/audit metadata."""
        provenance = {}

        for field, keys in self.PROVENANCE_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                provenance[field] = self._clean_value(value)

        return provenance

    def _extract_extra(self, meta: dict) -> dict:
        """Extract unrecognized metadata for debugging."""
        recognized = set()
        for key_map in [
            self.INSTRUMENT_KEYS,
            self.ACQUISITION_KEYS,
            self.CONDITION_KEYS,
            self.SAMPLE_KEYS,
            self.PROVENANCE_KEYS,
        ]:
            for keys in key_map.values():
                recognized.update(k.lower() for k in keys)

        recognized.update(["processing_history", "provenance", "spectra", "_"])

        extra = {}
        for key, value in meta.items():
            if key.lower() not in recognized and not key.startswith("_"):
                if value is not None and value != "":
                    extra[key] = self._clean_value(value)

        return extra

    def _parse_manufacturer_model(self, combined: str) -> dict:
        """Parse manufacturer and model from combined string."""
        result = {}
        combined_str = str(combined)

        # Thermo/Nicolet models
        thermo_variants = ["Thermo", "THERMO", "Thermo Scientific", "Thermo Fisher"]
        nicolet_variants = ["Nicolet", "NICOLET"]

        for variant in thermo_variants:
            if variant.lower() in combined_str.lower():
                result["manufacturer"] = "Thermo Scientific"
                result["model"] = combined_str.replace(variant, "").strip()
                return result

        for variant in nicolet_variants:
            if variant.lower() in combined_str.lower():
                result["manufacturer"] = "Thermo Scientific (Nicolet)"
                result["model"] = combined_str.replace(variant, "").strip()
                return result

        # If no manufacturer found, assume Thermo (SPA is their format)
        result["manufacturer"] = "Thermo Scientific"
        result["model"] = combined_str

        return result

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
