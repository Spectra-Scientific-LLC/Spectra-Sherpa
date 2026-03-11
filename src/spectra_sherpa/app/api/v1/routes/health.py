from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    from spectra_sherpa.app.services.plugin_loader import plugin_load_failures

    result: dict = {"status": "ok"}
    if plugin_load_failures:
        result["status"] = "degraded"
        result["plugin_failure_count"] = len(plugin_load_failures)
    return result


@router.get("/onboarding")
async def get_onboarding_status(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return first-run / onboarding state for the current user.

    Checks what the user has created so far to guide them through
    initial setup steps.
    """
    user_id = current_user.id

    project_count = (await session.scalar(select(func.count(Project.id)).where(Project.user_id == user_id))) or 0

    workflow_count = (await session.scalar(select(func.count(Workflow.id)).where(Workflow.user_id == user_id))) or 0

    experiment_count = (
        await session.scalar(select(func.count(Experiment.id)).where(Experiment.user_id == user_id))
    ) or 0

    model_count = (
        await session.scalar(select(func.count(ModelArtifact.id)).where(ModelArtifact.user_id == user_id))
    ) or 0

    has_executed = (
        await session.scalar(
            select(func.count(Workflow.id)).where(
                Workflow.user_id == user_id,
                Workflow.last_executed_at.isnot(None),
            )
        )
    ) or 0

    return {
        "is_first_run": project_count == 0 and workflow_count == 0,
        "steps": {
            "has_project": project_count > 0,
            "has_data": experiment_count > 0,
            "has_workflow": workflow_count > 0,
            "has_executed": has_executed > 0,
            "has_model": model_count > 0,
        },
        "counts": {
            "projects": project_count,
            "experiments": experiment_count,
            "workflows": workflow_count,
            "models": model_count,
        },
    }
