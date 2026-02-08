from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.config import settings
from app.models.user import User
from app.models.exp_version import ExpVersion
from app.models.experiment_file import ExperimentFile
from app.schemas.experiments import (
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFileOut,
    ExperimentSummary,
    ExperimentUpdate,
    VersionCreate,
    VersionInfo,
)
from app.services.experiments import (
    ALLOWED_STAGES,
    add_experiment_file,
    delete_experiment,
    delete_experiment_file,
    delete_experiment_files,
    experiment_dir,
    get_experiment,
    get_experiment_file,
    get_version_by_name,
    list_experiment_files,
    list_experiments,
    read_metadata,
    resolve_data_path,
    update_experiment,
    create_experiment,
)
from app.services.file_storage import FileValidationError, save_upload_file
from app.services.version_storage import ContentAddressableStorage

router = APIRouter(prefix="/experiments")


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
    )
    metadata_path = resolve_data_path(experiment.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(
        **ExperimentSummary.model_validate(experiment).model_dump(), metadata=metadata
    )


@router.get("/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check: user can only access their own experiments
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    metadata_path = resolve_data_path(experiment.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(
        **ExperimentSummary.model_validate(experiment).model_dump(), metadata=metadata
    )


@router.put("/{experiment_id}", response_model=ExperimentDetail)
async def update_experiment_endpoint(
    experiment_id: int,
    payload: ExperimentUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    updated = await update_experiment(
        session,
        experiment=experiment,
        name=payload.name,
        description=payload.description,
        metadata=payload.metadata,
    )
    metadata_path = resolve_data_path(updated.metadata_path)
    metadata = read_metadata(metadata_path)
    return ExperimentDetail(
        **ExperimentSummary.model_validate(updated).model_dump(), metadata=metadata
    )


@router.delete("/{experiment_id}")
async def delete_experiment_endpoint(
    experiment_id: int,
    purge_files: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await delete_experiment(session, experiment)
    if purge_files:
        delete_experiment_files(experiment_id)
    return {"status": "deleted"}


@router.post("/{experiment_id}/files", response_model=ExperimentFileOut, status_code=201)
async def upload_experiment_file(
    experiment_id: int,
    stage: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentFileOut:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
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


@router.get("/{experiment_id}/files", response_model=list[ExperimentFileOut])
async def list_experiment_files_endpoint(
    experiment_id: int,
    stage: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentFileOut]:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
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
    # First verify experiment ownership
    experiment = await get_experiment(session, experiment_id)
    if experiment is None or experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")

    experiment_file = await get_experiment_file(session, experiment_id, file_id)
    if experiment_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = experiment_dir(experiment_id) / experiment_file.file_path
    if file_path.exists():
        file_path.unlink()

    await delete_experiment_file(session, experiment_file)
    return {"status": "deleted"}


@router.get("/{experiment_id}/versions", response_model=list[VersionInfo])
async def list_versions_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[VersionInfo]:
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")

    result = await session.execute(
        select(ExpVersion)
        .where(ExpVersion.experiment_id == experiment_id)
        .order_by(ExpVersion.created_at.desc())
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
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if payload.file_ids and payload.stages:
        raise HTTPException(
            status_code=400, detail="Provide file_ids or stages, not both"
        )

    if payload.stages:
        for stage in payload.stages:
            if stage not in ALLOWED_STAGES:
                raise HTTPException(status_code=400, detail="Invalid stage")

    existing_version = await get_version_by_name(
        session, experiment_id, payload.version_name
    )
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

    files_query = select(ExperimentFile).where(
        ExperimentFile.experiment_id == experiment_id
    )
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
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    # Ownership check
    if experiment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")

    version = await get_version_by_name(session, experiment_id, version_name)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    storage = ContentAddressableStorage(experiment_id)
    try:
        restored_count = storage.restore_version(version_name, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"restored_files": restored_count}
