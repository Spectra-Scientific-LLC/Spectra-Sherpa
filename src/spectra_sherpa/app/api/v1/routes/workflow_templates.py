"""
API endpoints for workflow templates.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast, get_args

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    check_demo_capability,
    get_current_user,
    get_session,
)
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.lib.data_formats import CANONICAL_FILE_LOAD_EXTENSIONS
from spectra_sherpa.app.lib.data_roles import normalize_modalities
from spectra_sherpa.app.lib.dataset_compatibility import (
    analysis_profile_from_dataset,
    build_analysis_profile_readiness,
    build_compatibility_matrix,
    evaluate_template_compatibility,
)
from spectra_sherpa.app.lib.reference_artifacts import model_neutral_dataset_catalog, registered_reference_catalog
from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar
from spectra_sherpa.app.lib.target_authority import issue_target_authority, verify_target_authority
from spectra_sherpa.app.lib.template_runtime import template_runtime_readiness
from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW, MANAGED_CANDIDATE_AUTHORITY
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.schemas.template_schema import TemplateCanonicalProject, TemplateStatus
from spectra_sherpa.app.schemas.workflows import WorkflowDetail
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import (
    CanonicalWorkbenchBaselineError,
    canonical_workbench_baseline_from_records,
)
from spectra_sherpa.app.services.dag.executor_types import (
    WorkflowEdge as ExecutorWorkflowEdge,
)
from spectra_sherpa.app.services.dag.executor_types import (
    WorkflowNode as ExecutorWorkflowNode,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset
from spectra_sherpa.app.services.dag.nodes.data.sample_table import load_portable_sample_table
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.services.experiments import (
    delete_experiment_files,
    ensure_experiment_dirs,
    experiment_dir,
    import_reference_dataset,
    metadata_path_for,
    read_metadata,
    relative_to_data_dir,
    resolve_data_path,
    write_metadata,
)
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.app.services.prepared_data import (
    apply_dataset_prepared_data_overrides,
    load_prepared_data_overrides_strict,
)
from spectra_sherpa.app.services.template_availability import template_admitted_in_profile
from spectra_sherpa.app.services.template_workflow_persistence import persist_template_workflow
from spectra_sherpa.app.services.workflow_access import require_experiment_access, require_file_access
from spectra_sherpa.app.services.workflow_data_selections import selection_from_parameters
from spectra_sherpa.core.target_authority import TargetAuthority

router = APIRouter(prefix="/workflow-templates")
logger = logging.getLogger(__name__)

_TEMPLATE_STATUSES = frozenset(get_args(TemplateStatus))
TargetType = Literal["continuous", "categorical"]
LaunchMode = Literal["example", "user", "draft"]
ExampleSource = Literal["eigenvector", "sklearn", "oes", "synthetic"]
DataModality = Literal["spectra", "features", "hsi"]


class CompatibilityPreviewRequest(BaseModel):
    """One explicit My Dataset structural profile for read-only matching."""

    model_config = ConfigDict(extra="forbid")

    analysis_profile: dict[str, Any]


def _template_status(template: WorkflowTemplate) -> TemplateStatus:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    raw_status = template_data.get("status")
    if raw_status not in _TEMPLATE_STATUSES:
        raise ValueError(f"Template {template.slug!r} has no declared supported status")
    return cast(TemplateStatus, raw_status)


def _template_status_detail(template: WorkflowTemplate) -> str | None:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    status = _template_status(template)
    detail = template_data.get("status_detail")
    if status == "ready":
        if detail is not None:
            raise ValueError(f"Ready template {template.slug!r} must not declare status_detail")
        return None
    if not isinstance(detail, str) or not detail.strip() or detail != detail.strip() or len(detail) > 512:
        raise ValueError(f"Template {template.slug!r} has no exact status_detail")
    return detail


def _template_modalities(template: WorkflowTemplate) -> list[DataModality]:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    try:
        return normalize_modalities(template_data.get("data_modalities"))  # type: ignore[return-value]
    except ValueError:
        logger.warning("Template %s has invalid data_modalities; defaulting to spectra", template.id)
        return ["spectra"]


def _template_to_out(template: WorkflowTemplate) -> "WorkflowTemplateOut":
    from spectra_sherpa.app.services.template_availability import template_example_unavailable_reason

    return WorkflowTemplateOut(
        id=template.id,
        slug=getattr(template, "slug", None) or f"template_{template.id}",
        name=template.name,
        description=template.description,
        category=template.category,
        status=_template_status(template),
        status_detail=_template_status_detail(template),
        runtime_readiness=_template_runtime_readiness(template),
        data_modalities=_template_modalities(template),
        template_data=template.template_data,
        example_unavailable_reason=template_example_unavailable_reason(template),
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _template_runtime_readiness(template: WorkflowTemplate) -> dict[str, Any]:
    """Project the current server's optional dependencies for one starter."""

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    return template_runtime_readiness(template_data)


def _enforce_template_runtime_readiness(template: WorkflowTemplate) -> None:
    readiness = _template_runtime_readiness(template)
    if readiness["ready"]:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "template_runtime_unavailable",
            "message": "This server runtime cannot execute the selected analysis starter.",
            "blockers": readiness["blockers"],
            "remediation": readiness["remediation"],
            "unavailable_nodes": readiness["unavailable_nodes"],
        },
    )


def _resolve_binding_node_id(template: WorkflowTemplate, binding_key: str) -> str:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    node_ids = {
        node.get("node_id") for node in template_data.get("nodes", []) if isinstance(node, dict) and node.get("node_id")
    }
    if binding_key in node_ids:
        return binding_key

    data_roles = template_data.get("data_roles", {})
    if isinstance(data_roles, dict):
        role = data_roles.get(binding_key)
        if isinstance(role, dict):
            node_binding = role.get("node_binding")
            if isinstance(node_binding, str) and node_binding:
                return node_binding

    raise HTTPException(
        status_code=400,
        detail=f"Unknown template binding key '{binding_key}' for template '{template.name}'",
    )


def _resolve_target_port(template: WorkflowTemplate, node_binding: str) -> str:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {})
    if not isinstance(data_roles, dict):
        return "y"

    for role in data_roles.values():
        if not isinstance(role, dict):
            continue
        if role.get("node_binding") != node_binding:
            continue
        if role.get("role_type") not in {"Y_reference", "class_labels"}:
            continue
        connects_to_port = role.get("connects_to_port")
        if isinstance(connects_to_port, str) and connects_to_port:
            return connects_to_port
    return "y"


def _infer_target_type(
    template: WorkflowTemplate,
    binding: "DataBindingSpec",
    node_binding: str | None = None,
) -> TargetType:
    if binding.target_authority is not None:
        return binding.target_authority.target_type

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {})
    if isinstance(data_roles, dict):
        for role in data_roles.values():
            if not isinstance(role, dict):
                continue
            if node_binding is not None and role.get("node_binding") != node_binding:
                continue
            if role.get("role_type") not in {"Y_reference", "class_labels"}:
                continue
            target_type = role.get("target_type")
            if target_type in ("continuous", "categorical"):
                return target_type

    if template.category in {"classification", "quality_control"}:
        return "categorical"
    return "continuous"


def _required_separate_target_type(
    template: WorkflowTemplate,
    node_binding: str,
) -> TargetType | None:
    """Return the exact target type for one required separate-source role."""

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {})
    if not isinstance(data_roles, dict):
        return None
    matches = {
        role.get("target_type")
        for role in data_roles.values()
        if (
            isinstance(role, dict)
            and role.get("required", True)
            and role.get("binding_mode") == "separate_source"
            and role.get("role_type") in {"Y_reference", "class_labels"}
            and role.get("node_binding") == node_binding
            and role.get("target_type") in {"continuous", "categorical"}
        )
    }
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template.name}' declares conflicting separate target types for '{node_binding}'.",
        )
    return cast(TargetType | None, next(iter(matches), None))


def _binding_consumes_target(
    template: WorkflowTemplate,
    node_binding: str,
) -> bool:
    """Whether this template scientifically consumes a target on this source.

    Exploratory nodes may carry a selected annotation for plotting without
    treating it as a response.  Constant-target refusal belongs to supervised
    model admission, not to metadata display.
    """

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {})
    if not isinstance(data_roles, dict):
        return False
    return any(
        isinstance(role, dict)
        and role.get("required", True)
        and role.get("node_binding") == node_binding
        and role.get("role_type") in {"Y_reference", "class_labels"}
        for role in data_roles.values()
    )


def _binding_identity(
    binding: "DataBindingSpec",
) -> tuple[object, ...]:
    return (
        binding.experiment_id,
        binding.file_id,
        tuple(binding.file_ids or ()),
        binding.all_files,
        binding.stage,
        binding.asset_id,
        binding.target_authority,
        binding.group_column,
    )


