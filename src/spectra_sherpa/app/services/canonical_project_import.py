"""Atomic import of a verified canonical package into private project custody.

The legacy project importer is intentionally not involved here.  It accepts a
large mutable project snapshot, whereas this importer accepts only a sealed
canonical package whose application graph and fitted-state identities have
already been re-admitted from its archive bytes.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services.audit import audit_emitter
from spectra_sherpa.app.services.canonical_project_custody import CANONICAL_PROJECT_ARTIFACT_DIRECTORY
from spectra_sherpa.app.services.canonical_project_dependencies import (
    CanonicalProjectDependencyReadiness,
    canonical_project_dependency_readiness,
)
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.sdk.canonical_fitted_artifact import (
    CanonicalFittedArtifactError,
    require_private_artifact_directory,
)
from spectra_sherpa.sdk.canonical_project import CanonicalProjectPackage, CanonicalProjectPackageError


class CanonicalProjectImportError(ValueError):
    """A canonical package cannot be installed under durable project custody."""


@dataclass(frozen=True)
class CanonicalProjectImportResult:
    """Durable identities returned only after the import transaction commits."""

    project_id: int
    workflow_id: int
    application_handle: str
    artifact_digest: str
    application_plan_digest: str
    package_sha256: str
    status: str
    dependency_readiness: CanonicalProjectDependencyReadiness


async def import_canonical_project(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    archive: bytes,
    data_dir: Path,
    max_uncompressed_bytes: int,
    commercial_subscription_id: int | None = None,
    commercial_workspace_id: int | None = None,
) -> CanonicalProjectImportResult:
    """Verify, install, and commit one package as an all-or-nothing import.

    Archive validation occurs before opening a transaction.  The fitted-state
    directory is written only below a server-selected ``data_dir`` subtree;
    neither an archive member nor an API caller supplies a path.  On each
    confirmed rollback the database save and newly published private bytes
    are both removed. An uncertain commit retains bytes until its outcome can
    be established. The durable custody row is the sole later authority for
    reading the artifact.
    """

    try:
        package = CanonicalProjectPackage.from_archive(
            archive,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
    except CanonicalProjectPackageError as exc:
        raise CanonicalProjectImportError("canonical project package is invalid") from exc
    if not isinstance(user_id, int) or user_id <= 0:
        raise CanonicalProjectImportError("canonical project importer requires a valid user")
    dependency_readiness = canonical_project_dependency_readiness(package.application_plan)

    artifact_dir: Path | None = None
    commit_started = False
    try:
        async with session_factory() as session:
            async with session.begin():
                # Also serializes outcome reconciliation: a fresh reconciler
                # waits here until this transaction has committed or rolled back.
                await session.get(User, user_id, with_for_update={"key_share": True})
                project, workflow = await _materialize_canonical_project(
                    session,
                    user_id=user_id,
                    package=package,
                    dependency_readiness=dependency_readiness,
                    commercial_subscription_id=commercial_subscription_id,
                    commercial_workspace_id=commercial_workspace_id,
                )
                artifact_dir = _artifact_destination(
                    data_dir,
                    user_id=user_id,
                    project_id=project.id,
                    artifact_digest=package.artifact.artifact_digest,
                )
                try:
                    package.artifact.write_new(artifact_dir)
                except CanonicalFittedArtifactError as exc:
                    raise CanonicalProjectImportError("canonical fitted artifact cannot be installed") from exc
                # Re-read the private bytes after the server-owned write.  A
                # package cannot make its pre-write in-memory artifact an
                # authority for the custody record.
                try:
                    installed = package.artifact.load(artifact_dir)
                except CanonicalFittedArtifactError as exc:
                    raise CanonicalProjectImportError("canonical fitted artifact installation is invalid") from exc
                if (
                    installed.as_dict() != package.artifact.as_dict()
                    or installed.state_bytes != package.artifact.state_bytes
                ):
                    raise CanonicalProjectImportError("canonical fitted artifact changed during installation")
                from fastapi import HTTPException

                from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker
                from spectra_sherpa.app.contracts.project_access import uses_managed_project_access

                if uses_managed_project_access():
                    checker = get_hot_storage_checker()
                    if checker is None:
                        raise HTTPException(503, "Canonical artifact storage accounting is unavailable")
                    await checker(
                        session=session,
                        user_id=user_id,
                        project_id=project.id,
                        incoming_bytes=sum(p.stat().st_size for p in artifact_dir.rglob("*") if p.is_file()),
                    )
                canonical_artifact = CanonicalProjectArtifact(
                    user_id=user_id,
                    project_id=project.id,
                    workflow_id=workflow.id,
                    artifact_digest=package.artifact.artifact_digest,
                    capsule_digest=package.capsule.capsule_digest,
                    application_plan_digest=package.application_plan.application_plan_digest,
                    application_plan_payload=package.application_plan.as_dict(),
                    application_integrity_hash=workflow.integrity_hash,
                    package_sha256=package.archive_sha256,
                    artifact_dir=str(artifact_dir),
                )
                session.add(canonical_artifact)
                await session.flush()
                # The release row is the durable identity used by Deploy and
                # later hosted hand-offs. Keep it in this transaction so an
                # imported package can never become visible without a
                # corresponding application handle.
                from spectra_sherpa.app.services.application_release import ensure_canonical_release

                release = await ensure_canonical_release(
                    session,
                    artifact=canonical_artifact,
                    user_id=user_id,
                    label=project.name,
                    readiness={
                        "ready": dependency_readiness.ready,
                        "blockers": list(dependency_readiness.blockers),
                        "remediation": list(dependency_readiness.remediation),
                    },
                )
                audit_emitter.emit(
                    session=session,
                    action="project.canonical_imported",
                    target_type="Project",
                    target_id=project.id,
                    after={
                        "workflow_id": workflow.id,
                        "artifact_digest": package.artifact.artifact_digest,
                        "capsule_digest": package.capsule.capsule_digest,
                        "application_plan_digest": package.application_plan.application_plan_digest,
                        "package_sha256": package.archive_sha256,
                    },
                )
                await session.flush()
                result = CanonicalProjectImportResult(
                    project_id=project.id,
                    workflow_id=workflow.id,
                    application_handle=release.handle,
                    artifact_digest=package.artifact.artifact_digest,
                    application_plan_digest=package.application_plan.application_plan_digest,
                    package_sha256=package.archive_sha256,
                    status=("awaiting_local_data_binding" if dependency_readiness.ready else "dependency_blocked"),
                    dependency_readiness=dependency_readiness,
                )
                # Context exit starts COMMIT. A failed acknowledgement does not
                # prove rollback: retain custody bytes on an unknown outcome.
                commit_started = True
        return result
    except Exception:
        if artifact_dir is not None:
            remove_bytes = not commit_started
            if commit_started:
                try:
                    async with session_factory() as check:
                        async with check.begin():
                            await check.get(User, user_id, with_for_update={"key_share": True})
                            retained = await check.scalar(
                                select(CanonicalProjectArtifact.id).where(
                                    CanonicalProjectArtifact.project_id == result.project_id,
                                    CanonicalProjectArtifact.artifact_digest == package.artifact.artifact_digest,
                                    CanonicalProjectArtifact.artifact_dir == str(artifact_dir),
                                )
                            )
                            remove_bytes = retained is None
                except Exception:
                    # Unavailable reconciliation is not evidence of rollback.
                    remove_bytes = False
            if remove_bytes:
                _remove_imported_artifact(artifact_dir)
        raise


async def _materialize_canonical_project(
    session: AsyncSession,
    *,
    user_id: int,
    package: CanonicalProjectPackage,
    dependency_readiness: CanonicalProjectDependencyReadiness,
    commercial_subscription_id: int | None = None,
    commercial_workspace_id: int | None = None,
) -> tuple[Project, Workflow]:
    """Create the visible data-free project and application workflow.

    This helper receives a package already re-admitted from archive bytes and
    deliberately does not install files or commit a transaction.
    """

    payload = package.project_payload
    plan = package.application_plan.payload
    metadata = dict(payload["metadata"])
    canonical_metadata = dict(metadata["canonical_project"])
    canonical_metadata["package_status"] = (
        "awaiting_local_data_binding" if dependency_readiness.ready else "dependency_blocked"
    )
    canonical_metadata["dependency_readiness"] = {
        "ready": dependency_readiness.ready,
        "blockers": list(dependency_readiness.blockers),
        "remediation": list(dependency_readiness.remediation),
    }
    metadata["canonical_project"] = canonical_metadata
    from spectra_sherpa.app.contracts.scientific_access import create_managed_project
    from spectra_sherpa.app.schemas.projects import ProjectCreate

    creation = ProjectCreate(
        name=payload["name"],
        description=payload["description"],
        metadata=metadata,
        technique=payload["technique"],
        sample_type=payload["sample_type"],
        commercial_subscription_id=commercial_subscription_id,
        commercial_workspace_id=commercial_workspace_id,
    )
    project = await create_managed_project(session, user_id, creation)
    if project is None:
        project = Project(
            user_id=user_id,
            name=creation.name,
            description=creation.description,
            metadata_=metadata,
            technique=creation.technique,
            sample_type=creation.sample_type,
        )
        session.add(project)
    await session.flush()
    workflow = Workflow(
        user_id=user_id,
        project_id=project.id,
        name="Apply imported canonical model",
        description="Artifact-bound canonical application workflow; bind local data before execution.",
        status="draft" if dependency_readiness.ready else "dependency_blocked",
        purpose=ANALYSIS_WORKFLOW,
        technique=payload["technique"],
        sample_type=payload["sample_type"],
        sheet_order=0,
    )
    session.add(workflow)
    await session.flush()

    # Persist the local workflow identity rather than requiring application
    # consumers to rediscover this authority from its scientist-facing name.
    # This identifier is local import metadata, not part of the signed managed
    # package, and remains stable if the scientist later renames the workflow.
    updated_canonical_metadata = {
        **canonical_metadata,
        "application_workflow_id": workflow.id,
    }
    project.metadata_ = {
        **metadata,
        "canonical_project": updated_canonical_metadata,
    }

    workflow_nodes: list[dict[str, object]] = []
    for order, node in enumerate(plan["nodes"]):
        binding = node.get("artifact_binding")
        # The application plan retains original fitted-operation parameters as
        # scientific provenance, but an application-only node has a closed
        # runtime schema: it accepts precisely the immutable artifact binding.
        # Persisting both would make the saved graph look valid while every
        # worker correctly refuses to execute it.
        parameters = dict(binding) if binding is not None else dict(node["parameters"])
        node_record = {
            "node_id": node["node_id"],
            "node_type": node["application_operation_id"],
            "parameters": parameters,
        }
        workflow_nodes.append(node_record)
        session.add(
            WorkflowNode(
                workflow_id=workflow.id,
                execution_order=order,
                **node_record,
            )
        )
    workflow_edges = [dict(edge) for edge in plan["edges"]]
    for edge in workflow_edges:
        session.add(WorkflowEdge(workflow_id=workflow.id, **edge))
    workflow.integrity_hash = compute_workflow_hash(workflow_nodes, workflow_edges)
    await session.flush()
    return project, workflow


def _artifact_destination(
    data_dir: Path,
    *,
    user_id: int,
    project_id: int,
    artifact_digest: str,
) -> Path:
    """Return a new server-chosen, user/project-private artifact location."""

    if not data_dir.is_absolute():
        raise CanonicalProjectImportError("canonical project data directory is unavailable")
    root = data_dir / CANONICAL_PROJECT_ARTIFACT_DIRECTORY
    user_root = root / f"user-{user_id}"
    project_root = user_root / f"project-{project_id}"
    for path in (root, user_root, project_root):
        if path.is_symlink():
            raise CanonicalProjectImportError("canonical project artifact root must not be a symbolic link")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
        try:
            require_private_artifact_directory(path)
        except CanonicalFittedArtifactError as exc:
            raise CanonicalProjectImportError("canonical project artifact root is not private") from exc
    destination = project_root / artifact_digest
    if destination.parent != project_root or destination.exists():
        raise CanonicalProjectImportError("canonical project artifact destination is unavailable")
    return destination


def _remove_imported_artifact(artifact_dir: Path) -> None:
    """Best-effort cleanup of only the exact server-created artifact leaf."""

    try:
        if artifact_dir.is_dir() and not artifact_dir.is_symlink():
            shutil.rmtree(artifact_dir)
    except OSError:
        # The database transaction has already failed.  Do not obscure its
        # cause; a later custody-root maintenance task may remove an orphan.
        pass


__all__ = [
    "CanonicalProjectImportError",
    "CanonicalProjectImportResult",
    "import_canonical_project",
]
