"""Pure readers and unit normalization for SpectraSherpa synthetic NPZ files.

This module owns the portable file-format boundary.  It deliberately has no
database, settings, HTTP, or application-service dependencies so DAG readers
and bundled reference datasets can consume the format in the scientific core.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SYNTHETIC_NPZ_SIGNATURE = "spectra_sherpa_synthetic_v1"
MOLAR_ABSORPTION_COEFFICIENT_UNITS = "L mol^-1 cm^-1"
HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY = 6.02214076e23 / (1000.0 * math.log(10.0))


def load_synthetic_npz(path: str | Path) -> dict[str, Any]:
    """Load and normalize one signed-by-format synthetic dataset archive."""

    with np.load(path, allow_pickle=False) as data:
        if not _npz_has_synthesis_signature(data):
            raise ValueError("NPZ file is not a SpectraSherpa synthetic dataset")
        ground_truth_json = str(data["ground_truth_json"].item())
        payload = {
            "X": np.asarray(data["X"], dtype=float),
            "wavenumber": np.asarray(data["wavenumber"], dtype=float),
            "C": np.asarray(data["C"], dtype=float),
            "S": np.asarray(data["S"], dtype=float),
            "sample_labels": [str(x) for x in data["sample_labels"].tolist()],
            "feature_units": str(data["feature_units"].item()),
            "units": str(data["units"].item()),
            "recipe_json": str(data["recipe_json"].item()),
            "ground_truth_json": ground_truth_json,
            "metadata": read_synthesis_npz_metadata(data),
        }
        if "concentration_units" in data.files:
            payload["concentration_units"] = str(data["concentration_units"].item())
        else:
            try:
                ground_truth = json.loads(ground_truth_json)
                if isinstance(ground_truth, dict) and ground_truth.get("C_units") is not None:
                    payload["concentration_units"] = str(ground_truth["C_units"])
            except Exception:
                pass
    return normalize_synthetic_npz_payload(payload)


def is_synthetic_npz(path: str | Path) -> bool:
    try:
        with np.load(path, allow_pickle=False) as data:
            return _npz_has_synthesis_signature(data)
    except Exception:
        return False


def read_synthesis_npz_metadata(data: np.lib.npyio.NpzFile) -> dict[str, Any]:
    if "metadata_json" not in data.files:
        return {}
    try:
        raw = str(data["metadata_json"].item())
        parsed = json.loads(raw)
    except Exception:
        logger.warning("Failed to parse synthetic npz metadata_json", exc_info=True)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def hitran_cross_section_to_molar_absorptivity(values: Any) -> np.ndarray:
    """Convert HITRAN cross-section values to decadic molar absorptivity."""

    return np.asarray(values, dtype=float) * HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY


def is_hitran_cross_section_units(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("²", "^2").replace("⁻¹", "^-1")
    normalized = normalized.replace("⋅", " ").replace("/", " ")
    return "cm^2" in normalized and ("molecule" in normalized or "particle" in normalized)


def normalize_synthetic_npz_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Patch legacy synthetic-library metadata on read.

    The atmospheric benchmark stores mixture absorbance in X. Its paired
    component-library file stores HITRAN pure-component absorption cross
    sections in X/S. Normalize legacy cross-section payloads to decadic molar
    absorption coefficient, while leaving synthetic mixture X as absorbance.
    """

    try:
        ground_truth = json.loads(str(payload.get("ground_truth_json") or "{}"))
    except (TypeError, ValueError):
        ground_truth = {}
    if not isinstance(ground_truth, dict):
        return payload

    metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    s_units = ground_truth.get("S_units")
    legacy_s_units = (
        isinstance(s_units, list)
        and any(is_hitran_cross_section_units(unit) for unit in s_units)
        or is_hitran_cross_section_units(payload.get("units"))
        or is_hitran_cross_section_units(metadata.get("value_units"))
    )
    if not legacy_s_units:
        return payload

    is_component_library = ground_truth.get("role") == "pure_component_library"
    spectra = np.asarray(payload.get("S"), dtype=float)
    if spectra.ndim == 2 and spectra.size:
        payload["S"] = hitran_cross_section_to_molar_absorptivity(spectra)
        if isinstance(ground_truth.get("S"), list):
            ground_truth["S"] = payload["S"].tolist()

    n_spectra = int(payload["S"].shape[0]) if isinstance(payload.get("S"), np.ndarray) and payload["S"].ndim == 2 else 0
    ground_truth["S_units"] = [MOLAR_ABSORPTION_COEFFICIENT_UNITS] * n_spectra
    payload["ground_truth_json"] = json.dumps(ground_truth)

    if not is_component_library:
        return payload

    payload["X"] = hitran_cross_section_to_molar_absorptivity(payload.get("X"))
    payload["units"] = MOLAR_ABSORPTION_COEFFICIENT_UNITS
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = dict(metadata)
    metadata["data_quantity"] = "Molar absorption coefficient"
    metadata["value_units"] = MOLAR_ABSORPTION_COEFFICIENT_UNITS
    payload["metadata"] = metadata
    return payload


def has_synthesis_signature(data: np.lib.npyio.NpzFile) -> bool:
    """Return whether an open NPZ archive carries the synthetic signature."""

    return _npz_has_synthesis_signature(data)


def _npz_has_synthesis_signature(data: np.lib.npyio.NpzFile) -> bool:
    if "spectra_sherpa_synthetic" not in data.files:
        return False
    try:
        return str(data["spectra_sherpa_synthetic"].item()) == SYNTHETIC_NPZ_SIGNATURE
    except Exception:
        return False