def _binding_to_file_load_params(binding: "DataBindingSpec") -> dict[str, object]:
    if binding.file_ids is not None or binding.all_files:
        parameters: dict[str, object] = {
            "experiment_id": binding.experiment_id,
            "stage": binding.stage,
            "asset_id": binding.asset_id or "",
            "selected_file_ids": [str(value) for value in (binding.file_ids or [])],
            "source_manifest_sha256": binding.source_manifest_sha256 or "",
            "collection_definition_sha256": binding.collection_definition_sha256 or "",
            "scientific_collection_sha256": binding.scientific_collection_sha256 or "",
            "target_authority": (
                binding.target_authority.canonical_dict() if binding.target_authority is not None else None
            ),
            "group_column": binding.group_column or "",
        }
        if binding.display_name is not None:
            parameters["group_title"] = binding.display_name
        return parameters
    assert binding.file_id is not None
    parameters: dict[str, object] = {
        "experiment_id": binding.experiment_id,
        "file_id": binding.file_id,
        "stage": binding.stage,
    }
    if binding.asset_id is not None:
        parameters["asset_id"] = binding.asset_id
    if binding.target_authority is not None:
        parameters["target_authority"] = binding.target_authority.canonical_dict()
    return parameters


def _apply_binding_to_template_source(node: dict, binding: "DataBindingSpec") -> None:
    node_type = node.get("node_type")
    if node_type != "data.file_load":
        raise ValueError(f"Cannot apply dataset binding to node type '{node_type}'")
    if binding.file_ids is not None or binding.all_files:
        node["node_type"] = "data.collection_load"
    node["parameters"] = _binding_to_file_load_params(binding)


def _seed_initial_data_selection_revisions(
    *,
    session: AsyncSession,
    workflow: Workflow,
    workflow_nodes: list[Any],
    user_id: int,
) -> None:
    """Create the first immutable selection revision with the template sheet."""
    for source_node in workflow_nodes:
        if source_node.node_type != "data.collection_load":
            continue
        selection = selection_from_parameters(
            dict(source_node.parameters),
            dataset_name=(source_node.parameters.get("group_title") or source_node.label or source_node.node_id),
        )
        node_key = hashlib.sha256(source_node.node_id.encode("utf-8")).hexdigest()[:16]
        session.add(
            WorkflowDataSelectionRevision(
                workflow_id=workflow.id,
                source_node_id=source_node.node_id,
                revision_number=1,
                parent_revision_id=None,
                created_by=user_id,
                origin="canvas",
                reason="Initial template data binding",
                idempotency_key=f"template:{workflow.id}:{node_key}",
                selection=selection.model_dump(mode="json"),
                graph_digest=workflow.integrity_hash,
            )
        )


def _propagate_selected_target_name(
    *,
    source_node_id: str,
    selected_target: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Give reachable regression evidence the exact response selected at the source."""

    if selected_target is None:
        return
    successors: dict[str, set[str]] = {}
    for edge in edges:
        successors.setdefault(str(edge.get("from_node_id")), set()).add(str(edge.get("to_node_id")))
    reachable = {source_node_id}
    pending = [source_node_id]
    while pending:
        current = pending.pop()
        for successor in successors.get(current, set()):
            if successor not in reachable:
                reachable.add(successor)
                pending.append(successor)

    for node in nodes:
        if node.get("node_id") not in reachable:
            continue
        node_type = node.get("node_type")
        parameters = node.setdefault("parameters", {})
        if node_type == "model.fitted_pls":
            existing = parameters.get("target_names")
            target_names = [selected_target]
            if existing is not None and existing != target_names:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Fitted PLS node '{node.get('node_id')}' has a target identity that conflicts "
                        f"with selected target {selected_target!r}"
                    ),
                )
            parameters["target_names"] = target_names
            continue
        if node_type not in {"diagnostics.regression_evaluator", "diagnostics.labeled_regression_evaluator"}:
            continue
        existing = parameters.get("target_names")
        target_names = [selected_target]
        if existing is not None and existing != target_names:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Regression evaluator '{node.get('node_id')}' has target labels that conflict "
                    f"with selected target {selected_target!r}"
                ),
            )
        parameters["target_names"] = target_names


def _apply_managed_binding_to_source(
    node: dict,
    binding: "DataBindingSpec",
) -> None:
    """Bind the exact dataset and supervised response admitted for search.

    A multi-response reference file is not one scientific task until the
    scientist selects the response to optimize.  The managed source therefore
    carries the same exact target identity as the ordinary canonical DAG; the
    baseline digest and hosted resolver re-admit it before any fold runs.
    """

    if node.get("node_type") != "data.file_load":
        raise ValueError("Managed candidate source must be data.file_load")
    selected_target = binding.selected_target
    if not isinstance(selected_target, str) or not selected_target.strip():
        raise ValueError("Managed candidate source requires one exact selected target")
    if binding.file_ids is not None or binding.all_files:
        raise ValueError(
            "Managed campaign starters do not yet admit an interactive collection subset; "
            "create an ordinary analysis workflow from the selected files"
        )
    node["parameters"] = {
        "experiment_id": binding.experiment_id,
        "file_id": binding.file_id,
        "stage": binding.stage,
        "target_authority": binding.target_authority.canonical_dict(),
    }
    if binding.asset_id is not None:
        node["parameters"]["asset_id"] = binding.asset_id


def _canonical_project_contract(
    template_data: dict[str, Any],
    *,
    project_id: int | None,
) -> tuple[dict[str, Any] | None, str]:
    """Validate the optional closed starter-project contract."""

    raw_contract = template_data.get("canonical_project")
    if raw_contract is None:
        return None, str(template_data.get("schema_version", 1))

    try:
        contract = TemplateCanonicalProject.model_validate(raw_contract).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Canonical starter template contract is invalid: {exc}",
        ) from exc

    if project_id is None:
        raise HTTPException(
            status_code=400,
            detail="Canonical starter templates require a project so every declared workflow is persisted together.",
        )
    if template_data.get("schema_version", 1) != 1:
        raise HTTPException(status_code=400, detail="Canonical starter template schema version is unsupported")
    return contract, "1"


def _validate_declared_node_types(
    *,
    template: WorkflowTemplate,
    template_data: dict[str, Any],
    canonical_project: dict[str, Any] | None,
) -> None:
    """Require both visible starter DAGs to use registered node types."""

    declared_nodes = list(template_data.get("nodes", []))
    if canonical_project is not None:
        managed_candidate = canonical_project.get("managed_candidate")
        if not isinstance(managed_candidate, dict):
            raise HTTPException(status_code=400, detail="Canonical starter template has no managed candidate contract")
        declared_nodes.extend(managed_candidate.get("nodes", []))

    unknown_types = [node["node_type"] for node in declared_nodes if node["node_type"] not in node_registry]
    if unknown_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Template '{template.name}' contains unknown node type(s): "
                f"{', '.join(sorted(set(unknown_types)))}. The template may need updating."
            ),
        )


def _preflight_analysis_graph(
    *,
    template: WorkflowTemplate,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Admit the bound scientist DAG through the shared semantic authority.

    Template schemas prove that a graph is closed and structurally connected;
    this check proves that its exact bound parameters and typed edges are valid
    before any workflow row is persisted. Optional runtime dependencies remain
    an execution-time admission condition, so an OSS installation can create,
    save, and inspect an SCP-backed project before installing the SCP extra.
    """

    preflight = preflight_workflow(
        (
            ExecutorWorkflowNode(
                node_id=str(node["node_id"]),
                node_type=str(node["node_type"]),
                parameters=dict(node.get("parameters", {})),
            )
            for node in nodes
        ),
        (
            ExecutorWorkflowEdge(
                from_node=str(edge["from_node_id"]),
                to_node=str(edge["to_node_id"]),
                from_output=str(edge.get("from_output", "default")),
                to_input=str(edge.get("to_input", "default")),
            )
            for edge in edges
        ),
        require_runtime_dependencies=False,
    )
    if preflight.is_valid:
        return

    reasons = "; ".join(f"{issue.code}: {issue.message}" for issue in preflight.issues if issue.level == "error")
    raise HTTPException(
        status_code=400,
        detail=f"Template '{template.name}' failed canonical DAG preflight: {reasons}",
    )


async def _persist_managed_candidate(
    *,
    session: AsyncSession,
    template: WorkflowTemplate,
    template_version: str,
    canonical_project: dict[str, Any],
    applied_bindings: dict[str, "DataBindingSpec"],
    user_id: int,
    project_id: int,
    workflow_name: str,
    sheet_order: int,
) -> None:
    """Persist and admit the starter project's explicit managed-candidate DAG."""

    managed_candidate = canonical_project["managed_candidate"]
    managed_nodes = copy.deepcopy(managed_candidate.get("nodes", []))
    managed_edges = copy.deepcopy(managed_candidate.get("edges", []))
    managed_nodes_by_id = {
        str(node["node_id"]): node for node in managed_nodes if isinstance(node, dict) and node.get("node_id")
    }

    scientist_source_node_id = str(managed_candidate.get("scientist_source_node_id", ""))
    source_binding = applied_bindings.get(scientist_source_node_id)
    if source_binding is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Canonical starter managed candidate has no binding for its declared "
                f"scientist source '{scientist_source_node_id}'."
            ),
        )

    managed_source_node_id = str(managed_candidate.get("source_node_id", ""))
    managed_source = managed_nodes_by_id.get(managed_source_node_id)
    if managed_source is None:
        raise HTTPException(status_code=400, detail="Canonical starter managed source is missing")
    # A managed candidate optimizes one dataset against one response, and its
    # baseline digest and hosted resolver re-admit a single admitted file. A
    # collection subset -- two instrument views selected together, say -- has no
    # such single identity yet. That is a limit of this extra sheet, not of the
    # scientist's analysis, so decline to add the sheet and leave the ordinary
    # workflow alone. Raising here aborted the whole instantiation instead, so
    # selecting two files made every starter that declares a managed candidate
    # impossible to begin.
    if (
        source_binding.target_binding is not None
        or source_binding.all_files
        or (source_binding.file_ids is not None and len(source_binding.file_ids) != 1)
    ):
        logger.info(
            "Skipping the managed candidate sheet for template %r: the scientist source binds a "
            "collection subset or separate response asset, which managed starters do not admit yet. "
            "The ordinary analysis workflow is unaffected.",
            template.name,
        )
        return
    managed_binding = source_binding
    if source_binding.file_ids is not None and len(source_binding.file_ids) == 1:
        managed_binding = source_binding.model_copy(
            update={
                "file_id": source_binding.file_ids[0],
                "file_ids": None,
                "target_authority": None,
            }
        )
        assert source_binding.selected_target is not None
        assert source_binding.target_type is not None
        target_authority, asset_id = await _issue_file_target_authority(
            session,
            managed_binding,
            selected_target=source_binding.selected_target,
            target_type=source_binding.target_type,
        )
        managed_binding = managed_binding.model_copy(
            update={"target_authority": target_authority, "asset_id": asset_id}
        )
    try:
        _apply_managed_binding_to_source(managed_source, managed_binding)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    managed_workflow, managed_node_records, managed_edge_records = await persist_template_workflow(
        session=session,
        template=template,
        template_version=template_version,
        user_id=user_id,
        project_id=project_id,
        name=f"{workflow_name} — {managed_candidate['name']}",
        description=str(managed_candidate["description"]),
        nodes_data=managed_nodes,
        edges_data=managed_edges,
        canvas_state=managed_candidate.get("canvas_state", {}),
        sheet_order=sheet_order,
        purpose=MANAGED_CANDIDATE_AUTHORITY,
    )
    try:
        canonical_workbench_baseline_from_records(
            workflow_id=managed_workflow.id,
            stored_integrity_hash=managed_workflow.integrity_hash,
            nodes=managed_node_records,
            edges=managed_edge_records,
        )
    except CanonicalWorkbenchBaselineError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Canonical starter managed candidate is not admissible: {exc}",
        ) from exc


