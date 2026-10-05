"""Canonicalize public workflow operation identities.

Revision ID: s8t0u2v4w137
Revises: r7s9t1u3v826
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import sqlalchemy as sa
from alembic import op

from spectra_sherpa.core.node_identity import SERIALIZED_NODE_TYPE_ALIASES

revision = "s8t0u2v4w137"
down_revision = "r7s9t1u3v826"
branch_labels = None
depends_on = None

_LEGACY_BY_CANONICAL = {canonical: legacy for legacy, canonical in SERIALIZED_NODE_TYPE_ALIASES.items()}
_LEGACY_APPLY_PLS_ID = _LEGACY_BY_CANONICAL["model.apply_fitted_pls"]
_LOCAL_SOURCE_NODE_ID = "canonical-local-source"
_CURRENT_PLS_SOURCE_DIGEST = "77ca83c532d71be3d6e409bc1c01bdb96421d104169286f0814dd163f2e53b55"
_CURRENT_PLS_APPLICATION_DIGEST = "2fb0b9e97725fac816c130d6c7e635ed354a6ac4cbebf3b67820122b4d0150ef"
_LEGACY_PLS_APPLICATION_DIGEST_BY_SOURCE = {
    "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8": (
        "7a54cae94c875d150e16ea321960b6b3db5f1176cae2756f007d1bd134c94cf9"
    ),
    "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d": (
        "efee828721a2fa29dc3ddb8b0737a9fcd72d45830b5c9db391438cdd4f087baa"
    ),
}


def _columns(bind: sa.engine.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_columns(bind: sa.engine.Connection, table_name: str, required: set[str]) -> bool:
    return required <= _columns(bind, table_name)


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _workflow_hash(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    canonical = {
        "nodes": sorted(
            (
                {
                    "node_id": node["node_id"],
                    "node_type": node["node_type"],
                    "parameters": node.get("parameters", {}),
                }
                for node in nodes
            ),
            key=lambda node: node["node_id"],
        ),
        "edges": sorted(
            (
                {
                    "from_node_id": edge["from_node_id"],
                    "to_node_id": edge["to_node_id"],
                    "from_output": edge.get("from_output", "default"),
                    "to_input": edge.get("to_input", "default"),
                }
                for edge in edges
            ),
            key=lambda edge: (
                edge["from_node_id"],
                edge["to_node_id"],
                edge["from_output"],
                edge["to_input"],
            ),
        ),
    }
    return _digest(canonical)


def _node_uses_mapping(value: Any, aliases: Mapping[str, str]) -> bool:
    return isinstance(value, Mapping) and any(
        value.get(key) in aliases for key in ("node_type", "operation_id", "type")
    )


def _rewrite_serialized_workflow(value: Any, aliases: Mapping[str, str]) -> Any:
    """Rewrite key-directed identities and re-sign only verified changed graphs."""

    if isinstance(value, dict):
        original_nodes = value.get("nodes")
        original_edges = value.get("edges")
        changes_graph = isinstance(original_nodes, list) and any(
            _node_uses_mapping(node, aliases) for node in original_nodes
        )
        if changes_graph and "integrity_hash" in value and isinstance(original_edges, list):
            expected = _workflow_hash(original_nodes, original_edges)
            if value["integrity_hash"] != expected:
                raise RuntimeError("refusing to migrate a serialized workflow with an invalid integrity hash")

        result = {key: _rewrite_serialized_workflow(item, aliases) for key, item in value.items()}
        looks_like_node = (
            "node_id" in result
            or "parameters" in result
            or ("id" in result and ("type" in result or "operation_id" in result))
        )
        if looks_like_node:
            for key in ("node_type", "operation_id", "type"):
                identity = result.get(key)
                if isinstance(identity, str):
                    result[key] = aliases.get(identity, identity)
        if changes_graph and "integrity_hash" in result:
            nodes = result.get("nodes")
            edges = result.get("edges")
            if isinstance(nodes, list) and isinstance(edges, list):
                result["integrity_hash"] = _workflow_hash(nodes, edges)
        return result
    if isinstance(value, list):
        return [_rewrite_serialized_workflow(item, aliases) for item in value]
    if isinstance(value, tuple):
        return tuple(_rewrite_serialized_workflow(item, aliases) for item in value)
    return deepcopy(value)


def _rewrite_json_column(
    bind: sa.engine.Connection,
    table_name: str,
    aliases: Mapping[str, str],
) -> None:
    if not _has_columns(bind, table_name, {"id", "snapshot"}):
        return
    table = sa.table(table_name, sa.column("id", sa.Integer), sa.column("snapshot", sa.JSON))
    for row_id, snapshot in bind.execute(sa.select(table.c.id, table.c.snapshot)).all():
        migrated = _rewrite_serialized_workflow(snapshot, aliases)
        if migrated != snapshot:
            bind.execute(sa.update(table).where(table.c.id == row_id).values(snapshot=migrated))


def _workflow_tables(bind: sa.engine.Connection) -> tuple[sa.TableClause, sa.TableClause, sa.TableClause] | None:
    if not _has_columns(bind, "workflow", {"id", "integrity_hash"}):
        return None
    if not _has_columns(bind, "workflow_node", {"workflow_id", "node_id", "node_type", "parameters"}):
        return None
    if not _has_columns(
        bind,
        "workflow_edge",
        {"workflow_id", "from_node_id", "to_node_id", "from_output", "to_input"},
    ):
        return None
    return (
        sa.table("workflow", sa.column("id", sa.Integer), sa.column("integrity_hash", sa.String)),
        sa.table(
            "workflow_node",
            sa.column("workflow_id", sa.Integer),
            sa.column("node_id", sa.String),
            sa.column("node_type", sa.String),
            sa.column("parameters", sa.JSON),
        ),
        sa.table(
            "workflow_edge",
            sa.column("workflow_id", sa.Integer),
            sa.column("from_node_id", sa.String),
            sa.column("to_node_id", sa.String),
            sa.column("from_output", sa.String),
            sa.column("to_input", sa.String),
        ),
    )


def _load_graph(
    bind: sa.engine.Connection,
    workflow_id: int,
    node_table: sa.TableClause,
    edge_table: sa.TableClause,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        dict(row)
        for row in bind.execute(sa.select(node_table).where(node_table.c.workflow_id == workflow_id)).mappings()
    ]
    edges = [
        dict(row)
        for row in bind.execute(sa.select(edge_table).where(edge_table.c.workflow_id == workflow_id)).mappings()
    ]
    return nodes, edges


def _rewrite_live_nodes(bind: sa.engine.Connection, aliases: Mapping[str, str]) -> set[int]:
    if not _has_columns(bind, "workflow_node", {"workflow_id", "node_type"}):
        return set()
    node_identity_table = sa.table(
        "workflow_node",
        sa.column("workflow_id", sa.Integer),
        sa.column("node_type", sa.String),
    )
    affected: set[int] = set()
    for source in aliases:
        affected.update(
            bind.execute(
                sa.select(node_identity_table.c.workflow_id).where(node_identity_table.c.node_type == source)
            ).scalars()
        )

    tables = _workflow_tables(bind)
    prior_hashes: dict[int, str | None] = {}
    if tables is not None:
        workflow_table, node_table, edge_table = tables
        for workflow_id in affected:
            nodes, edges = _load_graph(bind, workflow_id, node_table, edge_table)
            stored_hash = bind.execute(
                sa.select(workflow_table.c.integrity_hash).where(workflow_table.c.id == workflow_id)
            ).scalar_one_or_none()
            if stored_hash is not None and stored_hash != _workflow_hash(nodes, edges):
                raise RuntimeError("refusing to migrate a workflow with an invalid integrity hash")
            prior_hashes[workflow_id] = stored_hash

    for source, target in aliases.items():
        bind.execute(
            sa.update(node_identity_table).where(node_identity_table.c.node_type == source).values(node_type=target)
        )

    if tables is not None:
        workflow_table, node_table, edge_table = tables
        run_table = None
        if _has_columns(bind, "execution_run", {"workflow_id", "integrity_hash"}):
            run_table = sa.table(
                "execution_run",
                sa.column("workflow_id", sa.Integer),
                sa.column("integrity_hash", sa.String),
            )
        for workflow_id in affected:
            nodes, edges = _load_graph(bind, workflow_id, node_table, edge_table)
            new_hash = _workflow_hash(nodes, edges)
            old_hash = prior_hashes.get(workflow_id)
            if run_table is not None and old_hash is not None:
                bind.execute(
                    sa.update(run_table)
                    .where(run_table.c.workflow_id == workflow_id)
                    .where(run_table.c.integrity_hash == old_hash)
                    .values(integrity_hash=new_hash)
                )
            bind.execute(
                sa.update(workflow_table).where(workflow_table.c.id == workflow_id).values(integrity_hash=new_hash)
            )
    return affected


def _rewrite_application_plan(value: Any, *, downgrade: bool) -> Any:
    if not isinstance(value, Mapping):
        return value
    plan = deepcopy(dict(value))
    nodes = plan.get("nodes")
    if not isinstance(nodes, list):
        return plan
    identity_map = _LEGACY_BY_CANONICAL if downgrade else SERIALIZED_NODE_TYPE_ALIASES
    changes = any(
        isinstance(node, Mapping)
        and (node.get("source_operation_id") in identity_map or node.get("application_operation_id") in identity_map)
        for node in nodes
    )
    if not changes:
        return plan
    unsigned_before = {key: item for key, item in plan.items() if key != "application_plan_digest"}
    if plan.get("application_plan_digest") != _digest(unsigned_before):
        raise RuntimeError("refusing to migrate an application plan with an invalid content digest")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        source_operation_id = node.get("source_operation_id")
        application_operation_id = node.get("application_operation_id")
        source_digest = node.get("source_contract_digest")
        application_digest = node.get("application_contract_digest")
        legacy_application_digest = _LEGACY_PLS_APPLICATION_DIGEST_BY_SOURCE.get(source_digest)
        if downgrade and (
            source_operation_id == "model.fitted_pls" or application_operation_id == "model.apply_fitted_pls"
        ):
            if (
                source_operation_id != "model.fitted_pls"
                or application_operation_id != "model.apply_fitted_pls"
                or legacy_application_digest is None
                or application_digest != _CURRENT_PLS_APPLICATION_DIGEST
            ):
                raise RuntimeError("refusing to downgrade a fitted-PLS application plan with invalid contract bindings")
        elif not downgrade and (
            source_operation_id == _LEGACY_BY_CANONICAL["model.fitted_pls"]
            or application_operation_id == _LEGACY_APPLY_PLS_ID
        ):
            if (
                source_operation_id != _LEGACY_BY_CANONICAL["model.fitted_pls"]
                or application_operation_id != _LEGACY_APPLY_PLS_ID
                or legacy_application_digest is None
                or application_digest != legacy_application_digest
            ):
                raise RuntimeError("refusing to migrate a fitted-PLS application plan with invalid contract bindings")
        for field in ("source_operation_id", "application_operation_id"):
            identity = node.get(field)
            if isinstance(identity, str):
                node[field] = identity_map.get(identity, identity)
        if downgrade:
            if legacy_application_digest is not None and node.get("application_operation_id") == _LEGACY_APPLY_PLS_ID:
                node["application_contract_digest"] = legacy_application_digest
        elif (
            source_digest in _LEGACY_PLS_APPLICATION_DIGEST_BY_SOURCE
            and node.get("application_operation_id") == "model.apply_fitted_pls"
        ):
            node["application_contract_digest"] = _CURRENT_PLS_APPLICATION_DIGEST

    unsigned_after = {key: item for key, item in plan.items() if key != "application_plan_digest"}
    plan["application_plan_digest"] = _digest(unsigned_after)
    return plan


def _artifact_table(bind: sa.engine.Connection) -> sa.TableClause | None:
    required = {
        "id",
        "workflow_id",
        "application_plan_digest",
        "application_plan_payload",
        "application_integrity_hash",
    }
    if not _has_columns(bind, "canonical_project_artifact", required):
        return None
    return sa.table(
        "canonical_project_artifact",
        sa.column("id", sa.Integer),
        sa.column("workflow_id", sa.Integer),
        sa.column("application_plan_digest", sa.String),
        sa.column("application_plan_payload", sa.JSON),
        sa.column("application_integrity_hash", sa.String),
    )


def _require_downgrade_safe(bind: sa.engine.Connection) -> None:
    artifact_table = _artifact_table(bind)
    if artifact_table is None:
        return
    for payload in bind.execute(sa.select(artifact_table.c.application_plan_payload)).scalars():
        if not isinstance(payload, Mapping) or not isinstance(payload.get("nodes"), list):
            continue
        for node in payload["nodes"]:
            if (
                isinstance(node, Mapping)
                and node.get("source_operation_id") == "model.fitted_pls"
                and node.get("source_contract_digest") == _CURRENT_PLS_SOURCE_DIGEST
            ):
                raise RuntimeError(
                    "cannot downgrade while a canonical fitted-PLS artifact created after this migration exists"
                )


def _rewrite_artifact_grants(
    bind: sa.engine.Connection,
    affected_workflows: set[int],
    *,
    downgrade: bool,
) -> None:
    artifact_table = _artifact_table(bind)
    if artifact_table is None:
        return
    tables = _workflow_tables(bind)
    for row in bind.execute(sa.select(artifact_table)).mappings():
        original_plan = row["application_plan_payload"]
        plan = _rewrite_application_plan(original_plan, downgrade=downgrade)
        values: dict[str, Any] = {}
        if plan != original_plan:
            if not isinstance(original_plan, Mapping) or row["application_plan_digest"] != original_plan.get(
                "application_plan_digest"
            ):
                raise RuntimeError("refusing to migrate an artifact with a mismatched application plan digest")
            values["application_plan_payload"] = plan
            values["application_plan_digest"] = plan["application_plan_digest"]
        if tables is not None and row["workflow_id"] in affected_workflows:
            _, node_table, edge_table = tables
            nodes, edges = _load_graph(bind, row["workflow_id"], node_table, edge_table)
            application_nodes = [node for node in nodes if node["node_id"] != _LOCAL_SOURCE_NODE_ID]
            application_edges = [
                edge
                for edge in edges
                if edge["from_node_id"] != _LOCAL_SOURCE_NODE_ID and edge["to_node_id"] != _LOCAL_SOURCE_NODE_ID
            ]
            prior_identity_map = SERIALIZED_NODE_TYPE_ALIASES if downgrade else _LEGACY_BY_CANONICAL
            prior_application_nodes = [
                {
                    **node,
                    "node_type": prior_identity_map.get(node["node_type"], node["node_type"]),
                }
                for node in application_nodes
            ]
            if row["application_integrity_hash"] != _workflow_hash(prior_application_nodes, application_edges):
                raise RuntimeError("refusing to migrate an artifact with an invalid application integrity hash")
            values["application_integrity_hash"] = _workflow_hash(application_nodes, application_edges)
        if values:
            bind.execute(sa.update(artifact_table).where(artifact_table.c.id == row["id"]).values(**values))


def upgrade() -> None:
    """Rewrite identities and every durable hash/binding that depends on them."""

    bind = op.get_bind()
    affected = _rewrite_live_nodes(bind, SERIALIZED_NODE_TYPE_ALIASES)
    _rewrite_artifact_grants(bind, affected, downgrade=False)
    _rewrite_json_column(bind, "workflow_version", SERIALIZED_NODE_TYPE_ALIASES)
    _rewrite_json_column(bind, "project_version", SERIALIZED_NODE_TYPE_ALIASES)


def downgrade() -> None:
    """Restore suffix-era identities when all artifact bytes remain compatible."""

    bind = op.get_bind()
    _require_downgrade_safe(bind)
    affected = _rewrite_live_nodes(bind, _LEGACY_BY_CANONICAL)
    _rewrite_artifact_grants(bind, affected, downgrade=True)
    _rewrite_json_column(bind, "workflow_version", _LEGACY_BY_CANONICAL)
    _rewrite_json_column(bind, "project_version", _LEGACY_BY_CANONICAL)
