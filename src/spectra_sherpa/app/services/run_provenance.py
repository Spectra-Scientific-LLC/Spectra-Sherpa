"""Preflight explanations for cleanup; restrictive foreign keys close races."""

from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion


async def has_retained_source(
    session: AsyncSession,
    *,
    run_id: int | None = None,
    workflow_id: int | None = None,
    project_id: int | None = None,
) -> bool:
    """Check source custody without disclosing a model that may have moved projects."""
    if sum(value is not None for value in (run_id, workflow_id, project_id)) != 1:
        raise ValueError("Specify exactly one provenance deletion scope")
    if run_id is not None:
        predicate = ModelArtifact.source_run_id == run_id
    elif workflow_id is not None:
        versions = select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id)
        runs = select(ExecutionRun.id).where(ExecutionRun.workflow_id == workflow_id)
        predicate = or_(
            ModelArtifact.workflow_id == workflow_id,
            ModelArtifact.workflow_version_id.in_(versions),
            ModelArtifact.source_run_id.in_(runs),
        )
    else:
        tree = select(Project.id).where(Project.id == project_id).cte("cleanup_projects", recursive=True)
        tree = tree.union_all(select(Project.id).where(Project.parent_id == tree.c.id))
        runs = select(ExecutionRun.id).where(ExecutionRun.project_id.in_(select(tree.c.id)))
        workflows = select(Workflow.id).where(Workflow.project_id.in_(select(tree.c.id)))
        versions = select(WorkflowVersion.id).where(WorkflowVersion.workflow_id.in_(workflows))
        predicate = or_(
            ModelArtifact.project_id.in_(select(tree.c.id)),
            ModelArtifact.workflow_id.in_(workflows),
            ModelArtifact.workflow_version_id.in_(versions),
            ModelArtifact.source_run_id.in_(runs),
        )
    if (await session.scalar(select(ModelArtifact.id).where(predicate).limit(1))) is not None:
        return True
    from spectra_sherpa.app.contracts.project_evidence import has_extension_evidence

    return await has_extension_evidence(session, run_id=run_id, workflow_id=workflow_id, project_id=project_id)


async def require_unretained_source(
    session: AsyncSession,
    *,
    run_id: int | None = None,
    workflow_id: int | None = None,
    project_id: int | None = None,
) -> None:
    if await has_retained_source(session, run_id=run_id, workflow_id=workflow_id, project_id=project_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: a retained model or campaign depends on this source evidence. "
            "No records were removed. The retained result and its source evidence must remain together.",
        )


@asynccontextmanager
async def provenance_cleanup(session: AsyncSession):
    """Translate a concurrent reference conflict and roll back the whole cleanup."""
    try:
        yield
    except IntegrityError as exc:
        await session.rollback()
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code == "23503" or "FOREIGN KEY constraint failed" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail="Deletion conflicts with retained source evidence or another dependent record. "
                "Nothing was deleted. Refresh and review dependent models before retrying.",
            ) from exc
        raise