def _extract_example_reference(source_node: dict) -> tuple[str, str] | None:
    binding = source_node.get("example_binding", {}) if isinstance(source_node, dict) else {}
    if not isinstance(binding, dict):
        return None
    source = binding.get("source")
    dataset_name = binding.get("dataset_name")
    if source in {"eigenvector", "sklearn", "oes", "synthetic"}:
        if isinstance(dataset_name, str) and dataset_name:
            return (source, dataset_name)
    return None


def _resolve_example_reference(
    source_node: dict,
    override_binding: "ExampleBindingSpec | None" = None,
) -> tuple[str, str] | None:
    if override_binding is not None:
        return (override_binding.source, override_binding.dataset_name)
    return _extract_example_reference(source_node)


def _certified_example_references(template: WorkflowTemplate) -> set[tuple[str, str]]:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    certified = template_data.get("certified_datasets") or []
    if not isinstance(certified, list):
        return set()

    pairs: set[tuple[str, str]] = set()
    for entry in certified:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        name = entry.get("name")
        if isinstance(source, str) and isinstance(name, str) and name:
            pairs.add((source, name))
    return pairs


def _assert_certified_example_reference(
    template: WorkflowTemplate,
    *,
    node_id: str,
    example_ref: tuple[str, str],
) -> None:
    # Only enforce certification gate for production-ready templates;
    # WIP templates allow any dataset for development/testing.
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    status = template_data.get("status", "wip")
    if status != "ready":
        return

    certified_pairs = _certified_example_references(template)
    if not certified_pairs:
        return

    if example_ref in certified_pairs:
        return

    source, dataset_name = example_ref
    raise HTTPException(
        status_code=400,
        detail=(
            f"Template '{template.name}' only allows certified example launches. "
            f"Node '{node_id}' requested '{source}:{dataset_name}', which is not in certified_datasets."
        ),
    )


def _supports_example_mode(template_data: dict) -> bool:
    for node in template_data.get("nodes", []):
        if isinstance(node, dict) and node.get("node_type") == "data.file_load" and _extract_example_reference(node):
            return True
    return False


def _example_experiment_name(template: WorkflowTemplate, source_node: dict, multiple_sources: bool) -> str:
    if multiple_sources:
        label = source_node.get("label") or source_node.get("node_id") or "Source"
        return f"Example - {template.name} - {label}"
    return f"Example - {template.name}"


async def _create_example_experiment(
    session: AsyncSession,
    *,
    user_id: int,
    project_id: int,
    name: str,
    description: str,
    metadata: dict[str, object],
) -> Experiment:
    experiment = Experiment(
        user_id=user_id,
        project_id=project_id,
        name=name,
        description=description,
        metadata_path="",
    )
    session.add(experiment)
    await session.flush()

    metadata_file = metadata_path_for(experiment.id)
    ensure_experiment_dirs(experiment.id)
    write_metadata(metadata_file, metadata)
    experiment.metadata_path = relative_to_data_dir(metadata_file)
    await session.flush()
    return experiment


