from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.exp_version import ExpVersion
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.experiments import (
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFileOut,
    ExperimentSummary,
    ExperimentUpdate,
    ReferenceDatasetImportRequest,
    ReferenceDatasetImportResponse,
    VersionCreate,
    VersionInfo,
)
from spectra_sherpa.app.services.experiments import (
    ALLOWED_STAGES,
    add_experiment_file,
    create_experiment,
    delete_experiment,
    delete_experiment_file,
    delete_experiment_files,
    experiment_dir,
    get_experiment,
    get_experiment_file,
    get_version_by_name,
    import_reference_dataset,
    list_experiment_files,
    list_experiments,
    read_metadata,
    resolve_data_path,
    update_experiment,
)
from spectra_sherpa.app.services.file_storage import FileValidationError, save_upload_file
from spectra_sherpa.app.services.version_storage import ContentAddressableStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments")


async def _require_experiment(session: AsyncSession, experiment_id: int, user_id: int):
    """Load experiment via service layer with ownership check."""
    experiment = await get_experiment(session, experiment_id)
    if experiment is None or experiment.user_id != user_id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.get("", response_model=list[ExperimentSummary])
async def list_experiments_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentSummary]:
    from sqlalchemy import func

    # Filter experiments by authenticated user
    experiments = await list_experiments(session, user_id=current_user.id, limit=limit, offset=offset)

    # Get file counts for all experiments in one query
    exp_ids = [exp.id for exp in experiments]
    if exp_ids:
        file_count_query = (
            select(
                ExperimentFile.experiment_id,
                func.count(ExperimentFile.id).label("file_count"),
            )
            .where(ExperimentFile.experiment_id.in_(exp_ids))
            .group_by(ExperimentFile.experiment_id)
        )
        result = await session.execute(file_count_query)
        file_counts = {row.experiment_id: row.file_count for row in result}
    else:
        file_counts = {}

    return [
        ExperimentSummary(
            id=exp.id,
            name=exp.name,
            description=exp.description,
            created_at=exp.created_at,
            file_count=file_counts.get(exp.id, 0),
        )
        for exp in experiments
    ]


