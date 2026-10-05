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
        manifest=manifest,
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