async def _materialize_example_bindings(
    session: AsyncSession,
    user_id: int,
    template: WorkflowTemplate,
    project_id: int,
    nodes_data: list[dict],
    created_experiment_ids: list[int],
    example_bindings: dict[str, "ExampleBindingSpec"] | None = None,
) -> dict[str, "DataBindingSpec"]:
    from spectra_sherpa.app.services.template_availability import template_example_unavailable_reason

    if reason := template_example_unavailable_reason(template):
        raise HTTPException(status_code=422, detail=reason)
    example_nodes = [
        node
        for node in nodes_data
        if isinstance(node, dict) and node.get("node_type") == "data.file_load" and _extract_example_reference(node)
    ]
    if not example_nodes:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template.name}' does not provide bundled example data.",
        )

    multiple_sources = len(example_nodes) > 1
    cached_bindings: dict[tuple[str, str, str | None, TargetType | None], DataBindingSpec] = {}
    bindings_by_node: dict[str, DataBindingSpec] = {}

    for node in example_nodes:
        node_id = str(node["node_id"])
        override = (example_bindings or {}).get(node_id)
        example_ref = _resolve_example_reference(node, override)
        if example_ref is None:
            continue
        from spectra_sherpa.app.contracts.project_access import uses_managed_project_access

        if uses_managed_project_access() and example_ref[0] != "synthetic":
            raise HTTPException(422, "Provider example import is unavailable. Select an uploaded My Dataset instead.")
        _assert_certified_example_reference(template, node_id=node_id, example_ref=example_ref)

        template_binding = node.get("example_binding") if isinstance(node.get("example_binding"), dict) else {}
        selected_target = override.selected_target if override is not None else template_binding.get("selected_target")
        target_type = override.target_type if override is not None else template_binding.get("target_type")
        cache_key = (*example_ref, selected_target, target_type)

        if cache_key not in cached_bindings:
            source, dataset_name = example_ref
            existing_binding = await _find_existing_example_binding(
                session=session,
                user_id=user_id,
                project_id=project_id,
                template_slug=getattr(template, "slug", None) or f"template_{template.id}",
                source=source,
                dataset_name=dataset_name,
            )
            if existing_binding is not None:
                exact_binding = existing_binding
                if selected_target is not None or target_type is not None:
                    if not isinstance(selected_target, str) or target_type not in {"continuous", "categorical"}:
                        raise HTTPException(
                            status_code=400,
                            detail="Example target selection requires one exact column and scientific type.",
                        )
                    exact_binding = exact_binding.model_copy(
                        update={
                            "target_authority": await _issue_file_target_authority(
                                session,
                                exact_binding,
                                selected_target=selected_target,
                                target_type=cast(TargetType, target_type),
                            )
                        }
                    )
                cached_bindings[cache_key] = exact_binding.model_copy(
                    update={"display_name": f"{dataset_name} (bundled example)"}
                )
                bindings_by_node[node_id] = cached_bindings[cache_key]
                continue

            experiment = await _create_example_experiment(
                session=session,
                user_id=user_id,
                project_id=project_id,
                name=_example_experiment_name(template, node, multiple_sources),
                description=f"Bundled example data materialized from template '{template.name}'",
                metadata={
                    "template_slug": getattr(template, "slug", None) or f"template_{template.id}",
                    "launch_mode": "example",
                    "example_source": source,
                    "example_dataset": dataset_name,
                },
            )
            created_experiment_ids.append(experiment.id)
            try:
                files = await import_reference_dataset(session, experiment.id, source, dataset_name)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            if len(files) != 1:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Template '{template.name}' example dataset '{dataset_name}' must materialize "
                        "as exactly one canonical portable file."
                    ),
                )

            exact_binding = DataBindingSpec(
                source="experiment",
                experiment_id=experiment.id,
                stage=files[0].stage,
                file_id=files[0].id,
            )
            if selected_target is not None or target_type is not None:
                if not isinstance(selected_target, str) or target_type not in {"continuous", "categorical"}:
                    raise HTTPException(
                        status_code=400,
                        detail="Example target selection requires one exact column and scientific type.",
                    )
                target_authority, asset_id = await _issue_file_target_authority(
                    session,
                    exact_binding,
                    selected_target=selected_target,
                    target_type=cast(TargetType, target_type),
                )
                exact_binding = exact_binding.model_copy(
                    update={"target_authority": target_authority, "asset_id": asset_id}
                )
            cached_bindings[cache_key] = exact_binding.model_copy(
                update={"display_name": f"{dataset_name} (bundled example)"}
            )

        bindings_by_node[node_id] = cached_bindings[cache_key]

    return bindings_by_node


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _issue_file_target_authority(
    session: AsyncSession,
    binding: "DataBindingSpec",
    *,
    selected_target: str,
    target_type: TargetType,
) -> tuple[TargetAuthority, str | None]:
    """Re-admit a file and return its target and exact scientific asset."""

    if binding.file_id is None or binding.file_ids is not None or binding.all_files:
        raise ValueError("single-file target authority requires one exact file")
    result = await session.execute(
        select(ExperimentFile).where(
            ExperimentFile.id == binding.file_id,
            ExperimentFile.experiment_id == binding.experiment_id,
        )
    )
    experiment_file = result.scalar_one_or_none()
    if experiment_file is None:
        raise ValueError("target authority source file is unavailable")
    source_path = experiment_dir(experiment_file.experiment_id) / experiment_file.file_path
    from spectra_sherpa.io import ingest, select_asset

    source_digest = await asyncio.to_thread(_sha256_path, source_path)
    try:
        reference = read_registered_reference_sidecar(source_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Registered reference source authority is invalid") from exc
    asset_id = binding.asset_id
    if reference is not None:
        if source_digest != reference["member_sha256"]:
            raise HTTPException(status_code=400, detail="Registered reference source bytes changed after import")
        projection_id = reference["projection_id"]
        if asset_id is not None and asset_id != projection_id:
            raise HTTPException(status_code=400, detail="Selected asset differs from the registered reference view")
        try:
            materialized = await asyncio.to_thread(materialize_reference_member, source_path, projection_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Registered reference projection could not be reproduced: {exc}",
            ) from exc
        if dict(materialized.portable_reference) != dict(reference):
            raise HTTPException(status_code=400, detail="Registered reference identity changed after import")
        dataset = materialized.dataset
        asset_id = projection_id
    else:
        parsed = await asyncio.to_thread(ingest, source_path)
        try:
            dataset = select_asset(parsed, asset_id=asset_id).dataset
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Select one exact scientific asset: {exc}") from exc
    return (
        issue_target_authority(
            dataset,
            column=selected_target,
            target_type=target_type,
            source_digest=source_digest,
        ),
        asset_id,
    )


async def _find_existing_example_binding(
    session: AsyncSession,
    *,
    user_id: int,
    project_id: int,
    template_slug: str,
    source: str,
    dataset_name: str,
) -> "DataBindingSpec | None":
    experiment_query = (
        select(Experiment)
        .where(
            Experiment.user_id == user_id,
            Experiment.project_id == project_id,
        )
        .order_by(Experiment.created_at.desc())
    )
    experiment_result = await session.execute(experiment_query)
    experiments = list(experiment_result.scalars().all())

    for experiment in experiments:
        metadata: dict[str, object] = {}
        try:
            metadata = read_metadata(resolve_data_path(experiment.metadata_path))
        except Exception:
            logger.debug(
                "Skipping example experiment metadata read failure for experiment %s", experiment.id, exc_info=True
            )
            continue

        if metadata.get("template_slug") != template_slug:
            continue
        if metadata.get("launch_mode") != "example":
            continue
        if metadata.get("example_source") != source:
            continue
        if metadata.get("example_dataset") != dataset_name:
            continue

        file_query = (
            select(ExperimentFile)
            .where(
                ExperimentFile.experiment_id == experiment.id,
                ExperimentFile.stage.in_(("raw", "synthetic")),
            )
            .order_by(ExperimentFile.created_at, ExperimentFile.id)
        )
        file_result = await session.execute(file_query)
        files = list(file_result.scalars().all())
        if not files:
            continue

        if len(files) != 1:
            continue
        return DataBindingSpec(
            source="experiment",
            experiment_id=experiment.id,
            stage=files[0].stage,
            file_id=files[0].id,
        )

    return None


def _require_target_variation(dataset: Any, selected_target: str) -> None:
    """Refuse a target that is empty or constant in the exact selected rows."""

    target = pd.Series(np.asarray(dataset.target, dtype=object).reshape(-1), dtype=object)
    if target.dropna().nunique() >= 2:
        return
    raise ValueError(f"Selected target {selected_target!r} is constant or empty in the selected dataset members")


async def _validate_binding(
    session: AsyncSession,
    user_id: int,
    binding: "DataBindingSpec",
    project_id: int | None,
    *,
    require_target_variation: bool = True,
) -> tuple["DataBindingSpec", dict[str, Any]]:
    await require_experiment_access(session, binding.experiment_id, user_id, project_id)
    if binding.file_ids is not None or binding.all_files:
        try:
            loaded = await load_project_dataset(
                session,
                user_id=user_id,
                experiment_id=binding.experiment_id,
                stage=cast(Literal["raw", "preprocessed", "synthetic"], binding.stage),
                file_ids=binding.file_ids,
                asset_id=binding.asset_id,
            )
            dataset = loaded.dataset
            if binding.target_authority is not None:
                verify_target_authority(dataset, binding.target_authority)
                dataset = attach_selected_target_dataset(
                    dataset,
                    target_type=binding.target_type,
                    target_column=binding.selected_target,
                    group_column=binding.group_column or "",
                    node_id="template_binding_validation",
                    target_authority=binding.target_authority,
                )
                if require_target_variation:
                    _require_target_variation(dataset, binding.selected_target)
            analysis_profile = analysis_profile_from_dataset(dataset)
        except ValueError as exc:
            logger.warning(
                "Scientific collection binding admission failed for experiment_id=%s file_ids=%s",
                binding.experiment_id,
                binding.file_ids,
                exc_info=True,
            )
            raise HTTPException(status_code=400, detail=f"Dataset binding could not be admitted: {exc}") from exc
        target_binding = None
        if binding.target_binding is not None:
            target_binding, _ = await _validate_binding(session, user_id, binding.target_binding, project_id)
        return (
            binding.model_copy(
                update={
                    "stage": loaded.stage,
                    "file_ids": loaded.file_ids,
                    "all_files": False,
                    "source_manifest_sha256": loaded.source_manifest_sha256,
                    "collection_definition_sha256": loaded.collection_definition_sha256,
                    "scientific_collection_sha256": loaded.scientific_collection_sha256,
                    "target_binding": target_binding,
                }
            ),
            analysis_profile,
        )

    assert binding.file_id is not None
    await require_file_access(
        session,
        binding.experiment_id,
        binding.file_id,
        user_id,
    )

    normalized_stage = binding.stage
    file_result = await session.execute(
        select(ExperimentFile).where(
            ExperimentFile.id == binding.file_id,
            ExperimentFile.experiment_id == binding.experiment_id,
        )
    )
    experiment_file = file_result.scalar_one_or_none()
    if experiment_file is None:
        raise HTTPException(status_code=404, detail="Experiment file not found")
    normalized_stage = experiment_file.stage

    from spectra_sherpa.io import builtin_registry, ingest, select_asset

    if not builtin_registry.accepts_filename(experiment_file.file_path):
        supported = ", ".join(CANONICAL_FILE_LOAD_EXTENSIONS)
        raise HTTPException(
            status_code=400,
            detail=(
                f"New Analysis templates require a canonical portable source file ({supported}). "
                "Import or convert this file through an explicit runtime-specific workflow first."
            ),
        )

    # A persisted workflow must already have one executable scientific source.
    # Re-admit the immutable bytes before any workflow row is created. A
    # registered reference uses its exact sidecar-governed projection; an
    # ordinary multi-asset file requires the Workbench-selected asset_id.
    # Parser work runs off the async application loop.
    source_path = experiment_dir(experiment_file.experiment_id) / experiment_file.file_path
    source_name = PurePosixPath(str(experiment_file.file_path).replace("\\", "/")).name or "source"
    public_source_identity = f"{normalized_stage}/{source_name}"
    try:
        reference = await asyncio.to_thread(read_registered_reference_sidecar, source_path)
        if reference is not None:
            projection_id = str(reference["projection_id"])
            if binding.asset_id is not None and binding.asset_id != projection_id:
                raise ValueError("selected asset differs from the registered reference view")
            materialized = await asyncio.to_thread(materialize_reference_member, source_path, projection_id)
            if dict(materialized.portable_reference) != dict(reference):
                raise ValueError("registered reference identity changed after import")
            dataset = materialized.dataset
            binding = binding.model_copy(update={"asset_id": projection_id})
        else:
            result = await asyncio.to_thread(ingest, source_path)
            dataset = select_asset(result, asset_id=binding.asset_id).dataset
        prepared = await asyncio.to_thread(
            load_prepared_data_overrides_strict,
            file_path=str(source_path),
        )
        dataset = apply_dataset_prepared_data_overrides(dataset, prepared.to_sidecar_dict())
        if binding.target_authority is not None:
            source_digest = await asyncio.to_thread(_sha256_path, source_path)
            verify_target_authority(
                dataset,
                binding.target_authority,
                source_digest=source_digest,
            )
        analysis_profile = analysis_profile_from_dataset(dataset)
    except (OSError, ValueError) as exc:
        # The parser exception is retained in the application log for operator
        # diagnosis, but it may contain the deployment's absolute data path.
        # An authenticated scientist needs the experiment-relative identity and
        # a recovery action, not the server filesystem layout.
        logger.warning(
            "Scientific source binding admission failed for experiment_id=%s file_id=%s path=%s",
            experiment_file.experiment_id,
            experiment_file.id,
            source_path,
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Scientific source {public_source_identity!r} could not be admitted. "
                "Re-import the source if its stored bytes are missing, or inspect it and "
                "choose its exact scientific asset_id before retrying."
            ),
        ) from exc

    target_binding = None
    if binding.target_binding is not None:
        target_binding, _ = await _validate_binding(
            session,
            user_id,
            binding.target_binding,
            project_id,
        )

    return (
        binding.model_copy(update={"stage": normalized_stage, "target_binding": target_binding}),
        analysis_profile,
    )


