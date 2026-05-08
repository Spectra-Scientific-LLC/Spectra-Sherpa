"""
Built-in workflow inspection tools.

These tools let the LLM inspect and validate the user's current
workflow state without requiring raw data egress.
"""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory

MAX_DESCRIBE_NODE_TYPES = 12
MAX_DESCRIPTION_CHARS = 140


def _compact_text(value: str | None, *, limit: int = MAX_DESCRIPTION_CHARS) -> str | None:
    if not value:
        return None
    compacted = " ".join(str(value).split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def _node_type(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or node.get("type") or "")


def _node_parameters(node: dict[str, Any]) -> dict[str, Any]:
    params = node.get("parameters") or node.get("params") or {}
    return params if isinstance(params, dict) else {}


def _edge_source(edge: dict[str, Any]) -> str:
    return str(edge.get("from_node_id") or edge.get("source") or "")


def _edge_target(edge: dict[str, Any]) -> str:
    return str(edge.get("to_node_id") or edge.get("target") or "")


def _edge_from_output(edge: dict[str, Any]) -> str:
    return str(edge.get("from_output") or "default")


def _edge_to_input(edge: dict[str, Any]) -> str:
    return str(edge.get("to_input") or "default")


def _issue(
    severity: str,
    message: str,
    node_id: str | None = None,
    port: str | None = None,
    code: str | None = None,
) -> dict[str, str]:
    payload = {"severity": severity, "message": message}
    if node_id:
        payload["node_id"] = node_id
    if port:
        payload["port"] = port
    if code:
        payload["code"] = code
    return payload


def _normalize_dag_spec(dag_spec: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if hasattr(dag_spec, "model_dump"):
        dag_spec = dag_spec.model_dump()
    nodes = []
    for node in dag_spec.get("nodes", []):
        nodes.append(
            {
                "node_id": _node_id(node),
                "node_type": _node_type(node),
                "parameters": _node_parameters(node),
                "position": node.get("position"),
            }
        )

    edges = []
    for edge in dag_spec.get("edges", []):
        edges.append(
            {
                "from_node_id": _edge_source(edge),
                "to_node_id": _edge_target(edge),
                "from_output": _edge_from_output(edge),
                "to_input": _edge_to_input(edge),
            }
        )
    return nodes, edges


def _data_loader_fingerprints(nodes: list[dict[str, Any]]) -> set[str]:
    from spectra_sherpa.app.services.project_data_sources import describe_node_data_source

    fingerprints: set[str] = set()
    for node in nodes:
        candidate = describe_node_data_source(node)
        if candidate is not None:
            fingerprints.add(candidate.fingerprint)
    return fingerprints


def substitute_parent_data_loaders(dag_spec: Any, parent_nodes: list[Any]) -> None:
    """Replace LLM-emitted loader params with the parent's verbatim, in place.

    The agentic prompt instructs the model to copy parent data-loader nodes
    verbatim, but cheaper models (Haiku 4.5 and below) drift on loader
    params — most commonly omitting ``stage`` so it defaults to ``"raw"`` —
    which flips the data-source fingerprint and fails parent-inheritance
    validation. Substituting params from the matching parent loader (by
    node-type, in workflow order) makes the agentic feature robust to
    loader-param drift regardless of which model proposed the DAG.

    Mutates ``dag_spec`` in place. Accepts both Pydantic ``WorkflowDagSpec``
    instances (route-handler path) and plain dicts (LLM tool path).
    """
    from spectra_sherpa.app.services.project_data_sources import _node_value, describe_node_data_source

    parent_fingerprints = {
        candidate.fingerprint
        for parent_node in parent_nodes
        if (candidate := describe_node_data_source(parent_node)) is not None
    }
    if not parent_fingerprints:
        return

    parent_pool: dict[str, list[dict[str, Any]]] = {}
    for parent_node in parent_nodes:
        if describe_node_data_source(parent_node) is None:
            continue
        node_type = _node_value(parent_node, "node_type", None) or _node_value(parent_node, "type", None)
        if not node_type:
            continue
        params = _node_value(parent_node, "parameters", None) or _node_value(parent_node, "params", None) or {}
        parent_pool.setdefault(str(node_type), []).append(dict(params))

    proposed_nodes = dag_spec.nodes if hasattr(dag_spec, "nodes") else dag_spec.get("nodes", [])
    for proposed_node in proposed_nodes:
        candidate = describe_node_data_source(proposed_node)
        if candidate is None or candidate.fingerprint in parent_fingerprints:
            continue
        node_type = _node_value(proposed_node, "type", None) or _node_value(proposed_node, "node_type", None)
        pool = parent_pool.get(str(node_type)) if node_type else None
        if not pool:
            continue
        substituted = pool.pop(0)
        if hasattr(proposed_node, "parameters"):
            proposed_node.parameters = substituted
        elif isinstance(proposed_node, dict):
            proposed_node["parameters"] = substituted


def _partition_outputs_upstream_of(
    node_id: str,
    node_types: dict[str, str],
    edges: list[dict[str, Any]],
    *,
    skip_inputs: set[str] | None = None,
) -> set[str]:
    """Return sample-partition outputs feeding a node's main branch."""
    skip_inputs = skip_inputs or set()
    incoming: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        incoming.setdefault(edge["to_node_id"], []).append(edge)

    outputs: set[str] = set()
    stack = [node_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for edge in incoming.get(current, []):
            if edge["to_input"] in skip_inputs:
                continue
            source = edge["from_node_id"]
            if node_types.get(source) == "selection.sample_partition":
                outputs.add(edge["from_output"])
            else:
                stack.append(source)
    return outputs


def _has_edge(
    edges: list[dict[str, Any]],
    *,
    source: str,
    target: str,
    from_output: str | None = None,
    to_input: str | None = None,
) -> bool:
    for edge in edges:
        if edge["from_node_id"] != source or edge["to_node_id"] != target:
            continue
        if from_output is not None and edge["from_output"] != from_output:
            continue
        if to_input is not None and edge["to_input"] != to_input:
            continue
        return True
    return False


def _partition_outputs_feeding_input(
    target_id: str,
    input_name: str,
    node_types: dict[str, str],
    edges: list[dict[str, Any]],
) -> set[str]:
    outputs: set[str] = set()
    for edge in edges:
        if edge["to_node_id"] != target_id or edge["to_input"] != input_name:
            continue
        source = edge["from_node_id"]
        if node_types.get(source) == "selection.sample_partition":
            outputs.add(edge["from_output"])
        else:
            outputs.update(_partition_outputs_upstream_of(source, node_types, edges, skip_inputs={"reference"}))
    return outputs


def _validate_holdout_classification_topology(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Reject structurally valid but leakage-prone train/test classification DAGs."""
    node_types = {node["node_id"]: node["node_type"] for node in nodes}
    partition_ids = {node_id for node_id, node_type in node_types.items() if node_type == "selection.sample_partition"}
    predict_ids = {node_id for node_id, node_type in node_types.items() if node_type == "classification.predict"}
    evaluation_ids = {
        node_id for node_id, node_type in node_types.items() if node_type == "diagnostics.holdout_evaluation"
    }
    if not partition_ids or not predict_ids or not evaluation_ids:
        return []

    classification_model_ids = {
        node_id
        for node_id, node_type in node_types.items()
        if node_type.startswith("classification.") and node_type != "classification.predict"
    }
    issues: list[dict[str, str]] = []

    for model_id in classification_model_ids:
        model_inputs = [edge for edge in edges if edge["to_node_id"] == model_id and edge["to_input"] == "X"]
        if not model_inputs:
            continue
        outputs = _partition_outputs_feeding_input(model_id, "X", node_types, edges)
        if "X_train" not in outputs or "X_test" in outputs:
            issues.append(
                _issue(
                    "error",
                    "Holdout classification models must train from the partition X_train branch, not X_test.",
                    model_id,
                    "X",
                    code="classification_model_must_use_x_train",
                )
            )

    for predict_id in predict_ids:
        model_edges = [edge for edge in edges if edge["to_node_id"] == predict_id and edge["to_input"] == "model"]
        model_sources = [edge["from_node_id"] for edge in model_edges]
        if model_sources and not any(source in classification_model_ids for source in model_sources):
            issues.append(
                _issue(
                    "error",
                    "Prediction must use the trained classification model output.",
                    predict_id,
                    "model",
                    code="classification_predict_model_missing",
                )
            )

        x_new_edges = [edge for edge in edges if edge["to_node_id"] == predict_id and edge["to_input"] == "X_new"]
        if not x_new_edges:
            continue
        outputs = _partition_outputs_feeding_input(predict_id, "X_new", node_types, edges)
        if "X_test" not in outputs or "X_train" in outputs:
            issues.append(
                _issue(
                    "error",
                    "Holdout predictions must use the partition X_test branch for X_new.",
                    predict_id,
                    "X_new",
                    code="classification_predict_must_use_x_test",
                )
            )

    for scale_id, node_type in node_types.items():
        if node_type != "preprocess.scale":
            continue
        main_outputs = _partition_outputs_upstream_of(scale_id, node_types, edges, skip_inputs={"reference"})
        if "X_test" not in main_outputs:
            continue
        has_train_reference = any(
            _has_edge(
                edges,
                source=partition_id,
                target=scale_id,
                from_output="X_train",
                to_input="reference",
            )
            for partition_id in partition_ids
        )
        if not has_train_reference:
            issues.append(
                _issue(
                    "error",
                    "A scaled X_test branch must connect partition X_train to the scale node's reference input "
                    "so preprocessing parameters are fitted on training data only.",
                    scale_id,
                    "reference",
                    code="classification_test_scale_requires_train_reference",
                )
            )

    for evaluation_id in evaluation_ids:
        y_true_outputs = set()
        for edge in edges:
            if edge["to_node_id"] != evaluation_id or edge["to_input"] != "y_true":
                continue
            if node_types.get(edge["from_node_id"]) == "selection.sample_partition":
                y_true_outputs.add(edge["from_output"])
            else:
                y_true_outputs.update(_partition_outputs_upstream_of(edge["from_node_id"], node_types, edges))
        if y_true_outputs and "y_test" not in y_true_outputs:
            issues.append(
                _issue(
                    "error",
                    "Holdout evaluation y_true must come from the partition y_test output.",
                    evaluation_id,
                    "y_true",
                    code="classification_eval_must_use_y_test",
                )
            )

    return issues


async def _llm_context_permissions(session: Any, user: Any) -> dict[str, bool]:
    from spectra_sherpa.app.core.security import check_egress_permission
    from spectra_sherpa.app.models.data_egress import DataType, EgressDestination

    permissions: dict[str, bool] = {}
    for data_type in (DataType.WORKFLOWS, DataType.METADATA, DataType.MODELS, DataType.SPECTRA):
        permissions[data_type] = await check_egress_permission(
            user,
            "allow_llm_context",
            data_type=data_type,
            destination=EgressDestination.LLM_CONTEXT,
            session=session,
        )
    return permissions


def _apply_egress_filter(payload: Any, permissions: dict[str, bool]) -> Any:
    """Remove fields the user has not allowed to enter LLM context."""
    from spectra_sherpa.app.models.data_egress import DataType

    if not isinstance(payload, dict):
        return payload

    filtered = dict(payload)
    if not permissions.get(DataType.WORKFLOWS, False):
        for key in (
            "nodes",
            "edges",
            "node_types",
            "node_count",
            "edge_count",
            "parameters",
            "input_ports",
            "output_ports",
        ):
            filtered.pop(key, None)

    if not permissions.get(DataType.METADATA, False):
        for key in ("name", "label", "summary", "category", "description", "dataset_shape", "units"):
            filtered.pop(key, None)

    if not permissions.get(DataType.MODELS, False):
        for key in ("diagnostics", "last_run", "run_results", "model_artifacts"):
            filtered.pop(key, None)

    if not permissions.get(DataType.SPECTRA, False):
        for key in ("spectra", "sample_table", "samples", "values"):
            filtered.pop(key, None)

    for key, value in list(filtered.items()):
        if isinstance(value, dict):
            filtered[key] = _apply_egress_filter(value, permissions)
        elif isinstance(value, list):
            filtered[key] = [
                _apply_egress_filter(item, permissions) if isinstance(item, dict) else item for item in value
            ]
    return filtered


def validate_workflow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    parent_loader_fingerprints: set[str] | None = None,
) -> dict[str, Any]:
    """Run structural validation on a workflow graph.

    This function intentionally remains synchronous for existing tests and
    callers. Async tool/orchestrator paths can pass precomputed parent loader
    fingerprints to enforce same-data inheritance without doing DB work here.
    """
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_types import (
        WorkflowEdge as DagEdge,
    )
    from spectra_sherpa.app.services.dag.executor_types import (
        WorkflowNode as DagNode,
    )
    from spectra_sherpa.app.services.dag.node_base import node_registry

    normalized_nodes = [
        {
            "node_id": _node_id(node),
            "node_type": _node_type(node),
            "parameters": _node_parameters(node),
            "position": node.get("position"),
        }
        for node in nodes
    ]
    normalized_edges = [
        {
            "from_node_id": _edge_source(edge),
            "to_node_id": _edge_target(edge),
            "from_output": _edge_from_output(edge),
            "to_input": _edge_to_input(edge),
        }
        for edge in edges
    ]

    issues: list[dict[str, str]] = []
    node_ids = {node["node_id"] for node in normalized_nodes}
    seen_node_ids: set[str] = set()
    executor = DAGExecutor()

    for node in normalized_nodes:
        node_id = node["node_id"]
        node_type = node["node_type"]
        if not node_id:
            issues.append(_issue("error", "Node is missing node_id"))
            continue
        if node_id in seen_node_ids:
            issues.append(_issue("error", f"Duplicate node id: {node_id}", node_id, code="duplicate_node_id"))
            continue
        seen_node_ids.add(node_id)
        if node_type not in node_registry._nodes:
            issues.append(_issue("error", f"Unknown node type: {node_type}", node_id))
            continue
        try:
            executor.add_node(
                DagNode(
                    node_id=node_id,
                    node_type=node_type,
                    parameters=node["parameters"],
                    position=node.get("position"),
                )
            )
        except Exception as exc:
            issues.append(_issue("error", f"Invalid node: {exc}", node_id))

    for edge in normalized_edges:
        source = edge["from_node_id"]
        target = edge["to_node_id"]
        if source not in node_ids:
            issues.append(_issue("error", f"Edge source not in node list: {source}", source))
            continue
        if target not in node_ids:
            issues.append(_issue("error", f"Edge target not in node list: {target}", target))
            continue
        executor.add_edge(
            DagEdge(
                from_node=source,
                to_node=target,
                from_output=edge["from_output"],
                to_input=edge["to_input"],
            )
        )

    if not any(issue["severity"] == "error" for issue in issues):
        result = executor.validate_full()
        for validation_issue in result.issues:
            issues.append(
                _issue(
                    validation_issue.level,
                    validation_issue.message,
                    validation_issue.node_id,
                    validation_issue.port,
                )
            )

    if not any(issue["severity"] == "error" for issue in issues):
        issues.extend(_validate_holdout_classification_topology(normalized_nodes, normalized_edges))

    if parent_loader_fingerprints is not None:
        proposed_fingerprints = _data_loader_fingerprints(normalized_nodes)
        if not proposed_fingerprints:
            issues.append(
                _issue(
                    "error",
                    "The proposed workflow must inherit the parent workflow data loader nodes.",
                    code="data_loader_missing",
                )
            )
        missing = parent_loader_fingerprints - proposed_fingerprints
        if missing:
            issues.append(
                _issue(
                    "error",
                    "The proposed workflow data loaders do not match the parent workflow data sources.",
                    code="data_loader_mismatch",
                )
            )

    return {
        "valid": all(issue["severity"] != "error" for issue in issues),
        "issue_count": len(issues),
        "issues": issues,
    }


async def validate_dag_spec_for_parent(
    dag_spec: Any,
    parent_workflow_id: int,
    session: Any,
    user: Any,
) -> dict[str, Any]:
    """Validate an agent-proposed DAG and enforce parent data-source inheritance."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.project_data_sources import describe_node_data_source

    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.nodes))
        .where(Workflow.id == parent_workflow_id, Workflow.user_id == user.id)
    )
    parent = result.scalar_one_or_none()
    if parent is None:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [_issue("error", "Parent workflow not found.", code="parent_workflow_missing")],
        }

    # Substitute parent loader params into the proposal before fingerprinting,
    # so models that drift on loader fields (e.g. omit `stage`) still pass
    # parent-inheritance validation. Mutation propagates to the route-handler
    # persist path, which iterates the same dag_spec after this call.
    substitute_parent_data_loaders(dag_spec, parent.nodes)

    nodes, edges = _normalize_dag_spec(dag_spec)
    parent_fingerprints = {
        candidate.fingerprint for node in parent.nodes if (candidate := describe_node_data_source(node)) is not None
    }
    return validate_workflow(nodes, edges, parent_fingerprints)


