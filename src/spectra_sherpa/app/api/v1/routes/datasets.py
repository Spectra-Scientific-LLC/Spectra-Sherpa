from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.nist_library import NistLibrary
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dataset_registry import dataset_registry
from spectra_sherpa.app.services.experiments import experiment_dir


def _resolve_handle_or_raise(dataset_id: str, current_user: User):
    """Resolve a dataset handle with ownership checks."""
    user_id = current_user.id if current_user is not None else None
    try:
        return dataset_registry.get(dataset_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Dataset is not accessible for this user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset handle not found: {dataset_id}") from exc


class ExperimentDataset(BaseModel):
    id: int
    name: str
    description: str | None
    stages: dict[str, list[dict]]


class LibraryDataset(BaseModel):
    id: int
    compound_name: str
    cas_number: str
    resolution: str | None
    file_path: str


class AvailableDatasetsResponse(BaseModel):
    experiments: list[ExperimentDataset]
    library: list[LibraryDataset]
    builder: list[dict]


router = APIRouter(prefix="/datasets")


@router.get("/available", response_model=AvailableDatasetsResponse)
async def list_available_datasets(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AvailableDatasetsResponse:
    """
    Return all available datasets grouped by source for the workflow builder.

    Structure:
    - experiments: List of experiments with files grouped by stage (raw/preprocessed/synthetic)
    - library: List of NIST library entries (user-owned only)
    - builder: Placeholder for saved builder outputs (future feature)
    """
    # Get experiments owned by current user
    experiments_result = await session.execute(
        select(Experiment).where(Experiment.user_id == current_user.id).order_by(Experiment.created_at.desc())
    )
    experiments = list(experiments_result.scalars())

    experiment_datasets: list[ExperimentDataset] = []
    for exp in experiments:
        # Get files grouped by stage for this experiment
        files_result = await session.execute(
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == exp.id)
            .order_by(ExperimentFile.stage, ExperimentFile.file_path)
        )
        files = list(files_result.scalars())

        # Group files by stage
        stages: dict[str, list[dict]] = {"raw": [], "preprocessed": [], "synthetic": []}
        for file in files:
            if file.stage in stages:
                stages[file.stage].append(
                    {
                        "id": file.id,
                        "file_path": file.file_path,
                        "file_type": file.file_type,
                        "file_size_bytes": file.file_size_bytes,
                    }
                )

        experiment_datasets.append(
            ExperimentDataset(
                id=exp.id,
                name=exp.name,
                description=exp.description,
                stages=stages,
            )
        )

    # Get all library entries (NIST library is shared, not per-user)
    library_result = await session.execute(select(NistLibrary).order_by(NistLibrary.compound_name))
    library_entries = list(library_result.scalars())

    library_datasets = [
        LibraryDataset(
            id=entry.id,
            compound_name=entry.compound_name,
            cas_number=entry.cas_number,
            resolution=entry.resolution,
            file_path=entry.file_path,
        )
        for entry in library_entries
    ]

    return AvailableDatasetsResponse(
        experiments=experiment_datasets,
        library=library_datasets,
        builder=[],  # Placeholder for future builder outputs
    )


@router.get("/download/{file_id}")
async def download_dataset(
    file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Download a specific dataset file by its ID.
    Looks up the file path from the database and streams it to the client.
    Only allows downloading files from experiments owned by the current user.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    # 1. Query Metadata with ownership check via experiment
    result = await session.execute(
        select(ExperimentFile)
        .join(Experiment, ExperimentFile.experiment_id == Experiment.id)
        .where(ExperimentFile.id == file_id)
        .where(Experiment.user_id == current_user.id)
    )
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # 2. Resolve path: file_path is relative to experiment directory
    exp_dir = experiment_dir(file_record.experiment_id)
    file_path = (exp_dir / file_record.file_path).resolve()

    # 3. Validate resolved path is within experiment directory (prevent traversal)
    if not file_path.is_relative_to(exp_dir):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")

    # 4. Stream File
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/octet-stream")


@router.get("/{dataset_id}/manifest")
async def dataset_manifest(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.manifest.model_dump(mode="json")


@router.get("/{dataset_id}/preview")
async def dataset_preview(
    dataset_id: str,
    n_rows: int = Query(5, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    ds = _resolve_handle_or_raise(dataset_id, current_user)
    resource = DatasetSummarizer().to_mcp_resource(ds)
    preview = resource.get("preview", {})
    preview["n_rows"] = min(n_rows, ds.shape[0])
    preview["data"] = ds.X[: preview["n_rows"]].tolist()
    return preview


@router.get("/{dataset_id}/provenance")
async def dataset_provenance(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.provenance.to_list()


@router.get("/{dataset_id}/quality")
async def dataset_quality(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
):
    ds = _resolve_handle_or_raise(dataset_id, current_user)
    return ds.quality.model_dump(exclude_none=True)


@router.get("/{dataset_id}/summary")
async def dataset_summary(
    dataset_id: str,
    tier: int = Query(1, ge=0, le=3),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    ds = _resolve_handle_or_raise(dataset_id, current_user)
    summarizer = DatasetSummarizer()
    return {
        "dataset_id": ds.dataset_id,
        "summary": summarizer.summarize(ds, tier=tier),
        "structured": summarizer.to_structured(ds, tier=tier),
    }


class BranchRequest(BaseModel):
    label: str


@router.post("/{dataset_id}/branch")
async def dataset_branch(
    dataset_id: str,
    payload: BranchRequest,
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.id if current_user is not None else None
    try:
        branched = dataset_registry.branch(dataset_id, label=payload.label, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Dataset is not accessible for this user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset handle not found: {dataset_id}") from exc
    return branched.manifest.model_dump(mode="json")
