"""Execute public SDK calls through the current canonical typed DAG.

The SDK does not own a second scientific runtime. Local arrays cross the same
``deploy.input`` admission boundary used by the prediction application, and
every operation is created by the node registry and run by ``DAGExecutor``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import io
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .deployment import DEPLOYMENT_INPUT_SCHEMA, admit_deployment_input
from .workflow import WorkflowSpec, workflow_spec

_SOURCE_PREFIX = "sdk.source"
_OPERATION_NODE_ID = "sdk.operation"


@dataclass(frozen=True)
class CanonicalSDKExecution:
    """One completed local DAG run with content-addressed input identities."""

    workflow: WorkflowSpec
    results: Mapping[str, Any]
    diagnostics: Mapping[str, Mapping[str, Any]]
    dataset_content_digests: Mapping[str, str]
    artifacts: tuple[Mapping[str, Any], ...]

    def output(self, node_id: str = _OPERATION_NODE_ID, port: str = "default") -> Any:
        """Return one named output from a completed canonical node."""

        if node_id not in self.results:
            raise KeyError(f"canonical execution has no result for node {node_id!r}")
        value = self.results[node_id]
        if isinstance(value, Mapping):
            if port not in value:
                raise KeyError(f"canonical node {node_id!r} has no output port {port!r}")
            return value[port]
        if port != "default":
            raise KeyError(f"canonical node {node_id!r} has only its default output")
        return value


@dataclass(frozen=True)
class _DatasetBinding:
    port: str
    node_id: str
    stream_name: str
    content_digest: str
    dataset: Any


class _MemoryModelArtifactWriter:
    """Run-scoped artifact sink for SDK operations that emit model artifacts.

    Canonical node execution is fail-closed when a model-producing node has no
    writer. The SDK therefore grants a bounded in-memory writer rather than
    bypassing executor persistence or creating an undeclared filesystem store.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]] = {}

    def save(self, artifact_uid: str, manifest: dict[str, Any], arrays: dict[str, Any]) -> str:
        normalized = {name: np.asarray(value).copy() for name, value in arrays.items()}
        payload = io.BytesIO()
        np.savez_compressed(payload, **normalized)
        digest = hashlib.sha256(payload.getvalue()).hexdigest()
        stored_manifest = dict(manifest)
        stored_manifest["integrity_hash"] = digest
        self._artifacts[artifact_uid] = (stored_manifest, normalized)
        return digest

    def artifact_directory(self, artifact_uid: str) -> str:
        if artifact_uid not in self._artifacts:
            raise KeyError(f"SDK artifact {artifact_uid!r} was not written")
        return f"memory://spectra-sherpa-sdk/{artifact_uid}"


def _bind_dataset(port: str, value: Any, *, ordinal: int) -> _DatasetBinding:
    dataset = admit_deployment_input(
        value,
        stream_name=f"sdk-{port}",
        schema_version=DEPLOYMENT_INPUT_SCHEMA,
    )
    supervision = admit_attached_sample_table_supervision(dataset)
    capability = SpectralDatasetCapability.from_dataset(
        dataset,
        custody_id="sdk-local",
        dataset_ref_digest=None if supervision is None else supervision.digest,
        groups=None if supervision is None else supervision.groups,
    )
    digest = capability.content_digest
    return _DatasetBinding(
        port=port,
        node_id=f"{_SOURCE_PREFIX}.{ordinal}",
        stream_name=f"sdk-{port}-{digest[:16]}",
        content_digest=digest,
        # Copy the typed dataset so caller mutation cannot race execution. The
        # capability owns the content digest; retaining this copy also keeps
        # presentation metadata (for example data units) that is outside the
        # bounded managed capability projection.
        dataset=dataset.copy(),
    )


def operation_workflow(
    node_type: str,
    *,
    parameters: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any],
) -> tuple[WorkflowSpec, Mapping[str, Any], Mapping[str, str]]:
    """Construct one registry-admitted operation DAG and its exact inputs."""

    if not isinstance(node_type, str) or not node_type:
        raise ValueError("canonical SDK operation requires a non-empty node_type")
    if not isinstance(inputs, Mapping) or not inputs:
        raise ValueError("canonical SDK operation requires at least one typed input")
    if not all(isinstance(port, str) and port for port in inputs):
        raise ValueError("canonical SDK input ports must be non-empty strings")

    bindings = tuple(
        _bind_dataset(port, value, ordinal=index) for index, (port, value) in enumerate(sorted(inputs.items()))
    )
    nodes = [
        {
            "node_id": binding.node_id,
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": binding.stream_name,
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
        }
        for binding in bindings
    ]
    nodes.append(
        {
            "node_id": _OPERATION_NODE_ID,
            "node_type": node_type,
            "parameters": dict(parameters or {}),
        }
    )
    edges = [
        {
            "from_node_id": binding.node_id,
            "to_node_id": _OPERATION_NODE_ID,
            "from_output": "default",
            "to_input": binding.port,
        }
        for binding in bindings
    ]
    spec = workflow_spec(nodes=nodes, edges=edges)
    payloads = MappingProxyType({binding.stream_name: binding.dataset for binding in bindings})
    digests = MappingProxyType({binding.stream_name: binding.content_digest for binding in bindings})
    return spec, payloads, digests