@register_tool(
    "inspect_workflow",
    "Get a summary or full topology of a workflow.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer"},
            "detail_level": {
                "type": "string",
                "enum": ["summary", "topology_only", "full"],
                "description": "Amount of detail to return",
            },
            "mode": {
                "type": "string",
                "enum": ["summary", "topology_only", "full"],
                "description": "Deprecated alias for detail_level",
            },
        },
        "required": ["workflow_id"],
    },
    requires_session=True,
    requires_user=True,
)
async def inspect_workflow(
    workflow_id: int,
    detail_level: str = "summary",
    mode: str | None = None,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from spectra_sherpa.app.models.workflow import Workflow

    mode = mode or detail_level
    permissions = await _llm_context_permissions(session, user)
    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
        .where(Workflow.id == workflow_id, Workflow.user_id == user.id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "Workflow not found"}

    nodes = [{"id": n.node_id, "type": n.node_type, "label": n.label} for n in wf.nodes]
    edges = [
        {
            "source": e.from_node_id,
            "target": e.to_node_id,
            "from_output": e.from_output,
            "to_input": e.to_input,
        }
        for e in wf.edges
    ]

    if mode == "summary":
        return _apply_egress_filter(
            {
                "workflow_id": wf.id,
                "name": wf.name,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "node_types": sorted({node["type"] for node in nodes}),
            },
            permissions,
        )

    if mode == "topology_only":
        return _apply_egress_filter({"nodes": nodes, "edges": edges}, permissions)

    # full mode
    for i, n in enumerate(wf.nodes):
        nodes[i]["parameters"] = n.parameters

    return _apply_egress_filter(
        {
            "workflow_id": wf.id,
            "name": wf.name,
            "nodes": nodes,
            "edges": edges,
        },
        permissions,
    )


@register_tool(
    "get_workflow_summary",
    "Get a human-readable summary of a saved workflow's DAG structure.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {"workflow_id": {"type": "integer"}},
        "required": ["workflow_id"],
    },
    requires_session=True,
    requires_user=True,
)
async def get_workflow_summary(
    workflow_id: int,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    """Backward-compatible summary tool used by existing advisor paths."""
    return await inspect_workflow(
        workflow_id=workflow_id,
        detail_level="full",
        session=session,
        user=user,
    )


@register_tool(
    "list_nodes",
    "List legal workflow node building blocks, optionally filtered by category or search text.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "search": {"type": "string"},
        },
        "required": [],
    },
    requires_session=True,
    requires_user=True,
)
async def list_nodes(
    category: str | None = None,
    search: str | None = None,
    session: Any = None,
    user: Any = None,
) -> list[dict[str, str]]:
    from spectra_sherpa.app.services.dag.node_base import node_registry

    search_text = (search or "").strip().lower()
    results = []
    for node_type, node_cls in sorted(node_registry._nodes.items()):
        meta = node_cls.metadata
        if category and meta.category != category:
            continue
        haystack = f"{meta.node_type} {meta.label} {meta.category} {meta.description}".lower()
        if search_text and search_text not in haystack:
            continue
        results.append(
            {
                "type": meta.node_type,
                "label": meta.label,
                "category": meta.category,
                "summary": meta.description[:160],
            }
        )
    return results


