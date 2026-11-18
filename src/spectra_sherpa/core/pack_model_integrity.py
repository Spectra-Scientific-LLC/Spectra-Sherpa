"""Bind ordinary-model pack provenance to the existing NPZ custody checksum.

This is alteration detection relative to retained custody, not a signature or
proof that an independently supplied model has authentic production history.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from spectra_sherpa.core.model_artifact import ModelArtifactIntegrityError
from spectra_sherpa.core.pack_requirements import (
    MAX_BINDING_BYTES,
    parse_pack_graph_binding,
    read_pack_preprocessing_binding,
)

PACK_MODEL_BINDING_ARRAY = "__spectra_pack_binding_v1_sha256"
_FIELDS = ("pack_production_binding", "pack_preprocessing_binding", "preprocessing_chain")


def _binding_digest(manifest: dict) -> bytes:
    try:
        production = manifest.get("pack_production_binding")
        if production is not None:
            parse_pack_graph_binding(
                json.dumps(production, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            )
        read_pack_preprocessing_binding(manifest)
        envelope = {
            "schema_version": "spectra-pack-model-custody/1",
            "fields": {name: {"present": name in manifest, "value": manifest.get(name)} for name in _FIELDS},
        }
        payload = json.dumps(
            envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(payload) > 3 * MAX_BINDING_BYTES:
            raise ValueError("Pack model custody exceeds its size limit")
        return hashlib.sha256(payload).digest()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ModelArtifactIntegrityError("Model pack provenance is malformed") from exc


def require_pack_model_integrity(manifest: dict, arrays: dict) -> None:
    """Validate metadata even when a caller opts out of file checksum checking."""
    declared = any(name in manifest for name in _FIELDS[:2])
    from spectra_sherpa.core.model_artifact import CANONICAL_MODEL_ARTIFACT_AUTHORITY

    if (declared or PACK_MODEL_BINDING_ARRAY in arrays) and manifest.get(
        "artifact_authority"
    ) == CANONICAL_MODEL_ARTIFACT_AUTHORITY:
        raise ModelArtifactIntegrityError("Canonical pack model custody requires an explicitly qualified profile")
    if PACK_MODEL_BINDING_ARRAY not in arrays:
        if declared:
            raise ModelArtifactIntegrityError("Model pack provenance has no retained custody binding")
        return
    marker = arrays[PACK_MODEL_BINDING_ARRAY]
    if type(marker) is not np.ndarray or marker.dtype != np.dtype("uint8") or marker.shape != (32,):
        raise ModelArtifactIntegrityError("Model pack custody marker is malformed")
    if marker.tobytes() != _binding_digest(manifest):
        raise ModelArtifactIntegrityError("Model pack provenance differs from retained custody")


def bind_pack_model_integrity(manifest: dict, arrays: dict) -> dict:
    """Add the marker before publication; never replace an existing assertion."""
    if PACK_MODEL_BINDING_ARRAY in arrays:
        require_pack_model_integrity(manifest, arrays)
        return arrays
    if not any(name in manifest for name in _FIELDS[:2]):
        return arrays
    from spectra_sherpa.core.model_artifact import CANONICAL_MODEL_ARTIFACT_AUTHORITY

    if manifest.get("artifact_authority") == CANONICAL_MODEL_ARTIFACT_AUTHORITY:
        raise ModelArtifactIntegrityError("Canonical pack model custody requires an explicitly qualified profile")
    return {**arrays, PACK_MODEL_BINDING_ARRAY: np.frombuffer(_binding_digest(manifest), dtype=np.uint8).copy()}


def scientific_model_arrays(manifest: dict, arrays: dict) -> dict:
    """Validate custody, then project fitted arrays without changing their schema."""
    require_pack_model_integrity(manifest, arrays)
    if PACK_MODEL_BINDING_ARRAY not in arrays:
        return arrays
    return {name: value for name, value in arrays.items() if name != PACK_MODEL_BINDING_ARRAY}