def _enforce_bound_dataset_requirements(
    template: WorkflowTemplate,
    *,
    node_id: str,
    binding: "DataBindingSpec",
    analysis_profile: dict[str, Any],
) -> None:
    """Refuse a structurally incompatible primary binding before persistence."""

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    roles = template_data.get("data_roles") if isinstance(template_data.get("data_roles"), dict) else {}
    effective_profile = copy.deepcopy(analysis_profile)
    provided_roles: dict[str, str | None] = {}
    for role_name, raw_role in roles.items():
        if not isinstance(raw_role, dict) or not raw_role.get("required", True):
            continue
        if str(raw_role.get("node_binding") or "") != node_id:
            continue
        role_type = str(raw_role.get("role_type") or "")
        if role_type not in {"Y_reference", "class_labels"}:
            if role_type not in {"X_spectra", "X_features", "X_hsi"}:
                # This binding itself supplies the declared secondary source
                # (reference axis, validation set, background, or metadata).
                provided_roles[str(role_name)] = None
            continue
        if binding.target_binding is not None:
            provided_roles[str(role_name)] = binding.target_binding.target_type

    if binding.selected_target is not None and binding.target_type is not None:
        # The Workbench may bind a response column at instantiation time. Its
        # explicit typed selection becomes the effective structural profile;
        # downstream attachment still verifies that the named column exists.
        effective_profile["target_type"] = binding.target_type
        effective_profile["target_fields"] = [binding.selected_target]

    decision = evaluate_template_compatibility(
        effective_profile,
        {
            "slug": template.slug,
            "name": template.name,
            "status": _template_status(template),
            "template_data": {**template_data, "status": _template_status(template)},
        },
        node_binding_filter=node_id,
        provided_roles=provided_roles,
    )
    if decision["status"] == "compatible":
        return
    reason = decision["reasons"][0] if decision["reasons"] else None
    detail = reason["message"] if isinstance(reason, dict) else "The selected dataset is not structurally ready."
    if detail:
        detail = detail[0].lower() + detail[1:]
    raise HTTPException(status_code=400, detail=f"Template '{template.name}': {detail}")


def _adapt_pca_scaling_to_bound_role(
    *,
    template: WorkflowTemplate,
    source_node_id: str,
    analysis_profile: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Make the PCA starter's scaling choice explicit for the bound X role."""

    if template.slug != "pca":
        return
    primary_role = analysis_profile.get("primary_role")
    if primary_role not in {"X_spectra", "X_features"}:
        return
    downstream: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("from_node_id") or "")
        target = str(edge.get("to_node_id") or "")
        if source and target:
            downstream.setdefault(source, set()).add(target)
    reachable = {source_node_id}
    pending = [source_node_id]
    while pending:
        current = pending.pop()
        for target in downstream.get(current, set()):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)

    method = "autoscale" if primary_role == "X_features" else "mean_center"
    label = "Autoscale Features" if primary_role == "X_features" else "Mean Center Spectra"
    for node in nodes:
        if str(node.get("node_id") or "") in reachable and node.get("node_type") == "preprocess.scale":
            node["parameters"] = {**dict(node.get("parameters") or {}), "method": method, "center": True}
            node["label"] = label


async def _is_portable_sample_table_binding(
    session: AsyncSession,
    binding: "DataBindingSpec",
) -> bool:
    """Identify the closed editor artifact from its contents, never its name.

    This decision controls whether the instantiated DAG contains an explicit
    ``data.filter_samples`` operation.  Ordinary separate target files remain
    attach-only; a portable sample table makes its recorded inclusion decisions
    executable and visible in the saved workflow.
    """

    result = await session.execute(
        select(ExperimentFile).where(
            ExperimentFile.id == binding.file_id,
            ExperimentFile.experiment_id == binding.experiment_id,
        )
    )
    experiment_file = result.scalar_one_or_none()
    if experiment_file is None:
        raise HTTPException(status_code=404, detail="Experiment file not found")
    try:
        table = load_portable_sample_table(
            experiment_dir(experiment_file.experiment_id) / experiment_file.file_path,
            selected_target=binding.selected_target,
            target_type=binding.target_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid portable sample table: {exc}") from exc
    return table is not None


def _inject_target_binding(
    template: WorkflowTemplate,
    source_node: dict,
    source_binding: "DataBindingSpec",
    nodes_data: list[dict],
    nodes_by_id: dict[str, dict],
    edges_data: list[dict],
    *,
    filter_sample_table: bool,
) -> list[dict]:
    if source_binding.target_binding is None:
        return edges_data
    if source_binding.target_binding.selected_target is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Template '{template.name}' requires an exact selected_target for a separately bound response file."
            ),
        )

    source_node_id = str(source_node["node_id"])
    target_source_id = f"{source_node_id}__target_source"
    attach_target_id = f"{source_node_id}__attach_target"
    filter_samples_id = f"{source_node_id}__filter_samples"

    injected_node_ids = {target_source_id, attach_target_id}
    if filter_sample_table:
        injected_node_ids.add(filter_samples_id)
    if injected_node_ids.intersection(nodes_by_id):
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template.name}' already contains injected target helper nodes for '{source_node_id}'",
        )

    pos_x = float(source_node.get("position_x") or 0)
    pos_y = float(source_node.get("position_y") or 0)

    target_source_node = {
        "node_id": target_source_id,
        "node_type": "data.file_load",
        "label": "Load Target Values",
        "parameters": _binding_to_file_load_params(source_binding.target_binding),
        "position_x": pos_x + 250,
        "position_y": pos_y,
    }
    attach_target_node = {
        "node_id": attach_target_id,
        "node_type": "data.attach_target",
        "label": "Attach Target",
        "parameters": {
            "target_type": _infer_target_type(template, source_binding, source_node_id),
            "target_authority": source_binding.target_binding.target_authority.canonical_dict(),
        },
        "position_x": pos_x + 125,
        "position_y": pos_y + 250,
    }

    nodes_data.extend([target_source_node, attach_target_node])
    nodes_by_id[target_source_id] = target_source_node
    nodes_by_id[attach_target_id] = attach_target_node
    if filter_sample_table:
        filter_samples_node = {
            "node_id": filter_samples_id,
            "node_type": "data.filter_samples",
            "label": "Apply Sample Inclusion",
            "parameters": {
                "field": "sample_table",
                "sample_table_column": "include",
                "filter_values": ["true"],
            },
            "position_x": pos_x + 125,
            "position_y": pos_y + 425,
        }
        nodes_data.append(filter_samples_node)
        nodes_by_id[filter_samples_id] = filter_samples_node

    updated_edges: list[dict] = []
    for edge in edges_data:
        new_edge = dict(edge)
        if new_edge.get("from_node_id") == source_node_id and new_edge.get("from_output", "default") == "default":
            new_edge["from_node_id"] = filter_samples_id if filter_sample_table else attach_target_id
        elif (
            not filter_sample_table
            and new_edge.get("from_node_id") == source_node_id
            and new_edge.get("from_output") == "target"
        ):
            # The X file has no embedded response in a separate-target binding.
            # Keep explicit response edges attached to the actual target source;
            # a null X.target happened to work live but is absent in deployment.
            new_edge["from_node_id"] = target_source_id
        updated_edges.append(new_edge)

    updated_edges.append(
        {
            "from_node_id": source_node_id,
            "to_node_id": attach_target_id,
            "from_output": "default",
            "to_input": "X",
        }
    )
    updated_edges.append(
        {
            "from_node_id": target_source_id,
            "to_node_id": attach_target_id,
            "from_output": "target",
            "to_input": _resolve_target_port(template, source_node_id),
        }
    )
    if filter_sample_table:
        updated_edges.append(
            {
                "from_node_id": target_source_id,
                "to_node_id": attach_target_id,
                "from_output": "sample_table",
                "to_input": "sample_table",
            }
        )
        updated_edges.append(
            {
                "from_node_id": attach_target_id,
                "to_node_id": filter_samples_id,
                "from_output": "default",
                "to_input": "default",
            }
        )
    return updated_edges


