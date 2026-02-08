"""
JCAMP-DX file metadata extractor.

JCAMP-DX (Joint Committee on Atomic and Molecular Physical Data - Data Exchange)
is an open, cross-platform spectral data format defined by IUPAC. It uses
labeled data records (LDRs) in ASCII format.

Key JCAMP-DX records:
- ##TITLE= - Spectrum title
- ##JCAMP-DX= - Format version
- ##DATA TYPE= - INFRARED SPECTRUM, RAMAN SPECTRUM, etc.
- ##ORIGIN= - Instrument/manufacturer
- ##OWNER= - Data owner/operator
- ##DATE= - Acquisition date
- ##TIME= - Acquisition time
- ##RESOLUTION= - Spectral resolution
- ##$... = Vendor-specific extensions (Bruker, Perkin Elmer, etc.)

Reference: IUPAC JCAMP-DX Standard (Pure Appl. Chem., Vol. 60, No. 9, pp. 1389-1403, 1988)
"""

from __future__ import annotations

from typing import Any, Dict

from ..extractor_base import BaseMetadataExtractor


class JCAMPExtractor(BaseMetadataExtractor):
    """
    Extractor for JCAMP-DX files (.jdx, .dx, .jcamp).

    JCAMP-DX is a widely supported open format, but metadata completeness
    varies by instrument vendor. Vendor-specific extensions (##$...) may
    contain additional information.
    """

    extensions = [".jdx", ".dx", ".jcamp"]

    # Standard JCAMP-DX labeled data records
    INSTRUMENT_KEYS = {
        "manufacturer_model": ["ORIGIN", "SPECTROMETER/DATA SYSTEM", "INSTRUMENT"],
        "serial_number": ["$SERIAL NUMBER", "$SN"],
        "detector_type": ["$DETECTOR", "DETECTOR"],
        "source_type": ["$SOURCE", "SOURCE"],
        "beamsplitter": ["$BEAMSPLITTER", "BEAMSPLITTER"],
        "data_type": ["DATA TYPE", "DATATYPE"],
    }

    ACQUISITION_KEYS = {
        "n_scans": ["$SCANS", "$NUMBER OF SCANS", "SCANS"],
        "resolution_cm": ["RESOLUTION", "$RESOLUTION", "$RES"],
        "acquisition_datetime": ["DATE", "TIME", "LONG DATE"],  # Combined later
        "acquisition_date": ["DATE"],
        "acquisition_time": ["TIME"],
        "first_x": ["FIRSTX", "FIRST X"],
        "last_x": ["LASTX", "LAST X"],
        "n_points": ["NPOINTS", "NUMBER OF POINTS"],
        "delta_x": ["DELTAX", "DELTA X"],
        "x_factor": ["XFACTOR", "X FACTOR"],
        "y_factor": ["YFACTOR", "Y FACTOR"],
    }

    SAMPLE_KEYS = {
        "sample_name": ["TITLE", "SAMPLE DESCRIPTION", "$SAMPLE NAME"],
        "sample_id": ["$SAMPLE ID", "SAMPLE ID"],
        "concentration": ["CONCENTRATIONS", "$CONCENTRATION"],
        "cas_number": ["CAS REGISTRY NO", "CAS NUMBER", "CASREGNO"],
        "molform": ["MOLFORM", "MOLECULAR FORMULA"],
        "state": ["STATE", "$STATE", "SAMPLE STATE"],
        "pathlength": ["PATHLENGTH", "$PATHLENGTH", "PATH LENGTH"],
    }

    PROVENANCE_KEYS = {
        "operator": ["OWNER", "$OWNER", "OPERATOR"],
        "original_title": ["TITLE"],
        "comment": ["$COMMENT", "COMMENT", "COMMENTS"],
        "cross_reference": ["CROSS REFERENCE", "XREF"],
        "source_reference": ["SOURCE REFERENCE"],
        "jcamp_version": ["JCAMP-DX"],
        "data_class": ["DATA CLASS", "CLASS"],
    }

    def extract(self, dataset: Any, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from JCAMP-DX file.

        JCAMP metadata is well-structured but vendor extensions vary.
        """
        meta = self._get_meta(dataset)

        result = {
            "instrument": self._extract_instrument(meta),
            "acquisition": self._extract_acquisition(meta, dataset),
            "conditions": {},  # JCAMP rarely has condition info
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

        # Parse manufacturer from ORIGIN if present
        if "manufacturer_model" in instrument:
            instrument.update(self._parse_manufacturer_model(instrument["manufacturer_model"]))

        return instrument

    def _extract_acquisition(self, meta: dict, dataset: Any) -> dict:
        """Extract acquisition parameters."""
        acquisition = {}

        for field, keys in self.ACQUISITION_KEYS.items():
            value = self._safe_get(meta, keys)
            if value is not None:
                if field in ["n_scans", "n_points"]:
                    acquisition[field] = self._to_int(value)
                elif field in ["resolution_cm", "first_x", "last_x", "delta_x",
                               "x_factor", "y_factor"]:
                    acquisition[field] = self._to_float(value)
                else:
                    acquisition[field] = self._clean_value(value)

        # Combine date and time if both present
        if "acquisition_date" in acquisition and "acquisition_time" in acquisition:
            date_str = acquisition.pop("acquisition_date", "")
            time_str = acquisition.pop("acquisition_time", "")
            if date_str:
                acquisition["acquisition_datetime"] = f"{date_str} {time_str}".strip()

        # Calculate spectral range from first_x, last_x if not in x-axis
        if "first_x" in acquisition and "last_x" in acquisition:
            first_x = acquisition.get("first_x")
            last_x = acquisition.get("last_x")
            if first_x is not None and last_x is not None:
                acquisition["wavenumber_min"] = min(first_x, last_x)
                acquisition["wavenumber_max"] = max(first_x, last_x)

        # Also extract from x-axis if available
        x_info = self._extract_x_axis_info(dataset)
        if x_info:
            # Only update if not already set from JCAMP headers
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
                if field in ["concentration", "pathlength"]:
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
        """Extract unrecognized metadata (vendor extensions, etc.)."""
        recognized = set()
        for key_map in [self.INSTRUMENT_KEYS, self.ACQUISITION_KEYS,
                        self.SAMPLE_KEYS, self.PROVENANCE_KEYS]:
            for keys in key_map.values():
                recognized.update(k.lower() for k in keys)

        recognized.update(["processing_history", "provenance", "spectra", "_",
                          "xydata", "xypoints", "peak table", "peak assignments"])

        extra = {}
        for key, value in meta.items():
            if key.lower() not in recognized and not key.startswith("_"):
                if value is not None and value != "":
                    extra[key] = self._clean_value(value)

        return extra

    def _parse_manufacturer_model(self, origin: str) -> dict:
        """Parse manufacturer and model from ORIGIN field."""
        result = {}
        origin_str = str(origin)

        known_manufacturers = {
            "Bruker": ["Bruker", "BRUKER"],
            "Thermo Scientific": ["Thermo", "THERMO", "Nicolet", "NICOLET"],
            "Agilent": ["Agilent", "AGILENT", "Varian"],
            "PerkinElmer": ["PerkinElmer", "Perkin", "PERKINELMER"],
            "JASCO": ["JASCO", "Jasco"],
            "Shimadzu": ["Shimadzu", "SHIMADZU"],
            "Bio-Rad": ["Bio-Rad", "BIO-RAD", "Biorad", "Sadtler"],
        }

        for canonical, variants in known_manufacturers.items():
            for variant in variants:
                if variant.lower() in origin_str.lower():
                    result["manufacturer"] = canonical
                    # Try to extract model
                    model = origin_str
                    for v in variants:
                        model = model.replace(v, "").replace(v.upper(), "").replace(v.lower(), "")
                    model = model.strip(" -,/")
                    if model:
                        result["model"] = model
                    break
            if result:
                break

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
            # JCAMP uses specific formatting - clean up
            return value.strip().strip("=").strip()

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
