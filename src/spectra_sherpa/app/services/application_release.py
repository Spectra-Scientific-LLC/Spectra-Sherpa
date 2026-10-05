"""Create and resolve the shared Deploy application-release identity."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.mode_policy import is_local
from spectra_sherpa.app.models.application_release import ApplicationRelease
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.model_artifact import ModelArtifact


def _handle() -> str:
    return f"app_{uuid4().hex}"


def _model_readiness(model: ModelArtifact) -> dict[str, object]:
    blockers: list[str] = []
    if model.model_type in {"hca", "dbscan"}:
        blockers.append("clustering artifact supports fitted-cohort replay only")
    if model.project_id is None:
        blockers.append("model has no project")
    if model.workflow_id is None or (model.workflow_version_id is None and model.source_run_id is None):
        blockers.append("model has no saved workflow version or source run")
    if not model.is_active:
        blockers.append("model artifact is inactive")
    if not is_local() and not model.is_deploy_ready:
        blockers.append("model is not marked deploy-ready")
    return {"ready": not blockers, "blockers": blockers}


async def ensure_model_release(
    session: AsyncSession,
    *,
    model: ModelArtifact,
    user_id: int,
) -> ApplicationRelease:
    """Return the stable release row for a deploy-ready model artifact."""

    existing = await session.scalar(
        select(ApplicationRelease).where(ApplicationRelease.model_artifact_uid == model.artifact_uid)
    )
    readiness = _model_readiness(model)
    if existing is not None:
        existing.state = "released" if readiness["ready"] else "revoked"
        existing.readiness = readiness
        existing.label = model.display_name or model.name
        if existing.state == "revoked" and existing.revoked_at is None:
            existing.revoked_at = datetime.now(timezone.utc)
        elif existing.state == "released":
            existing.revoked_at = None
        return existing
    if not is_local() and not model.is_deploy_ready:
        raise ValueError("model is not released")
    if model.project_id is None or model.workflow_id is None:
        raise ValueError("model is not bound to a project workflow")
    release = ApplicationRelease(
        handle=_handle(),
        user_id=user_id,
        project_id=model.project_id,
        workflow_id=model.workflow_id,
        workflow_version_id=model.workflow_version_id,
        source_run_id=model.source_run_id,
        model_artifact_uid=model.artifact_uid,
        origin="saved_run",
        state="released" if readiness["ready"] else "revoked",
        label=model.display_name or model.name,
        readiness=readiness,
        provenance={
            "artifact_uid": model.artifact_uid,
            "model_type": model.model_type,
            "training_dataset_id": model.training_dataset_id,
            "training_data_hash": model.training_data_hash,
            "validation_evidence_digest": model.validation_evidence_digest,
        },
    )
    session.add(release)
    await session.flush()
    return release


async def ensure_canonical_release(
    session: AsyncSession,
    *,
    artifact: CanonicalProjectArtifact,
    user_id: int,
    label: str,
    readiness: dict[str, object],
) -> ApplicationRelease:
    """Return the stable release row for an imported campaign application."""

    existing = await session.scalar(
        select(ApplicationRelease).where(ApplicationRelease.canonical_artifact_id == artifact.id)
    )
    ready = bool(readiness.get("ready"))
    validation_digest = (artifact.application_plan_payload or {}).get("validation_execution_digest")
    if existing is not None:
        existing.state = "released" if ready else "revoked"
        existing.readiness = readiness
        existing.provenance = {**(existing.provenance or {}), "validation_execution_digest": validation_digest}
        existing.label = label
        if ready:
            existing.revoked_at = None
        elif existing.revoked_at is None:
            existing.revoked_at = datetime.now(timezone.utc)
        return existing
    release = ApplicationRelease(
        handle=_handle(),
        user_id=user_id,
        project_id=artifact.project_id,
        workflow_id=artifact.workflow_id,
        canonical_artifact_id=artifact.id,
        origin="campaign_solution",
        state="released" if ready else "revoked",
        label=label,
        package_digest=artifact.package_sha256,
        package_schema_version="spectra-canonical-project-package/6",
        readiness=readiness,
        provenance={
            "validation_execution_digest": validation_digest,
            "artifact_digest": artifact.artifact_digest,
            "capsule_digest": artifact.capsule_digest,
            "application_plan_digest": artifact.application_plan_digest,
            "package_sha256": artifact.package_sha256,
        },
    )
    session.add(release)
    await session.flush()
    return release


async def revoke_stale_releases(
    session: AsyncSession,
    *,
    user_id: int,
    project_id: int,
) -> bool:
    """Revoke released handles whose scientific source is no longer usable.

    Releases are durable identities, so deleting or deactivating the source
    artifact must not silently leave a deployable handle in the project list.
    The canonical binding resolver remains the single readiness authority for
    imported campaign applications; this sweep only changes the release state.
    """

    releases = list(
        (
            await session.execute(
                select(ApplicationRelease).where(
                    ApplicationRelease.user_id == user_id,
                    ApplicationRelease.project_id == project_id,
                    ApplicationRelease.state == "released",
                )
            )
        )
        .scalars()
        .all()
    )
    changed = False
    now = datetime.now(timezone.utc)
    for release in releases:
        blocker: str | None = None
        if release.model_artifact_uid is not None:
            model = await session.scalar(
                select(ModelArtifact).where(
                    ModelArtifact.artifact_uid == release.model_artifact_uid,
                    ModelArtifact.user_id == user_id,
                    ModelArtifact.project_id == project_id,
                )
            )
            if model is None:
                blocker = "model artifact was deleted"
            elif not model.is_active:
                blocker = "model artifact is inactive"
            elif not is_local() and not model.is_deploy_ready:
                blocker = "model is no longer marked deploy-ready"
        elif release.canonical_artifact_id is not None:
            from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding

            try:
                await resolve_deployment_binding(
                    session,
                    user_id=user_id,
                    workflow_id=release.workflow_id,
                    artifact_uid=None,
                    canonical_artifact_id=release.canonical_artifact_id,
                )
            except (ValueError, PermissionError, OSError) as exc:
                blocker = str(exc)
        else:
            blocker = "release has no scientific source"

        if blocker is not None:
            release.state = "revoked"
            release.revoked_at = release.revoked_at or now
            readiness = dict(release.readiness or {})
            readiness["ready"] = False
            readiness["blockers"] = [blocker]
            release.readiness = readiness
            changed = True
    return changed


def release_payload(release: ApplicationRelease) -> dict[str, object]:
    """Return the stable public application handle projection."""

    return {
        "handle": release.handle,
        "origin": release.origin,
        "state": release.state,
        "label": release.label,
        "project_id": release.project_id,
        "workflow_id": release.workflow_id,
        "workflow_version_id": release.workflow_version_id,
        "source_run_id": release.source_run_id,
        "model_artifact_uid": release.model_artifact_uid,
        "canonical_artifact_id": release.canonical_artifact_id,
        "package_digest": release.package_digest,
        "package_schema_version": release.package_schema_version,
        "artifact_digest": (release.provenance or {}).get("artifact_digest"),
        "readiness": release.readiness or {"ready": False, "blockers": ["readiness unavailable"]},
        "provenance": release.provenance or {},
        "campaign_validation": {
            "recorded": bool(
                release.origin == "campaign_solution"
                and release.state == "released"
                and (release.provenance or {}).get("validation_execution_digest")
            ),
            "validation_execution_digest": (release.provenance or {}).get("validation_execution_digest"),
        },
        "analytical_qualification": {
            "status": "intended_use_review_available" if is_local() else "separate_intended_use_review_required",
            "readiness_is_qualification": False,
            "workflow_id": release.workflow_id,
        },
        "released_at": release.released_at,
    }


__all__ = ["ensure_canonical_release", "ensure_model_release", "release_payload", "revoke_stale_releases"]