# Schemas for templates
class WorkflowTemplateOut(BaseModel):
    """Schema for workflow template response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str
    category: str
    status: TemplateStatus
    status_detail: str | None
    runtime_readiness: dict[str, Any]
    data_modalities: list[DataModality] = Field(default_factory=lambda: ["spectra"])
    template_data: dict
    example_unavailable_reason: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WorkflowTemplateListResponse(BaseModel):
    """Schema for list of workflow templates."""

    templates: list[WorkflowTemplateOut] = Field(..., description="Available templates")
    total: int = Field(..., description="Total number of templates")


class DataBindingSpec(BaseModel):
    """Template data binding supplied at instantiation time."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["experiment"] = "experiment"
    experiment_id: int = Field(..., description="Experiment supplying the data")
    display_name: str | None = Field(
        None,
        min_length=1,
        max_length=255,
        description="Human-readable dataset identity for workflow provenance displays",
    )
    stage: str = Field("raw", description="Experiment stage to load from")
    file_id: int | None = Field(None, ge=1, description="Exact file within the experiment")
    file_ids: list[int] | None = Field(None, min_length=1, description="Exact selected collection members")
    all_files: bool = Field(False, description="Bind the exact collection present when the workflow is authored")
    asset_id: str | None = Field(None, min_length=1, description="Exact typed asset within a multi-asset source")
    target_authority: TargetAuthority | None = Field(
        None,
        description="Inseparable response column, type, units, and exact source identity",
    )
    group_column: str | None = Field(None, min_length=1, description="Exact sample-table validation group")
    source_manifest_sha256: str | None = None
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str | None = None
    target_binding: "DataBindingSpec | None" = Field(
        None,
        description="Optional separate target binding to inject via data.attach_target",
    )

    @property
    def selected_target(self) -> str | None:
        return self.target_authority.column if self.target_authority is not None else None

    @property
    def target_type(self) -> TargetType | None:
        return self.target_authority.target_type if self.target_authority is not None else None

    @model_validator(mode="after")
    def _one_source_scope(self) -> "DataBindingSpec":
        scopes = int(self.file_id is not None) + int(self.file_ids is not None) + int(self.all_files)
        if scopes != 1:
            raise ValueError("Data binding requires exactly one file_id, file_ids selection, or all_files scope")
        if self.file_ids is not None and len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("Data binding file_ids may not contain duplicates")
        if self.group_column is not None and self.target_authority is None:
            raise ValueError("A validation group requires an explicit selected target")
        return self


DataBindingSpec.model_rebuild()


class BindingCompatibilityPreviewRequest(BaseModel):
    """Read-only readiness projection for one already-bound workflow source."""

    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., ge=1)
    binding: DataBindingSpec


@router.post("/binding-compatibility-preview")
async def preview_bound_source_compatibility(
    payload: BindingCompatibilityPreviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-admit an active sheet source before advertising starter actions."""

    await require_scientific_access(session, current_user.id, payload.project_id, "read")
    binding, analysis_profile = await _validate_binding(
        session,
        current_user.id,
        payload.binding,
        payload.project_id,
        require_target_variation=False,
    )
    if binding.selected_target is not None and binding.target_type is not None:
        analysis_profile = {
            **analysis_profile,
            "target_type": binding.target_type,
            "target_fields": [binding.selected_target],
        }
    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.slug)
    )
    templates = [template for template in result.scalars().all() if template_admitted_in_profile(template)]
    return build_analysis_profile_readiness(
        analysis_profile,
        [
            {
                "slug": template.slug,
                "name": template.name,
                "category": template.category,
                "status": _template_status(template),
                "template_data": {
                    **(template.template_data if isinstance(template.template_data, dict) else {}),
                    "status": _template_status(template),
                },
                "runtime_readiness": _template_runtime_readiness(template),
            }
            for template in templates
        ],
    )


def _normalize_binding_target_authority(
    template: WorkflowTemplate,
    binding: DataBindingSpec,
    node_binding: str,
) -> DataBindingSpec:
    """Refuse target authorities that disagree with the template contract.

    Target type is never inferred or repaired here.  The scientist's selection
    has already been issued as one source-bound authority by My Dataset.
    """

    separate_type = _required_separate_target_type(template, node_binding)
    if separate_type is not None:
        if binding.target_authority is not None or binding.group_column is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template '{template.name}' requires a separate {separate_type} target source; "
                    "the primary dataset binding cannot also select an embedded target or validation group."
                ),
            )
        target_binding = binding.target_binding
        if target_binding is not None:
            if target_binding.target_authority is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Template '{template.name}' requires an exact response column in its separate target source."
                    ),
                )
            if target_binding.target_type != separate_type:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Template '{template.name}' requires a {separate_type} separate target, but "
                        f"{target_binding.selected_target!r} was declared {target_binding.target_type}."
                    ),
                )
        return binding.model_copy(update={"target_binding": target_binding})

    if binding.target_authority is None and binding.target_binding is not None:
        expected_type = _infer_target_type(template, binding, node_binding)
        target_binding = binding.target_binding
        if target_binding.target_authority is None:
            raise HTTPException(
                status_code=400,
                detail=f"Template '{template.name}' requires an exact response column in its target source.",
            )
        if target_binding.target_type != expected_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template '{template.name}' requires a {expected_type} target, but "
                    f"{target_binding.selected_target!r} was declared {target_binding.target_type}."
                ),
            )
        return binding.model_copy(update={"target_binding": target_binding})
    return binding


class ExampleBindingSpec(BaseModel):
    """Selected bundled example dataset for a source node."""

    source: ExampleSource = Field(..., description="Reference dataset source")
    dataset_name: str = Field(..., min_length=1, description="Dataset name from the source catalog")
    selected_target: str | None = Field(None, min_length=1, description="Exact response name")
    target_type: TargetType | None = None


class InstantiateTemplateRequest(BaseModel):
    """Schema for instantiating a template into a workflow."""

    workflow_name: str = Field(..., description="Name for the new workflow")
    workflow_description: str | None = Field(None, description="Optional description for the new workflow")
    project_id: int | None = Field(None, description="Optional project to link the instantiated workflow to")
    launch_mode: LaunchMode = Field(
        "user",
        description=(
            "Instantiate against bundled example data, explicit user data, or as an unbound draft starter workflow"
        ),
    )
    data_bindings: dict[str, DataBindingSpec] = Field(
        default_factory=dict,
        description="Bindings keyed by source node_id or template data-role name",
    )
    example_bindings: dict[str, ExampleBindingSpec] = Field(
        default_factory=dict,
        description="Optional example dataset selections keyed by source node_id",
    )


def _draft_bindings_for_request(payload: InstantiateTemplateRequest) -> dict[str, DataBindingSpec]:
    if payload.project_id is None:
        raise HTTPException(
            status_code=400,
            detail="Draft launch mode requires a project.",
        )
    if payload.data_bindings or payload.example_bindings:
        raise HTTPException(
            status_code=400,
            detail="Draft launch mode does not accept data or example bindings.",
        )
    return {}


@router.get("", response_model=WorkflowTemplateListResponse)
async def list_templates(
    category: str | None = Query(None, description="Filter by category"),
    include_wip: bool = Query(False, description="Include pending and work-in-progress templates"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> WorkflowTemplateListResponse:
    """List active workflow templates, defaulting to production-ready entries only."""
    query = select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True))

    if category:
        query = query.where(WorkflowTemplate.category == category)

    result = await session.execute(query.order_by(WorkflowTemplate.category, WorkflowTemplate.name))
    templates = [template for template in result.scalars().all() if template_admitted_in_profile(template)]

    if not include_wip:
        templates = [template for template in templates if _template_status(template) == "ready"]

    total = len(templates)
    templates = templates[offset : offset + limit]

    return WorkflowTemplateListResponse(
        templates=[_template_to_out(template) for template in templates],
        total=total,
    )


@router.get("/categories", response_model=list[str])
async def list_template_categories(
    include_wip: bool = Query(False, description="Include categories that only contain pending or WIP templates"),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Get template categories from the active template set."""
    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.category)
    )
    templates = [template for template in result.scalars().all() if template_admitted_in_profile(template)]
    if not include_wip:
        templates = [template for template in templates if _template_status(template) == "ready"]

    categories = sorted({template.category for template in templates})
    return categories


