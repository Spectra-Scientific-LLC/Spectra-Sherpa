"""Basic project availability, independent of scientific provenance qualification.

These indicators do not authorize execution, deployment, or publication. Those
operations retain their own integrity and scientific-evidence checks.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.model_store import get_model_store


def _availability(state: str, detail: str) -> dict[str, str]:
    return {"state": state, "detail": detail}


def _readable(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return bool(stream.read(1))
    except (OSError, ValueError):
        return False


def _source_readable(file: ExperimentFile) -> bool:
    root = experiment_dir(file.experiment_id).resolve()
    path = (root / file.file_path).resolve()
    return path.is_relative_to(root) and _readable(path)


async def project_availability(session: AsyncSession, project_id: int, *, run, model, records: dict) -> dict:
    """Report presence/lifecycle, not whether optional metadata is complete."""
    experiments = list((await session.scalars(select(Experiment.id).where(Experiment.project_id == project_id))).all())
    files = list(
        (
            await session.scalars(
                select(ExperimentFile)
                .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
                .where(Experiment.project_id == project_id)
            )
        ).all()
    )
    readable = sum(_source_readable(file) for file in files)
    result = {
        "source": _availability(
            "healthy" if readable else "faulty" if files else "missing",
            (
                f"{readable} of {len(files)} stored source files available in this project."
                if files
                else "No source files stored in this project."
            ),
        ),
        "dataset": _availability(
            "healthy" if experiments else "missing",
            (
                f"{len(experiments)} datasets available in this project."
                if experiments
                else "No datasets in this project."
            ),
        ),
    }
    workflow_id = await session.scalar(
        select(Workflow.id).where(Workflow.project_id == project_id, Workflow.purpose == "analysis").limit(1)
    )
    result["workflow"] = _availability(
        "healthy" if workflow_id is not None else "missing",
        "Analysis workflow available." if workflow_id is not None else "No analysis workflow in this project.",
    )
    result["run"] = _availability(
        "missing" if run is None else "faulty" if run.status in {"error", "failed", "cancelled"} else "healthy",
        f"Latest run: {run.status}." if run is not None else "No execution run recorded.",
    )
    environment = run.environment_snapshot if run is not None else None
    result["environment"] = _availability(
        "healthy" if environment else "missing",
        "Runtime environment recorded." if environment else "No runtime environment recorded.",
    )
    if model is None:
        result["model"] = _availability("missing", "No calibrated model saved.")
    elif not model.is_active:
        result["model"] = _availability("faulty", "Latest calibrated model is inactive.")
    else:
        try:
            directory = Path(get_model_store().artifact_directory(model.artifact_uid))
            available = all(_readable(directory / name) for name in ("manifest.json", "arrays.npz"))
        except (RuntimeError, ValueError):
            available = False
        result["model"] = _availability(
            "healthy" if available else "faulty",
            (
                "Active calibrated model and stored files available."
                if available
                else "Latest calibrated model files are missing or unreadable."
            ),
        )
    for kind in ("campaign", "package"):
        present = records[kind]["record_id"] is not None
        result[kind] = _availability(
            "healthy" if present else "missing",
            (
                f"{records[kind]['label']} recorded; see provenance details for qualification."
                if present
                else f"No {records[kind]['label'].lower()} recorded."
            ),
        )
    return result
