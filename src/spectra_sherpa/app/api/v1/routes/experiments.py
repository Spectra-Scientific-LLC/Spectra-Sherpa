from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    consume_reserved_demo_upload_quota_if_needed,
    demo_guard,
    get_current_user,
    get_session,
    release_demo_upload_quota_reservation_if_needed,
    require_project,
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.data_formats import ensure_reader_available
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
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides, save_prepared_data_overrides
from spectra_sherpa.app.services.version_storage import ContentAddressableStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments")


async def _require_experiment(session: AsyncSession, experiment_id: int, user_id: int):
    """Load experiment via service layer with ownership check."""
    experiment = await get_experiment(session, experiment_id)
    if experiment is None or experiment.user_id != user_id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


def _experiment_file_summary(experiment_id: int, file_record: ExperimentFile) -> dict[str, object]:
    """Return parser-derived dimensions for files where cheap inspection is available."""
    file_type = (file_record.file_type or "").lower()
    full_path = experiment_dir(experiment_id) / file_record.file_path

    if file_type == "npz" or file_record.file_path.lower().endswith(".npz"):
        try:
            from spectra_sherpa.app.services.synthesis import is_synthetic_npz, load_synthetic_npz

            if not is_synthetic_npz(full_path):
                return {}
            payload = load_synthetic_npz(full_path)
            X = payload["X"]
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            return {
                "shape": [int(X.shape[0]), int(X.shape[1])],
                "n_samples": int(X.shape[0]),
                "n_features": int(X.shape[1]),
                "data_role": str(metadata.get("data_role") or "X_spectra"),
                "x_title": str(metadata.get("x_title") or "Wavenumber"),
                "x_units": str(metadata.get("x_units") or payload.get("feature_units") or "cm^-1"),
                "is_spectra": True,
            }
        except Exception:
            logger.debug("Could not summarize synthetic experiment file %s", file_record.id, exc_info=True)
            return {}

    if file_type != "csv" and not file_record.file_path.lower().endswith(".csv"):
        return {}

    try:
        from spectra_sherpa.app.lib.io import load_csv_as_sherpa

        dataset = load_csv_as_sherpa(full_path)
        feature_axis = getattr(dataset, "feature_axis", None)
        return {
            "shape": list(dataset.shape),
            "n_samples": dataset.n_samples,
            "n_features": dataset.n_features,
            "data_role": dataset.data_role,
            "x_title": getattr(feature_axis, "title", None),
            "x_units": getattr(feature_axis, "units", None),
            "is_spectra": dataset.data_role == "X_spectra",
        }
    except Exception:
        logger.debug("Could not summarize experiment file %s", file_record.id, exc_info=True)
        return {}


def _experiment_file_out(file_record: ExperimentFile) -> ExperimentFileOut:
    base = ExperimentFileOut.model_validate(file_record)
    summary = _experiment_file_summary(file_record.experiment_id, file_record)
    return base.model_copy(update=summary) if summary else base


@router.get("", response_model=list[ExperimentSummary])
async def list_experiments_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentSummary]:
    from sqlalchemy import func

    if project_id is not None:
        await require_project(project_id, current_user.id, session)

    # Filter experiments by authenticated user
    experiments = await list_experiments(
        session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        project_id=project_id,
    )

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
            project_id=exp.project_id,
        )
        for exp in experiments
    ]


@router.post("", response_model=ExperimentDetail, status_code=201)
async def create_experiment_endpoint(
    payload: ExperimentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentDetail:
    if payload.project_id is not None:
        await require_project(payload.project_id, current_user.id, session)
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
    if payload.project_id is not None:
        await require_project(payload.project_id, current_user.id, session)
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
    data_role: str | None = Form(None),
    target_column: str | None = Form(None),
    target_type: str | None = Form(None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentFileOut:
    user_id = current_user.id
    await _require_experiment(session, experiment_id, user_id)
    if stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    try:
        ensure_reader_available(file.filename or "")
    except (ImportError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_reserved = reserve_demo_upload_quota_or_429(user_id)
    exp_dir = experiment_dir(experiment_id)
    destination_dir = exp_dir / stage
    saved_path = None
    persisted = False

    try:
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
            prepared = PreparedDataOverrides.from_mapping(
                {
                    "data_role": data_role,
                    "target_column": target_column,
                    "target_type": target_type,
                }
            )
            if not prepared.is_empty():
                save_prepared_data_overrides(prepared, file_path=str(saved_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        experiment_file = await add_experiment_file(
            session=session,
            experiment_id=experiment_id,
            stage=stage,
            file_path=rel_path,
            file_size_bytes=file_size,
            file_type=file_type,
        )
        persisted = True
    except BaseException:
        if not persisted and saved_path is not None and saved_path.exists():
            saved_path.unlink()
        raise
    finally:
        if persisted:
            consume_reserved_demo_upload_quota_if_needed(user_id, upload_reserved)
        else:
            release_demo_upload_quota_reservation_if_needed(user_id, upload_reserved)
    return _experiment_file_out(experiment_file)


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
            prepared = PreparedDataOverrides.from_mapping(ds.overrides)
            if not prepared.is_empty():
                for file_record in files:
                    save_prepared_data_overrides(prepared, file_path=str(exp_dir / file_record.file_path))
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
        files=[_experiment_file_out(f) for f in all_files],
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
    return [_experiment_file_out(file) for file in files]


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
