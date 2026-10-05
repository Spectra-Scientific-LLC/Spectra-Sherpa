"""Specialized data loader nodes for experiment files and file groups.

Contains the registered ``data.load_group`` node and the strict experiment
collection reader shared by Workbench preview and model-application services.
Project workflows bind the same ordered source manifest through the registered
node; no second collection assembler is admitted.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib import collection_assembly as collection_assembly_contract
from spectra_sherpa.app.lib import collection_definition as collection_definition_contract
from spectra_sherpa.app.lib import sample_labels as sample_labels_contract
from spectra_sherpa.app.lib.collection_assembly import (
    CollectionMember,
    assemble_collection,
    dataset_retained_footprint,
    prepared_data_digest,
    require_collection_budget,
)
from spectra_sherpa.app.lib.collection_definition import (
    apply_collection_definition,
    project_collection_definition,
    scientific_collection_identity,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    copy_registered_reference_collection_extras,
    registered_reference_collection_identity,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_authority import verify_target_authority
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import spectra_meta as spectra_meta_contract
from spectra_sherpa.core.execution_runtime import DatasetSourceResolver
from spectra_sherpa.core.prepared_data import (
    apply_dataset_prepared_data_overrides,
    parser_options_for_prepared_data,
)
from spectra_sherpa.core.spectra_meta import (
    DataProvenance,
    SourceType,
    SpectraMeta,
    set_spectra_meta,
)
from spectra_sherpa.core.target_authority import admit_target_authority
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.io import registry as ingestion_registry_contract
from spectra_sherpa.io.types import ParserLimits, SourceMember

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from . import source_contracts
from .source_contracts import file_manifest

logger = logging.getLogger(__name__)

_LOAD_GROUP_MAX_FILES = 512
_LOAD_GROUP_MAX_SOURCE_BYTES = 512 * 1024 * 1024
_LOAD_GROUP_MAX_DECODED_ELEMENTS = 32_000_000
_LOAD_GROUP_MAX_DECODED_BYTES = 256 * 1024 * 1024
_LOAD_GROUP_PARSER_LIMITS = ParserLimits()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_load_group_parameters(
    parameters: dict[str, object], *, allow_incomplete: bool = False
) -> dict[str, object]:
    """Validate the closed local-folder or project-collection source grammar."""

    projected = dict(parameters)
    source_mode = projected.get("source_mode", "local_folder")
    if source_mode not in {"local_folder", "experiment_collection"}:
        raise ValueError("source_mode is not admitted")
    projected["source_mode"] = source_mode
    for name in (
        "folder_path",
        "pattern",
        "group_title",
        "asset_id",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
    ):
        value = projected.get(name)
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text")
        projected[name] = value.strip()
    if not isinstance(projected.get("recursive"), bool):
        raise ValueError("recursive must be boolean")
    if projected.get("sort_by") not in {"filename", "numeric_suffix"}:
        raise ValueError("sort_by is not admitted")
    if source_mode == "local_folder":
        if not projected["folder_path"] and not allow_incomplete:
            raise ValueError("folder_path is required for local_folder mode")
        if not projected["pattern"] and not allow_incomplete:
            raise ValueError("pattern is required for local_folder mode")
        projected["experiment_id"] = None
        projected["stage"] = "raw"
        projected["source_manifest_sha256"] = ""
        projected["collection_definition_sha256"] = ""
        projected["scientific_collection_sha256"] = ""
        return projected

    if projected["folder_path"]:
        raise ValueError("folder_path is not admitted for experiment_collection mode")
    experiment_id = projected.get("experiment_id")
    if not (allow_incomplete and experiment_id is None) and (
        not isinstance(experiment_id, int) or isinstance(experiment_id, bool) or experiment_id < 1
    ):
        raise ValueError("experiment_id must be a positive integer")
    if projected.get("stage") not in {"raw", "preprocessed", "synthetic"}:
        raise ValueError("stage is not admitted")
    if not projected["asset_id"] and not allow_incomplete:
        raise ValueError("asset_id is required for experiment_collection mode")
    digest = str(projected["source_manifest_sha256"])
    if not (allow_incomplete and not digest) and (
        len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise ValueError("source_manifest_sha256 must be lowercase SHA-256 hex")
    for name in ("collection_definition_sha256", "scientific_collection_sha256"):
        digest = str(projected[name])
        if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError(f"{name} must be empty or lowercase SHA-256 hex")
    if (
        projected["collection_definition_sha256"]
        and not projected["scientific_collection_sha256"]
        and not allow_incomplete
    ):
        raise ValueError("scientific_collection_sha256 is required when a collection definition is bound")
    projected["pattern"] = ""
    projected["recursive"] = False
    projected["sort_by"] = "filename"
    return projected


def _draft_load_group_parameters(parameters: dict[str, object]) -> dict[str, object]:
    return _canonical_load_group_parameters(parameters, allow_incomplete=True)


def _canonical_collection_load_parameters(parameters: dict[str, object]) -> dict[str, object]:
    projected = dict(parameters)
    projected.setdefault("dataset_view_id", None)
    projected.setdefault("dataset_view_sha256", "")
    experiment_id = projected.get("experiment_id")
    if not isinstance(experiment_id, int) or isinstance(experiment_id, bool) or experiment_id < 1:
        raise ValueError("experiment_id must be a positive integer")
    if projected.get("stage") not in {"raw", "preprocessed", "synthetic"}:
        raise ValueError("stage is not admitted")
    for name in (
        "group_title",
        "asset_id",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "group_column",
        "dataset_view_sha256",
    ):
        value = projected.get(name)
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text")
        projected[name] = value.strip()
    selected_file_ids = projected.get("selected_file_ids", [])
    if not isinstance(selected_file_ids, list) or not all(isinstance(value, str) for value in selected_file_ids):
        raise ValueError("selected_file_ids must be a list of positive integer strings")
    if any(not value.isdigit() or int(value) < 1 for value in selected_file_ids):
        raise ValueError("selected_file_ids must be a list of positive integer strings")
    if len(set(selected_file_ids)) != len(selected_file_ids):
        raise ValueError("selected_file_ids may not contain duplicates")
    projected["selected_file_ids"] = selected_file_ids
    source_digest = str(projected["source_manifest_sha256"])
    if len(source_digest) != 64 or any(ch not in "0123456789abcdef" for ch in source_digest):
        raise ValueError("source_manifest_sha256 must be lowercase SHA-256 hex")
    for name in ("collection_definition_sha256", "scientific_collection_sha256"):
        digest = str(projected[name])
        if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError(f"{name} must be empty or lowercase SHA-256 hex")
    if projected["collection_definition_sha256"] and not projected["scientific_collection_sha256"]:
        raise ValueError("scientific_collection_sha256 is required when a collection definition is bound")
    authority = admit_target_authority(projected.get("target_authority"))
    projected["target_authority"] = authority.canonical_dict() if authority is not None else None
    if projected["group_column"] and authority is None:
        raise ValueError("group_column requires target_authority")
    dataset_view_id = projected.get("dataset_view_id")
    dataset_view_digest = projected["dataset_view_sha256"]
    if dataset_view_id is not None and (
        not isinstance(dataset_view_id, int) or isinstance(dataset_view_id, bool) or dataset_view_id < 1
    ):
        raise ValueError("dataset_view_id must be a positive integer")
    if (dataset_view_id is None) != (not dataset_view_digest):
        raise ValueError("dataset_view_id and dataset_view_sha256 must be paired")
    if dataset_view_digest and (
        len(dataset_view_digest) != 64 or any(ch not in "0123456789abcdef" for ch in dataset_view_digest)
    ):
        raise ValueError("dataset_view_sha256 must be lowercase SHA-256 hex")
    return projected


def _coordinate_text(coordinate: object, attribute: str) -> str:
    value = getattr(coordinate, attribute, None)
    return str(value).strip() if value is not None else ""


@dataclass
class _LoadedDataset:
    dataset: Any
    file_name: str
    file_path: str | None = None
    embedded_target_names: list[str] | None = None
    embedded_target_data: np.ndarray | None = None
    embedded_target_units: str | None = None
    ground_truth_spectra: np.ndarray | None = None
    ground_truth_spectra_names: list[str] | None = None
    ground_truth_spectra_units: list[str] | str | None = None
    ground_truth_spectra_x: np.ndarray | None = None
    ground_truth_spectra_x_title: str | None = None
    ground_truth_spectra_x_units: str | None = None
    prepared_overrides: Mapping[str, object] | None = None
    source_members: tuple[SourceMember, ...] = ()
    selected_asset_id: str = "single-auto"


def _retained_numeric_footprint(dataset: SherpaDataset) -> tuple[int, int]:
    """Delegate retained-state charging to the shared collection authority."""

    return dataset_retained_footprint(dataset)


class ExperimentDatasetReader:
    """Strict reader for one exact project-owned experiment collection."""

    def __init__(
        self,
        node_id: str,
        parameters: dict[str, Any],
        *,
        source_resolver: DatasetSourceResolver | None = None,
    ) -> None:
        self.node_id = node_id
        self.parameters = dict(parameters)
        self.source_resolver = source_resolver

    async def execute(self, *args) -> Any:
        """Admit every member and concatenate only through the shared authority."""
        del args
        dataset_id = self.parameters.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id is required")
        if self.source_resolver is None:
            raise ValueError("experiment collection resolution capability is unavailable")
        stage = str(self.parameters.get("stage") or "raw")
        asset_id = _optional_text(self.parameters.get("asset_id"))
        collection = await self.source_resolver.resolve_experiment_collection(
            experiment_id=int(dataset_id),
            stage=stage,
        )
        selected_file_ids = [int(value) for value in self.parameters.get("selected_file_ids", [])]
        if selected_file_ids:
            selected = set(selected_file_ids)
            available = {source.file_id for source in collection.files}
            if selected.difference(available):
                raise ValueError("selected experiment file is outside the admitted collection")
            collection = collection.__class__(
                experiment_id=collection.experiment_id,
                experiment_name=collection.experiment_name,
                files=tuple(source for source in collection.files if source.file_id in selected),
                collection_definition_bytes=collection.collection_definition_bytes,
                preloaded_dataset=(collection.preloaded_dataset if selected == available else None),
                preloaded_asset_id=collection.preloaded_asset_id,
            )
        exp_name = collection.experiment_name
        if collection.preloaded_dataset is not None:
            if (
                asset_id is not None
                and collection.preloaded_asset_id is not None
                and asset_id != collection.preloaded_asset_id
            ):
                raise ValueError("preloaded collection asset differs from the admitted trial asset")
            result = copy.deepcopy(collection.preloaded_dataset)
            source_collection = result.meta.get("source_collection")
            if not isinstance(source_collection, dict):
                raise ValueError("preloaded collection omitted its exact source identity")
            expected_manifest = _optional_text(self.parameters.get("source_manifest_sha256"))
            expected_definition = _optional_text(self.parameters.get("collection_definition_sha256"))
            expected_scientific = _optional_text(self.parameters.get("scientific_collection_sha256"))
            if expected_manifest is not None and source_collection.get("manifest_digest") != expected_manifest:
                raise ValueError(
                    "experiment collection does not match its saved source manifest; "
                    "source membership changed after binding, so re-import the dataset or rebind the workflow"
                )
            if (
                expected_definition is not None
                and source_collection.get("collection_definition_sha256") != expected_definition
            ):
                raise ValueError(
                    "experiment collection does not match its saved collection definition; "
                    "collection metadata changed after binding, so re-import the dataset or rebind the workflow"
                )
            if (
                expected_scientific is not None
                and source_collection.get("scientific_collection_sha256") != expected_scientific
            ):
                raise ValueError(
                    "experiment collection does not match its saved scientific identity; "
                    "parsed data or scientific metadata changed after binding, so re-import the dataset "
                    "or rebind the workflow"
                )
            result = self._apply_node_target_selection(result)
            add_processing_step(
                result,
                "spectrasherpa.experiment_dataset_read/2",
                {
                    **self._processing_parameters(
                        dataset_id=int(dataset_id),
                        file_count=len(collection.files),
                        dataset=result,
                    ),
                    "stage": stage,
                    "asset_id": asset_id,
                    "source_manifest_sha256": str(source_collection.get("manifest_digest") or ""),
                    "collection_definition_sha256": source_collection.get("collection_definition_sha256"),
                    "scientific_collection_sha256": source_collection.get("scientific_collection_sha256"),
                },
                node_id=self.node_id,
            )
            return {"default": result, "target": result.target}
        if not collection.files:
            raise ValueError(f"No files found in dataset '{exp_name}' for stage {stage!r}.")
        if len(collection.files) > _LOAD_GROUP_MAX_FILES:
            raise ValueError(f"experiment collection exceeds the {_LOAD_GROUP_MAX_FILES}-file limit")
        if any(source.size_bytes is None for source in collection.files):
            raise ValueError("experiment collection resolver omitted exact source sizes")
        total_source_bytes = sum(int(source.size_bytes) for source in collection.files if source.size_bytes is not None)
        if total_source_bytes > _LOAD_GROUP_MAX_SOURCE_BYTES:
            raise ValueError("experiment collection exceeds the 512 MiB source limit")

        loaded: list[_LoadedDataset] = []
        members: list[CollectionMember] = []
        retained_elements = 0
        retained_bytes = 0
        for source in collection.files:
            item = self._load_file(
                source.path,
                file_name=source.original_file_path,
                asset_id=asset_id,
                prepared_overrides=source.prepared_overrides,
            )
            if len(item.source_members) != 1:
                raise ValueError(
                    f"Registry result for {source.original_file_path!r} must identify exactly one source member"
                )
            observed = item.source_members[0]
            if source.size_bytes is not None and observed.size_bytes != source.size_bytes:
                raise ValueError(f"Collection member {source.original_file_path!r} changed during admission")
            if source.sha256 is not None and observed.sha256 != source.sha256:
                raise ValueError(f"Collection member {source.original_file_path!r} changed during admission")
            next_elements, next_bytes = _retained_numeric_footprint(item.dataset)
            retained_elements += next_elements
            retained_bytes += next_bytes
            if retained_elements > _LOAD_GROUP_MAX_DECODED_ELEMENTS:
                raise ValueError("experiment collection exceeds the decoded-element limit")
            if retained_bytes > _LOAD_GROUP_MAX_DECODED_BYTES:
                raise ValueError("experiment collection exceeds the decoded-byte limit")
            loaded.append(item)
            members.append(
                CollectionMember(
                    dataset=item.dataset,
                    file_name=source.original_file_path,
                    size_bytes=observed.size_bytes,
                    sha256=observed.sha256,
                    prepared_data_sha256=prepared_data_digest(source.prepared_overrides),
                    asset_id=item.selected_asset_id,
                )
            )
            require_collection_budget(members)

        definition = (
            validate_collection_definition(json.loads(collection.collection_definition_bytes))
            if collection.collection_definition_bytes is not None
            else None
        )
        if definition is not None and selected_file_ids:
            definition = project_collection_definition(definition, members)
        result = (
            apply_collection_definition(members, definition)
            if definition is not None
            else assemble_collection(
                members,
                title=exp_name if len(members) == 1 else f"{exp_name} ({len(members)} files)",
            )
        )
        if definition is None and len(loaded) == 1:
            copy_registered_reference_collection_extras(
                loaded[0].dataset,
                result,
                selected_asset_id=loaded[0].selected_asset_id,
            )
        manifest = result.meta["source_collection"]
        expected_definition = _optional_text(self.parameters.get("collection_definition_sha256"))
        identity = scientific_collection_identity(manifest, definition, result)
        if definition is None and expected_definition is not None:
            registered_identity = registered_reference_collection_identity(
                manifest,
                result,
                members=[(item.dataset, item.selected_asset_id) for item in loaded],
            )
            if registered_identity is not None:
                identity = registered_identity
        manifest.update(identity)
        expected_manifest = _optional_text(self.parameters.get("source_manifest_sha256"))
        if expected_manifest is not None and manifest["manifest_digest"] != expected_manifest:
            raise ValueError(
                "experiment collection does not match its saved source manifest; "
                "source membership changed after binding, so re-import the dataset or rebind the workflow"
            )
        expected_scientific = _optional_text(self.parameters.get("scientific_collection_sha256"))
        if identity["collection_definition_sha256"] != expected_definition:
            raise ValueError(
                "experiment collection does not match its saved collection definition; "
                "collection metadata changed after binding, so re-import the dataset or rebind the workflow"
            )
        if definition is not None and expected_scientific is None:
            raise ValueError(
                "experiment collection is missing its saved scientific identity; "
                "re-import the dataset or rebind the workflow"
            )
        if expected_scientific is not None and identity["scientific_collection_sha256"] != expected_scientific:
            raise ValueError(
                "experiment collection does not match its saved scientific identity; "
                "parsed data or scientific metadata changed after binding, so re-import the dataset "
                "or rebind the workflow"
            )
        result = self._apply_node_target_selection(result)
        set_spectra_meta(
            result,
            SpectraMeta(
                provenance=DataProvenance(
                    source_type=SourceType.EXPERIMENT,
                    experiment_id=int(dataset_id),
                    created_datetime=datetime.utcnow().isoformat(),
                ),
                processing_steps=["load_group"],
                custom={
                    "source_collection": {
                        "source_mode": "experiment_collection",
                        "stage": stage,
                        "asset_id": asset_id,
                        **manifest,
                        **identity,
                    }
                },
            ),
        )
        add_processing_step(
            result,
            "spectrasherpa.experiment_dataset_read/2",
            {
                **self._processing_parameters(dataset_id=int(dataset_id), file_count=len(loaded), dataset=result),
                "stage": stage,
                "asset_id": asset_id,
                "source_manifest_sha256": manifest["manifest_digest"],
                "collection_definition_sha256": identity["collection_definition_sha256"],
                "scientific_collection_sha256": identity["scientific_collection_sha256"],
            },
            node_id=self.node_id,
        )
        return {"default": result, "target": result.target}

    def _processing_parameters(self, *, dataset_id: int, file_count: int, dataset: SherpaDataset) -> dict[str, Any]:
        params: dict[str, Any] = {"dataset_id": dataset_id, "file_count": file_count}
        tc = getattr(dataset, "target_context", None)
        if tc is not None and getattr(tc, "selected_authority", None) is not None:
            params["target_mode"] = "single"
            params["target_authority"] = tc.selected_authority.canonical_dict()
        elif self.parameters.get("target_mode") == "multi":
            params["target_mode"] = "multi"
        return params

    def _apply_node_target_selection(self, dataset: SherpaDataset) -> SherpaDataset:
        authority = admit_target_authority(self.parameters.get("target_authority"))
        if authority is not None:
            from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset

            verify_target_authority(dataset, authority)
            return attach_selected_target_dataset(
                dataset,
                target_type=authority.target_type,
                target_column=authority.column,
                group_column=str(self.parameters.get("group_column") or ""),
                node_id=self.node_id,
                target_authority=authority,
            )
        target_mode = str(self.parameters.get("target_mode") or "dataset_default")
        if target_mode in {"", "dataset_default", "auto"}:
            return dataset

        tc = dataset.target_context
        if target_mode == "multi":
            dataset.target_context = tc.model_copy(update={"selected_target": None})
            dataset.meta["target_mode"] = "multi"
            dataset.meta.pop("selected_target", None)
            return dataset

        if target_mode != "single":
            raise ValueError(f"Unsupported experiment target mode: {target_mode}")

        names = [str(name) for name in (tc.target_names or [])]
        selected = str(self.parameters.get("selected_target") or "").strip()
        if not selected and names:
            selected = names[0]
        if not selected:
            raise ValueError("Single-property experiment loading requires a dataset with target names.")
        if names and selected not in names:
            available = ", ".join(names)
            raise ValueError(
                f"The selected target '{selected}' is not present; dataset target properties are: {available}."
            )
        dataset.target_context = tc.model_copy(update={"selected_target": selected})
        dataset.meta["target_mode"] = "single"
        dataset.meta["selected_target"] = selected
        return dataset

    def _load_file(
        self,
        file_path: str,
        *,
        file_name: str | None = None,
        asset_id: str | None = None,
        prepared_overrides: Mapping[str, object] | None = None,
    ) -> _LoadedDataset:
        """Load one exact file through the sole native ingestion registry."""
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")
        return _load_registry_asset(
            file_path,
            file_name=file_name,
            asset_id=asset_id,
            prepared_overrides=prepared_overrides,
        )


def _load_registry_asset(
    file_path: str | Path,
    *,
    file_name: str | None = None,
    asset_id: str | None = None,
    prepared_overrides: Mapping[str, object] | None = None,
) -> _LoadedDataset:
    """Project the one registry result into the experiment-reader record."""
    from spectra_sherpa.io import ingest, select_asset

    path = Path(file_path)
    from spectra_sherpa.app.lib.registered_reference_storage import (
        read_registered_reference_sidecar,
    )

    registered_reference = read_registered_reference_sidecar(path)
    if registered_reference is not None:
        return _load_registered_reference_asset(
            path,
            registered_reference=registered_reference,
            file_name=file_name,
            asset_id=asset_id,
            prepared_overrides=prepared_overrides,
        )
    result = ingest(path, parser_options=parser_options_for_prepared_data(path.name, prepared_overrides))
    selected_asset = select_asset(result, asset_id=asset_id)
    dataset = selected_asset.dataset
    dataset = apply_dataset_prepared_data_overrides(dataset, prepared_overrides or {})
    target_names: list[str] | None = None
    target_units: str | None = None
    if dataset.target_context is not None:
        target_names = list(dataset.target_context.target_names or [])
        if not target_names and dataset.target_context.target_name:
            target_names = [dataset.target_context.target_name]
        target_units = dataset.target_context.target_units
    embedded_target = None if dataset.target is None else np.asarray(dataset.target)
    if embedded_target is None:
        properties = dataset.get_extra("properties")
        declared_names = dataset.get_extra("prop_names")
        if isinstance(properties, Mapping):
            ordered_names = (
                [str(name) for name in declared_names]
                if isinstance(declared_names, list)
                else [str(name) for name in properties]
            )
            columns = [np.asarray(properties[name]) for name in ordered_names if name in properties]
            if columns and all(column.ndim == 1 and column.shape[0] == dataset.n_samples for column in columns):
                target_names = ordered_names
                embedded_target = np.column_stack(columns)
    if dataset.target is None and embedded_target is not None:
        dataset.target = embedded_target
        dataset.target_context = TargetContext(
            target_type="continuous",
            target_names=target_names or None,
            target_units=target_units,
        )
    ground_truth = _dataset_ground_truth(dataset)
    return _LoadedDataset(
        dataset=dataset,
        file_name=file_name or path.name,
        file_path=str(path),
        embedded_target_names=target_names,
        embedded_target_data=embedded_target,
        embedded_target_units=target_units,
        ground_truth_spectra=ground_truth.get("spectra"),
        ground_truth_spectra_names=target_names,
        ground_truth_spectra_units=ground_truth.get("units"),
        ground_truth_spectra_x=ground_truth.get("x"),
        ground_truth_spectra_x_title=ground_truth.get("x_title"),
        ground_truth_spectra_x_units=ground_truth.get("x_units"),
        prepared_overrides=prepared_overrides,
        source_members=result.source_members,
        selected_asset_id=selected_asset.asset_id,
    )


def _load_registered_reference_asset(
    path: Path,
    *,
    registered_reference: Mapping[str, Any],
    file_name: str | None,
    asset_id: str | None,
    prepared_overrides: Mapping[str, object] | None,
) -> _LoadedDataset:
    """Re-admit a retained exact member without changing generic parser policy."""

    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member

    projection_id = str(registered_reference["projection_id"])
    if asset_id is not None and asset_id != projection_id:
        raise ValueError("requested asset differs from the registered reference projection")
    materialized = materialize_reference_member(path, projection_id)
    if dict(materialized.portable_reference) != dict(registered_reference):
        raise ValueError("registered reference identity changed during workspace admission")
    dataset = apply_dataset_prepared_data_overrides(materialized.dataset, prepared_overrides or {})
    target_names = list(dataset.target_context.target_names or []) if dataset.target_context is not None else []
    if not target_names and dataset.target_context is not None and dataset.target_context.target_name:
        target_names = [dataset.target_context.target_name]
    target = None if dataset.target is None else np.asarray(dataset.target)
    return _LoadedDataset(
        dataset=dataset,
        file_name=file_name or path.name,
        file_path=str(path),
        embedded_target_names=target_names or None,
        embedded_target_data=target,
        embedded_target_units=(dataset.target_context.target_units if dataset.target_context is not None else None),
        prepared_overrides=prepared_overrides,
        source_members=(
            SourceMember(
                name=path.name,
                sha256=str(registered_reference["member_sha256"]),
                size_bytes=int(registered_reference["member_size_bytes"]),
            ),
        ),
        selected_asset_id=projection_id,
    )


def _dataset_ground_truth(dataset: SherpaDataset) -> dict[str, Any]:
    """Read optional synthetic ground truth without reparsing source bytes."""
    spectra = dataset.get_extra("ground_truth.spectra")
    if spectra is None:
        return {}
    parsed = dataset.get_extra("ground_truth")
    if isinstance(parsed, dict):
        metadata = parsed
    else:
        raw = dataset.get_extra("synthetic.ground_truth_json")
        try:
            metadata = json.loads(str(raw or "{}"))
        except (TypeError, ValueError):
            metadata = {}
    feature_axis = dataset.feature_axis
    return {
        "spectra": np.asarray(spectra, dtype=np.float64),
        "units": metadata.get("S_units") if isinstance(metadata, dict) else None,
        "x": None if feature_axis is None or feature_axis.values is None else np.asarray(feature_axis.values),
        "x_title": None if feature_axis is None else feature_axis.title,
        "x_units": None if feature_axis is None else feature_axis.units,
    }


def _synthesis_target_names(payload: dict[str, Any]) -> list[str]:
    ground_truth = _synthesis_ground_truth(payload)
    names = ground_truth.get("component_names")
    if isinstance(names, list) and names:
        return [str(name) for name in names]

    c = np.asarray(payload["C"])
    return [f"component_{index + 1}" for index in range(c.shape[1] if c.ndim == 2 else 1)]


def _synthesis_ground_truth(payload: dict[str, Any]) -> dict[str, Any]:
    raw_ground_truth = payload.get("ground_truth_json")
    if raw_ground_truth:
        try:
            parsed = json.loads(str(raw_ground_truth))
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            logger.debug("Could not parse synthesis ground-truth metadata", exc_info=True)
    return {}


@register_node
class LoadGroupNode(Node):
    """
    Load Group node for one strict local or project-owned spectral collection.

    Loads all matching files from a folder and concatenates them along the sample axis,
    creating a single SherpaDataset with multiple spectra. Useful for:
    - Time-series measurements (multiple time points)
    - Multi-sample studies (different samples)
    - Batch processing (entire folder of spectra)
    - Comparative studies (control vs treatment groups)

    Features:
    - Mixed format support through the frozen native ingestion registry
    - Strict x-axis validation (ensures all spectra have identical wavenumbers)
    - Fail-fast error handling (stops on first error, no silent failures)
    - Deterministic sorting (alphabetical or numeric suffix)
    - Content-manifest-bound provenance
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
        node_type="data.load_group",
        category="data",
        label="Load Group",
        description="Load one exact compatible collection as a grouped dataset",
        parameters=[
            NodeParameter(
                name="source_mode",
                label="Collection Source",
                param_type="select",
                options=["local_folder", "experiment_collection"],
                default="local_folder",
                description="Use a local folder or an exact project-owned experiment collection",
                required=False,
            ),
            NodeParameter(
                name="collection_definition_sha256",
                label="Collection Definition",
                param_type="text",
                default="",
                description="Exact scientist-definition digest, empty only when no definition is attached",
                required=False,
                category="internal",
            ),
            NodeParameter(
                name="scientific_collection_sha256",
                label="Scientific Collection",
                param_type="text",
                default="",
                description="Combined exact source and scientist-definition identity",
                required=False,
                category="internal",
            ),
            NodeParameter(
                name="folder_path",
                label="Folder Path",
                param_type="text",
                default="",
                description="Absolute local path; used only in local-folder mode",
                required=False,
            ),
            NodeParameter(
                name="pattern",
                label="File Pattern",
                param_type="text",
                default="*.csv",
                description="Glob pattern for native files (e.g., '*.csv', '*.jdx', '*.npz', or '*.mat')",
                required=False,
            ),
            NodeParameter(
                name="recursive",
                label="Include Subdirectories",
                param_type="boolean",
                default=False,
                description="Scan subdirectories recursively",
                required=False,
            ),
            NodeParameter(
                name="sort_by",
                label="Sort Files By",
                param_type="select",
                options=["filename", "numeric_suffix"],
                default="filename",
                description=(
                    "How to order files before concatenation "
                    "(filename=alphabetical, numeric_suffix=extract numbers from filename)"
                ),
                required=False,
            ),
            NodeParameter(
                name="group_title",
                label="Group Title",
                param_type="text",
                default="",
                description="Title for the grouped dataset (auto-generated from folder name if empty)",
                required=False,
            ),
            NodeParameter(
                name="asset_id",
                label="Scientific Asset",
                param_type="text",
                default="",
                description=(
                    "Exact asset identity to select from every file. Required for multi-asset formats; "
                    "the same identity is applied to all group members."
                ),
                required=False,
            ),
            NodeParameter(
                name="experiment_id",
                label="Experiment",
                param_type="number",
                default=None,
                description="Project experiment identity; used only in experiment-collection mode",
                required=False,
            ),
            NodeParameter(
                name="stage",
                label="Stage",
                param_type="select",
                options=["raw", "preprocessed", "synthetic"],
                default="raw",
                description="Exact persisted experiment stage",
                required=False,
            ),
            NodeParameter(
                name="source_manifest_sha256",
                label="Source Manifest",
                param_type="text",
                default="",
                description="Exact ordered collection digest recorded when the workflow is authored",
                required=False,
                category="internal",
            ),
        ],
        input_types=[],  # No inputs - this is a source node
        input_ports=[],
        output_type="SherpaDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Grouped Spectra",
                description="Strictly compatible spectra bound to a deterministic source manifest",
            )
        ],
        help_url="docs/nodes/data.md#load-group",
        canonical_parameter_validator=_canonical_load_group_parameters,
        draft_parameter_validator=_draft_load_group_parameters,
    )

    async def execute(self, *args) -> Any:  # noqa: C901 - existing multi-format loader dispatch
        """
        Execute group loading: load all matching files and concatenate.

        Returns:
            SherpaDataset containing all spectra concatenated along the sample axis
        """
        import re

        parameters = self.metadata.canonicalize_parameters(self.parameters)
        source_mode = str(parameters["source_mode"])
        if source_mode == "experiment_collection":
            reader = ExperimentDatasetReader(
                self.node_id,
                {
                    "dataset_id": int(parameters["experiment_id"]),
                    "stage": str(parameters["stage"]),
                    "asset_id": str(parameters["asset_id"]),
                    "source_manifest_sha256": str(parameters["source_manifest_sha256"]),
                    "collection_definition_sha256": str(parameters["collection_definition_sha256"]),
                    "scientific_collection_sha256": str(parameters["scientific_collection_sha256"]),
                },
                source_resolver=self.require_execution_runtime().require_dataset_source_resolver(),
            )
            return (await reader.execute())["default"]

        folder_path = str(parameters["folder_path"])
        pattern = str(parameters["pattern"])
        recursive = bool(parameters["recursive"])
        sort_by = str(parameters["sort_by"])
        group_title = str(parameters["group_title"])
        asset_id = str(parameters["asset_id"]) or None

        folder = Path(folder_path).expanduser()
        if not folder.is_absolute():
            raise ValueError("data.load_group requires an absolute folder path")

        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder}")

        if not folder.is_dir():
            raise ValueError(f"Path is not a directory: {folder}")

        # Find all matching files (case-insensitive)
        # Use case-insensitive matching to handle both .spa and .SPA extensions
        import fnmatch

        # Get all files (recursively if requested)
        if recursive:
            # Walk directory tree recursively
            all_files = [item for item in folder.rglob("*") if item.is_file()]
        else:
            # Only immediate directory
            all_files = [f for f in folder.iterdir() if f.is_file()]
        all_files.sort(key=lambda path: path.relative_to(folder).as_posix().casefold())

        # Filter with case-insensitive matching
        files = []
        for f in all_files:
            # Skip hidden files and system files
            if f.name.startswith((".", "__")):
                continue

            # Case-insensitive pattern matching
            # For recursive patterns, compare relative path; otherwise just filename
            if recursive and "/" in pattern:
                # Pattern includes path (e.g., "subfolder/*.spa")
                # Compare relative path from folder root
                try:
                    rel_path = f.relative_to(folder)
                    match_str = str(rel_path).replace("\\", "/")  # Normalize path separators
                except ValueError:
                    continue
            else:
                # Simple pattern - just match filename
                match_str = f.name

            # Apply case-insensitive matching
            if "*" in pattern or "?" in pattern:
                # Wildcard pattern - use fnmatch
                if fnmatch.fnmatch(match_str.lower(), pattern.lower()):
                    files.append(f)
            else:
                # Exact match - case-insensitive
                if match_str.lower() == pattern.lower():
                    files.append(f)

        if not files:
            raise ValueError(
                f"No files found matching pattern '{pattern}' in {folder}\n"
                f"Recursive: {recursive}\n"
                f"(Case-insensitive search performed)\n"
                f"Please verify the folder contains spectral files and the pattern is correct."
            )

        logger.debug(f"[LOAD_GROUP] Found {len(files)} files matching '{pattern}' in {folder}")

        # Sort files according to sort_by parameter
        if sort_by == "numeric_suffix":
            # Extract numeric suffix from filename (e.g., "sample_001.spa" -> 1)
            def extract_number(file_path: Path) -> tuple[int, str, str]:
                match = re.search(r"(\d+)", file_path.stem)
                return (
                    int(match.group(1)) if match else -1,
                    file_path.name.casefold(),
                    file_path.relative_to(folder).as_posix().casefold(),
                )

            files.sort(key=extract_number)
            logger.debug("[LOAD_GROUP] Sorted by numeric suffix")

        else:  # sort_by == "filename" (default)
            # Sort alphabetically by filename
            files.sort(
                key=lambda file_path: (
                    file_path.name.casefold(),
                    file_path.relative_to(folder).as_posix().casefold(),
                )
            )
            logger.debug("[LOAD_GROUP] Sorted alphabetically")

        admitted_manifest = file_manifest(
            folder,
            files,
            max_members=_LOAD_GROUP_MAX_FILES,
            max_file_bytes=_LOAD_GROUP_PARSER_LIMITS.max_source_bytes,
            max_total_bytes=_LOAD_GROUP_MAX_SOURCE_BYTES,
        )

        # Load all files (FAIL-FAST: stop on first error)
        datasets = []
        file_names = []
        parsed_members: list[tuple[Path, SourceMember]] = []
        retained_elements = 0
        retained_bytes = 0

        for i, file_path in enumerate(files, 1):
            try:
                logger.debug(f"[LOAD_GROUP] Loading {i}/{len(files)}: {file_path.name}")

                # Load using centralized reader (supports mixed formats)
                loaded = self._load_single_file(file_path, asset_id=asset_id)
                dataset = loaded.dataset

                if dataset is None:
                    # FAIL-FAST: No fallbacks allowed
                    raise ValueError(f"Reader returned None for {file_path.name}")

                if len(loaded.source_members) != 1:
                    raise ValueError(
                        f"Registry result for {file_path.name} must identify exactly one consumed source member"
                    )
                next_elements, next_bytes = _retained_numeric_footprint(dataset)
                retained_elements += next_elements
                retained_bytes += next_bytes
                if retained_elements > _LOAD_GROUP_MAX_DECODED_ELEMENTS:
                    raise ValueError(
                        f"group retains {retained_elements} decoded elements; "
                        f"limit is {_LOAD_GROUP_MAX_DECODED_ELEMENTS}"
                    )
                if retained_bytes > _LOAD_GROUP_MAX_DECODED_BYTES:
                    raise ValueError(
                        f"group retains {retained_bytes} decoded bytes; limit is {_LOAD_GROUP_MAX_DECODED_BYTES}"
                    )
                datasets.append(dataset)
                file_names.append(file_path.name)
                parsed_members.append((file_path, loaded.source_members[0]))

            except Exception as e:
                # FAIL-FAST: Stop immediately on first error
                error_msg = (
                    f"Failed to load file {i}/{len(files)}: {file_path.name}\n"
                    f"Error: {str(e)}\n\n"
                    f"FAIL-FAST policy: Stopped loading remaining files.\n"
                    f"Successfully loaded: {len(datasets)}/{len(files)} files\n"
                    f"Failed file: {file_path}\n\n"
                    f"Fix the error in this file before proceeding."
                )
                raise ValueError(error_msg) from e

        logger.debug(f"[LOAD_GROUP] Successfully loaded all {len(datasets)} files")

        source_manifest = source_contracts.file_manifest_from_members(
            folder,
            parsed_members,
            max_members=_LOAD_GROUP_MAX_FILES,
            max_file_bytes=_LOAD_GROUP_PARSER_LIMITS.max_source_bytes,
            max_total_bytes=_LOAD_GROUP_MAX_SOURCE_BYTES,
        )
        if source_manifest["manifest_digest"] != admitted_manifest["manifest_digest"]:
            raise ValueError("source files changed before their registry snapshots were admitted")

        members = [
            CollectionMember(
                dataset=dataset,
                file_name=source_member.name,
                size_bytes=source_member.size_bytes,
                sha256=source_member.sha256,
                prepared_data_sha256=prepared_data_digest(None),
                asset_id=loaded.selected_asset_id,
            )
            for dataset, (_, source_member) in zip(datasets, parsed_members)
        ]
        require_collection_budget(members)
        try:
            concatenated = assemble_collection(
                members,
                title=group_title or f"{folder.name} ({len(datasets)} files)",
            )
            total_spectra = int(concatenated.n_samples)
        except Exception as e:
            raise ValueError(
                f"Failed to concatenate datasets along sample axis.\n"
                f"Error: {str(e)}\n"
                f"All files loaded successfully but concatenation failed.\n"
                f"This may indicate incompatible data shapes or axes."
            ) from e

        if not group_title:
            concatenated.title = f"{folder.name} ({len(datasets)} files, {total_spectra} spectra)"

        # Attach rich metadata (SECURITY: only folder name, not full path)
        folder_name = folder.name if hasattr(folder, "name") else os.path.basename(str(folder))
        meta = SpectraMeta(
            provenance=DataProvenance(
                source_type=SourceType.EXPERIMENT,  # Closest match for file group
                original_file_path=folder_name,  # Only folder name, sanitized in to_api_json()
            ),
            processing_steps=["load_group"],
            custom={
                "group_load_params": {
                    "folder_name": folder_name,  # Only folder name, not full path
                    "pattern": pattern,
                    "recursive": recursive,
                    "sort_by": sort_by,
                    "n_files": len(files),
                    "file_names": file_names,  # File names only, should not contain paths
                    "source_manifest": source_manifest,
                    "asset_id": asset_id,
                    "resource_limits": {
                        "max_files": _LOAD_GROUP_MAX_FILES,
                        "max_source_bytes": _LOAD_GROUP_MAX_SOURCE_BYTES,
                        "max_decoded_elements": _LOAD_GROUP_MAX_DECODED_ELEMENTS,
                        "max_decoded_bytes": _LOAD_GROUP_MAX_DECODED_BYTES,
                    },
                }
            },
        )
        result = concatenated
        set_spectra_meta(result, meta)

        logger.debug(f"[LOAD_GROUP] Group loaded successfully: {concatenated.title}")

        # Record provenance in dataset.meta
        add_processing_step(
            result,
            "data.load_group",
            {
                "folder_path": folder_name,
                "pattern": pattern,
                "recursive": recursive,
                "sort_by": sort_by,
                "n_files": len(files),
                "source_manifest_digest": source_manifest["manifest_digest"],
                "asset_id": asset_id,
            },
            node_id=self.node_id,
        )
        return result

    def _load_single_file(self, file_path: Path, *, asset_id: str | None = None) -> _LoadedDataset:
        """
        Load a single spectral file through the frozen ingestion registry.

        Args:
            file_path: Path to file

        Returns:
            Registry projection containing the dataset and exact consumed bytes

        Raises:
            ValueError: If file cannot be loaded
        """
        try:
            loaded = _load_registry_asset(file_path, asset_id=asset_id)
            dataset = loaded.dataset
            if not isinstance(dataset, SherpaDataset):
                raise TypeError("ingestion registry returned a non-SherpaDataset asset")
            dataset.title = file_path.stem
            return loaded
        except Exception as e:
            raise ValueError(
                f"Failed to load {file_path.name}: {str(e)}\nFile type: {file_path.suffix}\nFull path: {file_path}"
            ) from e

    def _validate_axes_match(self, datasets: list[SherpaDataset], file_names: list[str]) -> None:
        """
        Validate that all datasets have identical x-axes (wavenumbers).

        STRICT VALIDATION: Raises error if any mismatch is found.

        Args:
            datasets: List of loaded datasets
            file_names: List of file names (for error messages)

        Raises:
            ValueError: If x-axes don't match across all files
        """
        if not datasets or len(datasets) != len(file_names):
            raise ValueError("axis validation requires one file identity per dataset")

        reference = datasets[0]
        reference_name = file_names[0]

        reference_axis = reference.feature_axis
        if reference_axis is None or reference_axis.values is None:
            raise ValueError(
                f"Reference file '{reference_name}' has no x-axis (wavenumbers).\n"
                f"All files must have x-axis coordinates for validation."
            )

        reference_x = np.asarray(reference_axis.values, dtype=np.float64).reshape(-1)
        if reference_x.size < 2 or not np.all(np.isfinite(reference_x)):
            raise ValueError(f"X-axis validation failed: '{reference_name}' lacks a finite feature axis")
        reference_differences = np.diff(reference_x)
        if not (np.all(reference_differences > 0.0) or np.all(reference_differences < 0.0)):
            raise ValueError(f"X-axis validation failed: '{reference_name}' axis is not strictly monotonic")
        reference_shape = reference_x.shape

        # Compare all other datasets to reference
        for i, (dataset, file_name) in enumerate(zip(datasets[1:], file_names[1:]), 2):
            axis = dataset.feature_axis
            if axis is None or axis.values is None:
                raise ValueError(
                    f"X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has no x-axis.\n"
                    f"Reference: '{reference_name}' has x-axis with {len(reference_x)} points.\n\n"
                    f"All files must have x-axis coordinates for concatenation."
                )

            dataset_x = np.asarray(axis.values, dtype=np.float64).reshape(-1)
            if dataset_x.size < 2 or not np.all(np.isfinite(dataset_x)):
                raise ValueError(f"X-axis validation failed: '{file_name}' lacks a finite feature axis")
            differences = np.diff(dataset_x)
            if not (np.all(differences > 0.0) or np.all(differences < 0.0)):
                raise ValueError(f"X-axis validation failed: '{file_name}' axis is not strictly monotonic")

            reference_axis_units = _coordinate_text(reference_axis, "units")
            dataset_axis_units = _coordinate_text(axis, "units")
            if dataset_axis_units != reference_axis_units:
                raise ValueError(
                    "X-axis validation failed: "
                    f"'{file_name}' uses {dataset_axis_units!r}, while "
                    f"'{reference_name}' uses {reference_axis_units!r}"
                )

            reference_axis_title = _coordinate_text(reference_axis, "title")
            dataset_axis_title = _coordinate_text(axis, "title")
            if dataset_axis_title != reference_axis_title:
                raise ValueError(
                    "X-axis validation failed: "
                    f"'{file_name}' axis title is {dataset_axis_title!r}, while "
                    f"'{reference_name}' uses {reference_axis_title!r}"
                )

            reference_units = _coordinate_text(reference, "units")
            dataset_units = _coordinate_text(dataset, "units")
            if dataset_units != reference_units:
                raise ValueError(
                    "Signal-unit validation failed: "
                    f"'{file_name}' uses {dataset_units!r}, while "
                    f"'{reference_name}' uses {reference_units!r}"
                )

            # Check shape match
            if dataset_x.shape != reference_shape:
                raise ValueError(
                    f"X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has {len(dataset_x)} points\n"
                    f"Reference: '{reference_name}' has {len(reference_x)} points\n\n"
                    f"All spectra must have the same x-axis (wavenumber range) for concatenation.\n"
                    f"Consider interpolating or cropping spectra to match before loading as a group."
                )

            # Check values match (with tolerance for floating-point precision)
            if not np.allclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12):
                # Find first mismatch for detailed error message
                mismatch_idx = np.where(~np.isclose(dataset_x, reference_x, rtol=1e-9, atol=1e-12))[0][0]

                raise ValueError(
                    f"X-axis validation failed:\n"
                    f"File {i}/{len(datasets)}: '{file_name}' has different x-axis values\n"
                    f"Reference: '{reference_name}'\n\n"
                    f"First mismatch at index {mismatch_idx}:\n"
                    f"  {reference_name}: {reference_x[mismatch_idx]:.6f}\n"
                    f"  {file_name}: {dataset_x[mismatch_idx]:.6f}\n\n"
                    f"All spectra must have identical wavenumber axes for concatenation.\n"
                    f"Consider reprocessing files to ensure consistent spectral range and resolution."
                )

        logger.debug(
            f"[LOAD_GROUP] X-axis validation passed: All {len(datasets)} spectra "
            f"have identical x-axes ({len(reference_x)} points)"
        )