@register_tool(
    "describe_nodes",
    "Get schema and description for specific node types.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "node_types": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["node_types"],
    },
    requires_session=True,
    requires_user=True,
)
async def describe_nodes(
    node_types: list[str],
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    from spectra_sherpa.app.services.dag.node_base import node_registry

    requested_node_types = list(node_types)
    requested_count = len(requested_node_types)
    node_types = requested_node_types[:MAX_DESCRIBE_NODE_TYPES]
    results = []
    for nt in node_types:
        cls = node_registry._nodes.get(nt)
        if not cls:
            results.append({"type": nt, "error": f"Unknown node type: {nt}"})
            continue

        md = cls.metadata
        results.append(
            {
                "type": nt,
                "label": md.label,
                "category": md.category,
                "summary": _compact_text(md.description),
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.param_type,
                        "default": p.default,
                        "required": p.required,
                        **({"min": p.min_value} if p.min_value is not None else {}),
                        **({"max": p.max_value} if p.max_value is not None else {}),
                        **({"options": p.options} if p.options else {}),
                        **({"description": _compact_text(p.description)} if p.description else {}),
                    }
                    for p in md.parameters
                ],
                "input_ports": [
                    {
                        "name": p.name,
                        "type": p.type_ref,
                        "required": p.required,
                        "label": p.label,
                        **({"description": _compact_text(p.description)} if p.description else {}),
                    }
                    for p in (md.input_ports or [])
                ],
                "output_ports": [
                    {
                        "name": p.name,
                        "type": p.type_ref,
                        "required": p.required,
                        "label": p.label,
                        **({"description": _compact_text(p.description)} if p.description else {}),
                    }
                    for p in (md.output_ports or [])
                ],
            }
        )

    response: dict[str, Any] = {"descriptions": results}
    if requested_count > MAX_DESCRIBE_NODE_TYPES:
        response["omitted_node_types"] = requested_node_types[MAX_DESCRIBE_NODE_TYPES:]
        response["warning"] = (
            f"describe_nodes is limited to {MAX_DESCRIBE_NODE_TYPES} node types per call; "
            "call again with a smaller shortlist if more schemas are needed."
        )
    return response


