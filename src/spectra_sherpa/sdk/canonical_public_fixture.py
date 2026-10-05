"""Load a bounded public fixture for OSS canonical-project reproduction.

The canonical project package deliberately contains no source spectra.  A
recipient who wants to check the managed validation claim therefore supplies a
separate public fixture.  This module admits a small, explicit NumPy format
and derives the otherwise opaque capability binding from the immutable
package.  It never contacts a managed service and it never treats the fixture
as a substitute for a protected or customer dataset.

The format is closed: ``X`` and ``y`` are required; ``wavelengths`` and
``groups`` are optional.  Object arrays, extra members, and malformed shapes
are rejected before the data reaches a DAG node.  A genuine reproduction still
requires the resulting capability and split plan to equal the identities
sealed in the package; :func:`reproduce_canonical_project` performs that
comparison and reports a non-passing scientific outcome if they differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability

from .canonical_project import CanonicalProjectPackage, CanonicalProjectPackageError
from .validate import (
    SplitPlan,
    make_classification_split_plan,
    make_leave_one_group_out_classification_plan,
    make_split_plan,
)

_FIXTURE_MEMBERS = frozenset({"X", "y", "wavelengths", "groups"})


class CanonicalPublicFixtureError(ValueError):
    """A supplied public reproduction fixture is unsafe or malformed."""


@dataclass(frozen=True)
class CanonicalPublicFixture:
    """A local capability and exact split reconstructed from one public NPZ."""

    capability: SpectralDatasetCapability
    split_plan: SplitPlan


def load_canonical_public_fixture(
    path: Path,
    package: CanonicalProjectPackage | bytes,
    *,
    custody_id: str,
    spectral_axis_title: str | None = None,
    spectral_axis_units: str | None = "cm-1",
) -> CanonicalPublicFixture:
    """Load a public fixture using only OSS code and package-bound identities.

    ``path`` is intentionally local and is never stored in the capability or
    returned object. ``custody_id`` and the spectral-axis title/units are
    data-free fields recorded by the producing Runner's public-fixture
    binding; their resulting envelope must still equal the package's
    immutable capability digest. The caller may retain a checksum of the
    bytes and this binding in an operator handoff, but the scientific verifier
    receives only typed arrays and opaque identities.
    """

    if not isinstance(path, Path) or not path.is_file() or path.is_symlink():
        raise CanonicalPublicFixtureError("canonical public fixture must be a regular local file")
    loaded = _load_package(package)
    request = loaded.capsule.payload.get("admitted_request")
    if not isinstance(request, dict):
        raise CanonicalPublicFixtureError("canonical project admitted request is unavailable")
    try:
        with np.load(path, allow_pickle=False) as archive:
            names = frozenset(archive.files)
            if not {"X", "y"}.issubset(names) or not names.issubset(_FIXTURE_MEMBERS):
                raise CanonicalPublicFixtureError("canonical public fixture members are closed")
            X = _matrix("X", archive["X"], rows=None)
            raw_y = np.asarray(archive["y"])
            wavelengths = (
                _vector("wavelengths", archive["wavelengths"], rows=X.shape[1])
                if "wavelengths" in names
                else np.arange(X.shape[1], dtype=float)
            )
            groups = _groups(archive["groups"], rows=X.shape[0]) if "groups" in names else None
    except (OSError, ValueError) as exc:
        if isinstance(exc, CanonicalPublicFixtureError):
            raise
        raise CanonicalPublicFixtureError("canonical public fixture cannot be read safely") from exc

    validation = request.get("validation")
    if not isinstance(validation, dict):
        raise CanonicalPublicFixtureError("canonical project validation plan is unavailable")
    outer_splits = validation.get("outer_splits")
    shuffle = validation.get("shuffle")
    task_type = validation.get("task_type")
    if (
        isinstance(outer_splits, bool)
        or not isinstance(outer_splits, int)
        or not isinstance(shuffle, bool)
        or task_type not in {"regression", "classification"}
    ):
        raise CanonicalPublicFixtureError("canonical project validation plan is malformed")
    y = _target_vector(raw_y, rows=X.shape[0], task_type=task_type)
    if groups is not None and shuffle:
        # This follows the explicit SDK split contract rather than silently
        # changing a grouped plan into KFold on the recipient's machine.
        raise CanonicalPublicFixtureError("grouped canonical public fixture cannot use shuffled splitting")
    dataset_ref_digest = request.get("dataset_ref_digest")
    if (
        not isinstance(custody_id, str)
        or not custody_id
        or not isinstance(dataset_ref_digest, str)
        or not isinstance(spectral_axis_title, (str, type(None)))
        or not isinstance(spectral_axis_units, (str, type(None)))
    ):
        raise CanonicalPublicFixtureError("canonical project dataset binding is unavailable")
    expected_split_digest = request.get("split_digest")
    if not isinstance(expected_split_digest, str):
        raise CanonicalPublicFixtureError("canonical project split identity is unavailable")
    try:
        split_plan = _matching_split_plan(
            y=y,
            rows=X.shape[0],
            groups=groups,
            task_type=task_type,
            outer_splits=outer_splits,
            shuffle=shuffle,
            expected_digest=expected_split_digest,
        )
        fixture = build_canonical_public_fixture(
            X=X,
            y=y,
            wavelengths=wavelengths,
            groups=groups,
            split_plan=split_plan,
            task_type=task_type,
            custody_id=custody_id,
            dataset_ref_digest=dataset_ref_digest,
            spectral_axis_title=spectral_axis_title,
            spectral_axis_units=spectral_axis_units,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalPublicFixtureError("canonical public fixture cannot build a spectral capability") from exc
    return fixture


def load_registered_reference_fixture(
    path: Path,
    package: CanonicalProjectPackage | bytes,
    *,
    projection_id: str,
) -> CanonicalPublicFixture:
    """Rebuild a hosted campaign fixture from provider-acquired exact bytes.

    The caller supplies the registered artifact downloaded directly from its
    provider.  Sherpa verifies and natively projects those bytes through the
    same registry used by the dedicated reference-import surface; it does not
    fetch, mirror, or retain the artifact.  Hosted campaigns bind capabilities
    to ``campaign-<public id>``, so the custody authority is recovered from the
    signed package instead of asking the scientist to copy an opaque server
    identifier.
    """

    from spectra_sherpa.app.lib.reference_artifacts import (
        ReferenceArtifactRegistryError,
        load_reference_artifact_registry,
    )
    from spectra_sherpa.app.lib.reference_materialization import (
        ReferenceMaterializationError,
        materialize_reference_projection,
    )

    if not isinstance(path, Path) or not path.is_file() or path.is_symlink():
        raise CanonicalPublicFixtureError("registered reference artifact must be a regular local file")
    if not isinstance(projection_id, str) or not projection_id.strip():
        raise CanonicalPublicFixtureError("registered reference projection ID is required")
    loaded = _load_package(package)
    request = loaded.capsule.payload.get("admitted_request")
    if not isinstance(request, dict):
        raise CanonicalPublicFixtureError("canonical project admitted request is unavailable")
    validation = request.get("validation")
    dataset_shape = request.get("dataset_shape")
    campaign_id = request.get("campaign_id")
    dataset_ref_digest = request.get("dataset_ref_digest")
    expected_split_digest = request.get("split_digest")
    if not isinstance(validation, dict):
        raise CanonicalPublicFixtureError("canonical project validation plan is unavailable")
    if not isinstance(dataset_shape, dict) or dataset_shape.get("grouped") is not False:
        raise CanonicalPublicFixtureError("registered reference reproduction does not expose a grouped authority")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise CanonicalPublicFixtureError("canonical project campaign identity is unavailable")
    if not isinstance(dataset_ref_digest, str) or not isinstance(expected_split_digest, str):
        raise CanonicalPublicFixtureError("canonical project dataset binding is unavailable")
    outer_splits = validation.get("outer_splits")
    shuffle = validation.get("shuffle")
    task_type = validation.get("task_type")
    if (
        isinstance(outer_splits, bool)
        or not isinstance(outer_splits, int)
        or not isinstance(shuffle, bool)
        or task_type not in {"regression", "classification"}
    ):
        raise CanonicalPublicFixtureError("canonical project validation plan is malformed")
    try:
        materialized = materialize_reference_projection(path, projection_id.strip())
    except ReferenceMaterializationError as exc:
        raise CanonicalPublicFixtureError(f"registered reference could not be materialized: {exc}") from exc
    dataset = materialized.dataset
    axis = dataset.get_feature_axis()
    if dataset.target is None or axis is None or axis.values is None:
        raise CanonicalPublicFixtureError("registered reference projection is missing its supervised spectral binding")
    X = _matrix("X", dataset.X, rows=None)
    target = np.asarray(dataset.target)
    if target.ndim == 2:
        try:
            projection = load_reference_artifact_registry().projection(projection_id.strip()).as_dict()
        except ReferenceArtifactRegistryError as exc:
            raise CanonicalPublicFixtureError("registered reference projection authority is unavailable") from exc
        target_names = None if dataset.target_context is None else dataset.target_context.target_names
        if not isinstance(target_names, list) or projection["target_name"] not in target_names:
            raise CanonicalPublicFixtureError("registered reference target authority is unavailable")
        target = target[:, target_names.index(projection["target_name"])]
    y = _target_vector(target, rows=X.shape[0], task_type=task_type)
    wavelengths = _vector("wavelengths", axis.values, rows=X.shape[1])
    if not isinstance(axis.title, (str, type(None))) or not isinstance(axis.units, (str, type(None))):
        raise CanonicalPublicFixtureError("registered reference spectral-axis authority is malformed")
    try:
        split_plan = _matching_split_plan(
            y=y,
            rows=X.shape[0],
            groups=None,
            task_type=task_type,
            outer_splits=outer_splits,
            shuffle=shuffle,
            expected_digest=expected_split_digest,
        )
        return build_canonical_public_fixture(
            X=X,
            y=y,
            wavelengths=wavelengths,
            groups=None,
            split_plan=split_plan,
            task_type=task_type,
            custody_id=f"campaign-{campaign_id}",
            dataset_ref_digest=dataset_ref_digest,
            spectral_axis_title=axis.title,
            spectral_axis_units=axis.units,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CanonicalPublicFixtureError):
            raise
        raise CanonicalPublicFixtureError("registered reference cannot build a canonical fixture") from exc


def build_canonical_public_fixture(
    *,
    X: Any,
    y: Any,
    wavelengths: Any,
    groups: Any | None,
    split_plan: SplitPlan,
    task_type: str,
    custody_id: str,
    dataset_ref_digest: str,
    spectral_axis_title: str | None,
    spectral_axis_units: str | None,
) -> CanonicalPublicFixture:
    """Issue the one minimal, data-separated capability used at both ends."""

    matrix = _matrix("X", X, rows=None)
    target = _target_vector(y, rows=matrix.shape[0], task_type=task_type)
    axis = _vector("wavelengths", wavelengths, rows=matrix.shape[1])
    admitted_groups = None if groups is None else _groups(groups, rows=matrix.shape[0])
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=matrix,
            target=target,
            feature_axis=SpectralAxis(
                values=axis,
                title=spectral_axis_title,
                units=spectral_axis_units,
            ),
        ),
        # This is an opaque custody label, not a path or customer identifier.
        custody_id=custody_id,
        dataset_ref_digest=dataset_ref_digest,
        split_plan_digest=split_plan.digest,
        groups=admitted_groups,
    )
    return CanonicalPublicFixture(capability=capability, split_plan=split_plan)


def _matching_split_plan(
    *,
    y: np.ndarray,
    rows: int,
    groups: np.ndarray | None,
    task_type: str,
    outer_splits: int,
    shuffle: bool,
    expected_digest: str,
) -> SplitPlan:
    candidates: list[SplitPlan] = []
    if task_type == "classification":
        candidates.append(make_classification_split_plan(y, n_splits=outer_splits, groups=groups))
        if groups is not None and len(np.unique(groups)) == outer_splits:
            candidates.append(
                make_leave_one_group_out_classification_plan(
                    y,
                    groups,
                    require_one_per_class_group=True,
                )
            )
    else:
        candidates.append(make_split_plan(rows, n_splits=outer_splits, groups=groups, shuffle=shuffle))
    matches = {candidate.digest: candidate for candidate in candidates}
    try:
        return matches[expected_digest]
    except KeyError as exc:
        raise CanonicalPublicFixtureError("canonical public fixture cannot reproduce the sealed split plan") from exc


def _load_package(value: CanonicalProjectPackage | bytes) -> CanonicalProjectPackage:
    try:
        if isinstance(value, CanonicalProjectPackage):
            return CanonicalProjectPackage.from_archive(value.archive)
        if isinstance(value, bytes):
            return CanonicalProjectPackage.from_archive(value)
    except CanonicalProjectPackageError as exc:
        raise CanonicalPublicFixtureError("canonical project package is not admissible") from exc
    raise CanonicalPublicFixtureError("canonical project package bytes are required")


def _matrix(name: str, value: Any, *, rows: int | None) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or array.dtype.kind == "O" or array.ndim != 2 or not array.size:
        raise CanonicalPublicFixtureError(f"canonical public fixture {name} must be a non-empty numeric matrix")
    if rows is not None and array.shape[0] != rows:
        raise CanonicalPublicFixtureError(f"canonical public fixture {name} row count is invalid")
    result = np.asarray(array, dtype=float)
    if not np.isfinite(result).all():
        raise CanonicalPublicFixtureError(f"canonical public fixture {name} must be finite")
    return result


def _vector(name: str, value: Any, *, rows: int) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or array.dtype.kind == "O" or array.ndim != 1 or array.shape[0] != rows:
        raise CanonicalPublicFixtureError(f"canonical public fixture {name} length is invalid")
    result = np.asarray(array, dtype=float)
    if not np.isfinite(result).all():
        raise CanonicalPublicFixtureError(f"canonical public fixture {name} must be finite")
    return result


def _target_vector(value: Any, *, rows: int, task_type: str) -> np.ndarray:
    """Admit the task-appropriate target without erasing label identity."""

    array = np.asarray(value)
    if array.dtype.kind == "O" or array.ndim != 1 or array.shape[0] != rows:
        raise CanonicalPublicFixtureError("canonical public fixture y length is invalid")
    if task_type == "regression":
        if array.dtype.kind not in "fiu":
            raise CanonicalPublicFixtureError("canonical public fixture regression y must be numeric")
        result = np.asarray(array, dtype=float)
        if not np.isfinite(result).all():
            raise CanonicalPublicFixtureError("canonical public fixture regression y must be finite")
        return result
    if task_type == "classification":
        if array.dtype.kind not in "fiuU":
            raise CanonicalPublicFixtureError(
                "canonical public fixture classification y must contain numeric or Unicode labels"
            )
        if array.dtype.kind == "f" and not np.isfinite(array).all():
            raise CanonicalPublicFixtureError("canonical public fixture classification y must be finite")
        return np.ascontiguousarray(array)
    raise CanonicalPublicFixtureError("canonical public fixture task type is invalid")


def _groups(value: Any, *, rows: int) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind == "O" or array.ndim != 1 or array.shape[0] != rows or array.dtype.kind not in "iufUSb":
        raise CanonicalPublicFixtureError("canonical public fixture groups are invalid")
    if array.dtype.kind == "f" and not np.isfinite(array).all():
        raise CanonicalPublicFixtureError("canonical public fixture groups must be finite")
    return array


__all__ = [
    "CanonicalPublicFixture",
    "CanonicalPublicFixtureError",
    "build_canonical_public_fixture",
    "load_canonical_public_fixture",
    "load_registered_reference_fixture",
]
