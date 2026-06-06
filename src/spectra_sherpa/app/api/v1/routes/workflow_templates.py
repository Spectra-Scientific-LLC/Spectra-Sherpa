"""
API endpoints for workflow templates.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    get_current_user,
    get_session,
    require_experiment,
    require_project,
)
from spectra_sherpa.app.lib.data_roles import normalize_modalities
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.schemas.workflows import WorkflowDetail
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.experiments import (
    delete_experiment_files,
    ensure_experiment_dirs,
    import_reference_dataset,
    metadata_path_for,
    read_metadata,
    relative_to_data_dir,
    resolve_data_path,
    write_metadata,
)
from spectra_sherpa.app.services.project_data_sources import (
    ensure_sheet_advisor_channel,
    sync_workflow_data_sources,
)

router = APIRouter(prefix="/workflow-templates")
logger = logging.getLogger(__name__)

TemplateStatus = Literal["ready", "wip"]
TargetType = Literal["continuous", "categorical"]
LaunchMode = Literal["example", "user"]
ExampleSource = Literal["eigenvector", "sklearn", "spectrochempy", "oes", "synthetic"]
DataModality = Literal["spectra", "features", "hsi"]


def _template_status(template: WorkflowTemplate) -> TemplateStatus:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    raw_status = template_data.get("status")
    return "wip" if raw_status == "wip" else "ready"


def _template_modalities(template: WorkflowTemplate) -> list[DataModality]:
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    try:
        return normalize_modalities(template_data.get("data_modalities"))  # type: ignore[return-value]
    except ValueError:
        logger.warning("Template %s has invalid data_modalities; defaulting to spectra", template.id)
        return ["spectra"]


def _template_to_out(template: WorkflowTemplate) -> "WorkflowTemplateOut":
    return WorkflowTemplateOut(
        id=template.id,
        slug=getattr(template, "slug", None) or f"template_{template.id}",
        name=template.name,
        description=template.description,
        category=template.category,
        status=_template_status(template),
        data_modalities=_template_modalities(template),
        template_data=template.template_data,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
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
    if binding.target_type in ("continuous", "categorical"):
        return binding.target_type

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


def _binding_identity(binding: "DataBindingSpec") -> tuple[int, int | None, str]:
    return (binding.experiment_id, binding.file_id, binding.stage)


def _binding_to_source_params(binding: "DataBindingSpec") -> dict[str, object]:
    return {
        "source": "experiment",
        "experiment_id": binding.experiment_id,
        "file_id": binding.file_id,
        "stage": binding.stage,
    }


def _binding_to_my_dataset_params(binding: "DataBindingSpec") -> dict[str, object]:
    return {"dataset_id": binding.experiment_id}


def _apply_binding_to_template_source(node: dict, binding: "DataBindingSpec") -> None:
    node_type = node.get("node_type")
    if node_type not in {"data.source", "data.my_dataset"}:
        raise ValueError(f"Cannot apply dataset binding to node type '{node_type}'")
    node["node_type"] = "data.my_dataset"
    node["parameters"] = _binding_to_my_dataset_params(binding)


def _extract_example_reference(source_node: dict) -> tuple[str, str] | None:
    parameters = source_node.get("parameters", {}) if isinstance(source_node, dict) else {}
    if not isinstance(parameters, dict):
        return None

    source = parameters.get("source")
    if source == "eigenvector" and isinstance(parameters.get("eigenvector_dataset"), str):
        return ("eigenvector", parameters["eigenvector_dataset"])
    if source == "sklearn" and isinstance(parameters.get("sklearn_dataset"), str):
        return ("sklearn", parameters["sklearn_dataset"])
    if source == "spectrochempy":
        dataset_name = parameters.get("example_dataset") or parameters.get("example_file")
        if isinstance(dataset_name, str) and dataset_name:
            return ("spectrochempy", dataset_name)
    if source == "oes" and isinstance(parameters.get("oes_dataset"), str):
        return ("oes", parameters["oes_dataset"])
    if source == "synthetic" and isinstance(parameters.get("synthetic_dataset"), str):
        return ("synthetic", parameters["synthetic_dataset"])
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
        if isinstance(node, dict) and node.get("node_type") == "data.source" and _extract_example_reference(node):
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
    example_nodes = [
        node
        for node in nodes_data
        if isinstance(node, dict) and node.get("node_type") == "data.source" and _extract_example_reference(node)
    ]
    if not example_nodes:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template.name}' does not provide bundled example data.",
        )

    multiple_sources = len(example_nodes) > 1
    cached_bindings: dict[tuple[str, str], DataBindingSpec] = {}
    bindings_by_node: dict[str, DataBindingSpec] = {}

    for node in example_nodes:
        node_id = str(node["node_id"])
        example_ref = _resolve_example_reference(node, (example_bindings or {}).get(node_id))
        if example_ref is None:
            continue
        _assert_certified_example_reference(template, node_id=node_id, example_ref=example_ref)

        if example_ref not in cached_bindings:
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
                cached_bindings[example_ref] = existing_binding
                bindings_by_node[node_id] = existing_binding
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

            if not files:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template '{template.name}' example dataset '{dataset_name}' produced no importable files.",
                )

            cached_bindings[example_ref] = DataBindingSpec(
                source="experiment",
                experiment_id=experiment.id,
                stage=files[0].stage,
                file_id=files[0].id if len(files) == 1 else None,
            )

        bindings_by_node[node_id] = cached_bindings[example_ref]

    return bindings_by_node


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

        return DataBindingSpec(
            source="experiment",
            experiment_id=experiment.id,
            stage=files[0].stage,
            file_id=files[0].id if len(files) == 1 else None,
        )

    return None


async def _validate_binding(
    session: AsyncSession,
    user_id: int,
    binding: "DataBindingSpec",
) -> "DataBindingSpec":
    await require_experiment(binding.experiment_id, user_id, session)

    normalized_stage = binding.stage
    if binding.file_id is not None:
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

    target_binding = None
    if binding.target_binding is not None:
        target_binding = await _validate_binding(session, user_id, binding.target_binding)

    return binding.model_copy(update={"stage": normalized_stage, "target_binding": target_binding})


def _inject_target_binding(
    template: WorkflowTemplate,
    source_node: dict,
    source_binding: "DataBindingSpec",
    nodes_data: list[dict],
    nodes_by_id: dict[str, dict],
    edges_data: list[dict],
) -> list[dict]:
    if source_binding.target_binding is None:
        return edges_data

    source_node_id = str(source_node["node_id"])
    target_source_id = f"{source_node_id}__target_source"
    attach_target_id = f"{source_node_id}__attach_target"

    if target_source_id in nodes_by_id or attach_target_id in nodes_by_id:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template.name}' already contains injected target helper nodes for '{source_node_id}'",
        )

    pos_x = float(source_node.get("position_x") or 0)
    pos_y = float(source_node.get("position_y") or 0)

    target_source_node = {
        "node_id": target_source_id,
        "node_type": "data.source",
        "label": "Load Target Values",
        "parameters": _binding_to_source_params(source_binding.target_binding),
        "position_x": pos_x + 250,
        "position_y": pos_y,
    }
    attach_target_node = {
        "node_id": attach_target_id,
        "node_type": "data.attach_target",
        "label": "Attach Target",
        "parameters": {"target_type": _infer_target_type(template, source_binding, source_node_id)},
        "position_x": pos_x + 125,
        "position_y": pos_y + 250,
    }

    nodes_data.extend([target_source_node, attach_target_node])
    nodes_by_id[target_source_id] = target_source_node
    nodes_by_id[attach_target_id] = attach_target_node

    updated_edges: list[dict] = []
    for edge in edges_data:
        new_edge = dict(edge)
        if new_edge.get("from_node_id") == source_node_id and new_edge.get("from_output", "default") == "default":
            new_edge["from_node_id"] = attach_target_id
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
            "from_output": "default",
            "to_input": _resolve_target_port(template, source_node_id),
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
    status: TemplateStatus = "ready"
    data_modalities: list[DataModality] = Field(default_factory=lambda: ["spectra"])
    template_data: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WorkflowTemplateListResponse(BaseModel):
    """Schema for list of workflow templates."""

    templates: list[WorkflowTemplateOut] = Field(..., description="Available templates")
    total: int = Field(..., description="Total number of templates")


class DataBindingSpec(BaseModel):
    """Template data binding supplied at instantiation time."""

    source: Literal["experiment"] = "experiment"
    experiment_id: int = Field(..., description="Experiment supplying the data")
    stage: str = Field("raw", description="Experiment stage to load from")
    file_id: int | None = Field(None, description="Specific file within the experiment")
    target_binding: "DataBindingSpec | None" = Field(
        None,
        description="Optional separate target binding to inject via data.attach_target",
    )
    target_type: TargetType | None = Field(None, description="Override target type for separate target attachment")


DataBindingSpec.model_rebuild()


class ExampleBindingSpec(BaseModel):
    """Selected bundled example dataset for a source node."""

    source: ExampleSource = Field(..., description="Reference dataset source")
    dataset_name: str = Field(..., min_length=1, description="Dataset name from the source catalog")


class InstantiateTemplateRequest(BaseModel):
    """Schema for instantiating a template into a workflow."""

    workflow_name: str = Field(..., description="Name for the new workflow")
    workflow_description: str | None = Field(None, description="Optional description for the new workflow")
    project_id: int | None = Field(None, description="Optional project to link the instantiated workflow to")
    launch_mode: LaunchMode = Field(
        "user", description="Instantiate against bundled example data or explicit user data"
    )
    data_bindings: dict[str, DataBindingSpec] = Field(
        default_factory=dict,
        description="Bindings keyed by source node_id or template data-role name",
    )
    example_bindings: dict[str, ExampleBindingSpec] = Field(
        default_factory=dict,
        description="Optional example dataset selections keyed by source node_id",
    )


@router.get("", response_model=WorkflowTemplateListResponse)
async def list_templates(
    category: str | None = Query(None, description="Filter by category"),
    include_wip: bool = Query(False, description="Include work-in-progress templates"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> WorkflowTemplateListResponse:
    """List active workflow templates, defaulting to production-ready entries only."""
    from spectra_sherpa.app.core.config import app_config

    is_demo = app_config.site_profile == "demo"

    query = select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True))

    # Demo mode: restrict to curated featured templates only
    if is_demo:
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        featured_slugs = get_demo_policy().featured_templates
        if featured_slugs:
            query = query.where(WorkflowTemplate.slug.in_(featured_slugs))

    if category:
        query = query.where(WorkflowTemplate.category == category)

    result = await session.execute(query.order_by(WorkflowTemplate.category, WorkflowTemplate.name))
    templates = list(result.scalars().all())

    # Never show WIP templates in demo mode
    if not include_wip or is_demo:
        templates = [template for template in templates if _template_status(template) == "ready"]

    total = len(templates)
    templates = templates[offset : offset + limit]

    return WorkflowTemplateListResponse(
        templates=[_template_to_out(template) for template in templates],
        total=total,
    )


@router.get("/categories", response_model=list[str])
async def list_template_categories(
    include_wip: bool = Query(False, description="Include categories that only contain work-in-progress templates"),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Get template categories from the active template set."""
    from spectra_sherpa.app.core.config import app_config

    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.category)
    )
    templates = list(result.scalars().all())
    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        featured_slugs = set(get_demo_policy().featured_templates)
        if featured_slugs:
            templates = [template for template in templates if template.slug in featured_slugs]
    if not include_wip:
        templates = [template for template in templates if _template_status(template) == "ready"]

    categories = sorted({template.category for template in templates})
    return categories


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

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    return _template_to_out(template)