@router.get("/compatibility-matrix")
async def get_reference_compatibility_matrix(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the total registered-reference × active-template decision matrix."""

    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.slug)
    )
    templates = [template for template in result.scalars().all() if template_admitted_in_profile(template)]
    template_payloads = [
        {
            "slug": template.slug,
            "name": template.name,
            "category": template.category,
            "status": _template_status(template),
            "template_data": {
                **(template.template_data if isinstance(template.template_data, dict) else {}),
                "status": _template_status(template),
            },
            "runtime_readiness": _template_runtime_readiness(template),
        }
        for template in templates
    ]
    catalog = model_neutral_dataset_catalog()
    from spectra_sherpa.app.services.experiments import builtin_lavender_source_files

    if not builtin_lavender_source_files():
        catalog = [dataset for dataset in catalog if dataset.get("dataset_id") != "builtin:lavender-essential-oil-v1"]
    dataset_payloads = [
        {
            "dataset_id": dataset.get("dataset_id") or f"{dataset['source']}:{dataset['name']}",
            "analysis_profile": dataset["analysis_profile"],
        }
        for dataset in catalog
    ]
    matrix = build_compatibility_matrix(dataset_payloads, template_payloads)
    return {
        "schema_version": "spectra-sherpa-reference-template-matrix/1",
        "dataset_count": len(dataset_payloads),
        "template_count": len(template_payloads),
        "pair_count": len(matrix),
        "datasets": catalog,
        "matrix": matrix,
    }


@router.post("/compatibility-preview")
async def preview_analysis_profile_compatibility(
    payload: CompatibilityPreviewRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-evaluate a target choice through the canonical compatibility engine."""

    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.slug)
    )
    templates = [template for template in result.scalars().all() if template_admitted_in_profile(template)]
    template_payloads = [
        {
            "slug": template.slug,
            "name": template.name,
            "category": template.category,
            "status": _template_status(template),
            "template_data": {
                **(template.template_data if isinstance(template.template_data, dict) else {}),
                "status": _template_status(template),
            },
            "runtime_readiness": _template_runtime_readiness(template),
        }
        for template in templates
    ]
    return build_analysis_profile_readiness(payload.analysis_profile, template_payloads)


@router.get("/{template_id}", response_model=WorkflowTemplateOut)
async def get_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
) -> WorkflowTemplateOut:
    """Get a specific workflow template by ID."""
    query = (
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id).where(WorkflowTemplate.is_active.is_(True))
    )
    result = await session.execute(query)
    template = result.scalar_one_or_none()

    if template is None or not template_admitted_in_profile(template):
        raise HTTPException(status_code=404, detail="Template not found or unavailable in this deployment profile")

    return _template_to_out(template)


def _compute_dataset_matches(
    data_roles: dict[str, dict],
    catalog: list[dict[str, Any]],
    certified_datasets: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """For each data role, return datasets sorted by scientific match score.

    ``certified_datasets`` identifies qualified example journeys; it is not a
    model-to-dataset allowlist. Compatible scientist-selected data remains
    visible and carries an explicit ``certified_example`` flag.
    """
    certified_set = {(c["source"], c["name"]) for c in (certified_datasets or [])}

    matches: dict[str, list[dict[str, Any]]] = {}

    for role_key, role in data_roles.items():
        accepted = {t.upper() for t in (role.get("accepted_techniques") or [])}
        accepted_roles = set(role.get("accepted_data_roles") or [])
        scored: list[dict[str, Any]] = []

        for ds in catalog:
            ds_role = ds.get("data_role")
            if accepted_roles and ds_role not in accepted_roles:
                continue
            # Baseline of 1 when the dataset's data_role matches the template's
            # accepted_data_roles, OR when certified_datasets are in play. The
            # three-shape role match alone makes a dataset eligible — without
            # this, feature-table sources (sklearn:wine/iris, technique
            # "ML/Statistics") get score=0 against spectroscopy templates whose
            # accepted_techniques only list FTIR/NIR/Raman/etc., and they
            # silently disappear from the wizard dropdown even though the
            # template accepts X_features. Technique-match still adds +10 below
            # so spectra → spectra templates rank ahead of feature-tables.
            score = 1 if (accepted_roles or certified_set) else 0
            tech = (ds.get("technique") or "").upper()

            # Technique match (primary signal)
            if accepted and tech:
                if tech in accepted:
                    score += 10
                elif any(a in tech or tech in a for a in accepted):
                    score += 5  # partial match (e.g. "IR" in "FTIR")
            elif not accepted:
                score += 3  # no restriction = everything is a candidate

            # Target type match
            role_target = role.get("target_type")
            if role_target and ds.get("target_type") == role_target:
                score += 5

            # Embedded target for Y roles
            role_type = role.get("role_type", "")
            if role_type in ("Y_reference", "class_labels") and ds.get("has_embedded_target"):
                score += 3

            if score > 0:
                scored.append(
                    {
                        **ds,
                        "match_score": score,
                        "certified_example": (ds["source"], ds["name"]) in certified_set,
                    }
                )

        scored.sort(key=lambda x: -x["match_score"])
        matches[role_key] = scored

    return matches


def _build_flat_catalog() -> list[dict[str, Any]]:
    """Build a flat list of all reference datasets from all sources."""
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
    from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG
    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG
    from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

    flat: list[dict[str, Any]] = [dict(item) for item in registered_reference_catalog()]

    for k, v in SYNTHETIC_REFERENCE_CATALOG.items():
        flat.append(
            {
                "name": k,
                "source": "synthetic",
                "label": v["label"],
                "technique": v["technique"],
                "data_role": "X_spectra",
                "data_modality": "spectra",
                "description": v["description"],
                "featured": v.get("featured", False),
                "has_embedded_target": bool(v.get("target_fields")),
                "target_type": v.get("target_type"),
                "target_fields": list(v.get("target_fields") or []),
            }
        )

    for k, v in DATASET_CATALOG.items():
        flat.append(
            {
                "name": k,
                "source": "eigenvector",
                "label": v["label"],
                "technique": v["technique"],
                "data_role": "X_spectra",
                "data_modality": "spectra",
                "description": v["description"],
                "featured": v.get("featured", False),
                "has_embedded_target": bool(v.get("prop_names")),
                "target_type": "continuous" if v.get("prop_names") else None,
                "target_fields": list(v.get("prop_names") or []),
            }
        )

    for k, v in OES_CATALOG.items():
        flat.append(
            {
                "name": k,
                "source": "oes",
                "label": v["label"],
                "technique": v["technique"],
                "data_role": "X_spectra",
                "data_modality": "spectra",
                "description": v["description"],
                "featured": v.get("featured", False),
                "has_embedded_target": False,
                "target_type": None,
            }
        )

    for k, v in SKLEARN_CATALOG.items():
        flat.append(
            {
                "name": k,
                "source": "sklearn",
                "label": v["label"],
                "technique": "ML/Statistics",
                "data_role": "X_features",
                "data_modality": "features",
                "description": f"Scikit-learn {k} dataset",
                "has_embedded_target": True,
                "target_type": ("categorical" if v.get("task_type") == "classification" else "continuous"),
                "target_fields": ["target"],
                "task_type": v.get("task_type"),
            }
        )

    return flat


@router.get("/{template_id}/matching-datasets")
async def get_matching_datasets(
    template_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[dict[str, Any]]]:
    """Return reference datasets matched against template data roles, ranked by score."""
    query = select(WorkflowTemplate).where(
        WorkflowTemplate.id == template_id,
        WorkflowTemplate.is_active.is_(True),
    )
    result = await session.execute(query)
    template = result.scalar_one_or_none()
    if template is None or not template_admitted_in_profile(template):
        raise HTTPException(status_code=404, detail="Template not found or unavailable in this deployment profile")

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {})
    if not data_roles:
        return {}

    catalog = _build_flat_catalog()
    # Only restrict to certified datasets for production-ready templates;
    # WIP templates show the full catalog so developers can test freely.
    status = template_data.get("status", "wip")
    certified = template_data.get("certified_datasets") or [] if status == "ready" else []
    return _compute_dataset_matches(data_roles, catalog, certified_datasets=certified)


