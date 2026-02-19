"""
Metadata normalizer for mapping raw extracted metadata to SpectraMeta schema.

This module bridges the gap between format-specific raw metadata and our
unified SpectraMeta Pydantic models. It handles:
- Field name mapping (raw keys -> SpectraMeta fields)
- Unit conversion (temperature, pressure, length)
- Date/time normalization
- Enumeration mapping (detector types, techniques, etc.)

The normalizer preserves raw headers under 'raw_file_metadata' for debugging
but excludes them from API responses by default.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from .parsers import (
    combine_date_time,
    map_apodization,
    map_detector_type,
    map_sampling_technique,
    map_window_material,
    parse_datetime,
    parse_length,
    parse_pressure,
    parse_temperature,
    parse_wavenumber,
)


class MetadataNormalizer:
    """
    Normalizer for mapping raw extracted metadata to SpectraMeta schema.

    Takes the intermediate format from extractors and produces a dict
    that can be used to construct SpectraMeta Pydantic models.
    """

    def normalize(self, raw_metadata: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        """
        Normalize raw metadata to SpectraMeta-compatible format.

        Args:
            raw_metadata: Dict from extractor with keys:
                - instrument, acquisition, conditions, sample, provenance, extra
            file_path: Original file path for provenance

        Returns:
            Dict with normalized metadata matching SpectraMeta structure:
            {
                "instrument_metadata": {...},   # -> InstrumentInfo
                "acquisition_params": {...},    # -> AcquisitionParams
                "experimental_conditions": {...}, # -> ExperimentalConditions
                "sample_info": {...},           # -> Sample-related fields
                "provenance": {...},            # -> DataProvenance + AuditInfo
                "raw_file_metadata": {...},     # Preserved but excluded from API
            }
        """
        result = {
            "instrument_metadata": self._normalize_instrument(raw_metadata.get("instrument", {})),
            "acquisition_params": self._normalize_acquisition(raw_metadata.get("acquisition", {})),
            "experimental_conditions": self._normalize_conditions(raw_metadata.get("conditions", {})),
            "sample_info": self._normalize_sample(raw_metadata.get("sample", {})),
            "provenance": self._normalize_provenance(raw_metadata.get("provenance", {}), file_path),
            # Raw metadata preserved for debugging but excluded from API by default
            "raw_file_metadata": raw_metadata.get("extra", {}),
        }

        # Remove empty sections
        result = {k: v for k, v in result.items() if v}

        return result

    def _normalize_instrument(self, raw: dict) -> dict:
        """
        Normalize instrument metadata to InstrumentInfo fields.

        Maps:
            manufacturer_model -> manufacturer, model (split)
            detector_type -> detector_type (enum mapping)
            source_type -> source_type
            beamsplitter -> beamsplitter
            serial_number -> serial_number
            firmware_version -> firmware_version
        """
        info = {}

        # Manufacturer and model
        if "manufacturer" in raw:
            info["manufacturer"] = raw["manufacturer"]
        if "model" in raw:
            info["model"] = raw["model"]

        # If only combined manufacturer_model, don't duplicate
        if "manufacturer_model" in raw and "manufacturer" not in info:
            info["manufacturer_model_raw"] = raw["manufacturer_model"]

        # Detector type (map to enum)
        if "detector_type" in raw:
            mapped = map_detector_type(raw["detector_type"])
            if mapped:
                info["detector_type"] = mapped
            else:
                info["detector_type_raw"] = raw["detector_type"]

        # Detector cooling
        if "detector_cooling" in raw:
            info["detector_cooling"] = raw["detector_cooling"]

        # Source type
        if "source_type" in raw:
            info["source_type"] = raw["source_type"]

        # Beamsplitter
        if "beamsplitter" in raw:
            info["beamsplitter"] = raw["beamsplitter"]

        # Serial number
        if "serial_number" in raw:
            info["serial_number"] = raw["serial_number"]

        # Firmware/software version
        for key in ["firmware_version", "software_version"]:
            if key in raw:
                info["firmware_version"] = raw[key]
                break

        return info

    def _normalize_acquisition(self, raw: dict) -> dict:
        """
        Normalize acquisition parameters to AcquisitionParams fields.

        Maps:
            n_scans -> n_scans (int)
            n_background_scans -> n_background_scans (int)
            resolution_cm -> resolution_cm (float, parsed)
            scan_velocity_khz -> scan_velocity_khz (float)
            apodization -> apodization (normalized name)
            zero_fill_factor -> zero_fill_factor (int)
            phase_correction -> phase_correction
            gain -> gain
            aperture_mm -> aperture_mm (float, parsed)
            acquisition_datetime -> acquisition_datetime (ISO format)
            wavenumber_min/max -> wavenumber_min/max (float)
            n_points -> n_points (int)
        """
        params = {}

        # Scan counts
        if "n_scans" in raw and raw["n_scans"] is not None:
            params["n_scans"] = int(raw["n_scans"])
        if "n_background_scans" in raw and raw["n_background_scans"] is not None:
            params["n_background_scans"] = int(raw["n_background_scans"])

        # Resolution
        if "resolution_cm" in raw:
            res = parse_wavenumber(raw["resolution_cm"])
            if res is not None:
                params["resolution_cm"] = res

        # Scan velocity
        if "scan_velocity_khz" in raw:
            vel = raw["scan_velocity_khz"]
            if isinstance(vel, (int, float)):
                params["scan_velocity_khz"] = float(vel)

        # Apodization (normalize name)
        if "apodization" in raw:
            params["apodization"] = map_apodization(raw["apodization"])

        # Zero fill factor
        if "zero_fill_factor" in raw and raw["zero_fill_factor"] is not None:
            params["zero_fill_factor"] = int(raw["zero_fill_factor"])

        # Phase correction
        if "phase_correction" in raw:
            params["phase_correction"] = raw["phase_correction"]

        # Gain
        if "gain" in raw:
            params["gain"] = str(raw["gain"])

        # Aperture
        if "aperture_mm" in raw:
            apt = parse_length(raw["aperture_mm"], target_unit="mm")
            if apt is not None:
                params["aperture_mm"] = apt

        # Acquisition datetime (normalize to ISO)
        dt_raw = raw.get("acquisition_datetime")
        if dt_raw:
            params["acquisition_datetime"] = parse_datetime(dt_raw)
        else:
            # Try combining separate date and time
            date_val = raw.get("acquisition_date")
            time_val = raw.get("acquisition_time")
            if date_val:
                combined = combine_date_time(date_val, time_val)
                if combined:
                    params["acquisition_datetime"] = combined

        # Spectral range
        if "wavenumber_min" in raw:
            wn = parse_wavenumber(raw["wavenumber_min"])
            if wn is not None:
                params["wavenumber_min"] = wn
        if "wavenumber_max" in raw:
            wn = parse_wavenumber(raw["wavenumber_max"])
            if wn is not None:
                params["wavenumber_max"] = wn

        # Number of points
        if "n_points" in raw and raw["n_points"] is not None:
            params["n_points"] = int(raw["n_points"])

        # Duration
        if "acquisition_duration_s" in raw:
            dur = raw["acquisition_duration_s"]
            if isinstance(dur, (int, float)):
                params["acquisition_duration_s"] = float(dur)

        return params

    def _normalize_conditions(self, raw: dict) -> dict:
        """
        Normalize experimental conditions to ExperimentalConditions fields.

        Maps:
            temperature_c -> temperature_c (converted to Celsius)
            pressure_mbar -> pressure_mbar (converted to mbar)
            humidity_percent -> ambient_humidity_percent
            purge_gas -> purge_gas
            co2_level / h2o_level -> background_co2_ppm / background_h2o_ppm
        """
        conditions = {}

        # Temperature (convert to Celsius)
        if "temperature_c" in raw:
            temp = parse_temperature(raw["temperature_c"], target_unit="C")
            if temp is not None:
                conditions["temperature_c"] = temp

        # Pressure (convert to mbar)
        if "pressure_mbar" in raw:
            pres = parse_pressure(raw["pressure_mbar"], target_unit="mbar")
            if pres is not None:
                conditions["pressure_mbar"] = pres

        # Humidity
        if "humidity_percent" in raw:
            hum = raw["humidity_percent"]
            if isinstance(hum, (int, float)):
                conditions["ambient_humidity_percent"] = float(hum)

        # Purge gas
        for key in ["purge_gas", "purge_status"]:
            if key in raw:
                conditions["purge_gas"] = raw[key]
                break

        # Background levels
        if "co2_level" in raw:
            conditions["background_co2_ppm"] = raw["co2_level"]
        if "h2o_level" in raw:
            conditions["background_h2o_ppm"] = raw["h2o_level"]

        # Bench temperature (ambient)
        if "bench_temp" in raw:
            temp = parse_temperature(raw["bench_temp"], target_unit="C")
            if temp is not None:
                conditions["ambient_temperature_c"] = temp

        return conditions

    def _normalize_sample(self, raw: dict) -> dict:
        """
        Normalize sample metadata.

        Maps:
            sample_name -> sample_name
            sample_id -> sample_id
            concentration -> concentration
            pathlength -> pathlength_mm (converted to mm)
            atr_crystal -> atr_crystal (enum mapping)
            atr_bounces -> atr_n_bounces
            accessory -> sampling_technique (inferred)
        """
        sample = {}

        # Sample identifiers
        if "sample_name" in raw:
            sample["sample_name"] = raw["sample_name"]
        if "sample_id" in raw:
            sample["sample_id"] = raw["sample_id"]
        if "sample_description" in raw:
            sample["sample_description"] = raw["sample_description"]

        # Concentration
        if "concentration" in raw:
            sample["concentration"] = raw["concentration"]

        # Pathlength (convert to mm)
        if "pathlength" in raw:
            pl = parse_length(raw["pathlength"], target_unit="mm")
            if pl is not None:
                sample["pathlength_mm"] = pl

        # ATR crystal (map to enum)
        if "atr_crystal" in raw:
            mapped = map_window_material(raw["atr_crystal"])
            if mapped:
                sample["atr_crystal"] = mapped
            else:
                sample["atr_crystal_raw"] = raw["atr_crystal"]

        # ATR bounces
        if "atr_bounces" in raw:
            sample["atr_n_bounces"] = raw["atr_bounces"]
        if "atr_angle" in raw:
            sample["atr_angle_deg"] = raw["atr_angle"]

        # Infer sampling technique from accessory
        if "accessory" in raw:
            technique = map_sampling_technique(raw["accessory"])
            if technique:
                sample["sampling_technique"] = technique
            sample["accessory"] = raw["accessory"]

        # Cell type
        if "cell_type" in raw:
            sample["cell_type"] = raw["cell_type"]

        # Background file reference
        if "background_file" in raw:
            sample["background_file"] = raw["background_file"]

        # Sample form/state
        if "sample_form" in raw:
            sample["sample_form"] = raw["sample_form"]

        # CAS number (for JCAMP)
        if "cas_number" in raw:
            sample["cas_number"] = raw["cas_number"]
        if "molform" in raw:
            sample["molecular_formula"] = raw["molform"]

        return sample

    def _normalize_provenance(self, raw: dict, file_path: str) -> dict:
        """
        Normalize provenance metadata.

        Maps:
            operator -> operator
            original_title -> original_title
            comment -> notes
            lab_name -> lab_name
            organization -> organization
            + file path info
        """
        provenance = {}

        # Operator/user
        if "operator" in raw:
            provenance["operator"] = raw["operator"]

        # Title
        if "original_title" in raw:
            provenance["original_title"] = raw["original_title"]
        elif "experiment_title" in raw:
            provenance["original_title"] = raw["experiment_title"]
        elif "experiment_name" in raw:
            provenance["original_title"] = raw["experiment_name"]

        # Comments/notes
        if "comment" in raw:
            provenance["notes"] = raw["comment"]

        # Lab/organization
        if "lab_name" in raw:
            provenance["lab_name"] = raw["lab_name"]
        if "organization" in raw:
            provenance["organization"] = raw["organization"]
        if "department" in raw:
            provenance["department"] = raw["department"]

        # File format info (SECURITY: only store filename, not full path)
        ext = os.path.splitext(file_path)[1].lower()
        provenance["original_file_format"] = ext.lstrip(".")
        provenance["original_filename"] = os.path.basename(file_path)

        # JCAMP-specific
        if "jcamp_version" in raw:
            provenance["jcamp_version"] = raw["jcamp_version"]
        if "cross_reference" in raw:
            provenance["cross_reference"] = raw["cross_reference"]

        return provenance

    def merge_with_existing(self, normalized: Dict[str, Any], existing_meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge normalized metadata with existing dataset.meta, preserving existing values.

        This implements the "never overwrite existing fields blindly" principle.
        Processing history is normalized to a list of dicts before merging.

        Args:
            normalized: Newly extracted and normalized metadata
            existing_meta: Existing dataset.meta dict

        Returns:
            Merged metadata dict
        """
        merged = dict(existing_meta)  # Copy existing

        # Merge each section, preserving existing values
        for section_key in [
            "instrument_metadata",
            "acquisition_params",
            "experimental_conditions",
            "sample_info",
            "provenance",
        ]:
            if section_key in normalized:
                existing_section = merged.get(section_key, {})
                new_section = normalized[section_key]

                # Only add new fields, don't overwrite existing
                for key, value in new_section.items():
                    if key not in existing_section or existing_section[key] is None:
                        existing_section[key] = value

                merged[section_key] = existing_section

        # Raw file metadata goes into a separate key (excluded from API)
        if "raw_file_metadata" in normalized:
            if "raw_file_metadata" not in merged:
                merged["raw_file_metadata"] = {}
            merged["raw_file_metadata"].update(normalized["raw_file_metadata"])

        # Ensure processing_history is a list of dicts
        if "processing_history" in merged:
            history = merged["processing_history"]
            if not isinstance(history, list):
                history = [history] if history else []
            # Normalize each entry to dict if needed
            normalized_history = []
            for entry in history:
                if isinstance(entry, dict):
                    normalized_history.append(entry)
                elif isinstance(entry, str):
                    normalized_history.append({"operation": entry})
                else:
                    normalized_history.append({"raw": str(entry)})
            merged["processing_history"] = normalized_history

        return merged
