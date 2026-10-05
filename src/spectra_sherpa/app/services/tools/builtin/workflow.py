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


def _is_scientific_source_node(node: Any) -> bool:
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.project_data_sources import _node_value, describe_node_data_source

    if describe_node_data_source(node) is not None:
        return True
    kind = _node_value(node, "node_type", None) or _node_value(node, "type", None)
    try:
        metadata = node_registry.get_metadata(kind)
    except (KeyError, TypeError):
        return False
    # NodeMetadata explicitly defines empty input_ports as a source operation.
    # This also covers reference/model sources absent from the project asset tree.
    return not metadata.input_ports


def source_binding_snapshot(nodes: list[Any]) -> dict[str, str]:
    """Hash complete scientific bindings separately from catalog asset identity."""
    import hashlib
    import json

    from spectra_sherpa.app.services.project_data_sources import _node_value

    bindings = {}
    for node in nodes:
        if not _is_scientific_source_node(node):
            continue
        node_id = str(_node_value(node, "node_id", None) or _node_value(node, "id", ""))
        if not node_id or node_id in bindings:
            raise ValueError("Parent source identities must be present and unique")
        node_type = _node_value(node, "node_type", None) or _node_value(node, "type", None)
        parameters = _node_value(node, "parameters", None) or _node_value(node, "params", None) or {}
        encoded = json.dumps(
            {"type": node_type, "parameters": parameters}, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        bindings[node_id] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return bindings


def substitute_parent_data_loaders(dag_spec: Any, parent_nodes: list[Any]) -> list[dict[str, Any]]:
    """Inherit complete source authority by stable node identity, never position.

    Keeping a parent's loader ID is an explicit inheritance reference. Omitted
    parameters are copied from that source with a receipt; conflicting values,
    renamed/missing sources and extra sources are refused. All checks precede
    mutation so a refused proposal is not partially rewritten.
    """
    import json
    from copy import deepcopy

    from spectra_sherpa.app.services.project_data_sources import _node_value

    def identity(node: Any) -> str:
        return str(_node_value(node, "node_id", None) or _node_value(node, "id", ""))

    def kind(node: Any) -> str:
        return str(_node_value(node, "node_type", None) or _node_value(node, "type", ""))

    def parameters(node: Any) -> dict[str, Any]:
        return _node_value(node, "parameters", None) or _node_value(node, "params", None) or {}

    bindings = source_binding_snapshot(parent_nodes)
    parents = {identity(node): node for node in parent_nodes if identity(node) in bindings}
    if not parents:
        return []
    proposed = dag_spec.nodes if hasattr(dag_spec, "nodes") else dag_spec.get("nodes", [])
    identities = [identity(node) for node in proposed]
    if len(set(identities)) != len(identities):
        raise ValueError("Proposal node identities must be unique for source inheritance")
    if set(parents) - set(identities):
        raise ValueError(
            "Preserve every parent source node ID; source rebinding requires an explicit data-selection change"
        )
    source_types = {kind(node) for node in parents.values()}
    replacements = []
    receipts = []
    for node in proposed:
        node_id = identity(node)
        parent = parents.get(node_id)
        if parent is None:
            if _is_scientific_source_node(node) or kind(node) in source_types:
                raise ValueError("A proposed source has no parent source identity; select its data explicitly first")
            continue
        if kind(node) != kind(parent):
            raise ValueError("An inherited source node cannot change operation type")
        actual = parameters(parent)
        supplied = parameters(node)
        if not isinstance(supplied, dict) or any(
            key not in actual
            or json.dumps(value, sort_keys=True, allow_nan=False)
            != json.dumps(actual[key], sort_keys=True, allow_nan=False)
            for key, value in supplied.items()
        ):
            raise ValueError("An inherited source conflicts with its saved parameters, target or asset authority")
        receipts.append(
            {
                "node_id": node_id,
                "source_node_id": node_id,
                "binding_sha256": bindings[node_id],
                "restored_fields": sorted(set(actual) - set(supplied)),
            }
        )
        replacements.append((node, deepcopy(actual)))
    for node, params in replacements:
        if hasattr(node, "parameters"):
            node.parameters = params
        else:
            node["parameters"] = params
    return receipts


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
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge as DagEdge
    from spectra_sherpa.app.services.dag.executor_types import WorkflowNode as DagNode
    from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    # Direct support/SDK use does not run ASGI lifespan.  It explicitly opts
    # into the packaged vocabulary before asking the shared preflight for an
    # answer; server admission itself remains fail-closed at its startup seam.
    ensure_type_registry_loaded()

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

    preflight = preflight_workflow(
        [
            DagNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=node["parameters"],
                position=node.get("position"),
            )
            for node in normalized_nodes
        ],
        [
            DagEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge["from_output"],
                to_input=edge["to_input"],
            )
            for edge in normalized_edges
        ],
    )
    issues = [
        _issue(issue.level, issue.message, issue.node_id, issue.port, code=issue.code) for issue in preflight.issues
    ]

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
    expected_source_bindings: dict[str, str] | None = None,
    *,
    lock_parent: bool = False,
) -> dict[str, Any]:
    """Validate an agent-proposed DAG and enforce parent data-source inheritance."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.project_data_sources import describe_node_data_source

    statement = (
        select(Workflow)
        .options(selectinload(Workflow.nodes))
        .where(Workflow.id == parent_workflow_id, Workflow.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    # Advisory tool validation spans provider yields. Never retain a row lock
    # there: the proposal consumer persists using a different transaction.
    if lock_parent:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    parent = result.scalar_one_or_none()
    if parent is None:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [_issue("error", "Parent workflow not found.", code="parent_workflow_missing")],
        }

    try:
        if expected_source_bindings is not None and source_binding_snapshot(parent.nodes) != expected_source_bindings:
            raise ValueError("Parent source bindings changed during generation; request a fresh proposal")
        source_bindings = substitute_parent_data_loaders(dag_spec, parent.nodes)
    except (TypeError, ValueError) as exc:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [_issue("error", str(exc), code="source_binding_refused")],
        }

    nodes, edges = _normalize_dag_spec(dag_spec)
    parent_fingerprints = {
        candidate.fingerprint for node in parent.nodes if (candidate := describe_node_data_source(node)) is not None
    }
    result = validate_workflow(nodes, edges, parent_fingerprints)
    result["source_bindings"] = source_bindings
    return result


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
    for meta in sorted(node_registry.list_catalog_nodes(), key=lambda item: item.node_type):
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
        try:
            md = node_registry.get_catalog_metadata(nt)
        except KeyError:
            results.append({"type": nt, "error": f"Unknown node type: {nt}"})
            continue
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
                    "Array of node objects. Use either DAG spec keys (id/type) or workflow keys (node_id/node_type)."
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
