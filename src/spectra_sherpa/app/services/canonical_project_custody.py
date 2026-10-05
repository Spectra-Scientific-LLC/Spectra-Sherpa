"""Resolve canonical fitted-artifact authority from durable project custody."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan, CanonicalApplicationPlanError
from spectra_sherpa.sdk.canonical_fitted_artifact import (
    CanonicalFittedArtifactError,
    require_private_artifact_directory,
)

CANONICAL_PROJECT_ARTIFACT_DIRECTORY = "canonical_project_artifacts"


class CanonicalProjectCustodyError(PermissionError):
    """Canonical application execution has no matching durable custody grant."""


@dataclass(frozen=True)
class CanonicalArtifactReadGrant:
    """The closed authority an executor may carry for one application workflow."""

    artifact_dir: Path
    artifact_digest: str
    application_integrity_hash: str
    project_id: int
    workflow_id: int


@dataclass(frozen=True)
class CanonicalApplicationPlanProvenance:
    """Read-only, revalidated canonical application-plan provenance."""

    workflow_id: int
    project_id: int
    application_plan: CanonicalApplicationPlan


async def resolve_canonical_artifact_read_grant(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
) -> CanonicalArtifactReadGrant:
    """Resolve exactly one user-owned workflow grant, otherwise fail closed."""

    record = await session.scalar(
        select(CanonicalProjectArtifact)
        .join(Workflow, Workflow.id == CanonicalProjectArtifact.workflow_id)
        .join(Project, Project.id == CanonicalProjectArtifact.project_id)
        .where(
            CanonicalProjectArtifact.user_id == user_id,
            CanonicalProjectArtifact.workflow_id == workflow_id,
            Workflow.user_id == user_id,
            Workflow.project_id == CanonicalProjectArtifact.project_id,
            Project.user_id == user_id,
        )
    )
    if record is None:
        raise CanonicalProjectCustodyError("canonical artifact custody is unavailable for this workflow")
    if len(record.application_integrity_hash) != 64:
        raise CanonicalProjectCustodyError("canonical application graph custody is unavailable")
    artifact_dir = Path(record.artifact_dir)
    expected_artifact_dir = (
        settings.data_dir
        / CANONICAL_PROJECT_ARTIFACT_DIRECTORY
        / f"user-{user_id}"
        / f"project-{record.project_id}"
        / record.artifact_digest
    )
    if (
        artifact_dir != expected_artifact_dir
        or not artifact_dir.is_absolute()
        or artifact_dir.is_symlink()
        or artifact_dir.name != record.artifact_digest
        or artifact_dir.parent.name != f"project-{record.project_id}"
        or artifact_dir.parent.parent.name != f"user-{user_id}"
    ):
        raise CanonicalProjectCustodyError("canonical artifact custody location is invalid")
    try:
        require_private_artifact_directory(artifact_dir)
    except CanonicalFittedArtifactError as exc:
        raise CanonicalProjectCustodyError("canonical artifact custody location is unavailable") from exc
    return CanonicalArtifactReadGrant(
        artifact_dir=artifact_dir,
        artifact_digest=record.artifact_digest,
        application_integrity_hash=record.application_integrity_hash,
        project_id=record.project_id,
        workflow_id=record.workflow_id,
    )


async def resolve_canonical_application_plan_provenance(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
) -> CanonicalApplicationPlanProvenance:
    """Return an owner's verified, data-free sealed plan for inspection only.

    The application workflow intentionally persists only closed runtime
    bindings on its fitted apply nodes.  This resolver is the separate,
    durable provenance path for the admitted original fitted-operation
    parameters.  It never creates a worker grant or makes the payload a
    mutable execution input.
    """

    record = await session.scalar(
        select(CanonicalProjectArtifact)
        .join(Workflow, Workflow.id == CanonicalProjectArtifact.workflow_id)
        .join(Project, Project.id == CanonicalProjectArtifact.project_id)
        .where(
            CanonicalProjectArtifact.user_id == user_id,
            CanonicalProjectArtifact.workflow_id == workflow_id,
            Workflow.user_id == user_id,
            Workflow.project_id == CanonicalProjectArtifact.project_id,
            Project.user_id == user_id,
        )
    )
    if record is None:
        raise CanonicalProjectCustodyError("canonical application provenance is unavailable for this workflow")
    try:
        plan = CanonicalApplicationPlan.from_dict(record.application_plan_payload)
    except (CanonicalApplicationPlanError, TypeError, ValueError) as exc:
        raise CanonicalProjectCustodyError("canonical application provenance is unavailable") from exc
    if (
        plan.application_plan_digest != record.application_plan_digest
        or plan.payload["artifact_digest"] != record.artifact_digest
        or plan.payload["capsule_digest"] != record.capsule_digest
    ):
        raise CanonicalProjectCustodyError("canonical application provenance identity is unavailable")
    return CanonicalApplicationPlanProvenance(
        workflow_id=record.workflow_id,
        project_id=record.project_id,
        application_plan=plan,
    )


__all__ = [
    "CANONICAL_PROJECT_ARTIFACT_DIRECTORY",
    "CanonicalApplicationPlanProvenance",
    "CanonicalArtifactReadGrant",
    "CanonicalProjectCustodyError",
    "resolve_canonical_application_plan_provenance",
    "resolve_canonical_artifact_read_grant",
]
