"""Governed public reference datasets used by qualification and examples.

The registry is the one authority for dataset identity, custody, loader
settings, supervised target, frozen split, and public-claim boundary.  It does
not download remote data: the existing reference loaders retain that job.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SpectralAxis
from spectra_sherpa.sdk.dataset_identity import public_dataset_digest

REFERENCE_DATASET_REGISTRY_SCHEMA = "spectra-sherpa-reference-dataset-registry/3"
REFERENCE_DATASET_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "reference_datasets_v3.json"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "datasets"})
_DATASET_FIELDS = frozenset(
    {
        "dataset_id",
        "title",
        "visibility",
        "spectral_domain",
        "source",
        "attribution",
        "loader",
        "shape",
        "target",
        "feature_axis",
        "supervised_eligible",
        "content_digests",
        "split",
        "allowed_uses",
        "prohibited_uses",
    }
)
_PACKAGED_SOURCE_FIELDS = frozenset(
    {
        "kind",
        "reference_name",
        "local_path",
        "url",
        "archive_sha256",
        "source_file_sha256",
        "redistribution",
    }
)
_REGISTERED_SOURCE_FIELDS = frozenset({"kind", "reference_name", "local_path", "artifact_projection_id"})
_ATTRIBUTION_FIELDS = frozenset({"license_id", "license_url", "citation", "homepage"})
_LOADER_FIELDS = frozenset({"kind", "reference_name", "target_index"})
_SHAPE_FIELDS = frozenset({"n_samples", "n_features"})
_TARGET_FIELDS = frozenset({"name", "units", "kind"})
_FEATURE_AXIS_FIELDS = frozenset({"kind", "title", "units", "values_digest", "digest_encoding"})
_CONTENT_DIGEST_FIELDS = frozenset({"complete", "development", "confirmation"})
_SPLIT_FIELDS = frozenset(
    {
        "method",
        "generator",
        "seed",
        "index_digest_encoding",
        "development_index_digest",
        "confirmation_index_digest",
        "development_indices",
        "confirmation_indices",
    }
)
_SOURCE_KINDS = frozenset({"packaged_synthetic_reference", "remote_eigenvector_archive"})
_LOADER_KINDS = frozenset({"synthetic_reference", "eigenvector"})
_SPLIT_METHODS = frozenset({"frozen_sequential_holdout", "frozen_random_permutation"})


class ReferenceDatasetRegistryError(ValueError):
    """Raised when a governed reference-dataset contract is invalid."""


@dataclass(frozen=True)
class ReferenceDatasetEntry:
    """One validated, detached registry entry."""

    _payload: dict[str, Any]

    @property
    def payload(self) -> dict[str, Any]:
        """Return a detached copy so callers cannot mutate registry authority."""
        return deepcopy(self._payload)

    @property
    def dataset_id(self) -> str:
        return str(self._payload["dataset_id"])

    @property
    def development_indices(self) -> np.ndarray:
        return np.asarray(self._payload["split"]["development_indices"], dtype="<i8")

    @property
    def confirmation_indices(self) -> np.ndarray:
        return np.asarray(self._payload["split"]["confirmation_indices"], dtype="<i8")

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


@dataclass(frozen=True)
class MaterializedReferenceDataset:
    """The exact supervised arrays and source bytes named by one entry."""

    entry: ReferenceDatasetEntry
    X: np.ndarray
    y: np.ndarray
    feature_axis: SpectralAxis
    source_path: Path | None

    @property
    def development(self) -> tuple[np.ndarray, np.ndarray]:
        indices = self.entry.development_indices
        return self.X[indices], self.y[indices]

    @property
    def confirmation(self) -> tuple[np.ndarray, np.ndarray]:
        indices = self.entry.confirmation_indices
        return self.X[indices], self.y[indices]


def load_reference_dataset_registry(
    path: Path = REFERENCE_DATASET_REGISTRY_PATH,
) -> tuple[ReferenceDatasetEntry, ...]:
    """Load and strictly validate the current governed registry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceDatasetRegistryError(f"cannot load reference-dataset registry: {exc}") from exc
    _require_fields(payload, _TOP_LEVEL_FIELDS, "registry")
    if payload["schema_version"] != REFERENCE_DATASET_REGISTRY_SCHEMA:
        raise ReferenceDatasetRegistryError("reference-dataset registry schema is unsupported")
    datasets = payload["datasets"]
    if not isinstance(datasets, list) or not datasets:
        raise ReferenceDatasetRegistryError("registry datasets must be a non-empty array")
    entries = tuple(ReferenceDatasetEntry(_validate_entry(item)) for item in datasets)
    identities = [entry.dataset_id for entry in entries]
    if len(identities) != len(set(identities)):
        raise ReferenceDatasetRegistryError("reference-dataset identities must be unique")
    if identities != sorted(identities):
        raise ReferenceDatasetRegistryError("reference-dataset entries must be sorted by dataset_id")
    return entries


