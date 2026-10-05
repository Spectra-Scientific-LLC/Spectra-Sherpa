"""Derive the first managed baseline from a saved workbench DAG.

The managed Runner must not accept a caller's convenient JSON rendering of a
graph.  A user first saves and validates a workflow in the ordinary workbench;
this module then re-reads that persisted DAG, verifies its execution-semantic
integrity hash, and projects the small first-party validation graph that a
Runner is allowed to score.  The source binding remains outside the scientific
candidate graph, but is bound into the resulting baseline identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationRuntimeAttestationError,
    admit_validation_graph,
)
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.core.target_authority import TargetAuthority, admit_target_authority

_LEGACY_BASELINE_VERSION = "spectra-canonical-workbench-baseline/5"
_BASELINE_VERSION = "spectra-canonical-workbench-baseline/6"
SEED_EXECUTION_BASELINE_VERSION = "spectra-canonical-seed-execution-baseline/1"
GROUPED_SEED_EXECUTION_BASELINE_VERSION = "spectra-canonical-seed-execution-baseline/2"
_DIGEST = __import__("re").compile(r"^[0-9a-f]{64}$")
_STAGES = frozenset({"raw", "synthetic", "preprocessed"})


class CanonicalWorkbenchBaselineError(ValueError):
    """A saved workbench graph is not an admissible managed baseline."""


@dataclass(frozen=True, kw_only=True)
class CanonicalDatasetSelection:
    """Data-free identity of the saved workflow's declared data source."""

    experiment_id: int
    file_id: int | None
    stage: str
    source_node_id: str
    target_authority: TargetAuthority
    asset_id: str | None = None
    group_column: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target_authority, TargetAuthority):
            raise TypeError("target_authority must be one admitted TargetAuthority")
        if self.group_column is not None and (
            not isinstance(self.group_column, str)
            or not self.group_column.strip()
            or self.group_column != self.group_column.strip()
            or len(self.group_column) > 255
        ):
            raise ValueError("group_column must be one normalized sample-table column")

    @property
    def selected_target(self) -> str:
        return self.target_authority.column

    @property
    def target_type(self) -> str:
        return self.target_authority.target_type

    def as_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "file_id": self.file_id,
            "stage": self.stage,
            "asset_id": self.asset_id,
            "source_node_id": self.source_node_id,
            "target_authority": self.target_authority.canonical_dict(),
            "group_column": self.group_column,
        }


