"""One strict authority for assembling project-owned scientific collections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import AxisClassSet, AxisLabelSet, AxisScaleSet, FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.scientific_values import lossless_json_scalar, lossless_scalar_identity
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetLayoutContext,
    DatasetSourceIdentity,
    Provenance,
    SherpaDataset,
    structured_scientific_projection,
)
from spectra_sherpa.core.axis_semantics import (
    AxisQuantity,
    axis_semantics,
    require_compatible_axis_semantics,
)

_EMPTY_PREPARED_DATA_SHA256 = hashlib.sha256(b"{}").hexdigest()
MAX_COLLECTION_MEMBERS = 512
MAX_COLLECTION_SOURCE_BYTES = 512 * 1024 * 1024
MAX_COLLECTION_RETAINED_BYTES = 256 * 1024 * 1024
MAX_COLLECTION_RETAINED_ELEMENTS = 32_000_000


@dataclass(frozen=True)
class CollectionMember:
    """One already-admitted dataset and its portable source identity."""

    dataset: SherpaDataset
    file_name: str
    size_bytes: int
    sha256: str
    prepared_data_sha256: str = _EMPTY_PREPARED_DATA_SHA256
    asset_id: str = "single-auto"


def prepared_data_digest(overrides: Mapping[str, Any] | None) -> str:
    """Bind the canonical persisted read semantics for one source member."""

    from spectra_sherpa.core.prepared_data import PreparedDataOverrides

    payload = PreparedDataOverrides.from_mapping(overrides).to_sidecar_dict()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_collection_file_name(file_name: str) -> str:
    """Require one exact, portable spelling for a collection member name."""

    if not isinstance(file_name, str) or not file_name:
        raise ValueError("scientific collection contains an invalid source identity")
    portable_name = PurePosixPath(file_name.replace("\\", "/"))
    canonical_name = portable_name.as_posix()
    if (
        portable_name.is_absolute()
        or any(part in {"", ".", ".."} for part in portable_name.parts)
        or file_name != canonical_name
    ):
        raise ValueError("scientific collection contains an invalid source identity")
    return canonical_name


def lossless_sample_table_scalar(
    value: object,
    *,
    max_text_chars: int | None = None,
) -> str | int | float | bool | None:
    """Project one sample-table cell without collapsing its typed identity."""

    return lossless_json_scalar(
        value,
        max_text_chars=max_text_chars,
        field_name="collection sample table",
    )


def validate_lossless_sample_table_wire(sample_table: Mapping[str, Sequence[object]] | None) -> None:
    """Refuse cells that the untagged JSON wire cannot preserve exactly."""

    if sample_table is None:
        return
    for values in sample_table.values():
        for value in values:
            lossless_sample_table_scalar(value)


def collection_manifest(members: Sequence[CollectionMember]) -> dict[str, Any]:
    """Return the ordered portable identity of one exact source collection."""

    if not members:
        raise ValueError("scientific collection has no admitted members")
    if len(members) > MAX_COLLECTION_MEMBERS:
        raise ValueError(f"scientific collection exceeds the {MAX_COLLECTION_MEMBERS}-member limit")
    if sum(member.size_bytes for member in members) > MAX_COLLECTION_SOURCE_BYTES:
        raise ValueError("scientific collection exceeds the 512 MiB source limit")
    canonical_names = [canonical_collection_file_name(member.file_name) for member in members]
    if len({name.casefold() for name in canonical_names}) != len(members):
        raise ValueError("scientific collection contains duplicate source names")
    for member in members:
        if not isinstance(member.asset_id, str) or not member.asset_id or member.asset_id != member.asset_id.strip():
            raise ValueError("scientific collection contains an invalid asset identity")
        if member.size_bytes < 0:
            raise ValueError("scientific collection contains an invalid source identity")
        if len(member.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in member.sha256):
            raise ValueError("scientific collection contains an invalid source digest")
        if len(member.prepared_data_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in member.prepared_data_sha256
        ):
            raise ValueError("scientific collection contains an invalid prepared-data digest")
    entries = [
        {
            "file_name": member.file_name,
            "size_bytes": member.size_bytes,
            "sha256": member.sha256,
            "prepared_data_sha256": member.prepared_data_sha256,
        }
        for member in members
    ]
    return source_collection_manifest(entries)


def source_collection_manifest(entries: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    """Validate and hash one already-captured ordered source inventory."""

    if not entries or len(entries) > MAX_COLLECTION_MEMBERS:
        raise ValueError("scientific collection contains an invalid member count")
    projected = [dict(entry) for entry in entries]
    canonical_names: list[str] = []
    source_bytes = 0
    for entry in projected:
        if set(entry) != {"file_name", "size_bytes", "sha256", "prepared_data_sha256"}:
            raise ValueError("scientific collection contains an invalid source identity")
        name = canonical_collection_file_name(entry["file_name"])  # type: ignore[arg-type]
        size = entry["size_bytes"]
        sha = entry["sha256"]
        prepared_sha = entry["prepared_data_sha256"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("scientific collection contains an invalid source identity")
        if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ValueError("scientific collection contains an invalid source digest")
        if (
            not isinstance(prepared_sha, str)
            or len(prepared_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in prepared_sha)
        ):
            raise ValueError("scientific collection contains an invalid prepared-data digest")
        canonical_names.append(name)
        source_bytes += size
    if len({name.casefold() for name in canonical_names}) != len(projected):
        raise ValueError("scientific collection contains duplicate source names")
    if source_bytes > MAX_COLLECTION_SOURCE_BYTES:
        raise ValueError("scientific collection exceeds the 512 MiB source limit")
    identity = {"schema_version": "spectrasherpa-source-collection/1", "files": projected}
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "spectrasherpa-source-collection/1",
        "file_count": len(projected),
        "files": projected,
        "manifest_digest": hashlib.sha256(payload).hexdigest(),
    }


def _retained_state_footprint(values: Sequence[object]) -> tuple[int, int]:
    """Conservatively charge an identity-deduplicated retained object graph."""

    seen: set[int] = set()
    elements = 0
    retained_bytes = 0

    def account(value: object) -> None:
        nonlocal elements, retained_bytes
        if value is None:
            return
        if isinstance(value, np.ndarray):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            elements += int(value.size)
            retained_bytes += int(value.nbytes) + 128
            if value.dtype.hasobject:
                for nested in value.flat:
                    account(nested)
            return
        if isinstance(value, str):
            retained_bytes += 64 + len(value.encode("utf-8"))
            return
        if isinstance(value, bytes):
            retained_bytes += 64 + len(value)
            return
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            retained_bytes += 128 + 72 * len(value)
            for key, nested in value.items():
                account(key)
                account(nested)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            retained_bytes += 96 + 16 * len(value)
            for nested in value:
                account(nested)
            return
        retained_bytes += 64

    for value in values:
        account(value)
    return elements, retained_bytes


def dataset_retained_footprint(dataset: SherpaDataset) -> tuple[int, int]:
    """Charge every retained scientific field of one admitted dataset."""

    feature_axis = dataset.feature_axis
    sample_axis = dataset.sample_axis
    inner_axes = dataset.inner_axes
    return _retained_state_footprint(
        [
            dataset.X,
            dataset.target,
            feature_axis.values if feature_axis is not None else None,
            feature_axis.model_dump(mode="python", exclude={"values"}) if feature_axis is not None else None,
            [axis.values for axis in inner_axes.values()],
            {dim: axis.model_dump(mode="python", exclude={"values"}) for dim, axis in inner_axes.items()},
            sample_axis.model_dump(mode="python") if sample_axis is not None else None,
            dataset.meta,
            dataset.provenance.to_list(),
            dataset.target_context.model_dump(mode="python"),
            dataset.domain.model_dump(mode="python"),
            dataset.descriptive.model_dump(mode="python"),
            dataset.source_identity.model_dump(mode="python"),
            dataset.source_history.model_dump(mode="python"),
            dataset.layout.model_dump(mode="python"),
            dataset.quality.model_dump(mode="python"),
            dataset.title,
            dataset.units,
            dataset.data_role,
        ]
    )


def collection_retained_footprint(members: Sequence[CollectionMember]) -> tuple[int, int]:
    """Charge retained inputs plus every array/list allocated by assembly."""

    # A one-member collection reuses the admitted dataset and its arrays.
    # Reserve space for the source-collection receipt added by assembly.
    if len(members) == 1:
        elements, retained_bytes = dataset_retained_footprint(members[0].dataset)
        return elements, retained_bytes + 4096

    input_values: list[object] = []
    for member in members:
        inner_axes = member.dataset.inner_axes
        input_values.extend(
            (
                member.dataset.X,
                member.dataset.target,
                member.dataset.feature_axis.values if member.dataset.feature_axis is not None else None,
                (
                    member.dataset.feature_axis.model_dump(mode="python", exclude={"values"})
                    if member.dataset.feature_axis is not None
                    else None
                ),
                [axis.values for axis in inner_axes.values()],
                {dim: axis.model_dump(mode="python", exclude={"values"}) for dim, axis in inner_axes.items()},
                (
                    member.dataset.sample_axis.model_dump(mode="python")
                    if member.dataset.sample_axis is not None
                    else None
                ),
                member.dataset.meta,
                member.dataset.provenance.to_list(),
                member.dataset.target_context.model_dump(mode="python"),
                member.dataset.domain.model_dump(mode="python"),
                member.dataset.descriptive.model_dump(mode="python"),
                member.dataset.source_identity.model_dump(mode="python"),
                member.dataset.source_history.model_dump(mode="python"),
                member.dataset.layout.model_dump(mode="python"),
                member.dataset.quality.model_dump(mode="python"),
                member.dataset.title,
                member.dataset.units,
                member.dataset.data_role,
            )
        )
    input_elements, input_bytes = _retained_state_footprint(input_values)
    output_elements = 0
    output_bytes = 4096 + 1024 * len(members)
    total_samples = 0
    for member in members:
        dataset = member.dataset
        total_samples += dataset.n_samples
        for array in (dataset.X, dataset.target):
            if array is not None:
                observed = np.asarray(array)
                output_elements += int(observed.size)
                output_bytes += int(observed.nbytes) + 128
        sample_axis = dataset.sample_axis
        if sample_axis is not None:
            for array in (sample_axis.values, sample_axis.classes):
                if array is not None:
                    observed = np.asarray(array)
                    output_elements += int(observed.size)
                    output_bytes += int(observed.nbytes) + 128
            output_elements += dataset.n_samples
            output_bytes += dataset.n_samples + 192 * dataset.n_samples
            output_bytes += 128 * dataset.n_samples
            output_bytes += 192 * dataset.n_samples * len(sample_axis.sample_table or {})
            for scale_set in sample_axis.alternate_scales:
                values = np.asarray(scale_set.values)
                output_elements += int(values.size)
                output_bytes += int(values.nbytes) + 256
            for label_set in sample_axis.alternate_label_sets:
                output_elements += len(label_set.values)
                output_bytes += 192 * len(label_set.values) + 256
            for class_set in sample_axis.class_sets:
                output_elements += len(class_set.values)
                output_bytes += 192 * len(class_set.values) + 512 * len(class_set.levels) + 256
    first_axis = members[0].dataset.feature_axis if members else None
    if first_axis is not None and first_axis.values is not None:
        observed = np.asarray(first_axis.values)
        output_elements += int(observed.size)
        output_bytes += int(observed.nbytes) + 128
    if members:
        for axis in members[0].dataset.inner_axes.values():
            if axis.values is not None:
                observed = np.asarray(axis.values)
                output_elements += int(observed.size)
                output_bytes += int(observed.nbytes) + 128
    member_metadata = [
        {
            "file_name": member.file_name,
            "title": member.dataset.title,
            "metadata": member.dataset.meta,
            "descriptive": member.dataset.descriptive.model_dump(mode="python"),
            "source_identity": member.dataset.source_identity.model_dump(mode="python"),
            "source_history": member.dataset.source_history.model_dump(mode="python"),
            "layout": member.dataset.layout.model_dump(mode="python"),
            # The emitted digest is a fixed 64-byte string.  Do not compute it
            # during budget projection: resource refusal must precede any
            # complete scientific projection or output construction.
            "scientific_digest": "0" * 64,
        }
        for member in members
    ]
    first = members[0].dataset if members else None
    copied_state = (
        [
            first.feature_axis.model_dump(mode="python", exclude={"values"}) if first.feature_axis else None,
            {dim: axis.model_dump(mode="python", exclude={"values"}) for dim, axis in first.inner_axes.items()},
            first.target_context.model_dump(mode="python"),
            first.domain.model_dump(mode="python"),
            first.quality.model_dump(mode="python"),
            [entry for member in members for entry in member.dataset.provenance.to_list()],
            member_metadata,
        ]
        if first is not None
        else []
    )
    copied_elements, copied_bytes = _retained_state_footprint(copied_state)
    output_elements += copied_elements
    output_bytes += copied_bytes
    output_bytes += 128 * total_samples
    return input_elements + output_elements, input_bytes + output_bytes


def require_collection_budget(members: Sequence[CollectionMember]) -> None:
    """Bound retained datasets and the complete concatenation projection."""

    collection_manifest(members)
    elements, retained_bytes = collection_retained_footprint(members)
    if elements > MAX_COLLECTION_RETAINED_ELEMENTS:
        raise ValueError("scientific collection exceeds the decoded-element limit")
    if retained_bytes > MAX_COLLECTION_RETAINED_BYTES:
        raise ValueError("scientific collection exceeds the 256 MiB retained-data limit")


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _sample_table(dataset: SherpaDataset) -> Mapping[str, list[Any]] | None:
    axis = dataset.sample_axis
    return axis.sample_table if axis is not None else None


def _collection_layout_semantics(dataset: SherpaDataset) -> dict[str, Any]:
    """Normalize only the sample extent while retaining every layout fact."""

    layout = dataset.layout.model_dump(
        mode="json",
        exclude={"source_shape", "original_unfolded_shape"},
        exclude_none=False,
    )
    layout["source_shape_tail"] = list(dataset.layout.source_shape[1:]) if dataset.layout.source_shape else None
    layout["original_unfolded_shape_tail"] = (
        list(dataset.layout.original_unfolded_shape[1:]) if dataset.layout.original_unfolded_shape else None
    )
    return layout


_SAMPLE_ALIGNED_FIELDS = frozenset(
    {
        "values",
        "labels",
        "include_mask",
        "alternate_scales",
        "alternate_label_sets",
        "class_sets",
        "classes",
        "exclusion_reasons",
        "sample_table",
    }
)


def _sample_axis_semantics(axis: SampleAxis) -> dict[str, Any]:
    """Return the non-aligned identity that every concatenated axis must share."""

    return axis.model_dump(mode="json", exclude=_SAMPLE_ALIGNED_FIELDS, exclude_none=False)


def _axis_set_semantics(axis: SampleAxis) -> dict[str, list[dict[str, Any]]]:
    """Return named-set definitions without their per-sample values."""

    return {
        "alternate_scales": [item.model_dump(mode="json", exclude={"values"}) for item in axis.alternate_scales],
        "alternate_label_sets": [
            item.model_dump(mode="json", exclude={"values"}) for item in axis.alternate_label_sets
        ],
        "class_sets": [item.model_dump(mode="json", exclude={"values", "levels"}) for item in axis.class_sets],
    }


def _concatenated_sample_axis(
    datasets: Sequence[SherpaDataset],
    *,
    labels: list[str],
    include_mask: list[bool],
    exclusion_reasons: list[str | None],
    combined_table: dict[str, list[Any]] | None,
) -> SampleAxis:
    """Concatenate every aligned SampleAxis field through one closed authority."""

    first = datasets[0].sample_axis
    assert first is not None
    axes = [dataset.sample_axis for dataset in datasets]
    assert all(axis is not None for axis in axes)
    typed_axes = [axis for axis in axes if axis is not None]

    def concat_optional_array(field: str) -> np.ndarray | None:
        values = [getattr(axis, field) for axis in typed_axes]
        if values[0] is None:
            return None
        return np.concatenate([np.asarray(value) for value in values])

    alternate_scales = tuple(
        AxisScaleSet.model_validate(
            {
                **first_set.model_dump(mode="python", exclude={"values"}),
                "values": np.concatenate([np.asarray(axis.alternate_scales[index].values) for axis in typed_axes]),
            }
        )
        for index, first_set in enumerate(first.alternate_scales)
    )
    alternate_label_sets = tuple(
        AxisLabelSet.model_validate(
            {
                **first_set.model_dump(mode="python", exclude={"values"}),
                "values": tuple(value for axis in typed_axes for value in axis.alternate_label_sets[index].values),
            }
        )
        for index, first_set in enumerate(first.alternate_label_sets)
    )
    combined_class_sets: list[AxisClassSet] = []
    for index, first_set in enumerate(first.class_sets):
        levels: dict[tuple[str, object], Any] = {}
        for axis in typed_axes:
            for level in axis.class_sets[index].levels:
                identity = lossless_scalar_identity(level.code)
                existing = levels.get(identity)
                if existing is not None and existing != level:
                    raise ValueError("collection sample class levels assign conflicting labels to one typed code")
                levels[identity] = level
        combined_class_sets.append(
            AxisClassSet.model_validate(
                {
                    **first_set.model_dump(mode="python", exclude={"values", "levels"}),
                    "values": tuple(value for axis in typed_axes for value in axis.class_sets[index].values),
                    "levels": tuple(levels.values()),
                }
            )
        )
    class_sets = tuple(combined_class_sets)
    return SampleAxis(
        values=concat_optional_array("values"),
        labels=labels,
        units=first.units,
        title=first.title,
        include_mask=np.asarray(include_mask, dtype=bool),
        primary_scale_name=first.primary_scale_name,
        alternate_scales=alternate_scales,
        primary_label_name=first.primary_label_name,
        alternate_label_sets=alternate_label_sets,
        primary_title_name=first.primary_title_name,
        alternate_title_sets=first.alternate_title_sets,
        class_sets=class_sets,
        primary_class_set_name=first.primary_class_set_name,
        classes=concat_optional_array("classes"),
        exclusion_reasons=exclusion_reasons,
        sample_table=combined_table,
    )


def _require_axis_compatibility(
    dataset: SherpaDataset,
    *,
    first: SherpaDataset,
    member_name: str,
    reference_axis: np.ndarray | None,
    feature_semantics: Mapping[str, Any],
    reference_inner_axes: Mapping[int, Any],
    sample_semantics: Mapping[str, Any],
    sample_set_semantics: Mapping[str, Any],
) -> None:
    axis = dataset.feature_axis
    sample_axis = dataset.sample_axis
    if axis is None or sample_axis is None:
        raise ValueError(f"collection member {member_name!r} lacks typed axes")
    if type(axis) is not type(first.feature_axis):
        raise ValueError(f"collection member {member_name!r} has incompatible feature-axis type")
    first_axis = first.feature_axis
    assert first_axis is not None
    if (axis.values is None) != (reference_axis is None):
        raise ValueError(f"collection member {member_name!r} has incompatible feature-axis coordinates")
    reference_semantics = axis_semantics(
        axis_class=type(first_axis).__name__,
        title=first_axis.title,
        units=first_axis.units,
        quantity=first_axis.quantity,
    )
    observed_semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=axis.title,
        units=axis.units,
        quantity=axis.quantity,
    )
    try:
        require_compatible_axis_semantics(
            reference_semantics,
            observed_semantics,
            context=f"collection member {member_name!r}",
            require_quantity=any(
                value is not None
                for value in (
                    reference_semantics.quantity,
                    reference_semantics.units,
                    observed_semantics.quantity,
                    observed_semantics.units,
                )
            ),
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if reference_axis is not None:
        observed_axis = np.asarray(axis.values)
        if observed_axis.dtype != reference_axis.dtype or not np.array_equal(observed_axis, reference_axis):
            guidance = (
                "; use preprocess.wavenumber_align with an explicit reference grid before collection assembly"
                if reference_semantics.quantity is AxisQuantity.WAVENUMBER
                else ""
            )
            raise ValueError(f"collection member {member_name!r} does not have the exact feature-axis grid{guidance}")
    if (
        axis.model_dump(
            mode="json",
            exclude={"values", "title", "display_units", "units", "quantity"},
            exclude_none=False,
        )
        != feature_semantics
    ):
        raise ValueError(f"collection member {member_name!r} has incompatible feature-axis semantics")
    if _text(sample_axis.title) != _text(first.sample_axis.title) or _text(sample_axis.units) != _text(
        first.sample_axis.units
    ):
        raise ValueError(f"collection member {member_name!r} has incompatible sample-axis semantics")
    if _sample_axis_semantics(sample_axis) != sample_semantics:
        raise ValueError(f"collection member {member_name!r} has incompatible sample-axis semantics")
    if _axis_set_semantics(sample_axis) != sample_set_semantics:
        raise ValueError(f"collection member {member_name!r} has incompatible sample-axis set definitions")
    if np.asarray(dataset.X).shape[1:] != np.asarray(first.X).shape[1:]:
        raise ValueError(f"collection member {member_name!r} has incompatible inner dimensions")
    observed_inner_axes = dataset.inner_axes
    if set(observed_inner_axes) != set(reference_inner_axes):
        raise ValueError(f"collection member {member_name!r} has incompatible inner axes")
    for dim, reference_inner_axis in reference_inner_axes.items():
        observed_inner_axis = observed_inner_axes[dim]
        if type(observed_inner_axis) is not type(reference_inner_axis):
            raise ValueError(f"collection member {member_name!r} has incompatible inner-axis type")
        reference_inner_values = reference_inner_axis.values
        observed_inner_values = observed_inner_axis.values
        if (reference_inner_values is None) != (observed_inner_values is None):
            raise ValueError(f"collection member {member_name!r} has incompatible inner-axis values")
        if reference_inner_values is not None:
            reference_inner_array = np.asarray(reference_inner_values)
            observed_inner_array = np.asarray(observed_inner_values)
            if observed_inner_array.dtype != reference_inner_array.dtype or not np.array_equal(
                observed_inner_array, reference_inner_array
            ):
                raise ValueError(f"collection member {member_name!r} has incompatible inner-axis values")
        if observed_inner_axis.model_dump(
            mode="json", exclude={"values"}, exclude_none=False
        ) != reference_inner_axis.model_dump(mode="json", exclude={"values"}, exclude_none=False):
            raise ValueError(f"collection member {member_name!r} has incompatible inner-axis semantics")


def _require_dataset_semantics(
    dataset: SherpaDataset,
    *,
    first: SherpaDataset,
    member_name: str,
    target_present: bool,
    target_context: Mapping[str, Any],
    domain: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> None:
    if _text(dataset.units) != _text(first.units) or dataset.data_role != first.data_role:
        raise ValueError(f"collection member {member_name!r} has incompatible signal semantics")
    if dataset.backend != first.backend:
        raise ValueError(f"collection member {member_name!r} has incompatible backend semantics")
    if dataset.domain.model_dump(mode="json", exclude_none=False) != domain:
        raise ValueError(f"collection member {member_name!r} has incompatible domain semantics")
    if (dataset.target is not None) != target_present:
        raise ValueError("collection cannot mix target-bearing and target-free members")
    if dataset.target_context.model_dump(mode="json", exclude_none=False) != target_context:
        raise ValueError(f"collection member {member_name!r} has incompatible target semantics")
    if dataset.quality.model_dump(mode="json", exclude_none=False) != quality:
        raise ValueError(f"collection member {member_name!r} has incompatible quality semantics")
    if dataset.is_time_series != first.is_time_series:
        raise ValueError(f"collection member {member_name!r} has incompatible time-series semantics")
    if _collection_layout_semantics(dataset) != _collection_layout_semantics(first):
        raise ValueError(f"collection member {member_name!r} has incompatible layout semantics")


def assemble_collection(
    members: Sequence[CollectionMember],
    *,
    title: str,
    dataset_id: str | None = None,
) -> SherpaDataset:
    """Strictly concatenate compatible datasets without inferring or dropping science."""

    require_collection_budget(members)
    first = members[0].dataset
    if first.feature_axis is None or first.sample_axis is None:
        raise ValueError(f"collection member {members[0].file_name!r} lacks typed axes")
    if first.feature_axis.values is None:
        labels = first.feature_axis.labels
        if (
            type(first.feature_axis) is not FeatureAxis
            or labels is None
            or len(labels) != np.asarray(first.X).shape[-1]
        ):
            raise ValueError(f"collection member {members[0].file_name!r} lacks typed axes")
        reference_axis = None
    else:
        reference_axis = np.asarray(first.feature_axis.values)
        if reference_axis.ndim != 1 or reference_axis.size < 2 or not np.all(np.isfinite(reference_axis)):
            raise ValueError(f"collection member {members[0].file_name!r} has an invalid feature axis")

    if len(members) == 1:
        # Preserve the native source, especially a rank-3 HSI cube and its
        # spatial layout. Concatenating a singleton allocates another complete
        # X matrix and turns an image into a generic batch.
        structured_scientific_projection(
            first.meta,
            field_name="collection member scientific metadata",
        )
        sample_axis = first.sample_axis
        assert sample_axis is not None
        validate_lossless_sample_table_wire(sample_axis.sample_table)
        if first.ndim == 2:
            labels = clean_sample_labels(
                sample_axis.labels,
                first.n_samples,
                fallback_prefix=Path(members[0].file_name).stem,
                source_name=members[0].file_name,
            )
            if len(set(labels)) != len(labels):
                raise ValueError("scientific collection contains duplicate sample identities")
        first.title = title
        if dataset_id is not None:
            first._dataset_id = dataset_id
        first.meta["source_collection"] = collection_manifest(members)
        return first

    reference_table = _sample_table(first)
    reference_inner_axes = first.inner_axes
    table_columns = tuple(reference_table) if reference_table is not None else ()
    datasets: list[SherpaDataset] = []
    labels: list[str] = []
    include_mask: list[bool] = []
    exclusion_reasons: list[str | None] = []
    combined_table: dict[str, list[Any]] | None = {column: [] for column in table_columns} if table_columns else None
    target_chunks: list[np.ndarray] = []
    target_present = first.target is not None
    target_shape = np.asarray(first.target).shape[1:] if target_present else ()
    target_dtype = np.asarray(first.target).dtype if target_present else None
    sample_values_present = first.sample_axis.values is not None
    sample_classes_present = first.sample_axis.classes is not None
    sample_values_dtype = np.asarray(first.sample_axis.values).dtype if sample_values_present else None
    sample_classes_dtype = np.asarray(first.sample_axis.classes).dtype if sample_classes_present else None
    target_context = first.target_context.model_dump(mode="json", exclude_none=False)
    domain = first.domain.model_dump(mode="json", exclude_none=False)
    feature_semantics = first.feature_axis.model_dump(
        mode="json",
        exclude={"values", "title", "display_units", "units", "quantity"},
        exclude_none=False,
    )
    quality = first.quality.model_dump(mode="json", exclude_none=False)
    sample_semantics = _sample_axis_semantics(first.sample_axis)
    sample_set_semantics = _axis_set_semantics(first.sample_axis)
    combined_provenance: list[dict[str, Any]] = []

    for member in members:
        dataset = member.dataset
        sample_axis = dataset.sample_axis
        _require_axis_compatibility(
            dataset,
            first=first,
            member_name=member.file_name,
            reference_axis=reference_axis,
            feature_semantics=feature_semantics,
            reference_inner_axes=reference_inner_axes,
            sample_semantics=sample_semantics,
            sample_set_semantics=sample_set_semantics,
        )
        assert sample_axis is not None
        _require_dataset_semantics(
            dataset,
            first=first,
            member_name=member.file_name,
            target_present=target_present,
            target_context=target_context,
            domain=domain,
            quality=quality,
        )
        observed_table = _sample_table(dataset)
        if (observed_table is None) != (reference_table is None):
            raise ValueError("collection cannot mix sample-table-bearing and sample-table-free members")
        if observed_table is not None:
            if tuple(observed_table) != table_columns:
                raise ValueError(f"collection member {member.file_name!r} has incompatible sample-table columns")
            assert combined_table is not None
            for column in table_columns:
                values = list(observed_table[column])
                if len(values) != dataset.n_samples:
                    raise ValueError(f"collection member {member.file_name!r} has a misaligned sample table")
                combined_table[column].extend(values)
        if (sample_axis.values is not None) != sample_values_present:
            raise ValueError("collection cannot mix sample-coordinate-bearing and coordinate-free members")
        if (sample_axis.classes is not None) != sample_classes_present:
            raise ValueError("collection cannot mix sample-class-bearing and class-free members")
        if sample_values_present and np.asarray(sample_axis.values).dtype != sample_values_dtype:
            raise ValueError(f"collection member {member.file_name!r} has incompatible sample-coordinate dtype")
        if sample_classes_present and np.asarray(sample_axis.classes).dtype != sample_classes_dtype:
            raise ValueError(f"collection member {member.file_name!r} has incompatible sample-class dtype")
        member_labels = clean_sample_labels(
            sample_axis.labels,
            dataset.n_samples,
            fallback_prefix=Path(member.file_name).stem,
            source_name=member.file_name,
        )
        labels.extend(member_labels)
        mask = sample_axis.include_mask
        include_mask.extend([True] * dataset.n_samples if mask is None else np.asarray(mask, dtype=bool).tolist())
        reasons = sample_axis.exclusion_reasons
        if reasons is None:
            exclusion_reasons.extend([None] * dataset.n_samples)
        elif len(reasons) != dataset.n_samples:
            raise ValueError(f"collection member {member.file_name!r} has misaligned exclusion reasons")
        else:
            exclusion_reasons.extend(reasons)
        if target_present:
            target = np.asarray(dataset.target)
            if target.shape[0] != dataset.n_samples:
                raise ValueError(f"collection member {member.file_name!r} has a misaligned target")
            if target.shape[1:] != target_shape:
                raise ValueError(f"collection member {member.file_name!r} has an incompatible target response shape")
            if target.dtype != target_dtype:
                raise ValueError(f"collection member {member.file_name!r} has an incompatible target dtype")
            target_chunks.append(target)
        combined_provenance.extend(dataset.provenance.to_list())
        datasets.append(dataset)

    member_science = [
        {
            "file_name": member.file_name,
            "title": member.dataset.title,
            "metadata": member.dataset.meta,
            "descriptive": member.dataset.descriptive.model_dump(mode="json", exclude_none=True),
            "source_identity": member.dataset.source_identity.model_dump(mode="json", exclude_none=True),
            "source_history": member.dataset.source_history.model_dump(mode="json", exclude_none=True),
            "layout": member.dataset.layout.model_dump(mode="json", exclude_none=True),
            "scientific_digest": member.dataset.scientific_digest,
        }
        for member in members
    ]
    structured_scientific_projection(
        member_science,
        field_name="collection member scientific metadata",
    )
    combined_X = np.concatenate([np.asarray(dataset.X) for dataset in datasets], axis=0)
    common_descriptive = (
        first.descriptive.model_copy(deep=True)
        if all(dataset.descriptive == first.descriptive for dataset in datasets[1:])
        else None
    )
    original_shapes = [dataset.layout.original_unfolded_shape for dataset in datasets]
    combined_original_shape = None
    if original_shapes[0] is not None:
        typed_original_shapes = [shape for shape in original_shapes if shape is not None]
        combined_original_shape = (
            sum(shape[0] for shape in typed_original_shapes),
            *typed_original_shapes[0][1:],
        )
    carries_extended_source = any(
        dataset.source_identity != DatasetSourceIdentity() or dataset.layout != DatasetLayoutContext()
        for dataset in datasets
    )
    collection_source_identity = (
        DatasetSourceIdentity(
            source_format="spectrasherpa.collection",
            storage_version="1",
            object_name=title,
        )
        if carries_extended_source
        else DatasetSourceIdentity()
    )
    collection_layout = (
        DatasetLayoutContext(
            kind="batch",
            source_type="scientific_collection",
            source_dtype=combined_X.dtype.str,
            source_shape=tuple(combined_X.shape),
            mode_roles=first.layout.mode_roles,
            image_size=first.layout.image_size,
            image_mode=first.layout.image_mode,
            image_include=first.layout.image_include,
            original_unfolded_shape=combined_original_shape,
        )
        if carries_extended_source
        else DatasetLayoutContext()
    )
    result = SherpaDataset(
        X=combined_X,
        feature_axis=first.feature_axis.model_copy(deep=True),
        axes=reference_inner_axes or None,
        sample_axis=_concatenated_sample_axis(
            datasets,
            labels=labels,
            include_mask=include_mask,
            exclusion_reasons=exclusion_reasons,
            combined_table=combined_table,
        ),
        target=np.concatenate(target_chunks, axis=0) if target_chunks else None,
        target_context=first.target_context.model_copy(deep=True),
        domain=first.domain.model_copy(deep=True),
        descriptive=common_descriptive,
        source_identity=collection_source_identity,
        layout=collection_layout,
        provenance=Provenance.from_list(combined_provenance),
        quality=first.quality.model_copy(deep=True),
        backend=first.backend,
        title=title,
        dataset_id=dataset_id,
        units=first.units,
        data_role=first.data_role,
        is_time_series=first.is_time_series,
        extra={
            "source_member_metadata": member_science,
        },
    )
    if len(set(labels)) != len(labels):
        raise ValueError("scientific collection contains duplicate sample identities")
    result.meta["source_collection"] = collection_manifest(members)
    return result


__all__ = [
    "MAX_COLLECTION_MEMBERS",
    "MAX_COLLECTION_RETAINED_BYTES",
    "MAX_COLLECTION_SOURCE_BYTES",
    "CollectionMember",
    "assemble_collection",
    "canonical_collection_file_name",
    "collection_retained_footprint",
    "collection_manifest",
    "dataset_retained_footprint",
    "lossless_sample_table_scalar",
    "prepared_data_digest",
    "require_collection_budget",
]
