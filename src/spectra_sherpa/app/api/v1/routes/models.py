"""
Model artifact API endpoints — list, inspect, select, and soft-delete.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    demo_guard,
    enforce_demo_execution_quota,
    get_current_user,
    get_session,
    require_project,
)
from spectra_sherpa.app.contracts.demo_capabilities import MODEL_MANAGE, MODEL_USE
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access, scientific_project_ids
from spectra_sherpa.app.models.application_release import ApplicationRelease
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.core.target_authority import TargetAuthority

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models")


# ── Schemas ──────────────────────────────────────────────────────────


class ModelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_uid: str
    name: str
    display_name: str | None = None
    model_type: str
    n_features: int
    n_components: int | None = None
    project_id: int | None = None
    workflow_id: int | None = None
    workflow_version_id: int | None = None
    source_run_id: int | None = None
    training_dataset_id: int | None = None
    node_id: str | None = None
    integrity_hash: str | None = None
    artifact_origin: str | None = None
    canonical_lineage_digest: str | None = None
    validation_evidence_digest: str | None = None
    is_active: bool = True
    is_deploy_ready: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    # Decoded training metrics (cv_accuracy, r2, rmse, f1_macro, etc.) so list
    # views can render a headline metric without a per-row inspect call.
    metrics: dict[str, Any] | None = None


class ModelDetail(ModelSummary):
    description: str | None = None
    classes: list[str] | None = None
    # Current fitted artifacts retain either a structured axis projection or
    # the exact ordered axis values.  PCA deliberately stores the latter; the
    # detail endpoint must not reinterpret that valid list as a dictionary.
    feature_axis: dict[str, Any] | list[Any] | None = None
    preprocessing_summary: str | None = None
    training_data_hash: str | None = None
    training_scientific_digest: str | None = None


class ModelInspection(BaseModel):
    metrics_presentation: dict[str, Any] = Field(default_factory=dict)
    artifact_uid: str
    model_type: str
    arrays: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Array name → {shape, dtype, mean, std, min, max}",
    )
    manifest: dict[str, Any] = Field(default_factory=dict)


class ModelSelectItem(BaseModel):
    artifact_uid: str
    name: str
    display_name: str | None = None
    model_type: str
    n_features: int
    n_components: int | None = None


class MyDatasetModelApplyRef(BaseModel):
    experiment_id: int = Field(..., description="My Dataset / Experiment id to apply the model to")
    file_id: int | None = Field(None, description="Optional single file id within the dataset")
    stage: Literal["raw", "preprocessed", "synthetic"] = Field(
        "raw", description="Dataset stage to load: raw, preprocessed, or synthetic"
    )
    asset_id: str | None = Field(None, min_length=1, max_length=255, description="Exact asset in every source")


class ModelCompareRequest(BaseModel):
    artifact_uids: list[str] = Field(..., min_length=2, max_length=8)
    dataset: MyDatasetModelApplyRef
    scope: str = Field("all", pattern="^(all|train|test)$")


TagValue = Annotated[str, Field(min_length=1, max_length=64)]


class ModelUpdateRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    tags: Annotated[list[TagValue], Field(max_length=24)] | None = None
    is_deploy_ready: bool | None = None


class ModelCompareResponse(BaseModel):
    scope: str
    dataset: dict[str, Any]
    models: list[dict[str, Any]]
    pairwise: list[dict[str, Any]] = Field(default_factory=list)


class SavedModelQualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_view_id: int = Field(gt=0)
    policy: dict[str, Any]
    context: dict[str, Any]
    independence_evidence: dict[str, Any] | None = None


class SavedModelQualificationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_digest: str = Field(pattern="^[a-f0-9]{64}$")
    accepted_context_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    decision: Literal["accepted_under_declared_policy", "rejected", "pending"]
    reason: str = Field(min_length=1, max_length=4000)


async def _qualification_model(
    session: AsyncSession, user: User, artifact_uid: str, operation: Literal["read", "write", "execute"]
) -> ModelArtifact:
    model = await session.scalar(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.is_active.is_(True),
            or_(ModelArtifact.user_id == user.id, uses_managed_project_access()),
        )
    )
    if model is None or model.project_id is None:
        raise HTTPException(404, "Saved model is unavailable")
    await require_scientific_access(session, user.id, model.project_id, operation, resource_owner_id=model.user_id)
    return model


async def _qualification_view(session: AsyncSession, user: User, model: ModelArtifact, view_id: int):
    from spectra_sherpa.app.models.dataset_view import DatasetView
    from spectra_sherpa.app.services.dataset_views import materialize_selection_receipt, receipt_sha256
    from spectra_sherpa.app.services.model_application import load_project_dataset

    view = await session.scalar(
        select(DatasetView).where(
            DatasetView.id == view_id,
            DatasetView.project_id == model.project_id,
            DatasetView.deleted_at.is_(None),
        )
    )
    if view is None:
        raise HTTPException(404, "Named validation dataset view is unavailable")
    await require_scientific_access(session, user.id, view.project_id, "read")
    try:
        receipt = view.selection
        if receipt_sha256(receipt) != view.selection_sha256:
            raise ValueError("named validation view receipt changed")
        loaded = await load_project_dataset(
            session,
            user_id=user.id,
            experiment_id=view.experiment_id,
            stage=receipt["stage"],
            file_ids=receipt["selected_file_ids"],
            asset_id=receipt["asset_id"],
        )
        if loaded.project_id != view.project_id:
            raise ValueError("validation dataset is outside the model project")
        loaded = materialize_selection_receipt(loaded, receipt)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Named validation view no longer matches its exact source and cohort") from exc
    return view, loaded


class CanonicalFullRefitImportRequest(BaseModel):
    project_id: int = Field(..., ge=1)
    canonical_workflow_id: int = Field(..., ge=1)
    training_experiment_id: int = Field(..., ge=1)
    asset_id: str = Field(..., min_length=1, max_length=255)
    graph: dict[str, Any]
    validation_execution: dict[str, Any]
    original_capability_metadata: dict[str, Any]
    custody_id: str = Field(..., min_length=1, max_length=128, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    target_attachment_node_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    target_authority: TargetAuthority
    group_column: str = Field(..., min_length=1, max_length=255)
    feature_mask: list[StrictBool] = Field(..., min_length=1, max_length=100_000)
    selection_report: dict[str, Any]
    display_name: str | None = Field(None, min_length=1, max_length=255)


class CanonicalFullRefitImportResponse(BaseModel):
    model: ModelDetail
    receipt: dict[str, Any]


# ── Helpers ──────────────────────────────────────────────────────────


def _decode_metrics(metrics_json: str | None) -> dict[str, Any] | None:
    if not metrics_json:
        return None
    try:
        decoded = json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return None
    from spectra_sherpa.app.services.regression_metric_presentation import regression_metric_presentation

    return regression_metric_presentation(decoded) if isinstance(decoded, dict) else None


def _model_to_summary(m: ModelArtifact) -> ModelSummary:
    return ModelSummary(
        artifact_uid=m.artifact_uid,
        name=m.name,
        display_name=m.display_name or m.name,
        model_type=m.model_type,
        n_features=m.n_features,
        n_components=m.n_components,
        project_id=m.project_id,
        workflow_id=m.workflow_id,
        workflow_version_id=m.workflow_version_id,
        source_run_id=m.source_run_id,
        training_dataset_id=m.training_dataset_id,
        node_id=m.node_id,
        integrity_hash=m.integrity_hash,
        artifact_origin=m.artifact_origin,
        canonical_lineage_digest=m.canonical_lineage_digest,
        validation_evidence_digest=m.validation_evidence_digest,
        is_active=m.is_active,
        is_deploy_ready=m.is_deploy_ready,
        tags=list(m.tags or []),
        created_at=m.created_at,
        updated_at=m.updated_at,
        metrics=_decode_metrics(m.metrics_json),
    )


def _model_to_detail(m: ModelArtifact) -> ModelDetail:
    classes = None
    if m.classes_json:
        try:
            classes = json.loads(m.classes_json)
        except (json.JSONDecodeError, TypeError):
            pass

    feature_axis = None
    if m.feature_axis_json:
        try:
            feature_axis = json.loads(m.feature_axis_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return ModelDetail(
        artifact_uid=m.artifact_uid,
        name=m.name,
        display_name=m.display_name or m.name,
        model_type=m.model_type,
        n_features=m.n_features,
        n_components=m.n_components,
        project_id=m.project_id,
        workflow_id=m.workflow_id,
        workflow_version_id=m.workflow_version_id,
        source_run_id=m.source_run_id,
        training_dataset_id=m.training_dataset_id,
        node_id=m.node_id,
        integrity_hash=m.integrity_hash,
        artifact_origin=m.artifact_origin,
        canonical_lineage_digest=m.canonical_lineage_digest,
        validation_evidence_digest=m.validation_evidence_digest,
        is_active=m.is_active,
        is_deploy_ready=m.is_deploy_ready,
        tags=list(m.tags or []),
        created_at=m.created_at,
        updated_at=m.updated_at,
        description=m.description,
        classes=classes,
        feature_axis=feature_axis,
        metrics=_decode_metrics(m.metrics_json),
        preprocessing_summary=m.preprocessing_summary,
        training_data_hash=m.training_data_hash,
        training_scientific_digest=m.training_scientific_digest,
    )


def _verify_canonical_detail_storage(model: ModelArtifact) -> None:
    """Re-admit canonical bytes and cross-bind the owner-scoped DB projection."""

    from spectra_sherpa.app.services.model_store import (
        ModelArtifactIntegrityError,
        verify_model_artifact_storage_record,
    )

    try:
        verify_model_artifact_storage_record(model)
    except (FileNotFoundError, RuntimeError, ModelArtifactIntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Model artifact storage is unavailable or invalid") from exc


async def _require_models(
    artifact_uids: list[str],
    user_id: int,
    session: AsyncSession,
) -> list[ModelArtifact]:
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid.in_(artifact_uids),
            or_(ModelArtifact.user_id == user_id, uses_managed_project_access()),
            ModelArtifact.is_active == True,  # noqa: E712
        )
    )
    models = list(result.scalars().all())
    by_uid = {model.artifact_uid: model for model in models}
    found = set(by_uid)
    missing = [uid for uid in artifact_uids if uid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"Model artifact not found: {missing[0]}")
    ordered = [by_uid[uid] for uid in artifact_uids]
    for model in ordered:
        await require_scientific_access(session, user_id, model.project_id, "read", resource_owner_id=model.user_id)
        _verify_canonical_detail_storage(model)
    return ordered


def _require_dataset_model_project_match(
    models: list[ModelArtifact],
    dataset: Any,
) -> None:
    dataset_project_id = dataset.project_id
    for model in models:
        if model.project_id != dataset_project_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Model artifact and My Dataset must belong to the same project "
                    f"(model_project_id={model.project_id}, dataset_project_id={dataset_project_id})"
                ),
            )


def _dataset_payload(dataset: Any) -> dict[str, Any]:
    payload = {
        "experiment_id": dataset.experiment_id,
        "name": dataset.experiment_name,
        "project_id": dataset.project_id,
        "file_ids": dataset.file_ids,
        "stage": dataset.stage,
        "asset_id": dataset.asset_id,
        "source_manifest_sha256": dataset.source_manifest_sha256,
    }
    if hasattr(dataset, "scientific_collection_sha256"):
        payload["collection_definition_sha256"] = dataset.collection_definition_sha256
        payload["scientific_collection_sha256"] = dataset.scientific_collection_sha256
    return payload


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("", response_model=list[ModelSummary])
async def list_models(
    model_type: str | None = Query(None, description="Filter by model type (pca, pls, plsda, etc.)"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    workflow_id: int | None = Query(None, description="Filter by workflow ID"),
    q: str | None = Query(None, min_length=1, max_length=128, description="Search name, display name, type, or tags"),
    deploy_ready: bool | None = Query(None, description="Filter by human deploy-ready flag"),
    include_inactive: bool = Query(False, description="Include soft-deleted models"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ModelSummary]:
    """List model artifacts (filter by model_type, project_id, workflow_id)."""
    query = select(ModelArtifact).where(or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()))
    admitted_projects = await scientific_project_ids(session, current_user.id)
    if admitted_projects is not None:
        query = query.where(ModelArtifact.project_id.in_(admitted_projects))
    if project_id is not None:
        await require_scientific_access(session, current_user.id, project_id, "read")

    if not include_inactive:
        query = query.where(ModelArtifact.is_active == True)  # noqa: E712

    if model_type:
        query = query.where(ModelArtifact.model_type == model_type)
    if project_id is not None:
        query = query.where(ModelArtifact.project_id == project_id)
    if workflow_id is not None:
        query = query.where(ModelArtifact.workflow_id == workflow_id)
    if deploy_ready is not None:
        query = query.where(ModelArtifact.is_deploy_ready == deploy_ready)
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                ModelArtifact.artifact_uid.ilike(needle),
                ModelArtifact.name.ilike(needle),
                ModelArtifact.display_name.ilike(needle),
                ModelArtifact.model_type.ilike(needle),
                ModelArtifact.node_id.ilike(needle),
                cast(ModelArtifact.tags, String).ilike(needle),
            )
        )

    query = query.order_by(ModelArtifact.created_at.desc(), ModelArtifact.id.desc()).limit(limit).offset(offset)
    result = await session.execute(query)

    return [_model_to_summary(m) for m in result.scalars().all()]


@router.get("/project-overview")
async def project_model_overview(
    project_id: int = Query(..., ge=1),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Compare ordinary saved models using verified artifact and run receipts.

    A model without exact evidence remains a row, but it cannot acquire a
    fabricated metric, validation cohort, or qualification status.
    """

    from asyncio import to_thread

    from spectra_sherpa.app.models.dataset_view import DatasetView
    from spectra_sherpa.app.models.project_choice_event import ProjectChoiceEvent
    from spectra_sherpa.app.models.saved_model_qualification import SavedModelQualificationRecord
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion
    from spectra_sherpa.app.schemas.run_evidence import RunEvidence
    from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record
    from spectra_sherpa.app.services.run_output_retention import read_output
    from spectra_sherpa.app.services.saved_model_overview import (
        heldout_evaluator_nodes,
        model_component_count,
        project_model_row,
        verified_heldout_classification,
        verified_run_definition,
    )
    from spectra_sherpa.app.services.saved_model_qualification import qualification_status

    await require_scientific_access(session, current_user.id, project_id, "read")
    models = (
        await session.scalars(
            select(ModelArtifact)
            .where(
                ModelArtifact.project_id == project_id,
                ModelArtifact.is_active.is_(True),
                or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
            )
            .order_by(ModelArtifact.created_at.desc(), ModelArtifact.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    run_ids = [model.source_run_id for model in models if model.source_run_id is not None]
    runs = (
        {
            run.id: run
            for run in (
                await session.scalars(
                    select(ExecutionRun).where(
                        ExecutionRun.id.in_(run_ids),
                        ExecutionRun.project_id == project_id,
                    )
                )
            ).all()
        }
        if run_ids
        else {}
    )
    version_ids = {run.workflow_version_id for run in runs.values() if run.workflow_version_id is not None}
    versions = (
        {
            version.id: version
            for version in (
                await session.scalars(select(WorkflowVersion).where(WorkflowVersion.id.in_(version_ids)))
            ).all()
        }
        if version_ids
        else {}
    )
    artifact_uids = [model.artifact_uid for model in models]
    qualification_records: dict[str, list[Any]] = {uid: [] for uid in artifact_uids}
    if artifact_uids:
        retained = (
            await session.scalars(
                select(SavedModelQualificationRecord).where(
                    SavedModelQualificationRecord.project_id == project_id,
                    SavedModelQualificationRecord.artifact_uid.in_(artifact_uids),
                    SavedModelQualificationRecord.user_id == current_user.id,
                )
            )
        ).all()
        for record in retained:
            qualification_records[record.artifact_uid].append(record)
    view_ids = {record.validation_view_id for records in qualification_records.values() for record in records}
    views = (
        {
            view.id: view
            for view in (
                await session.scalars(
                    select(DatasetView).where(DatasetView.id.in_(view_ids), DatasetView.project_id == project_id)
                )
            ).all()
        }
        if view_ids
        else {}
    )
    selected_choice = await session.scalar(
        select(ProjectChoiceEvent)
        .where(
            ProjectChoiceEvent.project_id == project_id,
            ProjectChoiceEvent.user_id == current_user.id,
            ProjectChoiceEvent.kind == "dataset",
        )
        .order_by(ProjectChoiceEvent.id.desc())
        .limit(1)
    )
    rows: list[dict[str, Any]] = []
    verified_view_sources: dict[int, Any | None] = {}
    for model in models:
        try:
            await to_thread(verify_model_artifact_storage_record, model)
            manifest, arrays = await to_thread(get_model_store().load, model.artifact_uid, verify=True)
            if manifest.get("integrity_hash") != model.integrity_hash:
                raise ValueError("saved model integrity differs from its database record")
            if (
                manifest.get("artifact_uid") != model.artifact_uid
                or manifest.get("node_id") != model.node_id
                or manifest.get("model_type") != model.model_type
                or (
                    model_component_count(model, manifest) is None
                    if model.model_type == "plsda"
                    else manifest.get("n_components") != model.n_components
                )
            ):
                raise ValueError("saved model producer identity differs from its database record")
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
            logger.warning("Saved model %s cannot enter project overview: %s", model.artifact_uid, exc)
            rows.append(
                {
                    "artifact_uid": model.artifact_uid,
                    "name": model.display_name or model.name,
                    "model_type": model.model_type,
                    "unavailable_reason": "Saved model artifact could not be verified.",
                    "comparison_key": None,
                }
            )
            continue
        run = runs.get(model.source_run_id)
        curve: dict[str, Any] | None = None
        heldout: dict[str, Any] | None = None
        exclusions: dict[str, Any] | None = None
        bound_run = (
            run is not None
            and run.user_id == model.user_id
            and run.workflow_id == model.workflow_id
            and model.artifact_uid in (run.produced_artifact_uids or [])
        )
        if bound_run:
            try:
                evidence = RunEvidence.model_validate(run.evidence_completeness)
                item = evidence.outputs.get(model.node_id or "", {}).get("component_curve")
                if (
                    item is not None
                    and item.state == "exact"
                    and item.storage == "file"
                    and item.byte_count
                    and item.byte_count < 2_000_000
                ):
                    value = await to_thread(read_output, run.user_id, item)
                    if isinstance(value, dict):
                        curve = value
                if model.model_type in {"pca", "pls"} and model.node_id:
                    from spectra_sherpa.app.services.saved_model_diagnostics import saved_model_diagnostics

                    reviewed = await saved_model_diagnostics(run, model.node_id)
                    exclusions = reviewed.get("decision")
                if model.model_type == "plsda" and model.node_id:
                    definition_receipt = evidence.outputs.get("__workflow__", {}).get("definition")
                    definition = None
                    if definition_receipt is not None:
                        if (
                            definition_receipt.state == "exact"
                            and definition_receipt.storage == "file"
                            and definition_receipt.byte_count
                            and definition_receipt.byte_count < 2_000_000
                        ):
                            retained_definition = await to_thread(read_output, run.user_id, definition_receipt)
                            definition = verified_run_definition(retained_definition, run.integrity_hash)
                    else:
                        # Older runs may have only an immutable workflow-version snapshot.
                        version = versions.get(run.workflow_version_id)
                        if version is not None and version.workflow_id == run.workflow_id:
                            definition = version.snapshot
                    if definition is not None:
                        candidates = []
                        for node_id in heldout_evaluator_nodes(definition, model.node_id):
                            retained = evidence.outputs.get(node_id, {}).get("default")
                            if (
                                retained is None
                                or retained.state != "exact"
                                or retained.storage != "file"
                                or not retained.byte_count
                                or retained.byte_count >= 2_000_000
                            ):
                                continue
                            value = await to_thread(read_output, run.user_id, retained)
                            if verified_heldout_classification(value):
                                candidates.append(value)
                        if len(candidates) == 1:
                            heldout = candidates[0]
            except (ValueError, TypeError, KeyError, FileNotFoundError, OSError):
                # The verified artifact remains visible, but a missing run
                # receipt cannot supply a scientific comparison statistic.
                pass
        model_qualification_records = qualification_records[model.artifact_uid]
        latest_assessment = max(
            (record for record in model_qualification_records if record.kind == "assessment"),
            key=lambda record: record.id,
            default=None,
        )
        latest_view = views.get(latest_assessment.validation_view_id) if latest_assessment is not None else None
        if latest_view is not None and latest_view.id not in verified_view_sources:
            try:
                _view, loaded = await _qualification_view(session, current_user, model, latest_view.id)
                verified_view_sources[latest_view.id] = loaded.dataset
            except HTTPException:
                verified_view_sources[latest_view.id] = None
        rows.append(
            project_model_row(
                model,
                manifest,
                curve=curve,
                run_source=run.source_metadata if bound_run else None,
                exclusions=exclusions,
                qualification=qualification_status(
                    model,
                    manifest,
                    arrays,
                    model_qualification_records,
                    latest_view,
                    selected_view_digest=selected_choice.selected_digest if selected_choice is not None else None,
                    selection_present=selected_choice is not None,
                    source_verified=latest_view is not None and verified_view_sources.get(latest_view.id) is not None,
                    current_dataset=verified_view_sources.get(latest_view.id) if latest_view is not None else None,
                ),
                heldout=heldout,
            )
        )
    groups: dict[str, list[str]] = {}
    for row in rows:
        key = row.get("comparison_key")
        if isinstance(key, str):
            groups.setdefault(key, []).append(row["artifact_uid"])
    return {
        "project_id": project_id,
        "rows": rows,
        "comparable_groups": [uids for uids in groups.values() if len(uids) > 1],
        "scope": (
            "Exact saved-model and producing-run evidence. CV is development evidence; "
            "missing independent evidence is unavailable."
        ),
    }


@router.get("/select", response_model=list[ModelSelectItem])
async def select_models(
    model_type: str | None = Query(None, description="Filter by model type"),
    n_features: int | None = Query(None, description="Filter by exact feature count"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ModelSelectItem]:
    """Compact model list for dropdown selection (e.g., Load & Apply node parameter)."""
    if project_id is not None:
        await require_scientific_access(session, current_user.id, project_id, "read")

    query = select(ModelArtifact).where(
        or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
        ModelArtifact.is_active == True,  # noqa: E712
    )
    admitted_projects = await scientific_project_ids(session, current_user.id)
    if admitted_projects is not None:
        query = query.where(ModelArtifact.project_id.in_(admitted_projects))

    if model_type:
        query = query.where(ModelArtifact.model_type == model_type)
    if n_features is not None:
        query = query.where(ModelArtifact.n_features == n_features)
    if project_id is not None:
        query = query.where(ModelArtifact.project_id == project_id)

    query = query.order_by(ModelArtifact.created_at.desc())
    result = await session.execute(query)

    return [
        ModelSelectItem(
            artifact_uid=m.artifact_uid,
            name=m.display_name or m.name,
            display_name=m.display_name or m.name,
            model_type=m.model_type,
            n_features=m.n_features,
            n_components=m.n_components,
        )
        for m in result.scalars().all()
    ]


@router.post("/import-canonical-full-refit", response_model=CanonicalFullRefitImportResponse, status_code=201)
async def import_canonical_full_refit(
    payload: CanonicalFullRefitImportRequest,
    _dg: None = Depends(demo_guard(MODEL_MANAGE)),
    _upload_dg: None = Depends(demo_guard("data_upload")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CanonicalFullRefitImportResponse:
    """Install one owned canonical PLS-DA refit as a normal application artifact."""

    await require_project(payload.project_id, current_user.id, session)
    from spectra_sherpa.app.services.canonical_model_bridge import (
        CanonicalModelBridgeError,
        bridge_canonical_plsda_artifact,
        persist_canonical_plsda_bridge,
    )
    from spectra_sherpa.app.services.canonical_project_custody import (
        CanonicalProjectCustodyError,
        resolve_canonical_artifact_read_grant,
    )
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact, CanonicalFittedArtifactError

    try:
        grant = await resolve_canonical_artifact_read_grant(
            session,
            user_id=current_user.id,
            workflow_id=payload.canonical_workflow_id,
        )
        if grant.project_id != payload.project_id:
            raise CanonicalModelBridgeError("canonical artifact belongs to a different project")
        artifact = CanonicalFittedArtifact.load(grant.artifact_dir)
        if artifact.artifact_digest != grant.artifact_digest:
            raise CanonicalModelBridgeError("canonical artifact custody digest is stale")
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=payload.training_experiment_id,
            stage="raw",
            asset_id=payload.asset_id,
            strict_prepared_data=True,
        )
        if loaded.project_id != payload.project_id:
            raise CanonicalModelBridgeError("canonical training dataset belongs to a different project")
        attached = attach_target_dataset(
            loaded.dataset,
            None,
            target_type=payload.target_authority.target_type,
            node_id=payload.target_attachment_node_id,
            target_source="sample_table_column",
            target_column=payload.target_authority.column,
            group_column=payload.group_column,
            target_authority=payload.target_authority,
        )
        bridge = bridge_canonical_plsda_artifact(
            artifact,
            graph_payload=payload.graph,
            training_dataset=attached,
            experiment_id=loaded.experiment_id,
            asset_id=payload.asset_id,
            validation_execution=payload.validation_execution,
            original_capability_metadata=payload.original_capability_metadata,
            custody_id=payload.custody_id,
            feature_mask=payload.feature_mask,
            selection_report=payload.selection_report,
        )

        async def re_admit_training_dataset():
            fresh = await load_project_dataset(
                session,
                user_id=current_user.id,
                experiment_id=payload.training_experiment_id,
                stage="raw",
                asset_id=payload.asset_id,
                strict_prepared_data=True,
            )
            if fresh.project_id != payload.project_id:
                raise CanonicalModelBridgeError("canonical training dataset belongs to a different project")
            return attach_target_dataset(
                fresh.dataset,
                None,
                target_type=payload.target_authority.target_type,
                node_id=payload.target_attachment_node_id,
                target_source="sample_table_column",
                target_column=payload.target_authority.column,
                group_column=payload.group_column,
                target_authority=payload.target_authority,
            )

        row, receipt = await persist_canonical_plsda_bridge(
            session,
            user_id=current_user.id,
            project_id=payload.project_id,
            training_dataset_id=loaded.experiment_id,
            bridge=bridge,
            re_admit_training_dataset=re_admit_training_dataset,
            display_name=payload.display_name,
        )
    except CanonicalProjectCustodyError as exc:
        raise HTTPException(status_code=404, detail="Canonical artifact custody is unavailable") from exc
    except CanonicalFittedArtifactError as exc:
        raise HTTPException(status_code=422, detail="Canonical fitted artifact is invalid") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Canonical import files are unavailable") from exc
    except (TypeError, ValueError) as exc:
        if not isinstance(exc, CanonicalModelBridgeError):
            raise HTTPException(status_code=409, detail="Canonical import authority is invalid") from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CanonicalFullRefitImportResponse(model=_model_to_detail(row), receipt=receipt)


@router.post("/compare", response_model=ModelCompareResponse)
async def compare_models(
    payload: ModelCompareRequest,
    _dg: None = Depends(demo_guard(MODEL_USE)),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ModelCompareResponse:
    """Apply multiple saved model artifacts to the same My Dataset and compare outputs."""
    artifact_uids = list(dict.fromkeys(payload.artifact_uids))
    if len(artifact_uids) < 2:
        raise HTTPException(status_code=400, detail="At least two distinct model artifacts are required")
    models = await _require_models(artifact_uids, current_user.id, session)
    for model in models:
        await require_scientific_access(session, current_user.id, model.project_id, "execute")
    from spectra_sherpa.app.services.model_application import compare_models_on_dataset, load_project_dataset

    try:
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=payload.dataset.experiment_id,
            stage=payload.dataset.stage,
            file_id=payload.dataset.file_id,
            asset_id=payload.dataset.asset_id,
        )
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=loaded.project_id,
            experiment_id=loaded.experiment_id,
            stage=loaded.stage,
            file_id=payload.dataset.file_id,
            asset_id=payload.dataset.asset_id,
            loaded_dataset=loaded,
        )
        _require_dataset_model_project_match(models, loaded)
        enforce_demo_execution_quota(current_user.id)
        result = await compare_models_on_dataset(artifact_uids, loaded.dataset, scope=payload.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    models = await _require_models(artifact_uids, current_user.id, session)
    for model in models:
        await require_scientific_access(session, current_user.id, model.project_id, "execute")
    result["dataset"] = _dataset_payload(loaded)
    return ModelCompareResponse.model_validate(result)


@router.patch("/{artifact_uid}", response_model=ModelDetail)
async def update_model(
    artifact_uid: str,
    payload: ModelUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ModelDetail:
    """Update user-editable artifact metadata only; the artifact payload stays immutable."""
    from spectra_sherpa.app.api.deps import check_demo_capability

    try:
        check_demo_capability(MODEL_MANAGE)
    except HTTPException as exc:
        if exc.status_code != 403 or payload.model_fields_set != {"is_deploy_ready"}:
            raise
        from spectra_sherpa.app.contracts.prediction_access import require_private_prediction

        await require_private_prediction(session, current_user.id)
    result = await session.execute(
        select(ModelArtifact)
        .where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == current_user.id,
            ModelArtifact.is_active == True,  # noqa: E712
        )
        .with_for_update()
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    before_state = {
        "display_name": model.display_name,
        "tags": list(model.tags or []),
        "is_deploy_ready": model.is_deploy_ready,
    }
    if payload.display_name is not None:
        model.display_name = payload.display_name.strip()
    if payload.tags is not None:
        model.tags = [tag.strip() for tag in payload.tags if tag.strip()]
    if payload.is_deploy_ready is not None:
        model.is_deploy_ready = payload.is_deploy_ready

        # Keep the durable Deploy application identity in lockstep with the
        # legacy user-facing toggle.  Existing releases are revoked when the
        # toggle is cleared; a new release is created only for a fully bound
        # model so Deploy never exposes a dangling application.
        from spectra_sherpa.app.services.application_release import ensure_model_release

        if payload.is_deploy_ready:
            try:
                await ensure_model_release(session, model=model, user_id=current_user.id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            existing_release = await session.scalar(
                select(ApplicationRelease).where(ApplicationRelease.model_artifact_uid == model.artifact_uid)
            )
            if existing_release is not None:
                await ensure_model_release(session, model=model, user_id=current_user.id)

    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="model_artifact.updated",
        target_type="ModelArtifact",
        target_id=artifact_uid,
        before=before_state,
        after={
            "display_name": model.display_name,
            "tags": list(model.tags or []),
            "is_deploy_ready": model.is_deploy_ready,
        },
    )
    await session.commit()
    await session.refresh(model)
    return _model_to_detail(model)


@router.get("/{artifact_uid}/diagnostics")
async def get_saved_model_diagnostics(
    artifact_uid: str,
    project_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read the exact diagnostic receipt and decisions of a saved model's fit."""
    from spectra_sherpa.app.services.saved_model_diagnostics import saved_model_diagnostics

    await require_scientific_access(session, current_user.id, project_id, "read")
    model = await session.scalar(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.project_id == project_id,
            ModelArtifact.is_active.is_(True),
            or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
        )
    )
    if model is None:
        raise HTTPException(404, "Model not found")
    _verify_canonical_detail_storage(model)
    if model.model_type not in {"pca", "pls"} or model.source_run_id is None or not model.node_id:
        raise HTTPException(409, "This model has no retained PCA/PLS diagnostic receipt.")
    run = await session.scalar(
        select(ExecutionRun).where(
            ExecutionRun.id == model.source_run_id,
            ExecutionRun.project_id == project_id,
            ExecutionRun.user_id == model.user_id,
            ExecutionRun.workflow_id == model.workflow_id,
        )
    )
    if run is None or artifact_uid not in (run.produced_artifact_uids or []):
        raise HTTPException(409, "The model is not bound to its producing run.")
    try:
        result = await saved_model_diagnostics(run, model.node_id)
        if result["receipt"].get("model_kind") != model.model_type:
            raise ValueError("Saved diagnostics do not match the model family.")
        return result
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(409, f"Saved diagnostics unavailable: {exc}") from exc


@router.get("/{artifact_uid}/plsda-diagnostics")
async def get_saved_plsda_diagnostics(
    artifact_uid: str,
    project_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read exact classifier sample terms bound to its saved fitted state."""
    from spectra_sherpa.app.services.saved_model_diagnostics import saved_plsda_sample_diagnostics

    await require_scientific_access(session, current_user.id, project_id, "read")
    model = await session.scalar(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.project_id == project_id,
            ModelArtifact.is_active.is_(True),
            or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
        )
    )
    if model is None:
        raise HTTPException(404, "Model not found")
    _verify_canonical_detail_storage(model)
    if model.model_type != "plsda" or model.source_run_id is None or not model.node_id:
        raise HTTPException(409, "This model has no retained PLS-DA sample diagnostics.")
    run = await session.scalar(
        select(ExecutionRun).where(
            ExecutionRun.id == model.source_run_id,
            ExecutionRun.project_id == project_id,
            ExecutionRun.user_id == model.user_id,
            ExecutionRun.workflow_id == model.workflow_id,
        )
    )
    if run is None or artifact_uid not in (run.produced_artifact_uids or []):
        raise HTTPException(409, "The model is not bound to its producing run.")
    try:
        return await saved_plsda_sample_diagnostics(run, model)
    except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
        raise HTTPException(409, f"Saved PLS-DA diagnostics unavailable: {exc}") from exc


@router.post("/{artifact_uid}/qualification", status_code=201)
async def assess_saved_model_qualification(
    artifact_uid: str,
    payload: SavedModelQualificationRequest,
    _dg: None = Depends(demo_guard(MODEL_USE)),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Execute an external cohort against a pinned native saved-model snapshot."""
    from spectra_sherpa.app.models.saved_model_qualification import SavedModelQualificationRecord
    from spectra_sherpa.app.services.saved_model_qualification import assess_saved_model
    from spectra_sherpa.sdk.analytical_qualification import QualificationContext, QualificationPolicy
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    model = await _qualification_model(session, current_user, artifact_uid, "execute")
    view, loaded = await _qualification_view(session, current_user, model, payload.dataset_view_id)
    try:
        policy = QualificationPolicy.model_validate(payload.policy)
        context = QualificationContext.model_validate(payload.context)
        dossier, plan = await assess_saved_model(
            model,
            loaded.dataset,
            validation_experiment_id=view.experiment_id,
            validation_view_digest=view.selection_sha256,
            validation_source_manifest_digest=loaded.source_manifest_sha256,
            policy=policy,
            context=context,
            independence_evidence=payload.independence_evidence,
        )
    except (ValueError, TypeError, KeyError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(422, f"Saved-model qualification unavailable: {exc}") from exc
    existing = await session.scalar(
        select(SavedModelQualificationRecord).where(
            SavedModelQualificationRecord.user_id == current_user.id,
            SavedModelQualificationRecord.artifact_uid == artifact_uid,
            SavedModelQualificationRecord.record_digest == dossier.record_digest,
        )
    )
    if existing is None:
        session.add(
            SavedModelQualificationRecord(
                user_id=current_user.id,
                project_id=model.project_id,
                artifact_uid=artifact_uid,
                record_digest=dossier.record_digest,
                kind="assessment",
                model_integrity_hash=plan.artifact_digest,
                manifest_digest=plan.manifest_digest,
                application_plan_digest=plan.application_plan_digest,
                validation_view_id=view.id,
                validation_view_digest=view.selection_sha256,
                payload={"dossier": dossier.model_dump(mode="json"), "plan": plan.model_dump(mode="json")},
            )
        )
        await session.commit()
    return {
        "dossier": dossier.model_dump(mode="json"),
        "context_digest": _digest(context.model_dump()),
        "validation_view_id": view.id,
        "analytical_qualification": "awaiting_human_review",
        "operational_readiness_changed": False,
    }


@router.get("/{artifact_uid}/qualification")
async def saved_model_qualification_history(
    artifact_uid: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from asyncio import to_thread

    from spectra_sherpa.app.models.dataset_view import DatasetView
    from spectra_sherpa.app.models.project_choice_event import ProjectChoiceEvent
    from spectra_sherpa.app.models.saved_model_qualification import SavedModelQualificationRecord
    from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record
    from spectra_sherpa.app.services.saved_model_qualification import qualification_status
    from spectra_sherpa.sdk.analytical_qualification import QualificationDecision, QualificationDossier
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    model = await _qualification_model(session, current_user, artifact_uid, "read")
    records = (
        await session.scalars(
            select(SavedModelQualificationRecord)
            .where(
                SavedModelQualificationRecord.project_id == model.project_id,
                SavedModelQualificationRecord.artifact_uid == artifact_uid,
                SavedModelQualificationRecord.user_id == current_user.id,
            )
            .order_by(SavedModelQualificationRecord.id)
        )
    ).all()
    latest = next((record for record in reversed(records) if record.kind == "assessment"), None)
    view = await session.get(DatasetView, latest.validation_view_id) if latest is not None else None
    source_verified = False
    current_dataset = None
    if view is not None:
        try:
            _view, loaded = await _qualification_view(session, current_user, model, view.id)
            current_dataset = loaded.dataset
            source_verified = True
        except HTTPException:
            pass
    choice = await session.scalar(
        select(ProjectChoiceEvent)
        .where(
            ProjectChoiceEvent.project_id == model.project_id,
            ProjectChoiceEvent.user_id == current_user.id,
            ProjectChoiceEvent.kind == "dataset",
        )
        .order_by(ProjectChoiceEvent.id.desc())
        .limit(1)
    )
    try:
        await to_thread(verify_model_artifact_storage_record, model)
        manifest, arrays = await to_thread(get_model_store().load, artifact_uid, verify=True)
        status = qualification_status(
            model,
            manifest,
            arrays,
            records,
            view,
            selected_view_digest=choice.selected_digest if choice is not None else None,
            selection_present=choice is not None,
            source_verified=source_verified,
            current_dataset=current_dataset,
        )
    except (ValueError, KeyError, TypeError, RuntimeError, FileNotFoundError, OSError):
        status = {"state": "stale", "reason": "Saved model artifact can no longer be verified."}
    history = []
    for record in records:
        evidence = (
            QualificationDossier.load(record.payload["dossier"])
            if record.kind == "assessment"
            else QualificationDecision.model_validate(record.payload["decision"])
        )
        history.append(
            {
                "kind": record.kind,
                "record_digest": record.record_digest,
                "record_digest_verified": record.record_digest
                == (evidence.record_digest if record.kind == "assessment" else evidence.decision_digest),
                "parent_digest": record.parent_digest,
                "context_digest": _digest(evidence.context.model_dump()) if record.kind == "assessment" else None,
                "validation_view_id": record.validation_view_id,
                "validation_view_digest": record.validation_view_digest,
                "payload": evidence.model_dump(mode="json"),
                "created_at": record.created_at,
            }
        )
    return {
        "artifact_uid": artifact_uid,
        "status": status,
        "records": history,
        "operational_readiness_implies_analytical_qualification": False,
    }


@router.post("/{artifact_uid}/qualification/decisions", status_code=201)
async def decide_saved_model_qualification(
    artifact_uid: str,
    payload: SavedModelQualificationDecisionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from asyncio import to_thread
    from datetime import timezone

    from spectra_sherpa.app.models.saved_model_qualification import SavedModelQualificationRecord
    from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record
    from spectra_sherpa.app.services.saved_model_qualification import verify_validation_cohort
    from spectra_sherpa.sdk.analytical_qualification import QualificationDossier, decide_qualification
    from spectra_sherpa.sdk.prediction_uncertainty import _digest
    from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan

    model = await _qualification_model(session, current_user, artifact_uid, "write")
    assessment = await session.scalar(
        select(SavedModelQualificationRecord)
        .where(
            SavedModelQualificationRecord.project_id == model.project_id,
            SavedModelQualificationRecord.artifact_uid == artifact_uid,
            SavedModelQualificationRecord.user_id == current_user.id,
            SavedModelQualificationRecord.kind == "assessment",
        )
        .order_by(SavedModelQualificationRecord.id.desc())
        .limit(1)
    )
    if assessment is None or assessment.record_digest != payload.dossier_digest:
        raise HTTPException(404, "Current saved-model assessment is unavailable")
    view, loaded = await _qualification_view(session, current_user, model, assessment.validation_view_id)
    try:
        dossier = QualificationDossier.load(assessment.payload["dossier"])
        await to_thread(verify_model_artifact_storage_record, model)
        manifest, arrays = await to_thread(get_model_store().load, artifact_uid, verify=True)
        plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
        if (
            assessment.record_digest != dossier.record_digest
            or f"validation-view-receipt-sha256:{assessment.validation_view_digest}" not in dossier.evidence_links
            or plan != SavedModelApplicationPlan.model_validate(assessment.payload["plan"])
            or assessment.model_integrity_hash != plan.artifact_digest
            or assessment.manifest_digest != plan.manifest_digest
            or assessment.application_plan_digest != plan.application_plan_digest
            or dossier.terminal_state_digest != plan.state_content_digest
            or assessment.validation_view_digest != view.selection_sha256
        ):
            raise ValueError("saved-model assessment is stale")
        dossier.assert_application(
            artifact_digest=plan.artifact_digest,
            application_plan_digest=plan.application_plan_digest,
            context=dossier.context,
        )
        verify_validation_cohort(dossier, loaded.dataset)
        if payload.decision == "accepted_under_declared_policy":
            if payload.accepted_context_digest != _digest(dossier.context.model_dump()):
                raise ValueError("explicit intended-use context acceptance is required")
            # Only this server's executed assessment endpoint writes this scoped row.
            dossier._computed_here = True
        decision = decide_qualification(
            dossier,
            decision=payload.decision,
            actor=f"user:{current_user.id}",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            reason=payload.reason,
        )
    except (ValueError, KeyError, TypeError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(409, f"Saved-model assessment no longer verifies: {exc}") from exc
    session.add(
        SavedModelQualificationRecord(
            user_id=current_user.id,
            project_id=model.project_id,
            artifact_uid=artifact_uid,
            record_digest=decision.decision_digest,
            kind="decision",
            parent_digest=dossier.record_digest,
            model_integrity_hash=plan.artifact_digest,
            manifest_digest=plan.manifest_digest,
            application_plan_digest=plan.application_plan_digest,
            validation_view_id=assessment.validation_view_id,
            validation_view_digest=assessment.validation_view_digest,
            payload={"decision": decision.model_dump(mode="json")},
        )
    )
    await session.commit()
    return {"decision": decision.model_dump(mode="json"), "operational_readiness_changed": False}


@router.get("/{artifact_uid}", response_model=ModelDetail)
async def get_model(
    artifact_uid: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ModelDetail:
    """Get model detail (manifest + DB metadata, no arrays)."""
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
            ModelArtifact.is_active.is_(True),
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    await require_scientific_access(session, current_user.id, model.project_id, "read", resource_owner_id=model.user_id)
    _verify_canonical_detail_storage(model)
    return _model_to_detail(model)


@router.get("/{artifact_uid}/inspect", response_model=ModelInspection)
async def inspect_model(
    artifact_uid: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ModelInspection:
    """Inspect model arrays: shapes, dtypes, and summary statistics."""
    import numpy as np

    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            or_(ModelArtifact.user_id == current_user.id, uses_managed_project_access()),
            ModelArtifact.is_active.is_(True),
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    await require_scientific_access(session, current_user.id, model.project_id, "read", resource_owner_id=model.user_id)

    # Load arrays from disk WITH integrity verification.
    # The model_store documents inspection as a use-the-model path that
    # must fail loud on hash mismatch rather than silently render wrong
    # stats — load() enforces verify=True by default, separate
    # load_manifest + load_arrays calls do not.
    from spectra_sherpa.app.services.model_store import (
        ModelArtifactIntegrityError,
        get_model_store,
    )

    try:
        store = get_model_store()
        manifest, arrays = store.load(artifact_uid)
    except ModelArtifactIntegrityError as e:
        # MUST come before the RuntimeError catch below: integrity error
        # inherits from RuntimeError, so a broader catch would swallow it
        # as a 404 and hide the corruption from the caller.
        raise HTTPException(
            status_code=422,
            detail=f"Model artifact is corrupt and cannot be inspected: {e}",
        ) from e
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=f"Model files not found: {e}") from e

    # Build array stats
    array_info: dict[str, dict[str, Any]] = {}
    for name, arr in arrays.items():
        info: dict[str, Any] = {
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
        }
        if np.issubdtype(arr.dtype, np.number) and arr.size > 0:
            info["mean"] = float(np.mean(arr))
            info["std"] = float(np.std(arr))
            info["min"] = float(np.min(arr))
            info["max"] = float(np.max(arr))
        array_info[name] = info

    await require_scientific_access(session, current_user.id, model.project_id, "read", resource_owner_id=model.user_id)
    from spectra_sherpa.app.services.regression_metric_presentation import regression_metric_presentation

    return ModelInspection(
        metrics_presentation=regression_metric_presentation(manifest).get("metrics", {}),
        artifact_uid=artifact_uid,
        model_type=model.model_type,
        arrays=array_info,
        # Fitted specimen labels are needed only by the server-side overlap
        # check. Keep them in the protected artifact, not routine UI inspection.
        manifest={key: value for key, value in manifest.items() if key != "training_specimen_ids"},
    )


@router.delete("/{artifact_uid}", status_code=204, response_class=Response)
async def delete_model(
    artifact_uid: str,
    purge: bool = Query(True, description="Also delete model files from disk (irreversible; default on)"),
    _dg: None = Depends(demo_guard(MODEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Soft-delete a model artifact. With purge=true, also removes files from disk."""
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == current_user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    dependent_watches = list(
        (
            await session.execute(
                select(FolderWatch.id, FolderWatch.name).where(
                    FolderWatch.user_id == current_user.id,
                    FolderWatch.artifact_uid == artifact_uid,
                )
            )
        ).all()
    )
    if dependent_watches:
        names = ", ".join(name for _watch_id, name in dependent_watches[:3])
        suffix = "" if len(dependent_watches) <= 3 else f" and {len(dependent_watches) - 3} more"
        raise HTTPException(
            status_code=409,
            detail=f"Model is used by folder watch(es): {names}{suffix}. Remove or rebind them before deletion.",
        )

    # ISO 17025 audit — emit BEFORE the commit so the audit row writes
    # in the same TX as the is_active mutation (fail-closed).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="model_artifact.deleted",
        target_type="ModelArtifact",
        target_id=artifact_uid,
        before={"is_active": True, "artifact_uid": artifact_uid, "model_type": model.model_type},
        after={"is_active": False, "purge_files": purge},
    )

    model.is_active = False
    await session.commit()

    if purge:
        try:
            from spectra_sherpa.app.services.model_store import get_model_store

            store = get_model_store()
            store.delete(artifact_uid)
            logger.info("Purged model artifact %s (DB soft-deleted + disk removed)", artifact_uid)
        except (OSError, RuntimeError) as e:
            # Previously this swallowed *every* exception
            # with a warning and still returned 204, so a caller that
            # asked for an irreversible purge was told it succeeded while
            # the files remained — and a soft-deleted row keeps a DB
            # record, so the orphan-reconcile sweep won't GC them either.
            # Surface the failure: the soft-delete is durable (and the
            # row still exists, so re-issuing delete?purge=true retries
            # the disk removal), but the response must not claim success.
            logger.error("Soft-deleted %s but on-disk purge FAILED: %s", artifact_uid, e)
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Model {artifact_uid} was soft-deleted, but removing its on-disk "
                    "artifact failed; files remain. Retry deletion with purge=true, or "
                    "let the startup reconcile sweep clean it once the row is gone."
                ),
            ) from e
    else:
        logger.info("Soft-deleted model artifact %s", artifact_uid)

    return Response(status_code=204)