@dataclass(frozen=True)
class CanonicalWorkbenchBaseline:
    """A digest-bound canonical projection of one persisted workflow."""

    workflow_id: int
    workflow_integrity_hash: str
    dataset: CanonicalDatasetSelection
    graph: ValidationGraph
    schema_version: str = _BASELINE_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {_LEGACY_BASELINE_VERSION, _BASELINE_VERSION}:
            raise CanonicalWorkbenchBaselineError("Canonical baseline uses an unsupported schema")

    def _identity_dict(self) -> dict[str, object]:
        dataset = self.dataset.as_dict()
        if self.schema_version == _LEGACY_BASELINE_VERSION:
            dataset.pop("group_column")
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_integrity_hash": self.workflow_integrity_hash,
            "dataset": dataset,
            "validation_graph": self.graph.as_dict(),
            # Search is intentionally unavailable in M4.15.  It becomes an
            # explicit closed contract in M4.16 rather than an ignored UI
            # payload that can acquire meaning later.
            "mutable_slots": [],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self._identity_dict())).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "baseline_digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CanonicalWorkbenchBaseline":
        """Re-admit a persisted, data-free baseline record.

        A managed campaign stores this closed record so a restart can verify
        its scientific authority without consulting the mutable workbench
        canvas.  This is deliberately not a shortcut around the normal saved
        workflow loader: a new admission still derives the record from the
        actor-owned workflow.  It is the durable-record counterpart used by
        the Runner immediately before execution.
        """

        if isinstance(payload, Mapping) and payload.get("schema_version") in {
            SEED_EXECUTION_BASELINE_VERSION,
            GROUPED_SEED_EXECUTION_BASELINE_VERSION,
        }:
            return CanonicalSeedExecutionBaseline.from_dict(payload)
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "workflow_id",
            "workflow_integrity_hash",
            "dataset",
            "validation_graph",
            "mutable_slots",
            "baseline_digest",
        }:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline uses an unsupported schema")
        schema_version = payload["schema_version"]
        if schema_version not in {_LEGACY_BASELINE_VERSION, _BASELINE_VERSION} or payload["mutable_slots"] != []:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline is not the current frozen authority")
        workflow_id = payload["workflow_id"]
        workflow_integrity_hash = payload["workflow_integrity_hash"]
        dataset_payload = payload["dataset"]
        if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id < 1:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline workflow identity is invalid")
        if not isinstance(workflow_integrity_hash, str) or _DIGEST.fullmatch(workflow_integrity_hash) is None:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline workflow hash is invalid")
        expected_dataset_fields = {
            "experiment_id",
            "file_id",
            "stage",
            "asset_id",
            "source_node_id",
            "target_authority",
        }
        if schema_version == _BASELINE_VERSION:
            expected_dataset_fields.add("group_column")
        if not isinstance(dataset_payload, Mapping) or set(dataset_payload) != expected_dataset_fields:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline dataset identity is invalid")
        experiment_id = dataset_payload["experiment_id"]
        file_id = dataset_payload["file_id"]
        stage = dataset_payload["stage"]
        asset_id = dataset_payload["asset_id"]
        source_node_id = dataset_payload["source_node_id"]
        group_column = dataset_payload.get("group_column")
        try:
            target_authority = admit_target_authority(dataset_payload["target_authority"], optional=False)
        except ValueError as exc:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline target authority is invalid") from exc
        assert target_authority is not None
        if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id < 1:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline experiment identity is invalid")
        if file_id is not None and (isinstance(file_id, bool) or not isinstance(file_id, int) or file_id < 1):
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline file identity is invalid")
        if not isinstance(stage, str) or stage not in _STAGES:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline stage is invalid")
        if asset_id is not None and (
            not isinstance(asset_id, str) or not asset_id or asset_id != asset_id.strip() or len(asset_id) > 255
        ):
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline asset identity is invalid")
        if not isinstance(source_node_id, str) or not source_node_id or len(source_node_id) > 128:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline source identity is invalid")
        if group_column is not None and (
            not isinstance(group_column, str)
            or not group_column.strip()
            or group_column != group_column.strip()
            or len(group_column) > 255
        ):
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline group identity is invalid")
        if not isinstance(payload["validation_graph"], Mapping):
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline graph is invalid")
        try:
            from spectra_sherpa.app.services.dag.validation_graph import validation_graph_from_dict

            graph = validation_graph_from_dict(payload["validation_graph"])
        except (TypeError, ValueError) as exc:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline graph cannot be re-admitted") from exc
        baseline = cls(
            workflow_id=workflow_id,
            workflow_integrity_hash=workflow_integrity_hash,
            dataset=CanonicalDatasetSelection(
                experiment_id=experiment_id,
                file_id=file_id,
                stage=stage,
                asset_id=asset_id,
                source_node_id=source_node_id,
                target_authority=target_authority,
                group_column=group_column,
            ),
            graph=graph,
            schema_version=schema_version,
        )
        if payload["baseline_digest"] != baseline.digest:
            raise CanonicalWorkbenchBaselineError("Persisted canonical baseline digest changed")
        return baseline