def _compute_dataset_matches(
    data_roles: dict[str, dict],
    catalog: list[dict[str, Any]],
    certified_datasets: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """For each data role, return reference datasets sorted by match score.

    When *certified_datasets* is provided and non-empty, the catalog is
    pre-filtered to only those (source, name) pairs so the wizard dropdown
    is restricted to end-to-end tested combinations.
    """
    if certified_datasets:
        certified_set = {(c["source"], c["name"]) for c in certified_datasets}
        catalog = [ds for ds in catalog if (ds["source"], ds["name"]) in certified_set]

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
            score = 1 if (accepted_roles or certified_datasets) else 0
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
                scored.append({**ds, "match_score": score})

        scored.sort(key=lambda x: -x["match_score"])
        matches[role_key] = scored

    return matches


def _build_flat_catalog() -> list[dict[str, Any]]:
    """Build a flat list of all reference datasets from all sources."""
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
    from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG
    from spectra_sherpa.app.lib.scp_catalog import build_scp_catalog
    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG
    from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

    flat: list[dict[str, Any]] = []

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
                "has_embedded_target": True,
                "target_type": v.get("target_type") or "continuous",
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
                "task_type": v.get("task_type"),
            }
        )

    for entry in build_scp_catalog():
        flat.append(
            {
                "name": entry["name"],
                "source": "spectrochempy",
                "label": entry["label"],
                "technique": entry["technique"],
                "data_role": "X_spectra",
                "data_modality": "spectra",
                "description": entry["description"],
                "has_embedded_target": False,
                "target_type": None,
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
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

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

    if payload.project_id is not None:
        await require_project(payload.project_id, user_id, session)

    template_query = (
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id).where(WorkflowTemplate.is_active.is_(True))
    )
    template_result = await session.execute(template_query)
    template = template_result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if _template_status(template) != "ready":
        raise HTTPException(status_code=400, detail="Template is still marked work in progress")

    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    data_roles = template_data.get("data_roles", {}) if isinstance(template_data.get("data_roles", {}), dict) else {}
    unknown_types = [
        node["node_type"] for node in template_data.get("nodes", []) if node["node_type"] not in node_registry
    ]
    if unknown_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Template '{template.name}' contains unknown node type(s): "
                f"{', '.join(sorted(set(unknown_types)))}. The template may need updating."
            ),
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
            and role.get("node_binding")
        )
    }

    created_example_experiment_ids: list[int] = []
    committed = False
    try:
        bindings_to_apply: dict[str, DataBindingSpec]
        if payload.launch_mode == "example":
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

        applied_bindings: dict[str, tuple[int, int | None, str]] = {}
        injected_targets: set[str] = set()

        for binding_key, binding_spec in bindings_to_apply.items():
            normalized_binding = await _validate_binding(session, user_id, binding_spec)
            node_id = _resolve_binding_node_id(template, binding_key)
            node = nodes_by_id.get(node_id)
            if node is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template '{template.name}' has no source node '{node_id}'",
                )
            if node.get("node_type") not in {"data.source", "data.my_dataset"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"Binding '{binding_key}' targets node '{node_id}', which is not a data source node",
                )

            binding_identity = _binding_identity(normalized_binding)
            existing_identity = applied_bindings.get(node_id)
            if existing_identity is not None and existing_identity != binding_identity:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Conflicting bindings supplied for source node '{node_id}'. "
                        "Embedded template roles bound to the same source must use the same experiment file."
                    ),
                )
            applied_bindings[node_id] = binding_identity

            try:
                _apply_binding_to_template_source(node, normalized_binding)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            if normalized_binding.target_binding is not None:
                if node_id in injected_targets:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Multiple target bindings supplied for source node '{node_id}'",
                    )
                edges_data = _inject_target_binding(
                    template, node, normalized_binding, nodes_data, nodes_by_id, edges_data
                )
                injected_targets.add(node_id)

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

        # Propagate is_time_series from template data_roles to the bound data node.
        for role in data_roles.values():
            if isinstance(role, dict) and role.get("is_time_series"):
                bound_node_id = str(role.get("node_binding", ""))
                if bound_node_id in nodes_by_id:
                    nodes_by_id[bound_node_id].setdefault("parameters", {})["is_time_series"] = True

        workflow = Workflow(
            user_id=user_id,
            project_id=payload.project_id,
            name=payload.workflow_name,
            description=payload.workflow_description or f"Created from template: {template.name}",
            status="draft",
            canvas_state=template_data.get("canvas_state", {}),
        )
        session.add(workflow)
        await session.flush()

        workflow_nodes: list[WorkflowNode] = []
        for node_data in nodes_data:
            node = WorkflowNode(
                workflow_id=workflow.id,
                node_id=node_data["node_id"],
                node_type=node_data["node_type"],
                label=node_data.get("label"),
                parameters=node_data.get("parameters", {}),
                position_x=node_data.get("position_x"),
                position_y=node_data.get("position_y"),
            )
            workflow_nodes.append(node)
            session.add(node)

        for edge_data in edges_data:
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=edge_data["from_node_id"],
                to_node_id=edge_data["to_node_id"],
                from_output=edge_data.get("from_output", "default"),
                to_input=edge_data.get("to_input", "default"),
            )
            session.add(edge)

        await sync_workflow_data_sources(workflow, session, workflow_nodes)
        await ensure_sheet_advisor_channel(workflow, session, color=workflow.tab_color)
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