def reference_dataset_registry_digest(
    path: Path = REFERENCE_DATASET_REGISTRY_PATH,
) -> str:
    """Return the canonical semantic digest of the validated registry."""
    entries = load_reference_dataset_registry(path)
    payload = {
        "schema_version": REFERENCE_DATASET_REGISTRY_SCHEMA,
        "datasets": [entry.as_dict() for entry in entries],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def get_reference_dataset(
    dataset_id: str,
    *,
    path: Path = REFERENCE_DATASET_REGISTRY_PATH,
) -> ReferenceDatasetEntry:
    """Resolve one exact dataset identity; aliases and partial matches fail."""
    for entry in load_reference_dataset_registry(path):
        if entry.dataset_id == dataset_id:
            return entry
    raise ReferenceDatasetRegistryError(f"unknown governed reference dataset: {dataset_id!r}")


def materialize_reference_dataset(
    entry: ReferenceDatasetEntry,
    *,
    eigenvector_data_dir: Path | None = None,
) -> MaterializedReferenceDataset:
    """Load and verify the supervised arrays named by one registry entry."""
    verified = ReferenceDatasetEntry(_validate_entry(entry.as_dict()))
    payload = verified.as_dict()
    loader = payload["loader"]
    source = payload["source"]
    target_index = int(loader["target_index"])
    source_path: Path | None
    if loader["kind"] == "synthetic_reference":
        from spectra_sherpa.app.lib.synthetic_references import (
            load_synthetic_reference_as_sherpa,
            synthetic_reference_path,
        )

        dataset = load_synthetic_reference_as_sherpa(loader["reference_name"])
        X = np.asarray(dataset.X, dtype=float)
        targets = np.asarray(dataset.target, dtype=float)
        feature_axis = dataset.get_feature_axis()
        if not isinstance(feature_axis, SpectralAxis):
            raise ReferenceDatasetRegistryError("synthetic reference is missing its spectral feature axis")
        feature_axis = feature_axis.copy()
        target_names = list(dataset.target_context.target_names or []) if dataset.target_context else []
        source_path = synthetic_reference_path(loader["reference_name"])
    elif loader["kind"] == "eigenvector":
        from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset

        dataset = load_eigenvector_dataset(loader["reference_name"], data_dir=eigenvector_data_dir)
        X = np.asarray(dataset["spectra"], dtype=float)
        targets = np.asarray(dataset["properties"], dtype=float)
        wavelengths = np.asarray(dataset["wavelengths"], dtype=float)
        feature_axis = SpectralAxis(
            values=wavelengths,
            title=payload["feature_axis"]["title"],
            units=payload["feature_axis"]["units"],
        )
        target_names = [str(value) for value in dataset.get("prop_names") or []]
        source_path = eigenvector_data_dir / source["local_path"] if eigenvector_data_dir is not None else None
    else:  # pragma: no cover - closed validation makes this unreachable
        raise ReferenceDatasetRegistryError("unsupported reference-dataset loader")

    if targets.ndim == 1:
        targets = targets.reshape(-1, 1)
    if target_index >= targets.shape[1]:
        raise ReferenceDatasetRegistryError("reference target index is outside loaded target columns")
    if not target_names or target_names[target_index] != entry.payload["target"]["name"]:
        raise ReferenceDatasetRegistryError("loaded target identity does not match the registry")
    materialized = MaterializedReferenceDataset(
        entry=verified,
        X=np.asarray(X, dtype=float),
        y=np.asarray(targets[:, target_index], dtype=float),
        feature_axis=feature_axis,
        source_path=source_path,
    )
    _verify_materialized(materialized)
    return materialized


def _validate_entry(value: Any) -> dict[str, Any]:
    _require_fields(value, _DATASET_FIELDS, "dataset")
    entry = deepcopy(value)
    _require_text(entry["dataset_id"], "dataset_id")
    _require_text(entry["title"], "title")
    if entry["visibility"] != "public_reproducibility_only":
        raise ReferenceDatasetRegistryError("reference datasets must retain the public-reproducibility boundary")
    if entry["spectral_domain"] not in {"ftir", "nir", "raman", "uv_vis"}:
        raise ReferenceDatasetRegistryError("reference dataset spectral_domain is unsupported")
    _require_fields(entry["attribution"], _ATTRIBUTION_FIELDS, "attribution")
    _require_fields(entry["loader"], _LOADER_FIELDS, "loader")
    _require_fields(entry["shape"], _SHAPE_FIELDS, "shape")
    _require_fields(entry["target"], _TARGET_FIELDS, "target")
    _require_fields(entry["feature_axis"], _FEATURE_AXIS_FIELDS, "feature_axis")
    _require_fields(entry["content_digests"], _CONTENT_DIGEST_FIELDS, "content_digests")
    _require_fields(entry["split"], _SPLIT_FIELDS, "split")

    source = entry["source"]
    loader = entry["loader"]
    if not isinstance(source, Mapping) or "kind" not in source:
        raise ReferenceDatasetRegistryError("reference-dataset source must name its kind")
    if source["kind"] not in _SOURCE_KINDS or loader["kind"] not in _LOADER_KINDS:
        raise ReferenceDatasetRegistryError("reference-dataset source or loader kind is unsupported")
    expected_source_fields = (
        _REGISTERED_SOURCE_FIELDS if source["kind"] == "remote_eigenvector_archive" else _PACKAGED_SOURCE_FIELDS
    )
    _require_fields(source, expected_source_fields, "source")
    if source["reference_name"] != loader["reference_name"]:
        raise ReferenceDatasetRegistryError("source and loader reference identities differ")
    if source["kind"] == "packaged_synthetic_reference" and loader["kind"] != "synthetic_reference":
        raise ReferenceDatasetRegistryError("packaged synthetic sources require the synthetic loader")
    if source["kind"] == "remote_eigenvector_archive" and loader["kind"] != "eigenvector":
        raise ReferenceDatasetRegistryError("Eigenvector sources require the Eigenvector loader")
    for field in ("reference_name", "local_path"):
        _require_text(source[field], f"source.{field}")
    if source["kind"] == "remote_eigenvector_archive":
        _require_text(source["artifact_projection_id"], "source.artifact_projection_id")
    else:
        for field in ("url", "redistribution"):
            _require_text(source[field], f"source.{field}")
        _require_digest(source["source_file_sha256"], "source.source_file_sha256")
        if source["archive_sha256"] is not None:
            raise ReferenceDatasetRegistryError("packaged sources must not declare an archive digest")
    for field in _ATTRIBUTION_FIELDS:
        _require_text(entry["attribution"][field], f"attribution.{field}")

    shape = entry["shape"]
    if type(shape["n_samples"]) is not int or shape["n_samples"] < 2:
        raise ReferenceDatasetRegistryError("shape.n_samples must be an integer greater than one")
    if type(shape["n_features"]) is not int or shape["n_features"] < 1:
        raise ReferenceDatasetRegistryError("shape.n_features must be a positive integer")
    if type(loader["target_index"]) is not int or loader["target_index"] < 0:
        raise ReferenceDatasetRegistryError("loader.target_index must be a non-negative integer")
    if entry["supervised_eligible"] is not True or entry["target"]["kind"] != "continuous":
        raise ReferenceDatasetRegistryError("current qualification entries must be supervised continuous targets")
    _require_text(entry["target"]["name"], "target.name")
    if entry["target"]["units"] is not None:
        _require_text(entry["target"]["units"], "target.units")
    feature_axis = entry["feature_axis"]
    if feature_axis["kind"] != "spectral":
        raise ReferenceDatasetRegistryError("feature_axis.kind must be spectral")
    _require_text(feature_axis["title"], "feature_axis.title")
    _require_text(feature_axis["units"], "feature_axis.units")
    if feature_axis["digest_encoding"] != "little-endian-float64":
        raise ReferenceDatasetRegistryError("feature_axis.digest_encoding is unsupported")
    _require_digest(feature_axis["values_digest"], "feature_axis.values_digest")
    if source["kind"] == "remote_eigenvector_archive":
        _validate_registered_projection_binding(entry)
    for field in _CONTENT_DIGEST_FIELDS:
        _require_digest(entry["content_digests"][field], f"content_digests.{field}")

    _validate_split(entry)
    for field in ("allowed_uses", "prohibited_uses"):
        values = entry[field]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item.strip() for item in values)
        ):
            raise ReferenceDatasetRegistryError(f"{field} must be a non-empty text array")
        if len(values) != len(set(values)):
            raise ReferenceDatasetRegistryError(f"{field} must not contain duplicates")
    return entry