@router.post("/{template_id}/instantiate", response_model=WorkflowDetail, status_code=201)
async def instantiate_template(
    template_id: int,
    payload: InstantiateTemplateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """
    Instantiate a template into a new workflow for the current user.

    The template definition remains canonical. User-supplied bindings rewrite only
    the source-node parameters required to point the workflow at project data.
    """
    user_id = current_user.id

    await require_scientific_access(session, user_id, payload.project_id, "write")

    template_query = (
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id).where(WorkflowTemplate.is_active.is_(True))
    )
    template_result = await session.execute(template_query)
    template = template_result.scalar_one_or_none()

    if template is None or not template_admitted_in_profile(template):
        raise HTTPException(status_code=404, detail="Template not found or unavailable in this deployment profile")
    if _template_status(template) != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Template is not ready for use (status: {_template_status(template)})",
        )
    _enforce_template_runtime_readiness(template)

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    canonical_project, template_version = _canonical_project_contract(
        template_data,
        project_id=payload.project_id,
    )
    data_roles = template_data.get("data_roles", {}) if isinstance(template_data.get("data_roles", {}), dict) else {}
    _validate_declared_node_types(
        template=template,
        template_data=template_data,
        canonical_project=canonical_project,
    )

    nodes_data = copy.deepcopy(template_data.get("nodes", []))
    edges_data = copy.deepcopy(template_data.get("edges", []))
    nodes_by_id = {str(node["node_id"]): node for node in nodes_data if isinstance(node, dict) and node.get("node_id")}
    required_source_bindings = {
        str(role.get("node_binding"))
        for role in data_roles.values()
        if isinstance(role, dict) and role.get("required", True) and role.get("node_binding")
    }
    required_separate_targets = {
        str(role.get("node_binding"))
        for role in data_roles.values()
        if (
            isinstance(role, dict)
            and role.get("required", True)
            and role.get("binding_mode") == "separate_source"
            and role.get("role_type") in {"Y_reference", "class_labels"}
            and role.get("node_binding")
        )
    }

    created_example_experiment_ids: list[int] = []
    committed = False
    try:
        bindings_to_apply: dict[str, DataBindingSpec]
        if payload.launch_mode == "example":
            check_demo_capability("reference_data_import")
            if payload.data_bindings:
                raise HTTPException(
                    status_code=400,
                    detail="Example launch mode does not accept manual data bindings.",
                )
            if payload.project_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Example launch mode requires a project so the bundled "
                        "dataset stays visible in project context."
                    ),
                )
            if not _supports_example_mode(template_data):
                raise HTTPException(
                    status_code=400,
                    detail=f"Template '{template.name}' does not provide bundled example data.",
                )
            bindings_to_apply = await _materialize_example_bindings(
                session=session,
                user_id=user_id,
                template=template,
                project_id=payload.project_id,
                nodes_data=nodes_data,
                created_experiment_ids=created_example_experiment_ids,
                example_bindings=payload.example_bindings,
            )
        elif payload.launch_mode == "draft":
            bindings_to_apply = _draft_bindings_for_request(payload)
        else:
            if required_source_bindings and not payload.data_bindings:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Template '{template.name}' requires explicit project data bindings. "
                        "Select experiment files for the template roles before instantiation."
                    ),
                )
            bindings_to_apply = payload.data_bindings

        applied_bindings: dict[str, DataBindingSpec] = {}
        injected_targets: set[str] = set()

        for binding_key, binding_spec in bindings_to_apply.items():
            node_id = _resolve_binding_node_id(template, binding_key)
            binding_spec = _normalize_binding_target_authority(template, binding_spec, node_id)
            normalized_binding, analysis_profile = await _validate_binding(
                session,
                user_id,
                binding_spec,
                payload.project_id,
                require_target_variation=_binding_consumes_target(template, node_id),
            )
            node = nodes_by_id.get(node_id)
            if node is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template '{template.name}' has no source node '{node_id}'",
                )
            if node.get("node_type") != "data.file_load":
                raise HTTPException(
                    status_code=400,
                    detail=f"Binding '{binding_key}' targets node '{node_id}', which is not a data source node",
                )

            if payload.launch_mode == "user":
                _enforce_bound_dataset_requirements(
                    template,
                    node_id=node_id,
                    binding=normalized_binding,
                    analysis_profile=analysis_profile,
                )

            binding_identity = _binding_identity(normalized_binding)
            existing_binding = applied_bindings.get(node_id)
            if existing_binding is not None and _binding_identity(existing_binding) != binding_identity:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Conflicting bindings supplied for source node '{node_id}'. "
                        "Embedded template roles bound to the same source must use the same experiment file."
                    ),
                )
            applied_bindings[node_id] = normalized_binding

            try:
                _apply_binding_to_template_source(node, normalized_binding)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            _adapt_pca_scaling_to_bound_role(
                template=template,
                source_node_id=node_id,
                analysis_profile=analysis_profile,
                nodes=nodes_data,
                edges=edges_data,
            )

            if normalized_binding.target_binding is not None:
                if node_id in injected_targets:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Multiple target bindings supplied for source node '{node_id}'",
                    )
                filter_sample_table = await _is_portable_sample_table_binding(
                    session,
                    normalized_binding.target_binding,
                )
                edges_data = _inject_target_binding(
                    template,
                    node,
                    normalized_binding,
                    nodes_data,
                    nodes_by_id,
                    edges_data,
                    filter_sample_table=filter_sample_table,
                )
                injected_targets.add(node_id)

            _propagate_selected_target_name(
                source_node_id=node_id,
                selected_target=normalized_binding.selected_target,
                nodes=nodes_data,
                edges=edges_data,
            )

        if payload.launch_mode != "draft":
            missing_bindings = sorted(required_source_bindings.difference(applied_bindings))
            if missing_bindings:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Missing required data bindings for source node(s): {', '.join(missing_bindings)}. "
                        "Templates no longer instantiate with hidden demo data."
                    ),
                )

            missing_target_bindings = sorted(required_separate_targets.difference(injected_targets))
            if missing_target_bindings:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Missing required separate target bindings for source node(s): "
                        f"{', '.join(missing_target_bindings)}."
                    ),
                )

        if payload.launch_mode != "draft":
            _preflight_analysis_graph(
                template=template,
                nodes=nodes_data,
                edges=edges_data,
            )

        first_sheet_order = 0
        if payload.project_id is not None:
            max_order = await session.scalar(
                select(func.max(Workflow.sheet_order)).where(
                    Workflow.user_id == user_id,
                    Workflow.project_id == payload.project_id,
                )
            )
            first_sheet_order = (max_order if max_order is not None else -1) + 1

        workflow, workflow_nodes, _ = await persist_template_workflow(
            session=session,
            template=template,
            template_version=template_version,
            user_id=user_id,
            project_id=payload.project_id,
            name=payload.workflow_name,
            description=payload.workflow_description or f"Created from template: {template.name}",
            nodes_data=nodes_data,
            edges_data=edges_data,
            canvas_state=template_data.get("canvas_state", {}),
            sheet_order=first_sheet_order,
            purpose=ANALYSIS_WORKFLOW,
            data_origin="example" if payload.launch_mode == "example" else "current",
            data_source_display_names={
                node_id: binding.display_name
                for node_id, binding in applied_bindings.items()
                if binding.display_name is not None
            },
        )

        _seed_initial_data_selection_revisions(
            session=session,
            workflow=workflow,
            workflow_nodes=workflow_nodes,
            user_id=user_id,
        )

        if canonical_project is not None:
            if payload.project_id is None:  # Defensive: the closed contract rejects this above.
                raise HTTPException(status_code=400, detail="Canonical starter project is missing a project")
            await _persist_managed_candidate(
                session=session,
                template=template,
                template_version=template_version,
                canonical_project=canonical_project,
                applied_bindings=applied_bindings,
                user_id=user_id,
                project_id=payload.project_id,
                workflow_name=payload.workflow_name,
                sheet_order=first_sheet_order + 1,
            )

        await session.commit()
        committed = True
        await session.refresh(workflow)

        from sqlalchemy.orm import selectinload

        reload_query = (
            select(Workflow)
            .where(Workflow.id == workflow.id)
            .options(
                selectinload(Workflow.nodes),
                selectinload(Workflow.edges),
                selectinload(Workflow.tags),
                selectinload(Workflow.folder),
                selectinload(Workflow.primary_data_source),
                selectinload(Workflow.data_source_links),
                selectinload(Workflow.advisor_channels),
            )
        )
        reload_result = await session.execute(reload_query)
        workflow = reload_result.scalar_one()

        return WorkflowDetail.model_validate(workflow)
    except Exception:
        if not committed:
            await session.rollback()
            for experiment_id in reversed(created_example_experiment_ids):
                try:
                    delete_experiment_files(experiment_id)
                except FileNotFoundError:
                    pass
                except Exception:
                    logger.exception("Failed to clean up example experiment files for exp_%03d", experiment_id)
        raise