@register_node
class CollectionLoadNode(Node):
    """Load one exact server-authorized experiment collection and its target."""

    metadata = NodeMetadata(
        node_type="data.collection_load",
        category="data",
        label="Collection Load",
        description="Load exact selected members of a project dataset",
        parameters=[
            NodeParameter("experiment_id", "Experiment", "number", default=None, min_value=1, category="internal"),
            NodeParameter(
                "stage",
                "Stage",
                "select",
                default="raw",
                options=["raw", "preprocessed", "synthetic"],
                category="internal",
            ),
            NodeParameter("group_title", "Dataset Name", "text", default="", required=False, category="internal"),
            NodeParameter("asset_id", "Scientific Asset", "text", default="", required=False, category="internal"),
            NodeParameter("selected_file_ids", "Selected Members", "string_list", default=[], category="internal"),
            NodeParameter("source_manifest_sha256", "Source Manifest", "text", default="", category="internal"),
            NodeParameter(
                "collection_definition_sha256",
                "Collection Definition",
                "text",
                default="",
                required=False,
                category="internal",
            ),
            NodeParameter(
                "scientific_collection_sha256",
                "Scientific Collection",
                "text",
                default="",
                required=False,
                category="internal",
            ),
            NodeParameter(
                "target_authority", "Target Authority", "json", default=None, required=False, category="internal"
            ),
            NodeParameter("group_column", "Validation Group", "text", default="", required=False, category="internal"),
            NodeParameter(
                "dataset_view_id",
                "Saved Dataset Definition",
                "number",
                default=None,
                required=False,
                category="internal",
            ),
            NodeParameter(
                "dataset_view_sha256",
                "Saved Definition Digest",
                "text",
                default="",
                required=False,
                category="internal",
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="dict",
        output_ports=[
            PortMetadata("default", "spectrasherpa://types/SpectralDataset/1.0", True, "Selected Dataset"),
            PortMetadata("target", "spectrasherpa://types/TargetMatrix/1.0", False, "Target Values"),
        ],
        canonical_parameter_validator=_canonical_collection_load_parameters,
        policy=NodePolicy(safe_for_auto_apply=False, requires_human_review=True, data_egress_risk="none"),
    )

    async def execute(self, *args: Any) -> dict[str, object]:
        del args
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        reader = ExperimentDatasetReader(
            self.node_id,
            {"dataset_id": parameters["experiment_id"], **parameters},
            source_resolver=self.require_execution_runtime().require_dataset_source_resolver(),
        )
        return await reader.execute()


bind_stable_execution_contract(
    CollectionLoadNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.data.collection_load",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="CeCILL-B",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        source_contracts,
        collection_assembly_contract,
        collection_definition_contract,
        spectra_meta_contract,
        dag_meta_helpers,
        sample_labels_contract,
        ingestion_registry_contract,
        *ingestion_registry_contract.native_implementation_modules(),
    ),
    implementation_distributions=("h5py", "numpy", "pandas", "scipy"),
    runtime_requirements=(
        ("h5py", "3.16.0"),
        ("numpy", "1.26.4"),
        ("pandas", "2.3.3"),
        ("scipy", "1.17.1"),
    ),
)


bind_stable_execution_contract(
    LoadGroupNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.data.load_group",
    implementation_version="6.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="CeCILL-B",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        source_contracts,
        collection_assembly_contract,
        collection_definition_contract,
        spectra_meta_contract,
        dag_meta_helpers,
        sample_labels_contract,
        ingestion_registry_contract,
        *ingestion_registry_contract.native_implementation_modules(),
    ),
    implementation_distributions=("h5py", "numpy", "pandas", "scipy"),
    runtime_requirements=(
        ("h5py", "3.16.0"),
        ("numpy", "1.26.4"),
        ("pandas", "2.3.3"),
        ("scipy", "1.17.1"),
    ),
)
