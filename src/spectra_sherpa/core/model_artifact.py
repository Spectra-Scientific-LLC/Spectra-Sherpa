"""Import-light, integrity-checking model-artifact read authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


class ModelArtifactIntegrityError(RuntimeError):
    """A model manifest or array payload does not match its stored identity."""


class ModelManifestJSONError(ValueError):
    """A received model manifest is ambiguous or not a JSON object."""


def parse_model_manifest_json(payload: str | bytes) -> dict[str, Any]:
    """Parse a model manifest while rejecting duplicate keys recursively."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ModelManifestJSONError(f"model manifest repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ModelManifestJSONError("model manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ModelManifestJSONError("model manifest must be a JSON object")
    return value


ORDINARY_MODEL_ARTIFACT_AUTHORITY = "workbench_native_or_imported_model"
CANONICAL_MODEL_ARTIFACT_AUTHORITY = "imported_canonical_full_refit_application_artifact"
_MODEL_ARTIFACT_AUTHORITIES = frozenset({ORDINARY_MODEL_ARTIFACT_AUTHORITY, CANONICAL_MODEL_ARTIFACT_AUTHORITY})
_CANONICAL_MARKER_FIELDS = frozenset(
    {"artifact_origin", "canonical_training_lineage", "classification_output_semantics"}
)
_EXPERIMENT_DATASET_READ_OPERATION = "spectrasherpa.experiment_dataset_read/2"


def require_model_artifact_authority(manifest: dict[str, Any]) -> str:
    """Return the closed persisted-artifact authority without inference."""

    authority = manifest.get("artifact_authority")
    if authority not in _MODEL_ARTIFACT_AUTHORITIES:
        raise ModelArtifactIntegrityError("model artifact has no supported persisted authority")
    canonical_markers = _CANONICAL_MARKER_FIELDS & set(manifest)
    if authority == ORDINARY_MODEL_ARTIFACT_AUTHORITY and canonical_markers:
        raise ModelArtifactIntegrityError("ordinary model artifact contains canonical-only authority fields")
    if authority == CANONICAL_MODEL_ARTIFACT_AUTHORITY and canonical_markers != _CANONICAL_MARKER_FIELDS:
        raise ModelArtifactIntegrityError("canonical model artifact authority fields are incomplete")
    return authority


def assign_model_artifact_authority(manifest: dict[str, Any]) -> str:
    """Assign the ordinary authority only at the sole persistence boundary."""

    if "artifact_authority" not in manifest:
        canonical_markers = _CANONICAL_MARKER_FIELDS & set(manifest)
        if canonical_markers:
            raise ModelArtifactIntegrityError(
                "canonical model manifests must declare their persisted artifact authority explicitly"
            )
        manifest["artifact_authority"] = ORDINARY_MODEL_ARTIFACT_AUTHORITY
    return require_model_artifact_authority(manifest)


def experiment_training_dataset_id(manifest: dict[str, Any]) -> int | None:
    """Return the strict workspace-local training source link, when declared."""

    chain = manifest.get("preprocessing_chain")
    if not isinstance(chain, list) or not chain:
        return None
    source = chain[0]
    if not isinstance(source, dict) or source.get("op_id") not in {
        _EXPERIMENT_DATASET_READ_OPERATION,
        "data.file_load",
    }:
        return None
    parameters = source.get("parameters")
    key = "experiment_id" if source["op_id"] == "data.file_load" else "dataset_id"
    dataset_id = parameters.get(key) if isinstance(parameters, dict) else None
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int) or dataset_id < 1:
        raise ModelArtifactIntegrityError("model artifact experiment training source link is invalid")
    return dataset_id


def require_experiment_training_dataset_id(manifest: dict[str, Any], expected_dataset_id: int) -> int | None:
    """Cross-bind an experiment-read preprocessing source to durable storage."""

    observed = experiment_training_dataset_id(manifest)
    if observed is not None and observed != expected_dataset_id:
        raise ModelArtifactIntegrityError("model artifact experiment training source link is stale")
    return observed


def require_artifact_identity(manifest: dict[str, Any], *, expected_uid: str | None = None) -> str:
    """Return the manifest authority, rejecting absent or contradictory identity."""

    artifact_uid = manifest.get("artifact_uid")
    if not isinstance(artifact_uid, str) or not artifact_uid or artifact_uid != artifact_uid.strip():
        raise ModelArtifactIntegrityError("model artifact manifest has no valid artifact_uid")
    if expected_uid is not None and artifact_uid != expected_uid:
        raise ModelArtifactIntegrityError(
            "model artifact identity mismatch " f"(requested {expected_uid!r}, manifest declares {artifact_uid!r})"
        )
    return artifact_uid