def _validate_registered_projection_binding(entry: Mapping[str, Any]) -> None:
    from spectra_sherpa.app.lib.reference_artifacts import (
        load_reference_artifact_registry,
        registered_projection_acquisition,
    )

    source = entry["source"]
    registry = load_reference_artifact_registry()
    projection = registry.projection(source["artifact_projection_id"]).as_dict()
    acquisition = registered_projection_acquisition(source["artifact_projection_id"], registry=registry)
    if Path(source["local_path"]).name != Path(acquisition["member_path"]).name:
        raise ReferenceDatasetRegistryError("registered source path disagrees with its artifact member")
    if (
        projection["scientific_sha256"] != entry["content_digests"]["complete"]
        or projection["n_samples"] != entry["shape"]["n_samples"]
        or projection["n_features"] != entry["shape"]["n_features"]
    ):
        raise ReferenceDatasetRegistryError("registered projection scientific identity disagrees with qualification")
    if (
        projection["target_index"] != entry["loader"]["target_index"]
        or projection["target_name"] != entry["target"]["name"]
        or projection["target_units"] != entry["target"]["units"]
    ):
        raise ReferenceDatasetRegistryError("registered projection target disagrees with qualification")
    feature_axis = entry["feature_axis"]
    if (
        projection["feature_axis_title"] != feature_axis["title"]
        or projection["feature_axis_units"] != feature_axis["units"]
        or projection["feature_axis_sha256"] != feature_axis["values_digest"]
    ):
        raise ReferenceDatasetRegistryError("registered projection feature axis disagrees with qualification")


