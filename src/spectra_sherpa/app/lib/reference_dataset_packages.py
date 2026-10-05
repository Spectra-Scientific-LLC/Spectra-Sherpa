"""Scientific package and data-view relationships for registered references.

Artifact admission remains governed by :mod:`reference_artifacts`: exact size
and SHA-256 identify provider-acquired bytes.  This separate registry explains
how qualified projections from those bytes belong to a scientist-facing
package.  A data-view default is display intent only; it never selects a
target, model, preprocessing operation, or validation method.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.reference_artifacts import (
    ReferenceArtifactRegistry,
    ReferenceArtifactRegistryError,
    load_reference_artifact_registry,
)

REFERENCE_DATASET_PACKAGES_SCHEMA = "spectra-sherpa-reference-dataset-packages/1"
REFERENCE_DATASET_PACKAGES_PATH = Path(__file__).resolve().parents[2] / "data" / "reference_dataset_packages_v1.json"

_IDENTITY = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_TOP_FIELDS = frozenset({"schema_version", "packages"})
_PACKAGE_FIELDS = frozenset(
    {
        "package_id",
        "title",
        "description",
        "provider",
        "assembly_mode",
        "artifact_ids",
        "initial_view_ids",
        "annotation_tables",
        "views",
        "relations",
    }
)
_VIEW_FIELDS = frozenset({"view_id", "projection_id", "label", "instrument", "cohort", "annotation_table_id"})
_ANNOTATION_TABLE_FIELDS = frozenset({"annotation_table_id", "object_name", "n_rows", "fields", "values_sha256"})
_ANNOTATION_FIELD_FIELDS = frozenset({"index", "name", "target_type", "units"})
_RELATION_FIELDS = frozenset({"relation_id", "relation_type", "view_ids", "row_identity"})
_TARGET_TYPES = frozenset({"continuous", "categorical", "ordinal"})
_ASSEMBLY_MODES = frozenset({"homogeneous_collection", "heterogeneous_views", "single_view"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ANNOTATION_DIGEST_VERSION = "spectra-sherpa-reference-annotation-table/1"
_RELATION_TYPES = frozenset(
    {
        "same_specimens_aligned",
        "calibration_application_cohorts",
        "partially_aligned",
        "unrelated_views",
        "alignment_unverified",
    }
)


@dataclass(frozen=True)
class ReferenceDatasetPackage:
    _payload: dict[str, Any]

    @property
    def package_id(self) -> str:
        return str(self._payload["package_id"])

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


@dataclass(frozen=True)
class ReferenceDatasetPackageRegistry:
    packages: tuple[ReferenceDatasetPackage, ...]

    def package(self, package_id: str) -> ReferenceDatasetPackage:
        for package in self.packages:
            if package.package_id == package_id:
                return package
        raise ReferenceArtifactRegistryError(f"unknown qualified reference dataset package: {package_id!r}")

    def package_for_projection(self, projection_id: str) -> ReferenceDatasetPackage | None:
        for package in self.packages:
            if any(view["projection_id"] == projection_id for view in package.as_dict()["views"]):
                return package
        return None


def load_reference_dataset_package_registry(
    path: Path = REFERENCE_DATASET_PACKAGES_PATH,
    *,
    artifact_registry: ReferenceArtifactRegistry | None = None,
) -> ReferenceDatasetPackageRegistry:
    """Load and cross-check the closed package/view relationship authority."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceArtifactRegistryError(f"cannot load reference dataset packages: {exc}") from exc
    _require_fields(payload, _TOP_FIELDS, "package registry")
    if payload["schema_version"] != REFERENCE_DATASET_PACKAGES_SCHEMA:
        raise ReferenceArtifactRegistryError("reference dataset package schema is unsupported")
    raw_packages = payload["packages"]
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ReferenceArtifactRegistryError("reference dataset packages must be a non-empty array")

    active_artifacts = artifact_registry or load_reference_artifact_registry()
    artifact_ids = {artifact.artifact_id for artifact in active_artifacts.artifacts}
    projection_by_id = {projection.projection_id: projection.as_dict() for projection in active_artifacts.projections}
    packages = tuple(
        ReferenceDatasetPackage(_validate_package(value, artifact_ids, projection_by_id)) for value in raw_packages
    )
    package_ids = [package.package_id for package in packages]
    _require_sorted_unique(package_ids, "package")
    projection_ids = [view["projection_id"] for package in packages for view in package.as_dict()["views"]]
    if len(projection_ids) != len(set(projection_ids)):
        raise ReferenceArtifactRegistryError("one reference projection cannot belong to multiple packages")
    missing_projections = sorted(set(projection_by_id) - set(projection_ids))
    if missing_projections:
        raise ReferenceArtifactRegistryError(
            "reference dataset packages do not account for projection(s): " + ", ".join(missing_projections)
        )
    return ReferenceDatasetPackageRegistry(packages=packages)


