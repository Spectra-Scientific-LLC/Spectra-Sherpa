"""
Deploy API — folder watches, labels, and prediction history.

Folder watches are managed from the Deploy page (monitoring tab).
Batch prediction is initiated through the Runs API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session, require_project
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.models.application_release import ApplicationRelease
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.deploy import (
    AssessQualificationRequest,
    BatchPredictionList,
    BatchPredictionOut,
    CalibratePredictionIntervalsRequest,
    DecideQualificationRequest,
    FolderWatchCreate,
    FolderWatchOut,
    FolderWatchUpdate,
    UpdateLabelsRequest,
)
from spectra_sherpa.app.schemas.execution_runs import ExecutionRunList, ExecutionRunOut
from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding
from spectra_sherpa.app.services.instrument_qc import QCRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deploy")


async def _resolve_application_handle(
    session: AsyncSession, *, handle: str, user_id: int, workflow_id: int
) -> tuple[str | None, int | None]:
    """Resolve an opaque release handle to legacy binding columns."""
    release = await session.scalar(
        select(ApplicationRelease).where(
            ApplicationRelease.handle == handle,
            ApplicationRelease.user_id == user_id,
            ApplicationRelease.state == "released",
        )
    )
    if release is None:
        raise ValueError("The selected application is unavailable or no longer released")
    if release.workflow_id != workflow_id:
        raise ValueError("The selected application does not belong to this workflow")
    return release.model_artifact_uid, release.canonical_artifact_id


@router.get("/applications")
async def list_applications(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List released applications by their durable Deploy handle.

    The release table is the public Deploy identity.  A small backfill keeps
    older databases usable after upgrading: models that were already marked
    deploy-ready receive a release row before they are projected.
    """
    from spectra_sherpa.app.services.application_release import (
        ensure_model_release,
        release_payload,
        revoke_stale_releases,
    )

    await require_scientific_access(session, current_user.id, project_id, "read")
    release_state_changed = await revoke_stale_releases(
        session,
        user_id=current_user.id,
        project_id=project_id,
    )

    from spectra_sherpa.app.core.mode_policy import is_local

    models = list(
        (
            await session.execute(
                select(ModelArtifact).where(
                    ModelArtifact.user_id == current_user.id,
                    ModelArtifact.project_id == project_id,
                    ModelArtifact.is_active.is_(True),
                    True if is_local() else ModelArtifact.is_deploy_ready.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for model in models:
        await ensure_model_release(session, model=model, user_id=current_user.id)
    if models or release_state_changed:
        await session.commit()
    releases = list(
        (
            await session.execute(
                select(ApplicationRelease)
                .where(
                    ApplicationRelease.user_id == current_user.id,
                    ApplicationRelease.project_id == project_id,
                    ApplicationRelease.state == "released",
                )
                .order_by(ApplicationRelease.released_at.desc(), ApplicationRelease.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [release_payload(release) for release in releases]


@router.get("/applications/{handle}")
async def get_application(
    handle: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return one released application by its opaque handle."""
    from spectra_sherpa.app.services.application_release import release_payload, revoke_stale_releases

    release = await session.scalar(
        select(ApplicationRelease).where(
            ApplicationRelease.handle == handle,
            ApplicationRelease.user_id == current_user.id,
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Application not found")
    await require_scientific_access(session, current_user.id, release.project_id, "read")
    if await revoke_stale_releases(
        session,
        user_id=current_user.id,
        project_id=release.project_id,
    ):
        await session.commit()
        await session.refresh(release)
    if release.state != "released":
        raise HTTPException(status_code=410, detail="Application is no longer released")
    return release_payload(release)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@router.patch("/runs/{run_id}/labels", response_model=ExecutionRunOut)
async def update_labels(
    run_id: int,
    payload: UpdateLabelsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut:
    """Update labels on any ExecutionRun owned by the current user."""
    query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run.labels = payload.labels
    await session.commit()
    await session.refresh(run)
    return ExecutionRunOut.model_validate(run)


@router.get("/capabilities")
async def prediction_capabilities(
    session: AsyncSession = Depends(get_session), current_user: User = Depends(get_current_user)
) -> dict:
    from spectra_sherpa.app.contracts.prediction_access import private_prediction_allowed
    from spectra_sherpa.app.core.config import settings

    return {
        "privateBatchUpload": await private_prediction_allowed(session, current_user.id),
        "maxFiles": settings.prediction_upload_max_files,
        "maxRequestBytes": settings.prediction_upload_max_request_bytes,
    }


# ---------------------------------------------------------------------------
# Per-file prediction results
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/predictions", response_model=BatchPredictionList)
async def list_predictions(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictionList:
    """List per-file prediction results for an execution run."""
    # Verify run ownership
    run_query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    run_result = await session.execute(run_query)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    query = select(BatchPrediction).where(BatchPrediction.run_id == run_id).order_by(BatchPrediction.id)
    result = await session.execute(query)
    predictions = list(result.scalars().all())

    return BatchPredictionList(
        predictions=[_prediction_with_nodes(p, run) for p in predictions],
        total=len(predictions),
    )


@router.get("/runs/{run_id}/predictions/{prediction_id}", response_model=BatchPredictionOut)
async def get_prediction(
    run_id: int,
    prediction_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictionOut:
    """Get a single per-file prediction result."""
    # Verify run ownership
    run_query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    run_result = await session.execute(run_query)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    query = select(BatchPrediction).where(
        BatchPrediction.id == prediction_id,
        BatchPrediction.run_id == run_id,
    )
    result = await session.execute(query)
    prediction = result.scalar_one_or_none()
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return _prediction_with_nodes(prediction, run)


# ---------------------------------------------------------------------------
# Folder Watches
# ---------------------------------------------------------------------------


@router.post("/watches", response_model=FolderWatchOut, status_code=201)
async def create_watch(
    payload: FolderWatchCreate,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Create a new folder watch (starts disabled)."""
    from spectra_sherpa.app.services.batch_predict import validate_user_folder_path

    # Validate folder path (prevents traversal in multi-user modes)
    try:
        folder_path = await validate_user_folder_path(session, payload.folder_path, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    artifact_uid = payload.artifact_uid
    canonical_artifact_id = payload.canonical_artifact_id
    if payload.application_handle:
        try:
            artifact_uid, canonical_artifact_id = await _resolve_application_handle(
                session,
                handle=payload.application_handle,
                user_id=current_user.id,
                workflow_id=payload.workflow_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        binding = await resolve_deployment_binding(
            session,
            user_id=current_user.id,
            workflow_id=payload.workflow_id,
            artifact_uid=artifact_uid,
            canonical_artifact_id=canonical_artifact_id,
            uncertainty_record=payload.uncertainty_record,
            uncertainty_population=payload.uncertainty_population,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    watch = FolderWatch(
        user_id=current_user.id,
        workflow_id=payload.workflow_id,
        artifact_uid=artifact_uid,
        workflow_version_id=binding.workflow_version_id,
        canonical_artifact_id=binding.canonical_artifact_id,
        canonical_plan_digest=binding.canonical_plan_digest,
        uncertainty_record=payload.uncertainty_record,
        uncertainty_population=payload.uncertainty_population,
        name=payload.name,
        folder_path=str(folder_path),
        file_pattern=payload.file_pattern,
        poll_interval_sec=payload.poll_interval_sec,
        settle_time_seconds=payload.settle_time_seconds,
        asset_id=payload.asset_id,
        is_enabled=False,
        processed_files={},
    )
    session.add(watch)
    await session.commit()
    await session.refresh(watch)
    logger.info("Created folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


@router.get("/watches", response_model=list[FolderWatchOut])
async def list_watches(
    project_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FolderWatchOut]:
    """List the current user's folder watches."""
    query = select(FolderWatch).where(FolderWatch.user_id == current_user.id).order_by(FolderWatch.created_at.desc())
    if project_id is not None:
        from spectra_sherpa.app.models.workflow import Workflow

        await require_project(project_id, current_user.id, session, operation="read")
        query = query.join(Workflow, FolderWatch.workflow_id == Workflow.id).where(Workflow.project_id == project_id)
    result = await session.execute(query)
    watches = list(result.scalars().all())
    return [FolderWatchOut.model_validate(w) for w in watches]


@router.get("/watches/{watch_id}", response_model=FolderWatchOut)
async def get_watch(
    watch_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Get a single folder watch."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    return FolderWatchOut.model_validate(watch)


@router.patch("/watches/{watch_id}", response_model=FolderWatchOut)
async def update_watch(
    watch_id: int,
    payload: FolderWatchUpdate,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Update a folder watch configuration."""
    from spectra_sherpa.app.services.batch_predict import validate_user_folder_path

    watch = await _get_user_watch(session, watch_id, current_user.id)
    from spectra_sherpa.app.services.watch_dry_run import lock_unchanged_watch, mutation_snapshot

    original_watch = mutation_snapshot(watch)

    if payload.folder_path is not None:
        try:
            folder_path = await validate_user_folder_path(session, payload.folder_path, current_user.id)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    update_data = payload.model_dump(exclude_unset=True)
    application_handle = update_data.pop("application_handle", None)
    if application_handle is not None:
        try:
            handle_artifact_uid, handle_canonical_id = await _resolve_application_handle(
                session,
                handle=application_handle,
                user_id=current_user.id,
                workflow_id=watch.workflow_id,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        update_data["artifact_uid"] = handle_artifact_uid
        update_data["canonical_artifact_id"] = handle_canonical_id
    artifact_changed = any(
        key in update_data and update_data[key] != getattr(watch, key)
        for key in ("artifact_uid", "canonical_artifact_id")
    )
    uncertainty_changed = any(
        key in update_data and update_data[key] != getattr(watch, key)
        for key in ("uncertainty_record", "uncertainty_population")
    )
    if uncertainty_changed and "uncertainty_record" in update_data and "uncertainty_population" not in update_data:
        raise HTTPException(status_code=422, detail="Explicitly declare or clear the population with interval evidence")
    if artifact_changed and watch.uncertainty_record is not None and "uncertainty_record" not in update_data:
        raise HTTPException(
            status_code=422, detail="Explicitly clear or replace interval evidence when changing the model"
        )
    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local() and watch.is_enabled and (artifact_changed or uncertainty_changed):
        raise HTTPException(status_code=409, detail="Disable the watch before changing its model or interval evidence")
    if artifact_changed or uncertainty_changed or update_data.get("is_enabled") is True:
        try:
            binding = await resolve_deployment_binding(
                session,
                user_id=current_user.id,
                workflow_id=watch.workflow_id,
                artifact_uid=update_data.get("artifact_uid", watch.artifact_uid),
                expected_version_id=None if artifact_changed else watch.workflow_version_id,
                canonical_artifact_id=update_data.get("canonical_artifact_id", watch.canonical_artifact_id),
                expected_plan_digest=None if artifact_changed else watch.canonical_plan_digest,
                uncertainty_record=update_data.get("uncertainty_record", watch.uncertainty_record),
                uncertainty_population=update_data.get("uncertainty_population", watch.uncertainty_population),
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        update_data["workflow_version_id"] = binding.workflow_version_id
        update_data["canonical_plan_digest"] = binding.canonical_plan_digest
    if payload.folder_path is not None:
        update_data["folder_path"] = str(folder_path)
    source_identity_fields = {
        "folder_path",
        "file_pattern",
        "asset_id",
        "artifact_uid",
        "workflow_version_id",
        "canonical_artifact_id",
        "canonical_plan_digest",
        "uncertainty_record",
        "uncertainty_population",
    }
    source_identity_changed = any(
        key in update_data and update_data[key] != getattr(watch, key) for key in source_identity_fields
    )
    try:
        await lock_unchanged_watch(session, original_watch)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not is_local() and watch.is_enabled and update_data.get("asset_id", watch.asset_id) != watch.asset_id:
        raise HTTPException(
            status_code=409, detail="Disable the folder watch before changing its scientific asset identity."
        )
    if source_identity_changed:
        # A source edit changes the scientific meaning or admitted file set.
        # Invalidate the old lease and make the new identity immediately due.
        watch.last_poll_at = None
        watch.active_poll_token = None
        watch.active_poll_claimed_at = None
    if (
        artifact_changed
        or uncertainty_changed
        or ("asset_id" in update_data and update_data["asset_id"] != watch.asset_id)
    ):
        # Scientific asset identity changes what every source byte means.
        # Reset the durable discovery history atomically so a corrected watch
        # retries prior files instead of silently treating them as complete.
        watch.processed_files = {}
        watch.last_error = None
    if source_identity_changed:
        watch.configuration_generation += 1
    enable_transition = "is_enabled" in update_data and bool(update_data["is_enabled"]) != watch.is_enabled
    if enable_transition and bool(update_data["is_enabled"]) and watch.active_poll_token is None:
        watch.last_poll_at = None
    for key, value in update_data.items():
        setattr(watch, key, value)

    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    return FolderWatchOut.model_validate(watch)


@router.delete("/watches/{watch_id}", status_code=204, response_class=Response)
async def delete_watch(
    watch_id: int,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a folder watch."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    await session.delete(watch)
    await session.commit()
    logger.info("Deleted folder watch %d", watch_id)
    return Response(status_code=204)


@router.post("/watches/{watch_id}/enable", response_model=FolderWatchOut)
async def enable_watch(
    watch_id: int,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Enable a folder watch for polling."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    from spectra_sherpa.app.services.watch_dry_run import lock_unchanged_watch, mutation_snapshot

    original_watch = mutation_snapshot(watch)
    try:
        await resolve_deployment_binding(
            session,
            user_id=current_user.id,
            workflow_id=watch.workflow_id,
            artifact_uid=watch.artifact_uid,
            expected_version_id=watch.workflow_version_id,
            canonical_artifact_id=watch.canonical_artifact_id,
            expected_plan_digest=watch.canonical_plan_digest,
            uncertainty_record=watch.uncertainty_record,
            uncertainty_population=watch.uncertainty_population,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if watch.is_enabled:
        return FolderWatchOut.model_validate(watch)
    try:
        await lock_unchanged_watch(session, original_watch)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    watch.is_enabled = True
    if watch.active_poll_token is None:
        watch.last_poll_at = None
    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    logger.info("Enabled folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


class WatchDryRunRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)


@router.post("/watches/{watch_id}/dry-run")
async def dry_run_watch(
    watch_id: int,
    payload: WatchDryRunRequest,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.services.watch_dry_run import run_dry_run

    watch = await _get_user_watch(session, watch_id, current_user.id)
    try:
        return await run_dry_run(session, watch, payload.file_name)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/watches/{watch_id}/dry-run")
async def get_watch_dry_run(
    watch_id: int, session: AsyncSession = Depends(get_session), current_user: User = Depends(get_current_user)
):
    from spectra_sherpa.app.core.mode_policy import is_local
    from spectra_sherpa.app.services.watch_dry_run import latest_receipt

    if not is_local():
        raise HTTPException(status_code=404, detail="Not found.")
    watch = await _get_user_watch(session, watch_id, current_user.id)
    return {"receipt": await latest_receipt(session, watch)}


@router.post("/watches/{watch_id}/disable", response_model=FolderWatchOut)
async def disable_watch(
    watch_id: int,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Disable a folder watch (stops polling)."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    if not watch.is_enabled:
        return FolderWatchOut.model_validate(watch)
    watch.is_enabled = False
    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    logger.info("Disabled folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


# ---------------------------------------------------------------------------
# Deploy runs (filtered view)
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=ExecutionRunList)
async def list_deploy_runs(
    source_type: str | None = Query(None, description="Filter by source type"),
    label: str | None = Query(None, description="Filter by label"),
    project_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunList:
    """List execution runs filtered by source type and/or label."""
    query = (
        select(ExecutionRun)
        .where(ExecutionRun.user_id == current_user.id, ExecutionRun.run_kind == "batch_inference")
        .order_by(ExecutionRun.executed_at.desc())
    )

    if project_id is not None:
        await require_project(project_id, current_user.id, session, operation="read")
        query = query.where(ExecutionRun.project_id == project_id)
    if source_type:
        query = query.where(ExecutionRun.source_type == source_type)

    result = await session.execute(query)
    runs = list(result.scalars().all())

    # Filter by label in Python (portable across SQLite/PostgreSQL)
    if label:
        runs = [r for r in runs if r.labels and label in r.labels]

    return ExecutionRunList(
        runs=[ExecutionRunOut.model_validate(r) for r in runs],
        total=len(runs),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_watch(session: AsyncSession, watch_id: int, user_id: int) -> FolderWatch:
    """Load a folder watch with ownership check."""
    query = select(FolderWatch).where(
        FolderWatch.id == watch_id,
        FolderWatch.user_id == user_id,
    )
    result = await session.execute(query)
    watch = result.scalar_one_or_none()
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    return watch


def _prediction_with_nodes(prediction: BatchPrediction, run: ExecutionRun) -> BatchPredictionOut:
    result = BatchPredictionOut.model_validate(prediction)
    nodes = (run.source_metadata or {}).get("retained_file_nodes", {}).get(prediction.file_path, [])
    result.retained_node_ids = [node for node in nodes if isinstance(node, str) and node in (run.node_statuses or {})]
    return result


@router.get("/canonical-targets")
async def list_canonical_targets(
    project_id: int,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List imported campaign solutions, including explicit readiness refusals."""
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.application_release import ensure_canonical_release, revoke_stale_releases

    release_state_changed = await revoke_stale_releases(
        session,
        user_id=current_user.id,
        project_id=project_id,
    )

    records = (
        await session.execute(
            select(CanonicalProjectArtifact, Workflow.name)
            .join(Workflow, Workflow.id == CanonicalProjectArtifact.workflow_id)
            .where(
                CanonicalProjectArtifact.user_id == current_user.id,
                CanonicalProjectArtifact.project_id == project_id,
                Workflow.user_id == current_user.id,
            )
        )
    ).all()
    targets = []
    for record, name in records:
        refusal = None
        try:
            await resolve_deployment_binding(
                session,
                user_id=current_user.id,
                workflow_id=record.workflow_id,
                artifact_uid=None,
                canonical_artifact_id=record.id,
            )
        except (ValueError, PermissionError, OSError):
            logger.warning("Canonical application binding is unavailable", exc_info=True)
            refusal = "This application is unavailable or its saved model no longer matches."
        application_handle = None
        if refusal is None:
            release = await ensure_canonical_release(
                session,
                artifact=record,
                user_id=current_user.id,
                label=name,
                readiness={"ready": True, "blockers": []},
            )
            application_handle = release.handle
            release_state_changed = True
        targets.append(
            {
                "canonical_artifact_id": record.id,
                "workflow_id": record.workflow_id,
                "name": name,
                "artifact_digest": record.artifact_digest,
                "application_plan_digest": record.application_plan_digest,
                "application_handle": application_handle,
                "deploy_ready": refusal is None,
                "refusal": refusal,
            }
        )
    if release_state_changed:
        await session.commit()
    return targets


@router.post("/workflows/{workflow_id}/uncertainty/calibrate")
async def calibrate_uncertainty(
    workflow_id: int,
    payload: "CalibratePredictionIntervalsRequest",
    _dg: None = Depends(demo_guard("model_use")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return a portable sidecar; never mutate the fitted model or its package."""
    from asyncio import to_thread
    from pathlib import Path

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.services.batch_predict import load_single_file
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import _response_identity
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
    from spectra_sherpa.sdk.prediction_uncertainty import calibrate_prediction_intervals

    experiment = await session.get(Experiment, payload.experiment_id)
    if experiment is None or experiment.user_id != current_user.id:
        raise HTTPException(404, "Calibration dataset is unavailable")
    await require_scientific_access(session, current_user.id, experiment.project_id, "read")
    from spectra_sherpa.app.core.config import app_config

    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=experiment.project_id,
            experiment_id=experiment.id,
            stage=payload.stage,
            file_id=payload.file_id,
            asset_id=payload.asset_id,
        )
    try:
        binding = await resolve_deployment_binding(
            session,
            user_id=current_user.id,
            workflow_id=workflow_id,
            artifact_uid=None,
            canonical_artifact_id=payload.canonical_artifact_id,
        )
        await require_scientific_access(session, current_user.id, binding.workflow.project_id, "execute")
        runtime = build_application_execution_runtime(canonical_artifact_read_grant=binding.canonical_read_grant)
        resolved = await runtime.dataset_source_resolver.resolve_experiment_file(
            experiment_id=payload.experiment_id, file_id=payload.file_id, stage=payload.stage
        )
        dataset = await to_thread(load_single_file, Path(resolved.path), asset_id=payload.asset_id)
        if dataset.target is None:
            raise ValueError("Calibration dataset must retain its reference target values and units")
        labels = dataset.sample_axis.labels if dataset.sample_axis is not None else None
        if labels is None:
            raise ValueError("Calibration requires explicit specimen IDs in the dataset sample labels")
        targets = 1 if dataset.target.ndim == 1 else dataset.target.shape[1]
        reference = {
            "method_id": payload.reference_method_id,
            "version": payload.reference_method_version,
            "response_identity": _response_identity(dataset, targets=targets, bound_names=[], embedded=True),
            "measurement_basis": payload.measurement_basis,
            "measurements_per_label": payload.measurements_per_label,
            "precision": payload.reference_precision,
        }
        record = await calibrate_prediction_intervals(
            CanonicalApplicationPlan.from_dict(binding.canonical_application_plan),
            dataset,
            runtime=runtime,
            specimen_ids=list(labels),
            specimen_namespace=payload.specimen_namespace,
            reference_method=reference,
            alpha=payload.alpha,
            intended_population=payload.intended_population,
            declarations=payload.declarations,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "record": record.model_dump(),
        "origin": "server_executed_frozen_pipeline",
        "qualification": "Laboratory independence and exchangeability are declared, not established by this receipt",
    }


async def _qualification_workflow(session: AsyncSession, user_id: int, workflow_id: int, action: str):
    from spectra_sherpa.app.models.workflow import Workflow

    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.user_id != user_id:
        raise HTTPException(404, "Workflow is unavailable")
    await require_scientific_access(session, user_id, workflow.project_id, action)
    return workflow


@router.get("/projects/{project_id}/qualification-applications")
async def qualification_applications(
    project_id: int, session: AsyncSession = Depends(get_session), current_user: User = Depends(get_current_user)
) -> list[dict]:
    """Read-only qualification candidates, independent of folder-watch entitlement.

    Listing does not release an application or assert suitability; assessment
    and acceptance revalidate the exact bound application separately.
    """
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = await session.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
        raise HTTPException(404, "Project is unavailable")
    await require_scientific_access(session, current_user.id, project_id, "read")
    rows = (
        await session.execute(
            select(CanonicalProjectArtifact, Workflow.name)
            .join(Workflow, Workflow.id == CanonicalProjectArtifact.workflow_id)
            .where(
                CanonicalProjectArtifact.project_id == project_id,
                CanonicalProjectArtifact.user_id == current_user.id,
                Workflow.user_id == current_user.id,
            )
            .order_by(CanonicalProjectArtifact.id)
        )
    ).all()
    return [
        {
            "canonical_artifact_id": record.id,
            "workflow_id": record.workflow_id,
            "name": name,
            "artifact_digest": record.artifact_digest,
        }
        for record, name in rows
    ]


@router.post("/workflows/{workflow_id}/qualification", status_code=201)
async def assess_qualification(
    workflow_id: int,
    payload: AssessQualificationRequest,
    _dg: None = Depends(demo_guard("model_use")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    from asyncio import to_thread
    from pathlib import Path

    from spectra_sherpa.app.core.config import app_config
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.services.batch_predict import load_single_file
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.sdk.analytical_qualification import (
        QualificationContext,
        QualificationPolicy,
        qualify_application,
    )
    from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    await _qualification_workflow(session, current_user.id, workflow_id, "execute")
    experiment = await session.get(Experiment, payload.experiment_id)
    if experiment is None or experiment.user_id != current_user.id:
        raise HTTPException(404, "Qualification dataset is unavailable")
    await require_scientific_access(session, current_user.id, experiment.project_id, "read")
    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=experiment.project_id,
            experiment_id=experiment.id,
            stage=payload.stage,
            file_id=payload.file_id,
            asset_id=payload.asset_id,
        )
    try:
        policy = QualificationPolicy.model_validate(payload.policy)
        context = QualificationContext.model_validate(payload.context)
        binding = await resolve_deployment_binding(
            session,
            user_id=current_user.id,
            workflow_id=workflow_id,
            artifact_uid=None,
            canonical_artifact_id=payload.canonical_artifact_id,
        )
        runtime = build_application_execution_runtime(canonical_artifact_read_grant=binding.canonical_read_grant)
        resolved = await runtime.dataset_source_resolver.resolve_experiment_file(
            experiment_id=experiment.id, file_id=payload.file_id, stage=payload.stage
        )
        dataset = await to_thread(load_single_file, Path(resolved.path), asset_id=payload.asset_id)
        labels = dataset.sample_axis.labels if dataset.sample_axis is not None else None
        if labels is None:
            raise ValueError("qualification requires explicit specimen IDs in sample labels")
        record = await qualify_application(
            CanonicalApplicationPlan.from_dict(binding.canonical_application_plan),
            dataset,
            runtime=runtime,
            policy=policy,
            context=context,
            specimen_ids=list(labels),
            allow_missing_reference_exclusion=payload.allow_missing_reference_exclusion,
            uncertainty_record=payload.uncertainty_record,
            independence_evidence=payload.independence_evidence,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = await session.scalar(
        select(AnalyticalQualificationRecord).where(
            AnalyticalQualificationRecord.user_id == current_user.id,
            AnalyticalQualificationRecord.record_digest == record.record_digest,
            AnalyticalQualificationRecord.workflow_id == workflow_id,
        )
    )
    if existing is None:
        session.add(
            AnalyticalQualificationRecord(
                user_id=current_user.id,
                workflow_id=workflow_id,
                canonical_artifact_id=payload.canonical_artifact_id,
                record_digest=record.record_digest,
                kind="assessment",
                created_at=datetime.now(timezone.utc),
                payload=record.model_dump(),
            )
        )
        await session.commit()
    return {
        "dossier": record.model_dump(),
        "context_digest": _digest(context.model_dump()),
        "analytical_qualification": "awaiting_human_review",
        "operational_readiness_changed": False,
    }


@router.get("/workflows/{workflow_id}/qualification")
async def qualification_history(
    workflow_id: int, session: AsyncSession = Depends(get_session), current_user: User = Depends(get_current_user)
) -> dict:
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.sdk.analytical_qualification import QualificationDecision, QualificationDossier
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    await _qualification_workflow(session, current_user.id, workflow_id, "read")
    rows = (
        await session.scalars(
            select(AnalyticalQualificationRecord)
            .where(
                AnalyticalQualificationRecord.user_id == current_user.id,
                AnalyticalQualificationRecord.workflow_id == workflow_id,
            )
            .order_by(AnalyticalQualificationRecord.id)
        )
    ).all()
    records = []
    for row in rows:
        validated = (
            QualificationDossier.load(row.payload)
            if row.kind == "assessment"
            else QualificationDecision.model_validate(row.payload)
        )
        records.append(
            {
                "kind": row.kind,
                "record_digest": row.record_digest,
                "parent_digest": row.parent_digest,
                "payload": validated.model_dump(),
                "context_digest": _digest(validated.context.model_dump()) if row.kind == "assessment" else None,
                "created_at": row.created_at,
            }
        )
    return {
        "records": records,
        "claim_scope": "historical declared-use evidence; confirm model and context before application",
        "operational_readiness_implies_analytical_qualification": False,
    }


@router.post("/workflows/{workflow_id}/qualification/decisions", status_code=201)
async def qualification_decision(
    workflow_id: int,
    payload: DecideQualificationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.sdk.analytical_qualification import QualificationDossier, decide_qualification
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    await _qualification_workflow(session, current_user.id, workflow_id, "write")
    row = await session.scalar(
        select(AnalyticalQualificationRecord).where(
            AnalyticalQualificationRecord.user_id == current_user.id,
            AnalyticalQualificationRecord.workflow_id == workflow_id,
            AnalyticalQualificationRecord.record_digest == payload.dossier_digest,
            AnalyticalQualificationRecord.kind == "assessment",
        )
    )
    if row is None:
        raise HTTPException(404, "Qualification dossier is unavailable")
    try:
        dossier = QualificationDossier.load(row.payload)
        # This owner-scoped append-only row is written only by the server's
        # executed assessment endpoint. There is no imported-assessment write API.
        dossier._computed_here = True
        if payload.decision == "accepted_under_declared_policy":
            if payload.accepted_context_digest != _digest(dossier.context.model_dump()):
                raise ValueError("explicit acceptance of this dossier's intended-use context is required")
            binding = await resolve_deployment_binding(
                session,
                user_id=current_user.id,
                workflow_id=workflow_id,
                artifact_uid=None,
                canonical_artifact_id=row.canonical_artifact_id,
            )
            dossier.assert_application(
                artifact_digest=binding.canonical_application_plan["artifact_digest"],
                application_plan_digest=binding.canonical_plan_digest,
                context=dossier.context,
            )
        decision = decide_qualification(
            dossier,
            decision=payload.decision,
            actor=f"user:{current_user.id}",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            reason=payload.reason,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.add(
        AnalyticalQualificationRecord(
            user_id=current_user.id,
            workflow_id=workflow_id,
            canonical_artifact_id=row.canonical_artifact_id,
            record_digest=decision.decision_digest,
            kind="decision",
            parent_digest=dossier.record_digest,
            payload=decision.model_dump(),
        )
    )
    await session.commit()
    return {
        "decision": decision.model_dump(),
        "authentication_scope": "server authenticated actor; exported identity remains an assertion",
    }


async def _qc_binding(session: AsyncSession, watch):
    return await resolve_deployment_binding(
        session,
        user_id=watch.user_id,
        workflow_id=watch.workflow_id,
        artifact_uid=watch.artifact_uid,
        expected_version_id=watch.workflow_version_id,
        canonical_artifact_id=watch.canonical_artifact_id,
        expected_plan_digest=watch.canonical_plan_digest,
    )


@router.get("/watches/{watch_id}/qc")
async def get_watch_qc(
    watch_id: int,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    from spectra_sherpa.app.services.instrument_qc import qc_events, qc_qualification_state
    from spectra_sherpa.sdk.instrument_qc import evaluate_qc

    watch = await _get_user_watch(session, watch_id, current_user.id)
    await _qualification_workflow(session, current_user.id, watch.workflow_id, "read")
    events = await qc_events(session, watch.id, current_user.id)
    error = None
    try:
        binding = await _qc_binding(session, watch)
        artifact_digest = binding.canonical_read_grant.artifact_digest if binding.canonical_read_grant else None
        plan_digest = binding.canonical_plan_digest
    except (ValueError, PermissionError, OSError):
        logger.warning("Folder watch QC application binding is unavailable", exc_info=True)
        artifact_digest = plan_digest = None
        error = "This application is unavailable or its saved model no longer matches."
    evaluated_at = datetime.now(timezone.utc).isoformat()
    snapshot = evaluate_qc(
        events,
        evaluated_at=evaluated_at,
        qualification_state=await qc_qualification_state(session, watch, events, evaluated_at),
        artifact_digest=artifact_digest,
        application_plan_digest=plan_digest,
    )
    return {
        "snapshot": snapshot,
        "events": [event.model_dump() for event in events],
        "last_event_digest": events[-1].event_digest if events else None,
        "application_refusal": error,
        "authority": "Server-owned local history; exported records are assertions on another installation",
    }


@router.post("/watches/{watch_id}/qc", status_code=201)
async def record_watch_qc(
    watch_id: int,
    payload: QCRequest,
    _dg: None = Depends(demo_guard("folder_watch")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy.exc import IntegrityError

    from spectra_sherpa.app.services.instrument_qc import append_qc_event

    watch = await _get_user_watch(session, watch_id, current_user.id)
    await _qualification_workflow(session, current_user.id, watch.workflow_id, "write")
    try:
        binding = await _qc_binding(session, watch)
        event = await append_qc_event(
            session, watch, binding, payload, recorded_at=datetime.now(timezone.utc).isoformat()
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "QC history changed or event ID already exists; refresh before appending") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"event": event.model_dump(), "action": "report_only", "watch_execution_changed": False}
