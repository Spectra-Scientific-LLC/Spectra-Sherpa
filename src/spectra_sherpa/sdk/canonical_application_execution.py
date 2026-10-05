"""Execute one verified canonical application plan through the typed DAG.

This module owns orchestration only.  It contains no preprocessing, model, or
metric formula: the plan's registered application operations remain the sole
scientific authorities and :class:`~spectra_sherpa.app.services.dag.executor.DAGExecutor`
remains the sole ordinary application executor.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .canonical_application import CanonicalApplicationPlan
from .deployment import DEPLOYMENT_INPUT_SCHEMA
from .runtime import CanonicalSDKExecution, execute_workflow_async
from .workflow import WorkflowSpec, workflow_spec

_INPUT_NODE_ID = "canonical.application.input"
_INPUT_STREAM_NAME = "canonical-application-input"


def application_workflow(plan: CanonicalApplicationPlan) -> WorkflowSpec:
    """Project a verified linear application plan into one executable DAG."""

    if not isinstance(plan, CanonicalApplicationPlan):
        raise TypeError("canonical application execution requires a verified application plan")
    application_nodes = plan.payload["nodes"]
    if any(node["node_id"] == _INPUT_NODE_ID for node in application_nodes):
        raise ValueError("canonical application plan collides with its reserved input node")

    nodes = [
        {
            "node_id": _INPUT_NODE_ID,
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": _INPUT_STREAM_NAME,
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
        },
        *[
            {
                "node_id": node["node_id"],
                "node_type": node["application_operation_id"],
                "parameters": dict(node.get("artifact_binding") or node["parameters"]),
            }
            for node in application_nodes
        ],
    ]
    edges = [
        {
            "from_node_id": _INPUT_NODE_ID,
            "to_node_id": application_nodes[0]["node_id"],
            "from_output": "default",
            "to_input": "default",
        },
        *[dict(edge) for edge in plan.payload["edges"]],
    ]
    return workflow_spec(nodes=nodes, edges=edges)


async def execute_canonical_application(
    plan: CanonicalApplicationPlan,
    input_data: Any,
    *,
    runtime: ExecutionRuntime,
    uncertainty_record: Any = None,
    uncertainty_population: str | None = None,
) -> CanonicalSDKExecution:
    """Execute an artifact-bound application plan through the canonical DAG."""

    if not isinstance(runtime, ExecutionRuntime):
        raise TypeError("canonical application execution requires an explicit runtime")
    from .prediction_uncertainty import BoundPredictionUncertainty, UncertaintyRecord

    if uncertainty_record is None and uncertainty_population is not None:
        raise ValueError("Population declaration requires an uncertainty record")
    provider = (
        None
        if uncertainty_record is None
        else BoundPredictionUncertainty.bind(UncertaintyRecord.load(uncertainty_record), plan, uncertainty_population)
    )
    runtime = replace(runtime, prediction_uncertainty=provider)
    return await execute_workflow_async(
        application_workflow(plan),
        deployment_inputs={_INPUT_STREAM_NAME: input_data},
        runtime=runtime,
    )


__all__ = ["application_workflow", "execute_canonical_application"]
