"""Exact upstream artifact authority for user-acquired reference datasets.

The registry identifies bytes that Spectra Sherpa may admit after a user
obtains them directly from the named provider.  It is not a downloader,
license grant, redistribution authority, or filename registry.  Artifact
identity is the exact byte size plus SHA-256; scientific projections are a
separate authority bound to an exact registered member and native reader.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from spectra_sherpa.app.lib.dataset_compatibility import normalize_analysis_profile

REFERENCE_ARTIFACT_REGISTRY_SCHEMA = "spectra-sherpa-reference-artifact-registry/2"
REFERENCE_ARTIFACT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "reference_artifacts_v2.json"
BUILTIN_DATASET_PROFILES_PATH = Path(__file__).resolve().parents[2] / "data" / "builtin_dataset_profiles_v1.json"
BUILTIN_DATASET_PROFILES_SCHEMA = "spectra-sherpa-builtin-dataset-profiles/1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROVIDER_HOSTS = frozenset({"eigenvector.com", "www.eigenvector.com"})
_TOP_FIELDS = frozenset({"schema_version", "artifacts", "projections"})
_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "title",
        "description",
        "provider",
        "provider_page",
        "download_url",
        "expected_size_bytes",
        "sha256",
        "media_type",
        "redistribution",
        "attribution",
        "no_endorsement",
        "qualification_status",
        "reviewed_at",
        "members",
    }
)
_MEMBER_FIELDS = frozenset({"path", "expected_size_bytes", "sha256"})
_PROJECTION_FIELDS = frozenset(
    {
        "projection_id",
        "artifact_id",
        "title",
        "member_path",
        "native_reader_contract",
        "object_name",
        "target_object_name",
        "target_index",
        "target_name",
        "target_units",
        "n_samples",
        "n_features",
        "feature_axis_title",
        "feature_axis_units",
        "feature_axis_sha256",
        "scientific_sha256",
        "qualification_status",
        "analysis",
    }
)
_TARGET_TYPES = frozenset({"continuous", "categorical", "ordinal"})
_NATIVE_READER_CONTRACTS = frozenset(
    {
        "spectrasherpa.matlab-dso/1",
        "spectrasherpa.matlab-source/1",
        "spectrasherpa.matlab-array-pair/1",
        "spectrasherpa.matlab-process-log/1",
    }
)

_REFERENCE_PROJECTION_SUMMARIES = {
    "public-corn-m5-moisture-v1": (
        "M5 instrument view of 80 matched corn samples: 700 NIR wavelength variables (nm); "
        "shared Moisture, Oil, Protein, and Starch properties."
    ),
    "public-corn-mp5-moisture-v1": (
        "MP5 instrument view of the same 80 corn samples: 700 NIR wavelength variables (nm); "
        "shared Moisture, Oil, Protein, and Starch properties."
    ),
    "public-corn-mp6-moisture-v1": (
        "MP6 instrument view of the same 80 corn samples: 700 NIR wavelength variables (nm); "
        "shared Moisture, Oil, Protein, and Starch properties."
    ),
    "public-metal-etch-machine-v1": (
        "Machine-sensor view of LAM 9600 etch wafers: 129 observations × 21 process variables; " "no embedded target."
    ),
    "public-metal-etch-oes-v1": (
        "Optical-emission view of LAM 9600 etch wafers: 126 observations × 129 wavelengths (nm); " "no embedded target."
    ),
    "public-metal-etch-rfm-v1": (
        "RF-monitor view of LAM 9600 etch wafers: 126 observations × 71 process variables; " "no embedded target."
    ),
}


class ReferenceArtifactRegistryError(ValueError):
    """The governed reference-artifact authority is malformed or unresolved."""


@dataclass(frozen=True)
class ReferenceArtifact:
    _payload: dict[str, Any]

    @property
    def artifact_id(self) -> str:
        return str(self._payload["artifact_id"])

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


@dataclass(frozen=True)
class ReferenceProjection:
    _payload: dict[str, Any]

    @property
    def projection_id(self) -> str:
        return str(self._payload["projection_id"])

    @property
    def artifact_id(self) -> str:
        return str(self._payload["artifact_id"])

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


@dataclass(frozen=True)
class ReferenceArtifactRegistry:
    artifacts: tuple[ReferenceArtifact, ...]
    projections: tuple[ReferenceProjection, ...]

    def artifact(self, artifact_id: str) -> ReferenceArtifact:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise ReferenceArtifactRegistryError(f"unknown qualified reference artifact: {artifact_id!r}")

    def projection(self, projection_id: str) -> ReferenceProjection:
        for projection in self.projections:
            if projection.projection_id == projection_id:
                return projection
        raise ReferenceArtifactRegistryError(f"unknown qualified reference projection: {projection_id!r}")


def load_reference_artifact_registry(
    path: Path = REFERENCE_ARTIFACT_REGISTRY_PATH,
) -> ReferenceArtifactRegistry:
    """Load the closed registry; unqualified or ambiguous entries fail."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceArtifactRegistryError(f"cannot load reference-artifact registry: {exc}") from exc
    _require_fields(payload, _TOP_FIELDS, "registry")
    if payload["schema_version"] != REFERENCE_ARTIFACT_REGISTRY_SCHEMA:
        raise ReferenceArtifactRegistryError("reference-artifact registry schema is unsupported")
    raw_artifacts = payload["artifacts"]
    raw_projections = payload["projections"]
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ReferenceArtifactRegistryError("registry artifacts must be a non-empty array")
    if not isinstance(raw_projections, list) or not raw_projections:
        raise ReferenceArtifactRegistryError("registry projections must be a non-empty array")
    artifacts = tuple(ReferenceArtifact(_validate_artifact(value)) for value in raw_artifacts)
    projections = tuple(ReferenceProjection(_validate_projection(value)) for value in raw_projections)
    _require_sorted_unique([value.artifact_id for value in artifacts], "artifact")
    _require_sorted_unique([value.projection_id for value in projections], "projection")
    artifact_members = {
        artifact.artifact_id: {member["path"] for member in artifact.as_dict()["members"]} for artifact in artifacts
    }
    for projection in projections:
        if projection.artifact_id not in artifact_members:
            raise ReferenceArtifactRegistryError("reference projection names an unknown artifact")
        if projection.as_dict()["member_path"] not in artifact_members[projection.artifact_id]:
            raise ReferenceArtifactRegistryError("reference projection names an unregistered artifact member")
    return ReferenceArtifactRegistry(artifacts=artifacts, projections=projections)