@register_tool(
    "validate_workflow",
    "Validate a workflow DAG for common issues: disconnected nodes, "
    "type mismatches, cycles, missing required parameters.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": (
                    "Array of node objects. Use either DAG spec keys (id/type) " "or workflow keys (node_id/node_type)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "node_id": {"type": "string"},
                        "node_type": {"type": "string"},
                        "parameters": {"type": "object"},
                        "position": {"type": "object"},
                    },
                    "required": [],
                },
            },
            "edges": {
                "type": "array",
                "description": (
                    "Array of edge objects. Use either DAG spec keys (source/target) "
                    "or workflow keys (from_node_id/to_node_id)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "from_node_id": {"type": "string"},
                        "to_node_id": {"type": "string"},
                        "from_output": {"type": "string"},
                        "to_input": {"type": "string"},
                    },
                    "required": [],
                },
            },
            "parent_workflow_id": {
                "type": "integer",
                "description": "Optional parent workflow ID to validate data-loader inheritance",
            },
        },
        "required": ["nodes", "edges"],
    },
    requires_session=True,
    requires_user=True,
)
async def _validate_workflow_tool(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    parent_workflow_id: int | None = None,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    if parent_workflow_id is not None:
        return await validate_dag_spec_for_parent(
            {"nodes": nodes, "edges": edges},
            parent_workflow_id,
            session,
            user,
        )
    return validate_workflow(nodes=nodes, edges=edges)


@register_tool(
    "propose_workflow",
    "Propose a new workflow. This is intercepted by the orchestrator.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "dag_spec": {"type": "object"},
            "suggested_name": {"type": "string"},
            "human_explanation": {"type": "string"},
        },
        "required": ["dag_spec", "suggested_name", "human_explanation"],
    },
)
async def propose_workflow(
    dag_spec: dict[str, Any],
    suggested_name: str,
    human_explanation: str,
) -> dict[str, Any]:
    # The actual write goes through the POST /workflows/{parent}/ai-fork endpoint
    # called by the orchestrator.
    return {
        "status": "intercepted",
        "dag_spec": dag_spec,
        "suggested_name": suggested_name,
        "human_explanation": human_explanation,
    }


@register_tool(
    "list_workflows",
    "List the user's saved workflows with ID, name, and node count.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max number of workflows to return (default 20)",
            },
        },
        "required": [],
    },
    requires_session=True,
    requires_user=True,
)
async def list_workflows(
    limit: int = 20,
    session: Any = None,
    user: Any = None,
) -> list[dict[str, Any]]:
    """Return a compact list of user's workflows."""
    from sqlalchemy import func, select

    from spectra_sherpa.app.models.workflow import Workflow, WorkflowNode

    # Subquery for node count
    node_count = (
        select(func.count(WorkflowNode.id))
        .where(WorkflowNode.workflow_id == Workflow.id)
        .correlate(Workflow)
        .scalar_subquery()
    )

    result = await session.execute(
        select(
            Workflow.id,
            Workflow.name,
            Workflow.created_at,
            Workflow.updated_at,
            node_count.label("node_count"),
        )
        .where(Workflow.user_id == user.id)
        .order_by(Workflow.updated_at.desc())
        .limit(limit)
    )

    return [
        {
            "workflow_id": row.id,
            "name": row.name,
            "node_count": row.node_count or 0,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in result
    ]