def _validate_split(entry: Mapping[str, Any]) -> None:
    split = entry["split"]
    if split["method"] not in _SPLIT_METHODS or split["index_digest_encoding"] != "little-endian-int64":
        raise ReferenceDatasetRegistryError("frozen split policy is unsupported")
    development = _index_array(split["development_indices"], "development_indices")
    confirmation = _index_array(split["confirmation_indices"], "confirmation_indices")
    n_samples = int(entry["shape"]["n_samples"])
    if np.any(development >= n_samples) or np.any(confirmation >= n_samples):
        raise ReferenceDatasetRegistryError("frozen split contains an out-of-range index")
    if set(development.tolist()) & set(confirmation.tolist()):
        raise ReferenceDatasetRegistryError("development and confirmation splits overlap")
    if set(development.tolist()) | set(confirmation.tolist()) != set(range(n_samples)):
        raise ReferenceDatasetRegistryError("frozen split does not partition every sample")
    for name, values in (("development", development), ("confirmation", confirmation)):
        _require_digest(split[f"{name}_index_digest"], f"split.{name}_index_digest")
        actual = hashlib.sha256(values.tobytes()).hexdigest()
        if actual != split[f"{name}_index_digest"]:
            raise ReferenceDatasetRegistryError(f"split.{name}_index_digest does not match frozen indices")
    if split["method"] == "frozen_random_permutation":
        if split["generator"] != "numpy.random.Generator(PCG64)" or type(split["seed"]) is not int:
            raise ReferenceDatasetRegistryError("random frozen split must name its generator and integer seed")
        order = np.random.default_rng(split["seed"]).permutation(n_samples)
        if development.tolist() != np.sort(order[: development.size]).tolist():
            raise ReferenceDatasetRegistryError("development indices do not reproduce the frozen random policy")
        if confirmation.tolist() != np.sort(order[development.size :]).tolist():
            raise ReferenceDatasetRegistryError("confirmation indices do not reproduce the frozen random policy")
    elif split["generator"] is not None or split["seed"] is not None:
        raise ReferenceDatasetRegistryError("sequential frozen split must not declare RNG settings")