async def execute_workflow_async(
    workflow: WorkflowSpec,
    *,
    deployment_inputs: Mapping[str, Any],
    runtime: ExecutionRuntime | None = None,
) -> CanonicalSDKExecution:
    """Execute a current workflow whose external inputs are explicit.

    Only ``deploy.input`` sources may be injected. Application-owned data
    nodes require application capabilities and remain the responsibility of
    the Workbench route that supplies those capabilities.
    """

    if not isinstance(workflow, WorkflowSpec):
        raise TypeError("execute_workflow_async requires a verified WorkflowSpec")
    if not isinstance(deployment_inputs, Mapping):
        raise TypeError("deployment_inputs must be a mapping keyed by stream name")

    executor = DAGExecutor(runtime=runtime or ExecutionRuntime(model_artifact_writer=_MemoryModelArtifactWriter()))
    for node in workflow.payload["nodes"]:
        executor.add_node(
            WorkflowNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=dict(node["parameters"]),
            )
        )
    for edge in workflow.payload["edges"]:
        executor.add_edge(
            WorkflowEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge["from_output"],
                to_input=edge["to_input"],
            )
        )

    for node_id in executor.find_entry_nodes():
        node = executor.nodes[node_id]
        if node.metadata is None or node.metadata.node_type != "deploy.input":
            node_type = None if node.metadata is None else node.metadata.node_type
            raise ValueError(
                "public SDK execution admits only explicit deploy.input sources; "
                f"entry node {node_id!r} is {node_type!r}"
            )

    declared: dict[str, tuple[str, str]] = {}
    for node_id, node in executor.nodes.items():
        if node.metadata is None or node.metadata.node_type != "deploy.input":
            continue
        stream_name = str(node.parameters.get("stream_name", ""))
        if stream_name in declared:
            raise ValueError(f"SDK workflow repeats deployment stream {stream_name!r}")
        declared[stream_name] = (node_id, stream_name)
    if set(deployment_inputs) != set(declared):
        missing = sorted(set(declared) - set(deployment_inputs))
        unexpected = sorted(set(deployment_inputs) - set(declared))
        raise ValueError(
            "SDK deployment input set does not match workflow " f"(missing={missing}, unexpected={unexpected})"
        )

    content_digests: dict[str, str] = {}
    for stream_name, (node_id, declared_name) in declared.items():
        binding = _bind_dataset("input", deployment_inputs[stream_name], ordinal=0)
        executor.inject_deployment_input(node_id, binding.dataset, stream_name=declared_name)
        content_digests[stream_name] = binding.content_digest

    results = await executor.execute()
    return CanonicalSDKExecution(
        workflow=workflow,
        results=MappingProxyType(dict(results)),
        diagnostics=MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in executor.diagnostics.items()}
        ),
        dataset_content_digests=MappingProxyType(content_digests),
        artifacts=tuple(MappingProxyType(dict(artifact)) for artifact in executor.saved_artifacts),
    )


def execute_workflow(
    workflow: WorkflowSpec,
    *,
    deployment_inputs: Mapping[str, Any],
    runtime: ExecutionRuntime | None = None,
) -> CanonicalSDKExecution:
    """Synchronous public bridge to :func:`execute_workflow_async`."""

    return _run_async(execute_workflow_async(workflow, deployment_inputs=deployment_inputs, runtime=runtime))


def execute_operation(
    node_type: str,
    *,
    parameters: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any],
    runtime: ExecutionRuntime | None = None,
) -> CanonicalSDKExecution:
    """Construct and execute one canonical operation DAG."""

    workflow, payloads, expected_digests = operation_workflow(
        node_type,
        parameters=parameters,
        inputs=inputs,
    )
    execution = execute_workflow(workflow, deployment_inputs=payloads, runtime=runtime)
    if dict(execution.dataset_content_digests) != dict(expected_digests):
        raise RuntimeError("canonical SDK dataset identity changed across execution admission")
    return execution


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


__all__ = [
    "CanonicalSDKExecution",
    "execute_operation",
    "execute_workflow",
    "execute_workflow_async",
    "operation_workflow",
]