def reference_dataset_package_registry_digest(path: Path = REFERENCE_DATASET_PACKAGES_PATH) -> str:
    registry = load_reference_dataset_package_registry(path)
    payload = {
        "schema_version": REFERENCE_DATASET_PACKAGES_SCHEMA,
        "packages": [package.as_dict() for package in registry.packages],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def package_view_projection(
    projection_id: str,
    *,
    registry: ReferenceDatasetPackageRegistry | None = None,
) -> dict[str, Any] | None:
    """Return detached package/view metadata for one technical projection."""

    active = registry or load_reference_dataset_package_registry()
    package = active.package_for_projection(projection_id)
    if package is None:
        return None
    payload = package.as_dict()
    view = next(view for view in payload["views"] if view["projection_id"] == projection_id)
    annotation_table = next(
        (
            table
            for table in payload["annotation_tables"]
            if table["annotation_table_id"] == view["annotation_table_id"]
        ),
        None,
    )
    return {
        "package_id": payload["package_id"],
        "package_title": payload["title"],
        "package_description": payload["description"],
        "assembly_mode": payload["assembly_mode"],
        "artifact_ids": list(payload["artifact_ids"]),
        "view_id": view["view_id"],
        "view_label": view["label"],
        "instrument": view["instrument"],
        "cohort": view["cohort"],
        "annotation_table": annotation_table,
        "initially_selected": view["view_id"] in payload["initial_view_ids"],
        "relations": [relation for relation in payload["relations"] if view["view_id"] in relation["view_ids"]],
    }


def package_import_projection(
    package_id: str,
    *,
    registry: ReferenceDatasetPackageRegistry | None = None,
) -> dict[str, Any]:
    """Return the complete, detached import authority for one package."""

    active = registry or load_reference_dataset_package_registry()
    return active.package(package_id).as_dict()


def reference_annotation_table_digest(values: Any, fields: list[dict[str, Any]]) -> str:
    """Hash one complete, labeled annotation matrix independent of its container."""

    try:
        matrix = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ReferenceArtifactRegistryError("reference annotation table values must be numeric") from exc
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] != len(fields):
        raise ReferenceArtifactRegistryError("reference annotation table shape disagrees with its fields")
    if not np.isfinite(matrix).all():
        raise ReferenceArtifactRegistryError("reference annotation table values must be finite")
    canonical_fields = [_validate_annotation_field(field) for field in fields]
    if [field["index"] for field in canonical_fields] != list(range(matrix.shape[1])):
        raise ReferenceArtifactRegistryError("reference annotation field indices must be contiguous")
    digest = hashlib.sha256()
    digest.update(_ANNOTATION_DIGEST_VERSION.encode("ascii"))
    digest.update(_canonical_json(canonical_fields))
    canonical = np.ascontiguousarray(matrix, dtype="<f8")
    digest.update(_canonical_json({"dtype": "float64-le", "shape": list(canonical.shape)}))
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _validate_package(
    value: Any,
    artifact_ids: set[str],
    projection_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    _require_fields(value, _PACKAGE_FIELDS, "package")
    result = deepcopy(value)
    for field in ("package_id", "title", "description", "provider"):
        _require_text(result[field], f"package.{field}")
    _require_identity(result["package_id"], "package.package_id")
    if result["provider"] != "Eigenvector Research":
        raise ReferenceArtifactRegistryError("reference dataset package provider is unsupported")
    if result["assembly_mode"] not in _ASSEMBLY_MODES:
        raise ReferenceArtifactRegistryError("reference dataset package assembly mode is unsupported")

    package_artifacts = _require_identity_list(result["artifact_ids"], "package.artifact_ids")
    if not set(package_artifacts).issubset(artifact_ids):
        raise ReferenceArtifactRegistryError("reference dataset package names an unknown artifact")

    raw_views = result["views"]
    if not isinstance(raw_views, list) or not raw_views:
        raise ReferenceArtifactRegistryError("reference dataset package must contain at least one view")
    raw_tables = result["annotation_tables"]
    if not isinstance(raw_tables, list):
        raise ReferenceArtifactRegistryError("reference dataset package annotation tables must be an array")
    tables = [_validate_annotation_table(table) for table in raw_tables]
    table_ids = [table["annotation_table_id"] for table in tables]
    _require_sorted_unique(table_ids, "package annotation table")
    result["annotation_tables"] = tables

    tables_by_id = {table["annotation_table_id"]: table for table in tables}
    views = [_validate_view(view, package_artifacts, projection_by_id, tables_by_id) for view in raw_views]
    view_ids = [view["view_id"] for view in views]
    _require_sorted_unique(view_ids, "package view")
    result["views"] = views
    if result["assembly_mode"] == "single_view":
        if len(package_artifacts) != 1 or len(views) != 1 or tables or result["relations"]:
            raise ReferenceArtifactRegistryError(
                "single-view reference package requires one artifact, one view, and no annotations or relations"
            )
    elif result["assembly_mode"] == "homogeneous_collection":
        if len(package_artifacts) != 1 or any(view["annotation_table_id"] is None for view in views):
            raise ReferenceArtifactRegistryError(
                "homogeneous reference package requires one artifact and annotations for every view"
            )
    elif len(package_artifacts) != len({projection_by_id[view["projection_id"]]["artifact_id"] for view in views}):
        raise ReferenceArtifactRegistryError(
            "heterogeneous reference package must represent every named artifact with a data view"
        )

    initial = _require_identity_list(result["initial_view_ids"], "package.initial_view_ids")
    if not initial or not set(initial).issubset(view_ids):
        raise ReferenceArtifactRegistryError("initial data views must be a non-empty subset of package views")

    raw_relations = result["relations"]
    if not isinstance(raw_relations, list):
        raise ReferenceArtifactRegistryError("package.relations must be an array")
    relations = [_validate_relation(relation, set(view_ids)) for relation in raw_relations]
    _require_sorted_unique([relation["relation_id"] for relation in relations], "package relation")
    result["relations"] = relations
    return result


def _validate_view(
    value: Any,
    package_artifact_ids: list[str],
    projection_by_id: dict[str, dict[str, Any]],
    annotation_tables_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    _require_fields(value, _VIEW_FIELDS, "package view")
    result = deepcopy(value)
    for field in _VIEW_FIELDS - {"annotation_table_id"}:
        _require_text(result[field], f"package view.{field}")
    _require_identity(result["view_id"], "package view.view_id")
    projection = projection_by_id.get(result["projection_id"])
    if projection is None:
        raise ReferenceArtifactRegistryError("package view names an unknown reference projection")
    if projection["artifact_id"] not in package_artifact_ids:
        raise ReferenceArtifactRegistryError("package view projection is outside the package artifacts")
    annotation_id = result["annotation_table_id"]
    if annotation_id is not None and annotation_id not in annotation_tables_by_id:
        raise ReferenceArtifactRegistryError("package view names an unknown annotation table")
    if annotation_id is None and projection["target_object_name"] is not None:
        raise ReferenceArtifactRegistryError("target-bearing package view requires an annotation table")
    if annotation_id is not None:
        annotation = annotation_tables_by_id[annotation_id]
        if annotation["object_name"] != projection["target_object_name"]:
            raise ReferenceArtifactRegistryError("package annotation object disagrees with its reference projection")
        if annotation["n_rows"] != projection["n_samples"]:
            raise ReferenceArtifactRegistryError("package annotation rows disagree with its reference projection")
        target_index = projection["target_index"]
        if type(target_index) is not int or not 0 <= target_index < len(annotation["fields"]):
            raise ReferenceArtifactRegistryError("reference projection target index is outside its package annotation")
        target_field = annotation["fields"][target_index]
        if (
            target_field["name"] != projection["target_name"]
            or target_field["units"] != projection["target_units"]
            or target_field["target_type"] != projection["analysis"]["target_type"]
        ):
            raise ReferenceArtifactRegistryError("package annotation target disagrees with its reference projection")
    return result


def _validate_annotation_table(value: Any) -> dict[str, Any]:
    _require_fields(value, _ANNOTATION_TABLE_FIELDS, "package annotation table")
    result = deepcopy(value)
    _require_identity(result["annotation_table_id"], "package annotation table.annotation_table_id")
    _require_text(result["object_name"], "package annotation table.object_name")
    if type(result["n_rows"]) is not int or result["n_rows"] < 1:
        raise ReferenceArtifactRegistryError("package annotation table.n_rows must be a positive integer")
    if not isinstance(result["fields"], list) or not result["fields"]:
        raise ReferenceArtifactRegistryError("package annotation table.fields must be a non-empty array")
    result["fields"] = [_validate_annotation_field(field) for field in result["fields"]]
    if [field["index"] for field in result["fields"]] != list(range(len(result["fields"]))):
        raise ReferenceArtifactRegistryError("reference annotation field indices must be contiguous")
    names = [field["name"] for field in result["fields"]]
    if len(names) != len(set(names)):
        raise ReferenceArtifactRegistryError("reference annotation field names must be unique")
    if not isinstance(result["values_sha256"], str) or not _SHA256.fullmatch(result["values_sha256"]):
        raise ReferenceArtifactRegistryError("package annotation table.values_sha256 must be a SHA-256 digest")
    return result


def _validate_annotation_field(value: Any) -> dict[str, Any]:
    _require_fields(value, _ANNOTATION_FIELD_FIELDS, "package annotation field")
    result = deepcopy(value)
    if type(result["index"]) is not int or result["index"] < 0:
        raise ReferenceArtifactRegistryError("package annotation field.index must be a non-negative integer")
    _require_text(result["name"], "package annotation field.name")
    if result["target_type"] not in _TARGET_TYPES:
        raise ReferenceArtifactRegistryError("package annotation field.target_type is unsupported")
    if result["units"] is not None:
        _require_text(result["units"], "package annotation field.units")
    return result


def _validate_relation(value: Any, view_ids: set[str]) -> dict[str, Any]:
    _require_fields(value, _RELATION_FIELDS, "package relation")
    result = deepcopy(value)
    _require_identity(result["relation_id"], "package relation.relation_id")
    if result["relation_type"] not in _RELATION_TYPES:
        raise ReferenceArtifactRegistryError("package relation type is unsupported")
    relation_views = _require_identity_list(result["view_ids"], "package relation.view_ids")
    if len(relation_views) < 2 or not set(relation_views).issubset(view_ids):
        raise ReferenceArtifactRegistryError("package relation views must name at least two package views")
    _require_text(result["row_identity"], "package relation.row_identity")
    return result


def _require_fields(value: Any, fields: frozenset[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ReferenceArtifactRegistryError(f"{name} fields differ from the closed schema")


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReferenceArtifactRegistryError(f"{name} must be non-empty text")


def _require_identity(value: Any, name: str) -> None:
    _require_text(value, name)
    if not _IDENTITY.fullmatch(value):
        raise ReferenceArtifactRegistryError(f"{name} must be a stable lowercase identity")


def _require_identity_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReferenceArtifactRegistryError(f"{name} must be an identity array")
    result = list(value)
    for item in result:
        _require_identity(item, name)
    _require_sorted_unique(result, name)
    return result


def _require_sorted_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ReferenceArtifactRegistryError(f"{name} identities must be unique")
    if values != sorted(values):
        raise ReferenceArtifactRegistryError(f"{name} entries must be sorted")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


__all__ = [
    "REFERENCE_DATASET_PACKAGES_PATH",
    "REFERENCE_DATASET_PACKAGES_SCHEMA",
    "ReferenceDatasetPackage",
    "ReferenceDatasetPackageRegistry",
    "load_reference_dataset_package_registry",
    "package_import_projection",
    "package_view_projection",
    "reference_annotation_table_digest",
    "reference_dataset_package_registry_digest",
]
