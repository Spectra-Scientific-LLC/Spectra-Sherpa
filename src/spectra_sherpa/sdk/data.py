"""Dataset construction and lightweight readers for the public SDK."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa

_COLLECTION_MAX_MEMBERS = 1000
_COLLECTION_MAX_SOURCE_BYTES = 512 * 1024 * 1024


def _feature_axis_from_x(
    x: Any,
    *,
    n_features: int,
    units: str | None,
    title: str | None,
) -> FeatureAxis | None:
    if x is None:
        return None
    if isinstance(x, FeatureAxis):
        return x

    if isinstance(x, str):
        return SpectralAxis(labels=[str(i) for i in range(n_features)], units=units, title=x)

    values = np.asarray(x)
    if values.ndim != 1:
        raise ValueError(f"x must be a 1D feature axis, got {values.ndim}D")
    if values.shape[0] != n_features:
        raise ValueError(f"x must have {n_features} values, got {values.shape[0]}")
    if np.issubdtype(values.dtype, np.number):
        return SpectralAxis(values=values.astype(np.float64), units=units, title=title)
    return SpectralAxis(labels=[str(v) for v in values.tolist()], units=units, title=title)


def _sample_axis_from_samples(samples: Any, *, n_samples: int) -> SampleAxis | None:
    if samples is None:
        return None
    if isinstance(samples, SampleAxis):
        return samples

    values = np.asarray(samples)
    if values.ndim != 1:
        raise ValueError(f"samples must be a 1D sample axis, got {values.ndim}D")
    if values.shape[0] != n_samples:
        raise ValueError(f"samples must have {n_samples} entries, got {values.shape[0]}")
    if np.issubdtype(values.dtype, np.number):
        return SampleAxis(values=values.astype(np.float64), title="Sample")
    return SampleAxis(labels=[str(v) for v in values.tolist()], title="Sample")


def _target_context_for(
    y: Any,
    *,
    y_name: str | Sequence[str] | None,
    target_type: str | None,
    target_units: str | None,
) -> TargetContext | None:
    if y is None and y_name is None and target_type is None and target_units is None:
        return None
    if y_name is None:
        target_name = None
        target_names = None
    elif isinstance(y_name, str):
        target_name = y_name
        target_names = [y_name]
    else:
        target_names = [str(name) for name in y_name]
        target_name = target_names[0] if len(target_names) == 1 else None

    return TargetContext(
        target_type=target_type,
        target_name=target_name,
        target_names=target_names,
        target_units=target_units,
    )


def from_array(
    X: Any,
    *,
    x: Any = None,
    samples: Any = None,
    y: Any = None,
    y_name: str | Sequence[str] | None = None,
    target_type: str | None = None,
    target_units: str | None = None,
    technique: str | None = None,
    units: str | None = None,
    title: str | None = None,
    data_units: str | None = None,
    feature_axis: FeatureAxis | None = None,
    sample_axis: SampleAxis | None = None,
    extra: dict[str, Any] | None = None,
    data_role: str | None = None,
) -> SherpaDataset:
    """Create a :class:`SherpaDataset` from array-like data.

    ``X`` is interpreted as ``n_samples x n_features``. The ``x`` argument can
    be a feature-axis object, a 1D coordinate vector, a 1D label vector, or a
    string used as the feature-axis title. ``samples`` can be a sample-axis
    object, numeric sample coordinates, or sample labels.
    """
    arr = np.asarray(X, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError("X must be at least 1-dimensional, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    resolved_feature_axis = feature_axis or _feature_axis_from_x(
        x,
        n_features=arr.shape[-1],
        units=units,
        title=None,
    )
    resolved_sample_axis = sample_axis or _sample_axis_from_samples(samples, n_samples=arr.shape[0])
    target_context = _target_context_for(
        y,
        y_name=y_name,
        target_type=target_type,
        target_units=target_units,
    )

    return SherpaDataset(
        X=arr,
        feature_axis=resolved_feature_axis,
        sample_axis=resolved_sample_axis,
        target=y,
        target_context=target_context,
        domain=DomainContext(technique=technique),
        backend="numpy",
        title=title,
        units=data_units,
        extra=extra,
        data_role=data_role,
    )


def like(source: Any, data: Any, *, units: str | None = None, title: str | None = None) -> SherpaDataset:
    """Create a dataset like ``source`` with replaced numeric data."""
    return build_dataset_like(data, source, units=units, title=title)


def to_numpy(dataset: Any, *, copy: bool = True) -> np.ndarray:
    """Return a numpy array from a dataset or array-like object."""
    ds = coerce_to_sherpa(dataset, input_name="dataset", allow_array=True)
    arr = np.asarray(ds.data)
    return arr.copy() if copy else arr


def read_csv(
    path: str | Path,
    *,
    csv_layout: str | None = None,
    x: str | None = None,
    y: str | None = None,
    target_type: str | None = None,
    data_role: str | None = None,
) -> SherpaDataset:
    """Read a CSV through the same loader used by GUI data-source nodes.

    ``x`` is accepted as a caller-facing axis hint for the two-tier SDK API.
    Current behavior delegates axis inference to the central CSV loader so SDK
    and GUI imports stay aligned.
    """
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    prepared_overrides = {"csv_layout": csv_layout} if csv_layout is not None else None
    ds = load_canonical_file_as_sherpa(
        path,
        selected_target=y,
        target_type=target_type,
        prepared_overrides=prepared_overrides,
    )
    if data_role is not None:
        ds.data_role = data_role
    if y and ds.target is None:
        props = ds.get_extra("properties")
        if isinstance(props, dict) and y in props:
            target = np.asarray(props[y])
            # SherpaDataset target metadata is mutable by design; mirror GUI loader post-processing here.
            ds.target = target
            ds.target_context = TargetContext(
                target_type=target_type or ("categorical" if target.dtype.kind in ("O", "S", "U") else "continuous"),
                target_name=y,
                target_names=[y],
            )
            ds.meta["csv.target_column"] = y
            ds.meta["csv.target_type"] = ds.target_context.target_type
    if x and ds.feature_axis is not None and not ds.feature_axis.title:
        axis = ds.feature_axis
        axis.title = x
        ds.feature_axis = axis
    return ds


def read(
    path: str | Path,
    *,
    asset_id: str | None = None,
    y: str | None = None,
    target_type: str | None = None,
    prepared_overrides: Mapping[str, Any] | None = None,
    expected_ingestion_authority: Mapping[str, Any] | None = None,
) -> SherpaDataset:
    """Read one canonical portable source exactly as ``data.file_load`` does.

    ``prepared_overrides`` is the closed, data-free projection persisted by
    Data/Explore.  Applying it here keeps an exported workflow on the same
    axis, unit, and explicit-target authority as the Workbench source node;
    the exporter never reproduces those mutations as generated Python.
    """
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
    from spectra_sherpa.core.prepared_data import apply_dataset_prepared_data_overrides
    from spectra_sherpa.io.authority import verify_portable_ingestion_authority

    dataset = load_canonical_file_as_sherpa(
        path,
        asset_id=asset_id,
        selected_target=y,
        target_type=target_type,
        prepared_overrides=prepared_overrides,
    )
    if prepared_overrides:
        dataset = apply_dataset_prepared_data_overrides(dataset, prepared_overrides)
    if expected_ingestion_authority is not None:
        verify_portable_ingestion_authority(dataset, expected_ingestion_authority)
    return dataset


def read_collection(
    members: Sequence[Mapping[str, Any]],
    *,
    title: str,
    collection_definition: Mapping[str, Any] | None = None,
    selected_target: str | None = None,
    target_type: str | None = None,
    group_column: str | None = None,
    expected_source_manifest_sha256: str | None = None,
    expected_collection_definition_sha256: str | None = None,
    expected_scientific_collection_sha256: str | None = None,
) -> SherpaDataset:
    """Rebuild an exported collection from explicit relocatable file references.

    Every member is size/digest checked before parsing. Registered references
    are rematerialized through their reviewed projection identity; ordinary
    customer files use the same native reader as :func:`read`. The optional
    collection definition preserves exported labels, annotations, targets,
    and validation groups without embedding source spectra in the workflow.
    """

    from spectra_sherpa.app.lib.collection_assembly import (
        CollectionMember,
        assemble_collection,
        prepared_data_digest,
    )
    from spectra_sherpa.app.lib.collection_definition import (
        apply_collection_definition,
        project_collection_definition,
        scientific_collection_identity,
        validate_collection_definition,
    )
    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
    from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision
    from spectra_sherpa.core.prepared_data import apply_dataset_prepared_data_overrides
    from spectra_sherpa.io.authority import verify_portable_ingestion_authority

    if not isinstance(title, str) or not title.strip():
        raise ValueError("collection title must be non-empty text")
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
        raise ValueError("collection members must be an ordered sequence")
    if not members or len(members) > _COLLECTION_MAX_MEMBERS:
        raise ValueError(f"collection must contain 1 to {_COLLECTION_MAX_MEMBERS} members")
    loaded: list[CollectionMember] = []
    total_source_bytes = 0
    seen_file_names: set[str] = set()
    for raw in members:
        if not isinstance(raw, Mapping):
            raise ValueError("collection source member must be an object")
        path = Path(str(raw.get("path") or "")).expanduser()
        file_name = str(raw.get("file_name") or "")
        expected_size = raw.get("byte_length")
        expected_sha256 = raw.get("sha256")
        asset_id = str(raw.get("asset_id") or "single-auto")
        overrides = raw.get("prepared_overrides")
        expected_ingestion_authority = raw.get("expected_ingestion_authority")
        external = raw.get("external_reference")
        if (
            not path.is_file()
            or path.is_symlink()
            or not file_name
            or file_name in seen_file_names
            or isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256)
            or not isinstance(overrides, Mapping)
            or (expected_ingestion_authority is not None and not isinstance(expected_ingestion_authority, Mapping))
        ):
            raise ValueError("collection source member identity is invalid")
        seen_file_names.add(file_name)
        total_source_bytes += expected_size
        if total_source_bytes > _COLLECTION_MAX_SOURCE_BYTES:
            raise ValueError("collection exceeds the 512 MiB source limit")
        source_bytes = path.read_bytes()
        if len(source_bytes) != expected_size or hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
            raise ValueError(f"collection source changed before parsing: {file_name}")
        if external is not None:
            if not isinstance(external, Mapping) or not isinstance(external.get("projection_id"), str):
                raise ValueError("registered collection member identity is invalid")
            materialized = materialize_reference_member(path, str(external["projection_id"]))
            if dict(materialized.portable_reference) != dict(external):
                raise ValueError("registered collection member authority changed")
            dataset = apply_dataset_prepared_data_overrides(materialized.dataset, overrides)
            if expected_ingestion_authority is not None:
                verify_portable_ingestion_authority(dataset, expected_ingestion_authority)
            effective_asset_id = str(external["projection_id"])
        else:
            dataset = read(
                path,
                asset_id=None if asset_id == "single-auto" else asset_id,
                prepared_overrides=overrides,
                expected_ingestion_authority=expected_ingestion_authority,
            )
            effective_asset_id = asset_id
        loaded.append(
            CollectionMember(
                dataset=dataset,
                file_name=file_name,
                size_bytes=expected_size,
                sha256=expected_sha256,
                prepared_data_sha256=prepared_data_digest(overrides),
                asset_id=effective_asset_id,
            )
        )

    definition = validate_collection_definition(collection_definition) if collection_definition is not None else None
    if definition is not None:
        definition = project_collection_definition(definition, loaded)
        dataset = apply_collection_definition(loaded, definition)
    else:
        dataset = assemble_collection(loaded, title=title.strip())
    source_manifest = dataset.meta.get("source_collection")
    if not isinstance(source_manifest, dict):
        raise ValueError("exported collection omitted its source identity")
    identity = scientific_collection_identity(source_manifest, definition, dataset)
    source_manifest.update(identity)
    expected_pairs = (
        ("source manifest", expected_source_manifest_sha256, source_manifest.get("manifest_digest")),
        ("collection definition", expected_collection_definition_sha256, identity["collection_definition_sha256"]),
        ("scientific collection", expected_scientific_collection_sha256, identity["scientific_collection_sha256"]),
    )
    for name, expected, observed in expected_pairs:
        if expected not in {None, ""} and expected != observed:
            raise ValueError(f"exported collection {name} does not match its workflow authority")
    if selected_target:
        dataset = attach_sample_table_supervision(
            dataset,
            target_type=str(target_type or ""),
            target_column=selected_target,
            group_column=str(group_column or "") or None,
            node_id="exported-collection-load",
        )
    elif target_type or group_column:
        raise ValueError("collection target type and group require selected_target")
    return dataset


def read_registered_reference(
    path: str | Path,
    *,
    projection_id: str,
    prepared_overrides: Mapping[str, Any] | None = None,
    expected_ingestion_authority: Mapping[str, Any] | None = None,
) -> SherpaDataset:
    """Materialize one exact user-acquired registered-reference projection."""

    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
    from spectra_sherpa.core.prepared_data import apply_dataset_prepared_data_overrides
    from spectra_sherpa.io.authority import verify_portable_ingestion_authority

    materialized = materialize_reference_member(Path(path), projection_id)
    dataset = apply_dataset_prepared_data_overrides(materialized.dataset, prepared_overrides or {})
    context = dataset.target_context
    if context.selected_target is not None and dataset.sample_axis is not None and dataset.sample_axis.sample_table:
        if context.target_type not in {"continuous", "categorical"}:
            raise ValueError("registered reference selected target requires an explicit response type")
        # Selection changes the scientific projection. Bind it through the
        # same annotation authority used by the application, not a stale
        # unselected collection digest or a freshly trusted arbitrary table.
        from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision

        dataset = attach_sample_table_supervision(
            dataset,
            target_column=context.selected_target,
            target_type=context.target_type,
            node_id="registered-reference-selection",
        )
    if expected_ingestion_authority is not None:
        verify_portable_ingestion_authority(dataset, expected_ingestion_authority)
    return dataset


__all__ = [
    "from_array",
    "like",
    "to_numpy",
    "read_csv",
    "read",
    "read_collection",
    "read_registered_reference",
]
