from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> dict:
    return {"status": "ok"}


class VersionResponse(BaseModel):
    backend_version: str
    python_version: str | None = None
    build_commit: str | None = None
    signing_identity: str | None = None
    package_hashes: dict[str, str] | None = None


# exclude_none keeps the public contract intact. Provenance comes from a
# packaged desktop bundle or a deployment's installed revision artifact.
# A plain pip install/dev checkout has neither; emitting nulls changes the shape
# every consumer sees. Two places lock that shape deliberately:
# tests/test_e2e_local_mode.py::test_version and the wheel qualification smoke
# in scripts/qualify_release_artifacts.py.
@router.get("/version", response_model=VersionResponse, response_model_exclude_none=True)
async def app_version() -> dict:
    """Return the running backend's package version and provenance.

    Public (no auth) so the frontend can read it before any user is
    signed in.  Pairs with the build-time-injected
    ``__SHERPA_FRONTEND_VERSION__`` on the frontend so users can spot
    bundle/server drift after upgrades.
    """
    import json
    import sys
    from pathlib import Path

    from spectra_sherpa import __version__

    response: dict = {"backend_version": __version__}

    # Docker embeds the admitted source revision in a read-only build artifact.
    # Do not infer deployment identity from the working checkout or package tag.
    try:
        import re

        revision = Path("/usr/local/share/spectra/source-revision").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", revision) and revision != "0" * 40:
            response["build_commit"] = revision
    except (OSError, UnicodeError):
        pass

    if hasattr(sys, "_MEIPASS"):
        provenance_path = Path(sys._MEIPASS) / "provenance.json"
        if provenance_path.exists():
            try:
                provenance_data = json.loads(provenance_path.read_text(encoding="utf-8"))
                response.update(
                    {
                        "python_version": provenance_data.get("python_version"),
                        "build_commit": provenance_data.get("build_commit"),
                        "signing_identity": provenance_data.get("signing_identity"),
                        "package_hashes": provenance_data.get("package_hashes"),
                    }
                )
            except Exception:
                pass

    return response


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