@dataclass(frozen=True, kw_only=True)
class CanonicalSeedExecutionBaseline(CanonicalWorkbenchBaseline):
    """A selected declarative seed with separately retained source custody.

    The inherited workflow identity names the source, not the selected graph.
    This distinct wire version makes that distinction explicit to every reader.
    """

    source_baseline: CanonicalWorkbenchBaseline
    seed_public_id: str
    seed_evidence_digest: str
    examination_digest: str
    saved_grouping: Mapping[str, object] | None = None
    schema_version: str = SEED_EXECUTION_BASELINE_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema_version not in {SEED_EXECUTION_BASELINE_VERSION, GROUPED_SEED_EXECUTION_BASELINE_VERSION}
            or not isinstance(self.source_baseline, CanonicalWorkbenchBaseline)
            or isinstance(self.source_baseline, CanonicalSeedExecutionBaseline)
            or self.workflow_id != self.source_baseline.workflow_id
            or self.workflow_integrity_hash != self.source_baseline.workflow_integrity_hash
            or self.dataset != self.source_baseline.dataset
            or not isinstance(self.graph, ValidationGraph)
        ):
            raise CanonicalWorkbenchBaselineError("Derived seed baseline changed its retained source custody")
        if not isinstance(self.seed_public_id, str) or not 1 <= len(self.seed_public_id) <= 64:
            raise CanonicalWorkbenchBaselineError("Derived seed identity is invalid")
        if any(
            not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            for value in (
                self.seed_evidence_digest,
                self.examination_digest,
            )
        ):
            raise CanonicalWorkbenchBaselineError("Derived seed evidence identity is invalid")
        if self.schema_version == SEED_EXECUTION_BASELINE_VERSION:
            if self.saved_grouping is not None:
                raise CanonicalWorkbenchBaselineError("Legacy derived seed cannot acquire grouping custody")
        else:
            read_saved_grouping(self.saved_grouping)

    def require_grouping(self, grouping: Mapping[str, object]) -> None:
        """Dispatch grouping authority without reinterpreting historical /1 records."""
        if self.schema_version == SEED_EXECUTION_BASELINE_VERSION:
            if grouping["grouped"] and grouping["column"] != self.dataset.group_column:
                raise CanonicalWorkbenchBaselineError("Legacy derived seed grouping changed")
        elif read_saved_grouping(self.saved_grouping)["grouping"] != dict(grouping):
            raise CanonicalWorkbenchBaselineError("Derived seed grouping custody changed")

    def _identity_dict(self) -> dict[str, object]:
        from spectra_sherpa.app.services.dag.managed_port_topology import managed_port_topology

        identity = {
            "schema_version": self.schema_version,
            "source_baseline": self.source_baseline.as_dict(),
            "seed_public_id": self.seed_public_id,
            "seed_evidence_digest": self.seed_evidence_digest,
            "examination_digest": self.examination_digest,
            "validation_graph": self.graph.as_dict(),
            "port_topology": managed_port_topology(
                [WorkflowNode(node.node_id, node.operation_id, dict(node.parameters)) for node in self.graph.nodes],
                [
                    WorkflowEdge(edge.from_node, edge.to_node, edge.from_output, edge.to_input)
                    for edge in self.graph.edges
                ],
            ),
        }
        if self.schema_version == GROUPED_SEED_EXECUTION_BASELINE_VERSION:
            identity["saved_grouping"] = read_saved_grouping(self.saved_grouping)
        return identity

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CanonicalSeedExecutionBaseline":
        from spectra_sherpa.app.services.dag.validation_graph import validation_graph_from_dict

        required = {
            "schema_version",
            "source_baseline",
            "seed_public_id",
            "seed_evidence_digest",
            "examination_digest",
            "validation_graph",
            "port_topology",
            "baseline_digest",
        }
        if isinstance(payload, Mapping) and payload.get("schema_version") == GROUPED_SEED_EXECUTION_BASELINE_VERSION:
            required.add("saved_grouping")
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise CanonicalWorkbenchBaselineError("Derived seed baseline fields are not closed")
        source_record = payload["source_baseline"]
        if not isinstance(source_record, Mapping) or source_record.get("schema_version") not in {
            _BASELINE_VERSION,
            _LEGACY_BASELINE_VERSION,
        }:
            raise CanonicalWorkbenchBaselineError("Derived seed requires one retained workbench source")
        source = CanonicalWorkbenchBaseline.from_dict(source_record)
        try:
            graph = validation_graph_from_dict(payload["validation_graph"])
            baseline = cls(
                workflow_id=source.workflow_id,
                workflow_integrity_hash=source.workflow_integrity_hash,
                dataset=source.dataset,
                graph=graph,
                source_baseline=source,
                seed_public_id=payload["seed_public_id"],
                seed_evidence_digest=payload["seed_evidence_digest"],
                examination_digest=payload["examination_digest"],
                schema_version=payload["schema_version"],
                saved_grouping=payload.get("saved_grouping"),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalWorkbenchBaselineError("Derived seed cannot be re-admitted") from exc
        if dict(payload) != baseline.as_dict():
            raise CanonicalWorkbenchBaselineError("Derived seed baseline or port topology changed")
        return baseline


def read_saved_grouping(payload: object) -> dict[str, object]:
    """Read the data-free custody wrapper; the host separately reproduces it."""
    from copy import deepcopy

    fields = {
        "schema_version",
        "projection_version",
        "projection_digest",
        "retained_definition_digest",
        "grouping",
        "grouping_digest",
        "custody_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise CanonicalWorkbenchBaselineError("Saved grouping custody fields are not closed")
    if payload["schema_version"] != "spectra-saved-run-grouping/1" or payload["projection_version"] not in {
        "spectra-saved-run-optimization-projection/1",
        "spectra-saved-run-optimization-projection/2",
        "spectra-saved-run-optimization-projection/3",
    }:
        raise CanonicalWorkbenchBaselineError("Saved grouping custody version is unsupported")
    if any(
        not isinstance(payload[key], str) or _DIGEST.fullmatch(payload[key]) is None
        for key in ("projection_digest", "retained_definition_digest", "grouping_digest", "custody_digest")
    ):
        raise CanonicalWorkbenchBaselineError("Saved grouping custody digest is invalid")
    grouping = payload["grouping"]
    if not isinstance(grouping, Mapping) or set(grouping) != {
        "schema_version",
        "mode",
        "column",
        "grouped",
        "dataset_content_digest",
    }:
        raise CanonicalWorkbenchBaselineError("Saved grouping fields are not closed")
    column = grouping["column"]
    if (
        grouping["schema_version"] != "spectra-development-grouping/1"
        or grouping["mode"] not in {"required_column", "no_grouping_declared"}
        or type(grouping["grouped"]) is not bool
        or grouping["grouped"] != (grouping["mode"] == "required_column")
        or (column is not None) != grouping["grouped"]
        or (
            column is not None
            and (not isinstance(column, str) or not column or column != column.strip() or len(column) > 255)
        )
        or not isinstance(grouping["dataset_content_digest"], str)
        or _DIGEST.fullmatch(grouping["dataset_content_digest"]) is None
    ):
        raise CanonicalWorkbenchBaselineError("Saved grouping identity is invalid")

    def custody_digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()

    if (
        custody_digest(dict(grouping)) != payload["grouping_digest"]
        or custody_digest({k: v for k, v in payload.items() if k != "custody_digest"}) != payload["custody_digest"]
    ):
        raise CanonicalWorkbenchBaselineError("Saved grouping custody digest changed")
    return deepcopy(dict(payload))


def canonical_workbench_baseline_from_records(
    *,
    workflow_id: int,
    stored_integrity_hash: str | None,
    nodes: Sequence[Any],
    edges: Sequence[Any],
) -> CanonicalWorkbenchBaseline:
    """Validate persisted workflow records without trusting a mutable canvas.

    This pure-record seam is also the contract exercised by the database
    loader.  It keeps the security property testable without a route fixture:
    the caller supplies records, never a pre-projected validation graph.
    """

    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id < 1:
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow identity is invalid")
    if not isinstance(stored_integrity_hash, str) or _DIGEST.fullmatch(stored_integrity_hash) is None:
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow has no valid integrity hash")

    workflow_nodes = [
        WorkflowNode(str(node.node_id), str(node.node_type), _require_parameters(node.parameters)) for node in nodes
    ]
    workflow_edges = [
        WorkflowEdge(
            str(edge.from_node_id),
            str(edge.to_node_id),
            str(edge.from_output),
            str(edge.to_input),
        )
        for edge in edges
    ]
    recomputed = compute_workflow_hash(
        [
            {"node_id": node.node_id, "node_type": node.node_type, "parameters": dict(node.parameters)}
            for node in workflow_nodes
        ],
        [
            {
                "from_node_id": edge.from_node,
                "to_node_id": edge.to_node,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in workflow_edges
        ],
    )
    if recomputed != stored_integrity_hash:
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow integrity no longer matches its persisted DAG")

    try:
        preflight = preflight_workflow(workflow_nodes, workflow_edges)
    except ValueError as exc:
        raise CanonicalWorkbenchBaselineError(
            "Saved workbench workflow contains invalid canonical node parameters"
        ) from exc
    if not preflight.is_valid:
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow does not pass semantic preflight")

    sources = [node for node in workflow_nodes if node.node_type in {"data.file_load", "data.load_group"}]
    if len(sources) != 1:
        raise CanonicalWorkbenchBaselineError("Managed baseline requires exactly one admitted data source node")
    source = sources[0]
    excluded_node_ids = {source.node_id}
    boundary_node_id = source.node_id
    if source.node_type == "data.load_group":
        source_outputs = [edge for edge in workflow_edges if edge.from_node == source.node_id]
        if len(source_outputs) != 1:
            raise CanonicalWorkbenchBaselineError("Managed collection source must feed one supervision node")
        source_supervision_edge = source_outputs[0]
        supervision = next(
            (node for node in workflow_nodes if node.node_id == source_supervision_edge.to_node),
            None,
        )
        if supervision is None or supervision.node_type != "data.attach_target":
            raise CanonicalWorkbenchBaselineError(
                "Managed collection source requires one sample-table supervision node"
            )
        supervision_inputs = [edge for edge in workflow_edges if edge.to_node == supervision.node_id]
        if (
            supervision_inputs != [source_supervision_edge]
            or source_supervision_edge.from_output != "default"
            or source_supervision_edge.to_input != "X"
        ):
            raise CanonicalWorkbenchBaselineError(
                "Managed collection supervision requires the exact source default-to-X edge"
            )
        dataset = _collection_dataset_selection(source, supervision)
        excluded_node_ids.add(supervision.node_id)
        boundary_node_id = supervision.node_id
    else:
        dataset = _dataset_selection(source)

    incoming = {node.node_id: 0 for node in workflow_nodes if node.node_id not in excluded_node_ids}
    boundary_edges = []
    scientific_edges: list[WorkflowEdge] = []
    for edge in workflow_edges:
        if edge.to_node == source.node_id:
            raise CanonicalWorkbenchBaselineError("Managed baseline source node cannot have an input")
        if edge.from_node == boundary_node_id:
            boundary_edges.append(edge)
        elif edge.from_node in excluded_node_ids or edge.to_node in excluded_node_ids:
            continue
        else:
            scientific_edges.append(edge)
            if edge.to_node in incoming:
                incoming[edge.to_node] += 1
    if len(boundary_edges) != 1:
        raise CanonicalWorkbenchBaselineError("Managed baseline data boundary must feed exactly one scientific root")

    scientific_nodes = [node for node in workflow_nodes if node.node_id not in excluded_node_ids]
    if not scientific_nodes:
        raise CanonicalWorkbenchBaselineError("Managed baseline must include a scientific candidate graph")
    root_ids = {node_id for node_id, count in incoming.items() if count == 0}
    if boundary_edges[0].to_node not in root_ids:
        raise CanonicalWorkbenchBaselineError("Managed baseline source must feed the canonical graph root")
    try:
        graph = admit_validation_graph(scientific_nodes, scientific_edges)
    except ValidationRuntimeAttestationError:
        raise
    except ValueError as exc:
        raise CanonicalWorkbenchBaselineError(
            "Saved workbench workflow is outside the managed first-party profile"
        ) from exc
    return CanonicalWorkbenchBaseline(
        workflow_id=workflow_id,
        workflow_integrity_hash=stored_integrity_hash,
        dataset=dataset,
        graph=graph,
    )


def _require_parameters(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CanonicalWorkbenchBaselineError("Saved workbench node parameters must be a JSON object")
    return dict(value)


def _dataset_selection(source: WorkflowNode) -> CanonicalDatasetSelection:
    parameters = source.parameters
    if set(parameters) - {"experiment_id", "file_id", "stage", "asset_id", "target_authority"}:
        raise CanonicalWorkbenchBaselineError("Managed baseline source has undeclared data binding parameters")
    experiment_id = parameters.get("experiment_id")
    file_id = parameters.get("file_id")
    stage = parameters.get("stage", "raw")
    asset_id = parameters.get("asset_id")
    try:
        target_authority = admit_target_authority(parameters.get("target_authority"), optional=False)
    except ValueError as exc:
        raise CanonicalWorkbenchBaselineError("Managed baseline source target authority is invalid") from exc
    assert target_authority is not None
    if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id < 1:
        raise CanonicalWorkbenchBaselineError("Managed baseline source experiment ID is invalid")
    if file_id is not None and (isinstance(file_id, bool) or not isinstance(file_id, int) or file_id < 1):
        raise CanonicalWorkbenchBaselineError("Managed baseline source file ID is invalid")
    if not isinstance(stage, str) or stage not in _STAGES:
        raise CanonicalWorkbenchBaselineError("Managed baseline source stage is invalid")
    if asset_id is not None and (
        not isinstance(asset_id, str) or not asset_id or asset_id != asset_id.strip() or len(asset_id) > 255
    ):
        raise CanonicalWorkbenchBaselineError("Managed baseline source asset identity is invalid")
    return CanonicalDatasetSelection(
        experiment_id=experiment_id,
        file_id=file_id,
        stage=stage,
        asset_id=asset_id,
        source_node_id=source.node_id,
        target_authority=target_authority,
    )


def _collection_dataset_selection(
    source: WorkflowNode,
    supervision: WorkflowNode,
) -> CanonicalDatasetSelection:
    parameters = source.parameters
    allowed_source = {
        "source_mode",
        "folder_path",
        "pattern",
        "recursive",
        "sort_by",
        "group_title",
        "asset_id",
        "experiment_id",
        "stage",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
    }
    if set(parameters) - allowed_source:
        raise CanonicalWorkbenchBaselineError("Managed collection source has undeclared binding parameters")
    if (
        parameters.get("source_mode") != "experiment_collection"
        or parameters.get("folder_path", "") != ""
        or parameters.get("pattern", "") != ""
        or parameters.get("recursive", False) is not False
        or parameters.get("sort_by", "filename") != "filename"
    ):
        raise CanonicalWorkbenchBaselineError("Managed collection source is not an exact experiment collection")
    experiment_id = parameters.get("experiment_id")
    stage = parameters.get("stage", "raw")
    asset_id = parameters.get("asset_id")
    if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id < 1:
        raise CanonicalWorkbenchBaselineError("Managed collection source experiment ID is invalid")
    if not isinstance(stage, str) or stage not in _STAGES:
        raise CanonicalWorkbenchBaselineError("Managed collection source stage is invalid")
    if asset_id is not None and (
        not isinstance(asset_id, str) or not asset_id or asset_id != asset_id.strip() or len(asset_id) > 255
    ):
        raise CanonicalWorkbenchBaselineError("Managed collection source asset identity is invalid")
    for name in (
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
    ):
        value = parameters.get(name)
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise CanonicalWorkbenchBaselineError(f"Managed collection source {name} is invalid")

    supervision_parameters = supervision.parameters
    if set(supervision_parameters) != {
        "target_source",
        "target_type",
        "target_column",
        "group_column",
        "target_authority",
    }:
        raise CanonicalWorkbenchBaselineError("Managed collection supervision parameters are not closed")
    try:
        target_authority = admit_target_authority(supervision_parameters.get("target_authority"), optional=False)
    except ValueError as exc:
        raise CanonicalWorkbenchBaselineError("Managed collection supervision target authority is invalid") from exc
    assert target_authority is not None
    group_column = supervision_parameters.get("group_column")
    if supervision_parameters.get("target_source") != "sample_table_column":
        raise CanonicalWorkbenchBaselineError("Managed collection supervision must use the sample table")
    if supervision_parameters.get("target_column") != target_authority.column:
        raise CanonicalWorkbenchBaselineError("Managed collection supervision target is invalid")
    if supervision_parameters.get("target_type") != target_authority.target_type:
        raise CanonicalWorkbenchBaselineError("Managed collection supervision target type is invalid")
    if not isinstance(group_column, str) or not group_column.strip() or len(group_column) > 255:
        raise CanonicalWorkbenchBaselineError("Managed collection supervision group is invalid")
    return CanonicalDatasetSelection(
        experiment_id=experiment_id,
        file_id=None,
        stage=stage,
        asset_id=asset_id,
        source_node_id=source.node_id,
        target_authority=target_authority,
        group_column=group_column,
    )


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalWorkbenchBaselineError("Managed baseline must be finite JSON") from exc


__all__ = [
    "CanonicalDatasetSelection",
    "CanonicalWorkbenchBaseline",
    "CanonicalWorkbenchBaselineError",
    "canonical_workbench_baseline_from_records",
]