class ReadOnlyModelArtifactReader:
    """Root-confined read capability suitable for a spawned worker."""

    def __init__(self, base_dir: Path, *, allowed_artifact_uids: tuple[str, ...] | None = None) -> None:
        self.models_dir = (Path(base_dir) / "models").resolve()
        self.allowed_artifact_uids = None if allowed_artifact_uids is None else frozenset(allowed_artifact_uids)

    def _artifact_dir(self, artifact_uid: str) -> Path:
        if self.allowed_artifact_uids is not None and artifact_uid not in self.allowed_artifact_uids:
            raise FileNotFoundError("Model artifact is not admitted for this execution")
        if not isinstance(artifact_uid, str) or not artifact_uid or "/" in artifact_uid or "\\" in artifact_uid:
            raise ValueError("Invalid model artifact identifier")
        resolved = (self.models_dir / artifact_uid).resolve()
        if not resolved.is_relative_to(self.models_dir):
            raise ValueError("Invalid model artifact identifier")
        return resolved

    def load(self, artifact_uid: str, *, verify: bool = True) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        artifact_dir = self._artifact_dir(artifact_uid)
        manifest_path = artifact_dir / "manifest.json"
        arrays_path = artifact_dir / "arrays.npz"
        if not manifest_path.is_file() or not arrays_path.is_file():
            raise FileNotFoundError(f"Model artifact not found: {artifact_uid}")
        try:
            manifest = parse_model_manifest_json(manifest_path.read_bytes())
        except ModelManifestJSONError as exc:
            raise ModelArtifactIntegrityError(
                f"Model artifact {artifact_uid}: manifest JSON is ambiguous or malformed"
            ) from exc
        require_model_artifact_authority(manifest)
        if verify:
            expected = manifest.get("integrity_hash", "")
            actual = sha256_file(arrays_path)
            if not expected or actual != expected:
                raise ModelArtifactIntegrityError(f"Model artifact {artifact_uid}: arrays.npz hash mismatch")
        require_artifact_identity(manifest, expected_uid=artifact_uid)
        with np.load(str(arrays_path), allow_pickle=False) as archive:
            arrays = {name: np.array(values, copy=True) for name, values in archive.items()}
        return manifest, arrays


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of one file."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_verified_artifact_directory(artifact_dir: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Load an exported artifact directory only after verifying its bytes."""

    directory = Path(artifact_dir)
    manifest_path = directory / "manifest.json"
    arrays_path = directory / "arrays.npz"
    if not manifest_path.is_file() or not arrays_path.is_file():
        raise FileNotFoundError("model artifact directory must contain manifest.json and arrays.npz")
    try:
        manifest = parse_model_manifest_json(manifest_path.read_bytes())
    except ModelManifestJSONError as exc:
        raise ModelArtifactIntegrityError("model artifact manifest JSON is ambiguous or malformed") from exc
    require_model_artifact_authority(manifest)
    require_artifact_identity(manifest)
    expected = manifest.get("integrity_hash")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ModelArtifactIntegrityError("model artifact manifest has no valid integrity_hash")
    actual = sha256_file(arrays_path)
    if actual != expected:
        raise ModelArtifactIntegrityError(
            "model artifact arrays.npz hash mismatch "
            f"(expected {expected[:12]}…, got {actual[:12]}…) — artifact is corrupt"
        )
    with np.load(str(arrays_path), allow_pickle=False) as archive:
        arrays = {name: np.array(values, copy=True) for name, values in archive.items()}
    return manifest, arrays


__all__ = [
    "assign_model_artifact_authority",
    "CANONICAL_MODEL_ARTIFACT_AUTHORITY",
    "experiment_training_dataset_id",
    "ModelArtifactIntegrityError",
    "ModelManifestJSONError",
    "ORDINARY_MODEL_ARTIFACT_AUTHORITY",
    "ReadOnlyModelArtifactReader",
    "load_verified_artifact_directory",
    "parse_model_manifest_json",
    "require_artifact_identity",
    "require_experiment_training_dataset_id",
    "require_model_artifact_authority",
    "sha256_file",
]