def _verify_materialized(materialized: MaterializedReferenceDataset) -> None:
    entry = materialized.entry.payload
    expected_shape = (entry["shape"]["n_samples"], entry["shape"]["n_features"])
    if materialized.X.shape != expected_shape or materialized.y.shape != (expected_shape[0],):
        raise ReferenceDatasetRegistryError("loaded dataset shape does not match the registry")
    if not np.all(np.isfinite(materialized.X)) or not np.all(np.isfinite(materialized.y)):
        raise ReferenceDatasetRegistryError("loaded dataset contains non-finite supervised values")
    axis_values = materialized.feature_axis.values
    if axis_values is None or np.asarray(axis_values).shape != (expected_shape[1],):
        raise ReferenceDatasetRegistryError("loaded spectral axis does not align to the feature dimension")
    if not np.all(np.isfinite(np.asarray(axis_values, dtype=float))):
        raise ReferenceDatasetRegistryError("loaded spectral axis contains non-finite values")
    axis_contract = entry["feature_axis"]
    if (
        materialized.feature_axis.title != axis_contract["title"]
        or materialized.feature_axis.units != axis_contract["units"]
        or feature_axis_values_digest(axis_values) != axis_contract["values_digest"]
    ):
        raise ReferenceDatasetRegistryError("loaded spectral axis does not match the governed registry")
    source_path = materialized.source_path
    if source_path is not None:
        if not source_path.is_file():
            raise ReferenceDatasetRegistryError(f"registered source file is unavailable: {source_path}")
        actual_source = hashlib.sha256(source_path.read_bytes()).hexdigest()
        source = entry["source"]
        if source["kind"] == "remote_eigenvector_archive":
            from spectra_sherpa.app.lib.reference_artifacts import registered_projection_acquisition

            expected_source_sha256 = registered_projection_acquisition(source["artifact_projection_id"])[
                "member_sha256"
            ]
        else:
            expected_source_sha256 = source["source_file_sha256"]
        if actual_source != expected_source_sha256:
            raise ReferenceDatasetRegistryError("registered source-file digest does not match loaded bytes")
    development_X, development_y = materialized.development
    confirmation_X, confirmation_y = materialized.confirmation
    actual = {
        "complete": public_dataset_digest(materialized.X, materialized.y),
        "development": public_dataset_digest(development_X, development_y),
        "confirmation": public_dataset_digest(confirmation_X, confirmation_y),
    }
    if actual != entry["content_digests"]:
        raise ReferenceDatasetRegistryError("loaded dataset content does not match the governed registry")


def _require_fields(value: Any, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        actual = set(value) if isinstance(value, Mapping) else set()
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ReferenceDatasetRegistryError(f"{label} fields are not closed (missing={missing}, extra={extra})")


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReferenceDatasetRegistryError(f"{label} must be non-empty text")


def _require_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ReferenceDatasetRegistryError(f"{label} must be a lowercase SHA-256 digest")


def _index_array(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, list) or not value or not all(type(item) is int and item >= 0 for item in value):
        raise ReferenceDatasetRegistryError(f"split.{label} must be a non-empty non-negative integer array")
    if value != sorted(value) or len(value) != len(set(value)):
        raise ReferenceDatasetRegistryError(f"split.{label} must be sorted and unique")
    return np.asarray(value, dtype="<i8")


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def feature_axis_values_digest(values: Any) -> str:
    """Digest one numeric spectral grid using the registry's fixed encoding."""

    array = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    if array.ndim != 1 or not array.size or not np.all(np.isfinite(array)):
        raise ReferenceDatasetRegistryError("spectral axis must be a finite non-empty numeric vector")
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


__all__ = [
    "MaterializedReferenceDataset",
    "REFERENCE_DATASET_REGISTRY_PATH",
    "REFERENCE_DATASET_REGISTRY_SCHEMA",
    "ReferenceDatasetEntry",
    "ReferenceDatasetRegistryError",
    "get_reference_dataset",
    "feature_axis_values_digest",
    "load_reference_dataset_registry",
    "materialize_reference_dataset",
    "reference_dataset_registry_digest",
]
