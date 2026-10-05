"""Shared executor for scientist-facing New Analysis project proofs.

The helper deliberately contains no scientific operations.  It loads the
same template shown in the workbench, binds exact source-node identities, and
executes the persisted node/edge vocabulary through :class:`DAGExecutor`.
Project tests remain responsible for interpreting the resulting scientific
outputs; merely completing a graph is not qualification evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    NodeStatus,
    WorkflowEdge,
    WorkflowNode,
)
from spectra_sherpa.app.services.model_store import get_model_store
from spectra_sherpa.core.execution_runtime import (
    DatasetSourceResolver,
    ExecutionCapabilityError,
    ExecutionRuntime,
    ResolvedExperimentCollection,
    ResolvedExperimentFile,
    ResolvedNistLibraryEntry,
)


@dataclass(frozen=True)
class ConsumerProjectSource:
    """One test-owned source binding and its already-authorized exact file."""

    parameters: Mapping[str, Any]
    resolved_file: ResolvedExperimentFile

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


class _ExactFileSourceResolver(DatasetSourceResolver):
    """Resolve only the exact experiment files granted by one project proof."""

    def __init__(self, sources: Mapping[str, ConsumerProjectSource]) -> None:
        records: dict[tuple[int, int, str], ResolvedExperimentFile] = {}
        for source in sources.values():
            key = (
                int(source.parameters["experiment_id"]),
                int(source.parameters["file_id"]),
                str(source.parameters["stage"]),
            )
            if key in records:
                raise AssertionError(f"duplicate exact consumer-project source identity {key!r}")
            records[key] = source.resolved_file
        self._records = MappingProxyType(records)

    async def resolve_experiment_file(
        self,
        *,
        experiment_id: int,
        file_id: int,
        stage: str,
    ) -> ResolvedExperimentFile:
        key = (experiment_id, file_id, stage)
        try:
            return self._records[key]
        except KeyError as exc:
            raise ExecutionCapabilityError(f"consumer-project source identity is not granted: {key!r}") from exc

    async def resolve_experiment_collection(self, *, experiment_id: int) -> ResolvedExperimentCollection:
        raise ExecutionCapabilityError(
            f"consumer-project proof does not grant experiment-collection access: {experiment_id}"
        )

    async def resolve_nist_library_entry(self, *, library_id: int) -> ResolvedNistLibraryEntry:
        raise ExecutionCapabilityError(f"consumer-project proof does not grant NIST-library access: {library_id}")


@dataclass(frozen=True)
class ConsumerProjectRun:
    """One exact template execution and its retained runtime evidence."""

    executor: DAGExecutor
    results: Mapping[str, Any]
    slug: str
    template: Mapping[str, Any]

    @property
    def node_types(self) -> dict[str, str]:
        return {str(node["node_id"]): str(node["node_type"]) for node in self.template["nodes"]}


def load_consumer_project(slug: str) -> dict[str, Any]:
    """Load one exact workbench template by its public slug."""

    templates = {str(entry["slug"]): dict(entry["template_data"]) for entry in TemplateLoader().load_all()}
    try:
        return templates[slug]
    except KeyError as exc:
        raise AssertionError(f"unknown consumer project {slug!r}") from exc


async def execute_consumer_project(
    slug: str,
    *,
    source_parameters: Mapping[str, ConsumerProjectSource],
) -> ConsumerProjectRun:
    """Execute one exact workbench project with explicit source identities."""

    template = load_consumer_project(slug)
    node_ids = {str(node["node_id"]) for node in template["nodes"]}
    source_ids = {str(node["node_id"]) for node in template["nodes"] if node["node_type"] == "data.file_load"}
    unknown_sources = sorted(set(source_parameters) - node_ids)
    if unknown_sources:
        raise AssertionError(f"consumer project {slug!r} has no source nodes {unknown_sources}")
    non_source_bindings = sorted(set(source_parameters) - source_ids)
    missing_source_bindings = sorted(source_ids - set(source_parameters))
    if non_source_bindings or missing_source_bindings:
        raise AssertionError(
            f"consumer project {slug!r} source bindings are not exact: "
            f"non_sources={non_source_bindings}, missing={missing_source_bindings}"
        )

    invalid_bindings = sorted(
        node_id for node_id, source in source_parameters.items() if not isinstance(source, ConsumerProjectSource)
    )
    if invalid_bindings:
        raise AssertionError(
            f"consumer project {slug!r} source bindings lack explicit resolved files: {invalid_bindings}"
        )

    # Consumer-project proofs exercise fitted producers and application-owned
    # files. Their caller grants both capabilities explicitly. The autouse
    # fixture owns the temporary artifact store and each source fixture owns
    # its exact resolved file; the scientific executor discovers neither.
    executor = DAGExecutor(
        process_pool=None,
        runtime=ExecutionRuntime(
            model_artifact_writer=get_model_store(),
            dataset_source_resolver=_ExactFileSourceResolver(source_parameters),
        ),
    )

    for raw_node in template["nodes"]:
        node = dict(raw_node)
        node_id = str(node["node_id"])
        parameters = dict(node.get("parameters", {}))
        if node_id in source_parameters:
            parameters.update(source_parameters[node_id].parameters)
        executor.add_node(
            WorkflowNode(
                node_id=node_id,
                node_type=str(node["node_type"]),
                parameters=parameters,
            )
        )
    for raw_edge in template["edges"]:
        edge = dict(raw_edge)
        executor.add_edge(
            WorkflowEdge(
                from_node=str(edge["from_node_id"]),
                to_node=str(edge["to_node_id"]),
                from_output=str(edge.get("from_output", "default")),
                to_input=str(edge.get("to_input", "default")),
            )
        )

    errors = executor.validate_full().to_error_strings()
    if errors:
        raise AssertionError(f"consumer project {slug!r} failed semantic preflight:\n" + "\n".join(errors))
    results = await executor.execute()
    unexpected = {
        node_id: node.status.value
        for node_id, node in executor.nodes.items()
        if node.status is not NodeStatus.COMPLETED
    }
    if unexpected:
        raise AssertionError(f"consumer project {slug!r} has incomplete nodes: {unexpected}")
    return ConsumerProjectRun(
        executor=executor,
        results=results,
        slug=slug,
        template=template,
    )