@router.post("", response_model=ExperimentDetail, status_code=201)
async def create_experiment_endpoint(
    payload: ExperimentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    experiment = await create_experiment(
        session,
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        metadata=payload.metadata,
        project_id=payload.project_id,
    )
    metadata_path = resolve_data_path(experiment.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(**ExperimentSummary.model_validate(experiment).model_dump(), metadata=metadata)


@router.get("/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    metadata_path = resolve_data_path(experiment.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(**ExperimentSummary.model_validate(experiment).model_dump(), metadata=metadata)


@router.put("/{experiment_id}", response_model=ExperimentDetail)
async def update_experiment_endpoint(
    experiment_id: int,
    payload: ExperimentUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    updated = await update_experiment(
        session,
        experiment=experiment,
        name=payload.name,
        description=payload.description,
        metadata=payload.metadata,
        project_id=payload.project_id,
    )
    metadata_path = resolve_data_path(updated.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(**ExperimentSummary.model_validate(updated).model_dump(), metadata=metadata)


@router.delete("/{experiment_id}")
async def delete_experiment_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    await delete_experiment(session, experiment)
    delete_experiment_files(experiment_id)
    return {"status": "deleted"}


@router.post(
    "/{experiment_id}/files",
    response_model=ExperimentFileOut,
    status_code=201,
    dependencies=[Depends(demo_guard("data_upload"))],
)
async def upload_experiment_file(
    experiment_id: int,
    stage: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentFileOut:
    await _require_experiment(session, experiment_id, current_user.id)
    if stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    exp_dir = experiment_dir(experiment_id)
    destination_dir = exp_dir / stage

    try:
        saved_path = await save_upload_file(
            file,
            destination_dir=destination_dir,
            max_file_size_mb=settings.max_file_size_mb,
        )
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rel_path = saved_path.relative_to(exp_dir).as_posix()
    file_size = saved_path.stat().st_size
    file_type = saved_path.suffix.lstrip(".") or None

    try:
        experiment_file = await add_experiment_file(
            session=session,
            experiment_id=experiment_id,
            stage=stage,
            file_path=rel_path,
            file_size_bytes=file_size,
            file_type=file_type,
        )
    except Exception:
        if saved_path.exists():
            saved_path.unlink()
        raise

    return ExperimentFileOut.model_validate(experiment_file)


@router.post(
    "/{experiment_id}/import-reference",
    response_model=ReferenceDatasetImportResponse,
    status_code=201,
)
async def import_reference_datasets_endpoint(
    experiment_id: int,
    payload: ReferenceDatasetImportRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReferenceDatasetImportResponse:
    await _require_experiment(session, experiment_id, current_user.id)

    all_files: list[ExperimentFile] = []
    exp_dir = experiment_dir(experiment_id)

    def _cleanup_orphan_files() -> None:
        """Remove files written by previously-successful datasets on failure."""
        for f in all_files:
            path = exp_dir / f.file_path
            if path.exists():
                path.unlink()

    try:
        for ds in payload.datasets:
            files = await import_reference_dataset(session, experiment_id, ds.source, ds.name)
            all_files.extend(files)
        # Commit all DB rows atomically
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        _cleanup_orphan_files()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        await session.rollback()
        _cleanup_orphan_files()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        _cleanup_orphan_files()
        raise

    # Post-commit: refresh is best-effort — files and DB rows are already safe.
    # A refresh failure here must NOT trigger file cleanup.
    for f in all_files:
        await session.refresh(f)

    return ReferenceDatasetImportResponse(
        imported=len(all_files),
        files=[ExperimentFileOut.model_validate(f) for f in all_files],
    )


@router.get("/{experiment_id}/files", response_model=list[ExperimentFileOut])
async def list_experiment_files_endpoint(
    experiment_id: int,
    stage: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentFileOut]:
    await _require_experiment(session, experiment_id, current_user.id)
    if stage and stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    files = await list_experiment_files(session, experiment_id, stage=stage)
    return [ExperimentFileOut.model_validate(file) for file in files]


@router.delete("/{experiment_id}/files/{file_id}")
async def delete_experiment_file_endpoint(
    experiment_id: int,
    file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    # Verify experiment ownership
    await _require_experiment(session, experiment_id, current_user.id)

    experiment_file = await get_experiment_file(session, experiment_id, file_id)
    if experiment_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = experiment_dir(experiment_id) / experiment_file.file_path

    # ISO 17025 — commit the audited DB transaction BEFORE removing
    # bytes from disk. If the audit insert / chainer commit fails,
    # delete_experiment_file rolls back and the file stays. Reverse
    # ordering would leave the disk gone but the row still present.
    await delete_experiment_file(session, experiment_file)

    # DB+audit succeeded. Filesystem unlink is best-effort cleanup —
    # an orphan file is recoverable; an orphan DB row is not.
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError as exc:
            logger.warning(
                "Audited delete of ExperimentFile id=%s succeeded but "
                "filesystem unlink of %s failed: %s. File is now an "
                "orphan; safe to remove out-of-band.",
                experiment_file.id,
                file_path,
                exc,
            )

    return {"status": "deleted"}


@router.get("/{experiment_id}/versions", response_model=list[VersionInfo])
async def list_versions_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[VersionInfo]:
    await _require_experiment(session, experiment_id, current_user.id)

    result = await session.execute(
        select(ExpVersion).where(ExpVersion.experiment_id == experiment_id).order_by(ExpVersion.created_at.desc())
    )
    versions = result.scalars().all()

    storage = ContentAddressableStorage(experiment_id)
    payload: list[VersionInfo] = []
    for version in versions:
        try:
            manifest = storage.load_manifest(version.version_name)
            file_count = len(manifest.get("files", {}))
        except FileNotFoundError:
            file_count = 0
        payload.append(
            VersionInfo(
                id=version.id,
                version_name=version.version_name,
                description=version.description,
                created_at=version.created_at,
                parent_version_id=version.parent_version_id,
                file_count=file_count,
            )
        )

    return payload


@router.post("/{experiment_id}/versions", response_model=VersionInfo, status_code=201)
async def create_version_endpoint(
    experiment_id: int,
    payload: VersionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> VersionInfo:
    await _require_experiment(session, experiment_id, current_user.id)

    if payload.file_ids and payload.stages:
        raise HTTPException(status_code=400, detail="Provide file_ids or stages, not both")

    if payload.stages:
        for stage in payload.stages:
            if stage not in ALLOWED_STAGES:
                raise HTTPException(status_code=400, detail="Invalid stage")

    existing_version = await get_version_by_name(session, experiment_id, payload.version_name)
    if existing_version:
        raise HTTPException(status_code=409, detail="Version name already exists")

    parent_version_name = None
    if payload.parent_version_id:
        result = await session.execute(
            select(ExpVersion)
            .where(ExpVersion.id == payload.parent_version_id)
            .where(ExpVersion.experiment_id == experiment_id)
        )
        parent = result.scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent version not found")
        parent_version_name = parent.version_name

    files_query = select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id)
    if payload.file_ids:
        files_query = files_query.where(ExperimentFile.id.in_(payload.file_ids))
    if payload.stages:
        files_query = files_query.where(ExperimentFile.stage.in_(payload.stages))

    result = await session.execute(files_query)
    files = result.scalars().all()

    if not files:
        raise HTTPException(status_code=400, detail="No files found for version")

    exp_dir = experiment_dir(experiment_id)
    file_paths = []
    for file in files:
        absolute_path = (exp_dir / file.file_path).resolve()
        if not absolute_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Missing file for version: {file.file_path}",
            )
        file_paths.append(absolute_path)

    storage = ContentAddressableStorage(experiment_id)
    manifest_path = storage.create_version(
        version_name=payload.version_name,
        files=file_paths,
        description=payload.description,
        parent_version=parent_version_name,
        base_path=exp_dir,
    )
    manifest_relative = str(manifest_path.relative_to(settings.data_dir))

    version = ExpVersion(
        experiment_id=experiment_id,
        version_name=payload.version_name,
        description=payload.description,
        manifest_path=manifest_relative,
        parent_version_id=payload.parent_version_id,
    )
    session.add(version)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Version already exists") from exc

    await session.refresh(version)

    return VersionInfo(
        id=version.id,
        version_name=version.version_name,
        description=version.description,
        created_at=version.created_at,
        parent_version_id=version.parent_version_id,
        file_count=len(file_paths),
    )


@router.post("/{experiment_id}/versions/{version_name}/restore")
async def restore_version_endpoint(
    experiment_id: int,
    version_name: str,
    overwrite: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _require_experiment(session, experiment_id, current_user.id)

    version = await get_version_by_name(session, experiment_id, version_name)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    storage = ContentAddressableStorage(experiment_id)
    try:
        restored_count = storage.restore_version(version_name, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"restored_files": restored_count}
