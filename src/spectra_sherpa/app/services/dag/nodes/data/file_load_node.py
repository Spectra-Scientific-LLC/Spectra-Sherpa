"""Canonical Sherpa-native experiment-file source node."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from spectra_sherpa.app.lib import data_formats as data_formats_contract
from spectra_sherpa.app.lib import io as sherpa_io
from spectra_sherpa.app.lib.data_formats import CANONICAL_FILE_LOAD_EXTENSIONS
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.target_authority import verify_target_authority
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.io_contracts import extract_target_like
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import spectra_meta as spectra_meta_contract
from spectra_sherpa.core.prepared_data import (
    PreparedDataOverrides,
    apply_dataset_prepared_data_overrides,
    bind_explicit_target_selection,
)
from spectra_sherpa.core.spectra_meta import DataProvenance, SourceType, SpectraMeta, set_spectra_meta
from spectra_sherpa.core.target_authority import admit_target_authority
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.io import registry as ingestion_registry_contract

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from . import sample_table as sample_table_contract
from .sample_table import load_portable_sample_table

_PORTABLE_EXTENSIONS = frozenset(CANONICAL_FILE_LOAD_EXTENSIONS)


def _canonical_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Require exact persisted identities at the source-admission boundary."""

    projected = dict(parameters)
    for name in ("experiment_id", "file_id"):
        value = projected[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be an exact positive integer")
    authority = admit_target_authority(projected.get("target_authority"))
    if authority is None:
        projected.pop("target_authority", None)
    else:
        projected["target_authority"] = authority.canonical_dict()
    asset_id = projected.get("asset_id")
    if asset_id is not None and (not isinstance(asset_id, str) or not asset_id.strip() or asset_id != asset_id.strip()):
        raise ValueError("asset_id must be one non-empty exact asset identity")
    if asset_id is None:
        projected.pop("asset_id", None)
    return projected


@register_node
class FileLoadNode(Node):
    """Load one actor-authorized experiment file through a visible runtime."""

    metadata = NodeMetadata(
        node_type="data.file_load",
        category="data",
        label="File Load",
        description="Load a portable experiment file through the Sherpa-native reader",
        parameters=[
            NodeParameter(
                name="experiment_id",
                label="Experiment ID",
                param_type="number",
                default=None,
                description="Experiment containing the file",
                min_value=1,
                required=True,
            ),
            NodeParameter(
                name="file_id",
                label="File ID",
                param_type="number",
                default=None,
                description="Specific file to load",
                min_value=1,
                required=True,
            ),
            NodeParameter(
                name="stage",
                label="Stage",
                param_type="select",
                default="raw",
                options=["raw", "preprocessed", "synthetic"],
                description="Data processing stage",
                required=False,
            ),
            NodeParameter(
                name="asset_id",
                label="Scientific Asset",
                param_type="text",
                default=None,
                description=(
                    "Exact named result inside a multi-asset source, such as OPUS absorbance 'a'; "
                    "single-asset files do not require it"
                ),
                required=False,
            ),
            NodeParameter(
                name="target_authority",
                label="Target Authority",
                param_type="json",
                default=None,
                description="Exact response column, type, units, and source identity",
                required=False,
                category="internal",
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectral Data",
                description="Loaded spectra in the canonical SherpaDataset representation",
            ),
            PortMetadata(
                name="target",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values",
                description="Embedded reference or class values when present in the selected file",
            ),
            PortMetadata(
                name="sample_table",
                type_ref="spectrasherpa://types/SampleTable/2.0",
                required=False,
                label="Sample Table",
                description=(
                    "Exact source-row identities, inclusion decisions, target values, and annotations "
                    "when the selected file is a portable Sherpa sample table"
                ),
            ),
        ],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
        canonical_parameter_validator=_canonical_parameters,
    )

    async def execute(self, *args: Any) -> dict[str, object]:
        """Load the exact source record selected by the saved DAG."""
        del args
        experiment_id = int(self.parameters["experiment_id"])
        file_id = int(self.parameters["file_id"])
        stage = str(self.parameters["stage"])

        try:
            source = (
                await self.require_execution_runtime()
                .require_dataset_source_resolver()
                .resolve_experiment_file(
                    experiment_id=experiment_id,
                    file_id=file_id,
                    stage=stage,
                )
            )
            requested_asset = self.parameters.get("asset_id")
            target_authority = admit_target_authority(self.parameters.get("target_authority"))
            if (
                source.preloaded_asset_id is not None
                and requested_asset is not None
                and requested_asset != source.preloaded_asset_id
            ):
                raise ValueError("preloaded source asset differs from the admitted trial asset")
            if source.preloaded_dataset is not None:
                dataset = copy.deepcopy(source.preloaded_dataset)
                dataset = sherpa_io.select_dataset_target(
                    dataset,
                    selected_target=target_authority.column if target_authority is not None else None,
                    target_type=target_authority.target_type if target_authority is not None else None,
                    source_name=source.original_file_path,
                )
                axis = dataset.sample_axis
                sample_table = None if axis is None or axis.sample_table is None else dict(axis.sample_table)
            else:
                overrides = PreparedDataOverrides.from_mapping(source.prepared_overrides)
                selected_target = (
                    target_authority.column
                    if target_authority is not None
                    else overrides.selected_target or overrides.target_column
                )
                target_type = target_authority.target_type if target_authority is not None else overrides.target_type
                dataset = self._load_file(
                    source.path,
                    asset_id=requested_asset,
                    selected_target=selected_target,
                    target_type=target_type,
                    prepared_overrides=source.prepared_overrides,
                )
                sample_table = load_portable_sample_table(
                    source.path,
                    selected_target=selected_target,
                    target_type=target_type,
                )
            if source.preloaded_dataset is None:
                self._verify_resolved_source_identity(
                    dataset,
                    expected_size_bytes=source.size_bytes,
                    expected_sha256=source.sha256,
                )
            if target_authority is not None:
                verify_target_authority(dataset, target_authority, source_digest=source.sha256)
                dataset.target_context = dataset.target_context.model_copy(
                    update={"selected_authority": target_authority}
                )
            set_spectra_meta(
                dataset,
                SpectraMeta(
                    provenance=DataProvenance(
                        source_type=SourceType.EXPERIMENT,
                        experiment_id=experiment_id,
                        file_id=file_id,
                        original_file_path=source.original_file_path,
                        original_file_format=Path(source.original_file_path).suffix.lower().lstrip("."),
                        created_datetime=source.created_datetime,
                    ),
                    processing_steps=["load"] if stage == "raw" else ["load", stage],
                ),
            )
            add_processing_step(
                dataset,
                "data.file_load",
                _canonical_parameters(dict(self.parameters)),
                node_id=self.node_id,
            )
            return {
                "default": dataset,
                "target": extract_target_like(dataset),
                "sample_table": sample_table,
            }
        except Exception as exc:
            raise ValueError(f"Error loading file: {exc}") from exc

    @staticmethod
    def _verify_resolved_source_identity(
        dataset: SherpaDataset,
        *,
        expected_size_bytes: int | None,
        expected_sha256: str | None,
    ) -> None:
        """Bind parser output to the application-authorized source bytes."""

        if expected_size_bytes is None and expected_sha256 is None:
            return
        authority = dataset.get_extra("ingestion.authority")
        if not isinstance(authority, Mapping):
            raise ValueError("parsed dataset is missing its native ingestion authority")
        members = authority.get("source_members")
        if not isinstance(members, list):
            raise ValueError("parsed dataset has malformed native source-member authority")
        matching = [
            member
            for member in members
            if isinstance(member, Mapping)
            and (expected_size_bytes is None or member.get("size_bytes") == expected_size_bytes)
            and (expected_sha256 is None or member.get("sha256") == expected_sha256)
        ]
        if len(matching) != 1:
            raise ValueError("parsed source identity differs from the authorized experiment file")

    def _load_file(
        self,
        file_path: str | Path,
        *,
        asset_id: object = None,
        selected_target: object = None,
        target_type: object = None,
        prepared_overrides: Mapping[str, object] | None = None,
    ) -> SherpaDataset:
        """Load one portable format without choosing an optional runtime."""

        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        extension = path.suffix.lower()
        if not ingestion_registry_contract.builtin_registry.accepts_filename(path.name):
            supported = ", ".join(sorted(_PORTABLE_EXTENSIONS))
            raise ValueError(
                f"Canonical data.file_load does not admit {extension or 'extensionless'} files. "
                f"Supported native formats: {supported}."
            )
        dataset = sherpa_io.load_canonical_file_as_sherpa(
            path,
            asset_id=str(asset_id) if asset_id is not None else None,
            selected_target=str(selected_target) if selected_target is not None else None,
            target_type=str(target_type) if target_type is not None else None,
            prepared_overrides=prepared_overrides,
        )
        if not isinstance(dataset, SherpaDataset):
            raise ValueError(f"Canonical reader is unavailable for admitted file format: {extension}")
        overrides = bind_explicit_target_selection(
            PreparedDataOverrides.from_mapping(prepared_overrides),
            selected_target=selected_target,
            target_type=target_type,
        )
        return apply_dataset_prepared_data_overrides(dataset, overrides)

    def exported_output_ports(self) -> set[str]:
        """Declare the named source envelope used by every export runtime."""

        return {"default", "target", "sample_table"}


bind_stable_execution_contract(
    FileLoadNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.data.file_load",
    implementation_version="6.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        data_formats_contract,
        spectra_meta_contract,
        dag_meta_helpers,
        dag_io_contracts,
        sample_table_contract,
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
