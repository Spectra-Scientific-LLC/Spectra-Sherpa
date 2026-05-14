"""
Model artifact API endpoints — list, inspect, select, and soft-delete.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models")


# ── Schemas ──────────────────────────────────────────────────────────


class ModelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_uid: str
    name: str
    model_type: str
    n_features: int
    n_components: int | None = None
    project_id: int | None = None
    workflow_id: int | None = None
    node_id: str | None = None
    integrity_hash: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class ModelDetail(ModelSummary):
    description: str | None = None
    classes: list[str] | None = None
    feature_axis: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    preprocessing_summary: str | None = None
    training_data_hash: str | None = None


class ModelInspection(BaseModel):
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
    model_type: str
    n_features: int
    n_components: int | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _model_to_summary(m: ModelArtifact) -> ModelSummary:
    return ModelSummary(
        artifact_uid=m.artifact_uid,
        name=m.name,
        model_type=m.model_type,
        n_features=m.n_features,
        n_components=m.n_components,
        project_id=m.project_id,
        workflow_id=m.workflow_id,
        node_id=m.node_id,
        integrity_hash=m.integrity_hash,
        is_active=m.is_active,
        created_at=m.created_at,
        updated_at=m.updated_at,
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

    metrics = None
    if m.metrics_json:
        try:
            metrics = json.loads(m.metrics_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return ModelDetail(
        artifact_uid=m.artifact_uid,
        name=m.name,
        model_type=m.model_type,
        n_features=m.n_features,
        n_components=m.n_components,
        project_id=m.project_id,
        workflow_id=m.workflow_id,
        node_id=m.node_id,
        integrity_hash=m.integrity_hash,
        is_active=m.is_active,
        created_at=m.created_at,
        updated_at=m.updated_at,
        description=m.description,
        classes=classes,
        feature_axis=feature_axis,
        metrics=metrics,
        preprocessing_summary=m.preprocessing_summary,
        training_data_hash=m.training_data_hash,
    )


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("", response_model=list[ModelSummary])
async def list_models(
    model_type: str | None = Query(None, description="Filter by model type (pca, pls, plsda, etc.)"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    workflow_id: int | None = Query(None, description="Filter by workflow ID"),
    include_inactive: bool = Query(False, description="Include soft-deleted models"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ModelSummary]:
    """List model artifacts (filter by model_type, project_id, workflow_id)."""
    query = select(ModelArtifact).where(ModelArtifact.user_id == current_user.id)

    if not include_inactive:
        query = query.where(ModelArtifact.is_active == True)  # noqa: E712

    if model_type:
        query = query.where(ModelArtifact.model_type == model_type)
    if project_id is not None:
        query = query.where(ModelArtifact.project_id == project_id)
    if workflow_id is not None:
        query = query.where(ModelArtifact.workflow_id == workflow_id)

    query = query.order_by(ModelArtifact.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)

    return [_model_to_summary(m) for m in result.scalars().all()]


@router.get("/select", response_model=list[ModelSelectItem])
async def select_models(
    model_type: str | None = Query(None, description="Filter by model type"),
    n_features: int | None = Query(None, description="Filter by exact feature count"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ModelSelectItem]:
    """Compact model list for dropdown selection (e.g., Load & Apply node parameter)."""
    query = select(ModelArtifact).where(
        ModelArtifact.user_id == current_user.id,
        ModelArtifact.is_active == True,  # noqa: E712
    )

    if model_type:
        query = query.where(ModelArtifact.model_type == model_type)
    if n_features is not None:
        query = query.where(ModelArtifact.n_features == n_features)

    query = query.order_by(ModelArtifact.created_at.desc())
    result = await session.execute(query)

    return [
        ModelSelectItem(
            artifact_uid=m.artifact_uid,
            name=m.name,
            model_type=m.model_type,
            n_features=m.n_features,
            n_components=m.n_components,
        )
        for m in result.scalars().all()
    ]


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
            ModelArtifact.user_id == current_user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

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
            ModelArtifact.user_id == current_user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    # Load arrays from disk
    from spectra_sherpa.app.services.model_store import get_model_store

    try:
        store = get_model_store()
        manifest = store.load_manifest(artifact_uid)
        arrays = store.load_arrays(artifact_uid)
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=f"Model files not found: {e}")

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

    return ModelInspection(
        artifact_uid=artifact_uid,
        model_type=model.model_type,
        arrays=array_info,
        manifest=manifest,
    )


@router.delete("/{artifact_uid}", status_code=204, response_class=Response)
async def delete_model(
    artifact_uid: str,
    purge: bool = Query(False, description="Also delete model files from disk (irreversible)"),
    _dg: None = Depends(demo_guard("model_delete")),
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
        except (RuntimeError, Exception) as e:
            logger.warning("Soft-deleted %s but disk purge failed: %s", artifact_uid, e)
    else:
        logger.info("Soft-deleted model artifact %s", artifact_uid)

    return Response(status_code=204)