def reference_artifact_registry_digest(path: Path = REFERENCE_ARTIFACT_REGISTRY_PATH) -> str:
    registry = load_reference_artifact_registry(path)
    payload = {
        "schema_version": REFERENCE_ARTIFACT_REGISTRY_SCHEMA,
        "artifacts": [value.as_dict() for value in registry.artifacts],
        "projections": [value.as_dict() for value in registry.projections],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def registered_artifact_acquisition(
    artifact_id: str,
    member_path: str,
    *,
    registry: ReferenceArtifactRegistry | None = None,
) -> dict[str, Any]:
    """Resolve one exact registered archive member without claiming its semantics."""

    active = registry or load_reference_artifact_registry()
    artifact = active.artifact(artifact_id).as_dict()
    try:
        member = next(value for value in artifact["members"] if value["path"] == member_path)
    except StopIteration as exc:
        raise ReferenceArtifactRegistryError("registered artifact member is unknown") from exc
    return {
        "artifact_id": artifact["artifact_id"],
        "download_url": artifact["download_url"],
        "archive_expected_size_bytes": artifact["expected_size_bytes"],
        "archive_sha256": artifact["sha256"],
        "redistribution": artifact["redistribution"],
        "member_path": member["path"],
        "member_expected_size_bytes": member["expected_size_bytes"],
        "member_sha256": member["sha256"],
    }


def registered_projection_acquisition(
    projection_id: str,
    *,
    registry: ReferenceArtifactRegistry | None = None,
) -> dict[str, Any]:
    """Resolve the exact upstream bytes behind one scientific projection."""

    active = registry or load_reference_artifact_registry()
    projection = active.projection(projection_id).as_dict()
    return registered_artifact_acquisition(
        projection["artifact_id"],
        projection["member_path"],
        registry=active,
    )


def _registered_reference_technical_summary(projection: dict[str, Any]) -> str:
    """Return one compact, model-neutral sentence that distinguishes a projection."""

    projection_id = str(projection["projection_id"])
    if projection_id in _REFERENCE_PROJECTION_SUMMARIES:
        return _REFERENCE_PROJECTION_SUMMARIES[projection_id]
    analysis = projection["analysis"]
    axis_kind = str(projection["feature_axis_title"]).strip().lower() or "feature"
    feature_phrase = "variables" if axis_kind in {"variable", "variables"} else f"{axis_kind} variables"
    modality = {
        "spectra": "spectra",
        "features": "features",
        "hsi": "hyperspectral-image data",
    }.get(str(analysis["modality"]), "data")
    target_fields = [str(value) for value in analysis["target_fields"]]
    if target_fields:
        target_summary = f'{analysis["target_type"]} target “{", ".join(target_fields)}”'
    else:
        target_summary = "no declared target"
    return (
        f'{projection["title"]} contains {int(projection["n_samples"]):,} observations × '
        f'{int(projection["n_features"]):,} {feature_phrase} as '
        f'{analysis["technique"]} {modality}, with {target_summary}.'
    )


def registered_reference_catalog(
    registry: ReferenceArtifactRegistry | None = None,
) -> list[dict[str, Any]]:
    """Project registered authorities into path-free, model-neutral cards."""

    active = registry or load_reference_artifact_registry()
    package_view = None
    package_registry = None
    if registry is None:
        # Avoid a circular import: package relationships depend on this
        # artifact registry, while this public projection only enriches the
        # catalog when the canonical on-disk authorities are in use.
        from spectra_sherpa.app.lib.reference_dataset_packages import (
            load_reference_dataset_package_registry,
            package_view_projection,
        )

        package_view = package_view_projection
        package_registry = load_reference_dataset_package_registry(artifact_registry=active)
    artifacts = {artifact.artifact_id: artifact.as_dict() for artifact in active.artifacts}
    options: list[dict[str, Any]] = []
    for registered_projection in active.projections:
        projection = registered_projection.as_dict()
        artifact = artifacts[registered_projection.artifact_id]
        analysis = projection["analysis"]
        technical_summary = _registered_reference_technical_summary(projection)
        option = {
            "name": projection["projection_id"],
            "source": "registered",
            "label": projection["title"],
            "technique": analysis["technique"],
            "is_spectra": analysis["primary_role"] in {"X_spectra", "X_hsi"},
            "data_role": analysis["primary_role"],
            "data_modality": analysis["modality"],
            "description": artifact["description"],
            "technical_summary": technical_summary,
            "provider": artifact["provider"],
            "provider_page": artifact["provider_page"],
            "download_url": artifact["download_url"],
            "attribution": artifact["attribution"],
            "no_endorsement": artifact["no_endorsement"],
            "admission": "exact_user_acquired_file",
            # Catalog presence describes a governed source identity, not bytes
            # mounted in this deployment.  The user must still supply the exact
            # registered archive before any workflow can bind this source.
            "availability": "exact_user_acquisition_required",
            "mounted": False,
            "expected_size_bytes": artifact["expected_size_bytes"],
            "has_embedded_target": analysis["target_type"] is not None,
            "target_type": analysis["target_type"],
            "target_fields": analysis["target_fields"],
            "analysis_profile": analysis,
        }
        if package_view is not None:
            view_projection = package_view(projection["projection_id"], registry=package_registry)
            if view_projection is not None:
                option["dataset_package"] = view_projection
                annotation_table = view_projection["annotation_table"]
                if annotation_table is None:
                    option["analysis_profile"] = {
                        **analysis,
                        "identity_fields": ["sample_id", "instrument"],
                        "group_fields": [],
                    }
                    options.append(option)
                    continue
                fields = annotation_table["fields"]
                field_types = {field["target_type"] for field in fields}
                target_type = next(iter(field_types)) if len(field_types) == 1 else None
                target_fields = [field["name"] for field in fields]
                option.update(
                    {
                        "has_embedded_target": bool(target_fields),
                        "target_type": target_type,
                        "target_fields": target_fields,
                        "analysis_profile": {
                            **analysis,
                            "target_type": target_type,
                            "target_fields": target_fields,
                            "identity_fields": ["sample_id", "specimen_id", "instrument"],
                            # `instrument` names which view a row came from, so it
                            # is both an identity and a legitimate grouping: holding
                            # one instrument out is how a scientist tests whether a
                            # calibration survives a change of instrument.
                            "group_fields": ["specimen_id", "instrument"],
                        },
                    }
                )
        options.append(option)
    return options


def builtin_dataset_catalog(path: Path = BUILTIN_DATASET_PROFILES_PATH) -> list[dict[str, Any]]:
    """Return distributed datasets through the same model-neutral profile contract."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceArtifactRegistryError("built-in dataset profiles are unavailable") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "datasets"}:
        raise ReferenceArtifactRegistryError("built-in dataset profile registry has an invalid schema")
    if payload["schema_version"] != BUILTIN_DATASET_PROFILES_SCHEMA:
        raise ReferenceArtifactRegistryError("built-in dataset profile schema version is unsupported")
    datasets = payload["datasets"]
    if not isinstance(datasets, list) or not datasets:
        raise ReferenceArtifactRegistryError("built-in dataset profiles must be a non-empty array")
    expected_fields = {
        "dataset_id",
        "name",
        "source",
        "label",
        "description",
        "availability",
        "analysis_profile",
    }
    result: list[dict[str, Any]] = []
    for raw in datasets:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ReferenceArtifactRegistryError("built-in dataset profile has an invalid schema")
        item = deepcopy(raw)
        for field in ("dataset_id", "name", "source", "label", "description", "availability"):
            _require_text(item[field], f"built-in dataset.{field}")
        if item["source"] != "builtin" or item["dataset_id"] != f"builtin:{item['name']}":
            raise ReferenceArtifactRegistryError("built-in dataset identity is inconsistent")
        try:
            item["analysis_profile"] = normalize_analysis_profile(item["analysis_profile"])
        except ValueError as exc:
            raise ReferenceArtifactRegistryError(str(exc)) from exc
        profile = item["analysis_profile"]
        item.update(
            {
                "technique": profile["technique"],
                "is_spectra": profile["primary_role"] in {"X_spectra", "X_hsi"},
                "data_role": profile["primary_role"],
                "data_modality": profile["modality"],
                "has_embedded_target": profile["target_type"] is not None,
                "target_type": profile["target_type"],
                "target_fields": profile["target_fields"],
            }
        )
        result.append(item)
    identities = [item["dataset_id"] for item in result]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise ReferenceArtifactRegistryError("built-in dataset profiles must be sorted and unique")
    return result


def model_neutral_dataset_catalog() -> list[dict[str, Any]]:
    """Return all governed dataset profiles without coupling any one to a model."""

    return [
        *builtin_dataset_catalog(),
        *_distributed_synthetic_dataset_catalog(),
        *_distributed_sklearn_dataset_catalog(),
        *registered_reference_catalog(),
    ]


def _distributed_synthetic_dataset_catalog() -> list[dict[str, Any]]:
    """Project bundled synthetic references into the model-neutral catalog."""

    from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

    datasets: list[dict[str, Any]] = []
    for name, raw in SYNTHETIC_REFERENCE_CATALOG.items():
        profile = normalize_analysis_profile(
            {
                "primary_role": "X_spectra",
                "modality": "spectra",
                "technique": raw.get("technique"),
                "target_type": raw.get("target_type"),
                "target_fields": list(raw.get("target_fields") or []),
                "identity_fields": [],
                "group_fields": [],
                "ordered_samples": False,
            }
        )
        datasets.append(
            {
                "dataset_id": f"synthetic:{name}",
                "name": name,
                "source": "synthetic",
                "label": str(raw["label"]),
                "description": str(raw["description"]),
                "availability": "distributed_reference",
                "analysis_profile": profile,
                "technique": profile["technique"],
                "is_spectra": True,
                "data_role": profile["primary_role"],
                "data_modality": profile["modality"],
                "has_embedded_target": profile["target_type"] is not None,
                "target_type": profile["target_type"],
                "target_fields": profile["target_fields"],
            }
        )
    return datasets


def _distributed_sklearn_dataset_catalog() -> list[dict[str, Any]]:
    """Project bundled scikit-learn tables into the model-neutral catalog."""

    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG

    datasets: list[dict[str, Any]] = []
    for name, raw in SKLEARN_CATALOG.items():
        profile = normalize_analysis_profile(
            {
                "primary_role": "X_features",
                "modality": "features",
                "technique": "ML/Statistics",
                "target_type": "categorical" if raw.get("task_type") == "classification" else "continuous",
                "target_fields": ["target"],
                "identity_fields": [],
                "group_fields": [],
                "ordered_samples": False,
            }
        )
        datasets.append(
            {
                "dataset_id": f"sklearn:{name}",
                "name": name,
                "source": "sklearn",
                "label": str(raw["label"]),
                "description": f"Scikit-learn {name} dataset",
                "availability": "distributed_reference",
                "analysis_profile": profile,
                "technique": profile["technique"],
                "is_spectra": False,
                "data_role": profile["primary_role"],
                "data_modality": profile["modality"],
                "has_embedded_target": True,
                "target_type": profile["target_type"],
                "target_fields": profile["target_fields"],
            }
        )
    return datasets


def _validate_artifact(value: Any) -> dict[str, Any]:
    _require_fields(value, _ARTIFACT_FIELDS, "artifact")
    result = deepcopy(value)
    for field in (
        "artifact_id",
        "title",
        "description",
        "provider",
        "provider_page",
        "download_url",
        "media_type",
        "redistribution",
        "attribution",
        "no_endorsement",
    ):
        _require_text(result[field], f"artifact.{field}")
    if result["provider"] != "Eigenvector Research":
        raise ReferenceArtifactRegistryError("reference artifact provider is unsupported")
    for field in ("provider_page", "download_url"):
        parsed = urlparse(result[field])
        if parsed.scheme != "https" or parsed.hostname not in _PROVIDER_HOSTS or parsed.username or parsed.password:
            raise ReferenceArtifactRegistryError(f"artifact.{field} must be provider-controlled HTTPS")
    _require_positive_int(result["expected_size_bytes"], "artifact.expected_size_bytes")
    _require_digest(result["sha256"], "artifact.sha256")
    if result["media_type"] != "application/zip":
        raise ReferenceArtifactRegistryError("reference artifacts must use the qualified ZIP media type")
    if result["redistribution"] != "upstream_only_not_redistributed":
        raise ReferenceArtifactRegistryError("reference artifact redistribution boundary changed")
    if result["qualification_status"] != "qualified":
        raise ReferenceArtifactRegistryError("only qualified reference artifacts may enter the active registry")
    if not isinstance(result["reviewed_at"], str) or not _DATE.fullmatch(result["reviewed_at"]):
        raise ReferenceArtifactRegistryError("artifact.reviewed_at must be an ISO date")
    members = result["members"]
    if not isinstance(members, list) or not members:
        raise ReferenceArtifactRegistryError("qualified reference artifact must name exact members")
    result["members"] = [_validate_member(member) for member in members]
    member_paths = [member["path"] for member in result["members"]]
    _require_sorted_unique(member_paths, "artifact member")
    return result


def _validate_member(value: Any) -> dict[str, Any]:
    _require_fields(value, _MEMBER_FIELDS, "artifact member")
    result = deepcopy(value)
    _require_text(result["path"], "artifact member.path")
    path = PurePosixPath(result["path"])
    if path.is_absolute() or ".." in path.parts or "." in path.parts or len(path.parts) > 8:
        raise ReferenceArtifactRegistryError("artifact member path must be one bounded relative member")
    _require_positive_int(result["expected_size_bytes"], "artifact member.expected_size_bytes")
    _require_digest(result["sha256"], "artifact member.sha256")
    return result


def _validate_projection(value: Any) -> dict[str, Any]:
    _require_fields(value, _PROJECTION_FIELDS, "projection")
    result = deepcopy(value)
    for field in (
        "projection_id",
        "artifact_id",
        "title",
        "member_path",
        "native_reader_contract",
        "object_name",
        "feature_axis_title",
    ):
        _require_text(result[field], f"projection.{field}")
    if result["native_reader_contract"] not in _NATIVE_READER_CONTRACTS:
        raise ReferenceArtifactRegistryError("reference projection is not bound to a qualified native reader")
    if result["qualification_status"] != "qualified":
        raise ReferenceArtifactRegistryError("only qualified projections may enter the active registry")
    for field in ("n_samples", "n_features"):
        _require_positive_int(result[field], f"projection.{field}")
    has_target = result["target_object_name"] is not None
    for field in ("target_object_name", "target_name"):
        if has_target:
            _require_text(result[field], f"projection.{field}")
        elif result[field] is not None:
            raise ReferenceArtifactRegistryError(f"projection.{field} must be null without a target")
    if has_target:
        _require_positive_int(result["target_index"], "projection.target_index", allow_zero=True)
    elif result["target_index"] is not None:
        raise ReferenceArtifactRegistryError("projection.target_index must be null without a target")
    if result["target_units"] is not None:
        _require_text(result["target_units"], "projection.target_units")
    if result["feature_axis_units"] is not None:
        _require_text(result["feature_axis_units"], "projection.feature_axis_units")
    for field in ("feature_axis_sha256", "scientific_sha256"):
        _require_digest(result[field], f"projection.{field}")
    result["analysis"] = _validate_analysis(
        result["analysis"],
        has_target=has_target,
        target_name=result["target_name"],
    )
    return result


def _validate_analysis(value: Any, *, has_target: bool, target_name: str | None) -> dict[str, Any]:
    try:
        result = normalize_analysis_profile(value)
    except ValueError as exc:
        raise ReferenceArtifactRegistryError(str(exc).replace("dataset analysis", "projection analysis")) from exc
    target_fields = result["target_fields"]
    if has_target:
        if result["target_type"] not in _TARGET_TYPES or target_fields != [target_name]:
            raise ReferenceArtifactRegistryError("projection analysis target authority disagrees with projection")
    elif result["target_type"] is not None or target_fields:
        raise ReferenceArtifactRegistryError("target-free projection analysis must not declare a target")
    return result


def _require_fields(value: Any, fields: frozenset[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ReferenceArtifactRegistryError(f"{name} fields differ from the closed schema")


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReferenceArtifactRegistryError(f"{name} must be non-empty text")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ReferenceArtifactRegistryError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive_int(value: Any, name: str, *, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        raise ReferenceArtifactRegistryError(f"{name} must be an integer greater than or equal to {minimum}")


def _require_sorted_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ReferenceArtifactRegistryError(f"{name} identities must be unique")
    if values != sorted(values):
        raise ReferenceArtifactRegistryError(f"{name} entries must be sorted")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


__all__ = [
    "BUILTIN_DATASET_PROFILES_PATH",
    "BUILTIN_DATASET_PROFILES_SCHEMA",
    "REFERENCE_ARTIFACT_REGISTRY_PATH",
    "REFERENCE_ARTIFACT_REGISTRY_SCHEMA",
    "ReferenceArtifact",
    "ReferenceArtifactRegistry",
    "ReferenceArtifactRegistryError",
    "ReferenceProjection",
    "builtin_dataset_catalog",
    "load_reference_artifact_registry",
    "model_neutral_dataset_catalog",
    "registered_reference_catalog",
    "reference_artifact_registry_digest",
    "registered_artifact_acquisition",
    "registered_projection_acquisition",
]
