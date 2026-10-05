from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

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
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.api.v1.routes._http_utils import scientific_asset_warnings
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access, scientific_project_ids
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.lib.collection_definition import (
    MAX_COLLECTION_DEFINITION_BYTES,
    ValidatedCollectionDefinition,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.data_formats import ensure_reader_available
from spectra_sherpa.app.lib.target_summary import target_summary
from spectra_sherpa.app.models.exp_version import ExpVersion
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.acquisition_plans import AcquisitionPlanOut, AcquisitionPlanUpdate
from spectra_sherpa.app.schemas.experiments import (
    CollectionDefinitionReceipt,
    ExperimentAnalysisSelection,
    ExperimentAnalysisSelectionUpdate,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFileAssetsOut,
    ExperimentFileOut,
    ExperimentSummary,
    ExperimentUpdate,
    ReferenceDatasetImportRequest,
    ReferenceDatasetImportResponse,
    ScientificAssetOut,
    VersionCreate,
    VersionInfo,
)
from spectra_sherpa.app.services.acquisition_plans import (
    AcquisitionPlanRevisionConflict,
    read_acquisition_plan,
    replace_acquisition_plan,
)
from spectra_sherpa.app.services.collection_definitions import (
    collection_definition_path,
    read_collection_definition,
    remove_collection_definition,
    write_collection_definition,
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
    preferred_experiment_stage,
    read_metadata,
    resolve_data_path,
    update_experiment,
)
from spectra_sherpa.app.services.file_storage import FileValidationError, save_upload_file
from spectra_sherpa.app.services.model_application import LoadedProjectDataset, load_project_dataset
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    load_prepared_data_overrides,
    save_prepared_data_overrides,
)
from spectra_sherpa.app.services.version_storage import ContentAddressableStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments")

_COLLECTION_DEFINITION_RECEIPT_SCHEMA = "spectrasherpa-collection-definition-receipt/1"
_ANALYSIS_SELECTION_SCHEMA = "spectra-sherpa-analysis-selection/1"
_CollectionDefinitionStatus = Literal["absent", "preview", "attached", "stale", "invalid"]
_BUILTIN_LAVENDER_NAME = "lavender-essential-oil-v1"
_BUILTIN_LAVENDER_TRIAL_DATASET_KEY = "avatar-lavender-essential-oils-v1"
_REFERENCE_IMPORT_DISABLED_DETAIL = (
    "The free hosted trial accepts only server-issued datasets and exact registered reference artifacts. "
    "Use local OSS, Enterprise Hybrid, or a qualified paid profile for customer data."
)


class RegisteredReferenceUploadMismatch(ValueError):
    """The selected bytes do not match the immutable reference authority."""


async def _stage_registered_reference_upload(
    upload: UploadFile,
    destination: Path,
    *,
    maximum_size_bytes: int,
) -> tuple[int, str]:
    """Write and independently identify one bounded temporary snapshot."""

    if upload.size is not None and upload.size > maximum_size_bytes:
        await upload.close()
        raise RegisteredReferenceUploadMismatch("selected file exceeds the largest registered reference size")
    observed = 0
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as target:
            while chunk := await upload.read(min(1024 * 1024, maximum_size_bytes + 1 - observed)):
                observed += len(chunk)
                if observed > maximum_size_bytes:
                    raise RegisteredReferenceUploadMismatch(
                        "selected file exceeds the largest registered reference size"
                    )
                digest.update(chunk)
                target.write(chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return observed, digest.hexdigest()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def _uploaded_collection_definition(file: UploadFile) -> ValidatedCollectionDefinition:
    """Read one bounded JSON upload before constructing its in-memory object graph."""

    if file.size is not None and file.size > MAX_COLLECTION_DEFINITION_BYTES:
        raise ValueError("collection definition exceeds the 4 MiB limit")
    payload = bytearray()
    while True:
        chunk = await file.read(min(1024 * 1024, MAX_COLLECTION_DEFINITION_BYTES + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > MAX_COLLECTION_DEFINITION_BYTES:
            raise ValueError("collection definition exceeds the 4 MiB limit")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("collection definition is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("collection definition must be an object")
    return validate_collection_definition(decoded)


def _definition_receipt(
    *,
    experiment_id: int,
    status: _CollectionDefinitionStatus,
    definition: ValidatedCollectionDefinition | None,
    loaded: LoadedProjectDataset | None = None,
    message: str,
) -> CollectionDefinitionReceipt:
    payload = definition.payload if definition is not None else None
    rows = payload.get("rows", []) if payload is not None else []
    columns = payload.get("columns", []) if payload is not None else []
    collection = payload.get("collection", {}) if payload is not None else {}
    declared_files = {(row["file_name"], row["sha256"], row["asset_id"]) for row in rows if isinstance(row, Mapping)}
    source = loaded.dataset.meta.get("source_collection", {}) if loaded is not None else {}
    target_context = loaded.dataset.target_context if loaded is not None else None
    return CollectionDefinitionReceipt(
        schema_version=_COLLECTION_DEFINITION_RECEIPT_SCHEMA,
        status=status,
        experiment_id=experiment_id,
        definition_sha256=definition.sha256 if definition is not None else None,
        source_manifest_sha256=source.get("source_manifest_sha256"),
        scientific_collection_sha256=source.get("scientific_collection_sha256"),
        file_count=int(source.get("file_count", len(declared_files))),
        row_count=len(rows),
        column_count=len(columns),
        columns=list(columns),
        shape=list(loaded.dataset.shape) if loaded is not None else None,
        dataset_id=(loaded.dataset.dataset_id if loaded is not None else collection.get("dataset_id")),
        title=(loaded.dataset.title if loaded is not None else collection.get("title")),
        target_present=bool(loaded is not None and loaded.dataset.target is not None),
        sample_classes_present=bool(
            target_context is not None
            and (target_context.n_classes is not None or target_context.class_names is not None)
        ),
        message=message,
    )


async def _require_persisted_definition_revision(
    experiment_id: int,
    expected_sha256: str,
) -> ValidatedCollectionDefinition:
    """Require that the exact definition revision is still authoritative."""

    try:
        current = await asyncio.to_thread(read_collection_definition, experiment_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="The collection definition changed during verification. Refresh its current status.",
        ) from exc
    if current is None or current.sha256 != expected_sha256:
        raise HTTPException(
            status_code=409,
            detail="The collection definition changed during verification. Refresh its current status.",
        )
    return current


async def _require_experiment(session: AsyncSession, experiment_id: int, user_id: int, operation="write"):
    """Load experiment via service layer with ownership check."""
    experiment = await get_experiment(session, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await require_scientific_access(
        session, user_id, experiment.project_id, operation, resource_owner_id=experiment.user_id
    )
    return experiment


def _experiment_file_summary(experiment_id: int, file_record: ExperimentFile) -> dict[str, object]:
    """Return parser-derived dimensions for files where cheap inspection is available."""
    file_type = (file_record.file_type or "").lower()
    full_path = experiment_dir(experiment_id) / file_record.file_path

    if file_type == "npz" or file_record.file_path.lower().endswith(".npz"):
        try:
            from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

            prepared = load_prepared_data_overrides(file_path=str(full_path))
            dataset = load_canonical_file_as_sherpa(
                full_path,
                prepared_overrides=prepared.to_sidecar_dict(),
            )
            axis = dataset.feature_axis
            return {
                "shape": [int(value) for value in dataset.shape],
                "n_samples": int(dataset.n_samples),
                "n_features": int(dataset.n_features),
                "data_role": str(dataset.data_role),
                "x_title": None if axis is None else _optional_text(axis.title),
                "x_units": None if axis is None else _optional_text(axis.units),
                "is_spectra": bool(dataset.is_spectra),
                **target_summary(dataset),
            }
        except Exception:
            logger.debug("Could not summarize NumPy experiment file %s", file_record.id, exc_info=True)
            return {}

    if file_type != "csv" and not file_record.file_path.lower().endswith(".csv"):
        return {}

    try:
        from spectra_sherpa.app.services.dag.nodes.data.sample_table import (
            inspect_portable_sample_table,
        )

        target_definitions = inspect_portable_sample_table(full_path)
        if target_definitions is not None:
            import pandas as pd

            row_count = int(len(pd.read_csv(full_path).index))
            return {
                "shape": [row_count, len(target_definitions)],
                "n_samples": row_count,
                "n_features": len(target_definitions),
                "data_role": "sample_metadata",
                "is_spectra": False,
                "target_names": list(target_definitions),
                "target_types": target_definitions,
            }

        from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

        prepared = load_prepared_data_overrides(file_path=str(full_path))
        dataset = load_canonical_file_as_sherpa(
            full_path,
            prepared_overrides=prepared.to_sidecar_dict(),
        )
        feature_axis = getattr(dataset, "feature_axis", None)
        return {
            "shape": list(dataset.shape),
            "n_samples": dataset.n_samples,
            "n_features": dataset.n_features,
            "data_role": dataset.data_role,
            "x_title": getattr(feature_axis, "title", None),
            "x_units": getattr(feature_axis, "units", None),
            "is_spectra": dataset.data_role == "X_spectra",
            **target_summary(dataset),
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
        await require_scientific_access(session, current_user.id, project_id, "read")

    admitted = await scientific_project_ids(session, current_user.id)
    if admitted is not None:
        query = (
            select(Experiment)
            .where(Experiment.project_id.in_(admitted))
            .order_by(Experiment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if project_id is not None:
            query = query.where(Experiment.project_id == project_id)
        experiments = list((await session.scalars(query)).all())
    else:
        experiments = await list_experiments(
            session, user_id=current_user.id, limit=limit, offset=offset, project_id=project_id
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
    await require_scientific_access(session, current_user.id, payload.project_id, "write")
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
    experiment = await _require_experiment(session, experiment_id, current_user.id, "read")
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
        await require_scientific_access(session, current_user.id, payload.project_id, "write")
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


@router.put("/{experiment_id}/analysis-selection", response_model=ExperimentAnalysisSelection)
async def update_experiment_analysis_selection(
    experiment_id: int,
    payload: ExperimentAnalysisSelectionUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentAnalysisSelection:
    """Persist the active target and grouping intent without replacing other metadata."""

    experiment = await _require_experiment(session, experiment_id, current_user.id)
    selected_target = (payload.selected_target or "").strip() or None
    group_column = (payload.group_column or "").strip() or None
    if (selected_target is None) != (payload.target_type is None):
        raise HTTPException(status_code=400, detail="Target name and target type must be selected together")
    if group_column is not None and selected_target is None:
        raise HTTPException(status_code=400, detail="Grouped validation requires a selected target")

    metadata_path = resolve_data_path(experiment.metadata_path)
    metadata = read_metadata(metadata_path)
    selection = ExperimentAnalysisSelection(
        schema_version=_ANALYSIS_SELECTION_SCHEMA,
        selected_target=selected_target,
        target_type=payload.target_type,
        group_column=group_column,
        source_digest=payload.source_digest,
        updated_at=datetime.now(timezone.utc),
    )
    metadata["analysis_selection"] = selection.model_dump(mode="json")
    await update_experiment(
        session,
        experiment=experiment,
        name=None,
        description=None,
        metadata=metadata,
    )
    return selection


@router.get("/{experiment_id}/acquisition-plan", response_model=AcquisitionPlanOut)
async def get_acquisition_plan_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AcquisitionPlanOut:
    """Return the complete scientific intent for a multi-well experiment."""

    await _require_experiment(session, experiment_id, current_user.id)
    try:
        plan = await read_acquisition_plan(session, experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AcquisitionPlanOut.model_validate(plan)


@router.put(
    "/{experiment_id}/acquisition-plan",
    response_model=AcquisitionPlanOut,
    dependencies=[Depends(demo_guard("sample_table_authoring"))],
)
async def replace_acquisition_plan_endpoint(
    experiment_id: int,
    payload: AcquisitionPlanUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AcquisitionPlanOut:
    """CAS-update one owned dataset's complete acquisition plan."""

    await _require_experiment(session, experiment_id, current_user.id)
    try:
        plan = await replace_acquisition_plan(
            session,
            experiment_id,
            payload.model_dump(exclude={"expected_revision"}, exclude_unset=True, mode="json"),
            format_id=payload.plate_format_id or "plate-96",
            expected_revision=payload.expected_revision,
        )
    except AcquisitionPlanRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AcquisitionPlanOut.model_validate(plan)


@router.get("/{experiment_id}/collection-definition", response_model=CollectionDefinitionReceipt)
async def get_collection_definition_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CollectionDefinitionReceipt:
    """Return an owner-scoped receipt and visibly report stale durable bindings."""

    experiment = await _require_experiment(session, experiment_id, current_user.id)
    from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

    admission = await require_trial_dataset_access(
        session=session,
        user_id=current_user.id,
        workflow_project_id=experiment.project_id,
        experiment_id=experiment_id,
        stage="raw",
        file_id=None,
        asset_id=None,
    )
    try:
        definition = await asyncio.to_thread(read_collection_definition, experiment_id)
    except ValueError:
        return _definition_receipt(
            experiment_id=experiment_id,
            status="invalid",
            definition=None,
            message="The saved collection definition is invalid. Remove it, then attach a verified JSON definition.",
        )
    if definition is None:
        return _definition_receipt(
            experiment_id=experiment_id,
            status="absent",
            definition=None,
            message="No scientific collection definition is attached.",
        )
    try:
        loaded = (
            admission.loaded_dataset
            if admission is not None
            else await load_project_dataset(
                session,
                user_id=current_user.id,
                experiment_id=experiment_id,
                stage="raw",
                definition_override=definition,
            )
        )
    except ValueError:
        await _require_persisted_definition_revision(experiment_id, definition.sha256)
        return _definition_receipt(
            experiment_id=experiment_id,
            status="stale",
            definition=definition,
            message=(
                "The saved definition no longer matches the current files or parsed assets. "
                "Restore the exact sources, replace the definition, or remove it."
            ),
        )
    await _require_persisted_definition_revision(experiment_id, definition.sha256)
    if loaded.collection_definition_sha256 != definition.sha256:
        raise HTTPException(status_code=409, detail="The collection definition identity changed during verification.")
    return _definition_receipt(
        experiment_id=experiment_id,
        status="attached",
        definition=definition,
        loaded=loaded,
        message="The definition is attached and matches the current scientific collection.",
    )


@router.post(
    "/{experiment_id}/collection-definition/preview",
    response_model=CollectionDefinitionReceipt,
    dependencies=[Depends(demo_guard("collection_definition_authoring"))],
)
async def preview_collection_definition_endpoint(
    experiment_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CollectionDefinitionReceipt:
    """Validate a prospective definition against exact current sources without saving it."""

    await _require_experiment(session, experiment_id, current_user.id)
    try:
        definition = await _uploaded_collection_definition(file)
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment_id,
            stage="raw",
            definition_override=definition,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _definition_receipt(
        experiment_id=experiment_id,
        status="preview",
        definition=definition,
        loaded=loaded,
        message="Preview verified. Attach this exact definition to make it authoritative.",
    )


@router.put(
    "/{experiment_id}/collection-definition",
    response_model=CollectionDefinitionReceipt,
    dependencies=[Depends(demo_guard("collection_definition_authoring"))],
)
async def attach_collection_definition_endpoint(
    experiment_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CollectionDefinitionReceipt:
    """Attach only a definition that exactly re-admits the current owned collection."""

    await _require_experiment(session, experiment_id, current_user.id)
    try:
        definition = await _uploaded_collection_definition(file)
        await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment_id,
            stage="raw",
            definition_override=definition,
        )
        await asyncio.to_thread(write_collection_definition, experiment_id, definition.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Re-admit the persisted definition and current source inventory after the
    # atomic write. A source may have changed while the prospective definition
    # was being checked; never return an "attached" receipt for that stale state.
    try:
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment_id,
            stage="raw",
            definition_override=definition,
        )
    except ValueError:
        await _require_persisted_definition_revision(experiment_id, definition.sha256)
        return _definition_receipt(
            experiment_id=experiment_id,
            status="stale",
            definition=definition,
            message=(
                "The definition was saved, but the source inventory changed during verification. "
                "Review the current files, then replace or remove the stale definition."
            ),
        )
    await _require_persisted_definition_revision(experiment_id, definition.sha256)
    if loaded.collection_definition_sha256 != definition.sha256:
        raise HTTPException(status_code=409, detail="The collection definition identity changed during verification.")
    return _definition_receipt(
        experiment_id=experiment_id,
        status="attached",
        definition=definition,
        loaded=loaded,
        message="Definition attached. The receipt is bound to the current sources and parsed assets.",
    )


@router.delete(
    "/{experiment_id}/collection-definition",
    response_model=CollectionDefinitionReceipt,
    dependencies=[Depends(demo_guard("collection_definition_authoring"))],
)
async def remove_collection_definition_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CollectionDefinitionReceipt:
    """Remove only the dedicated definition; source files remain unchanged."""

    await _require_experiment(session, experiment_id, current_user.id)
    try:
        await asyncio.to_thread(remove_collection_definition, experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _definition_receipt(
        experiment_id=experiment_id,
        status="absent",
        definition=None,
        message="Scientific collection definition removed. Source files were not changed.",
    )


@router.delete("/{experiment_id}")
async def delete_experiment_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    from spectra_sherpa.app.contracts.demo_policy import require_trial_starter_experiment_deletion

    await require_trial_starter_experiment_deletion(
        session=session,
        user_id=current_user.id,
        experiment_id=experiment_id,
    )
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
    experiment = await _require_experiment(session, experiment_id, user_id)
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
        if app_config.site_profile == "pro":
            from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker

            checker = get_hot_storage_checker()
            if checker is not None:
                await checker(
                    session=session, user_id=user_id, incoming_bytes=file_size, project_id=experiment.project_id
                )

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


async def _retain_pro_reference_views(session, user_id, project_id, import_dir, materialized_views, destinations):
    """Account actual expanded bytes before retaining unique Pro source members."""
    if app_config.site_profile != "pro":
        return materialized_views
    from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker

    checker = get_hot_storage_checker()
    if checker is None:
        raise HTTPException(503, "Storage accounting is unavailable")
    await checker(
        session=session,
        user_id=user_id,
        project_id=project_id,
        incoming_bytes=sum(view[3].stat().st_size for view in materialized_views),
    )
    retained_views = []
    for projection, view_id, suffix, staged, materialized in materialized_views:
        # The caller owns a fresh import directory. Preserve the registered
        # basename without allowing a retry to overwrite a retained view.
        destination = import_dir / f"{view_id}{suffix}"
        destinations.append(destination)
        shutil.copyfile(staged, destination)
        retained_views.append((projection, view_id, suffix, destination, materialized))
    return retained_views


def _remove_uncommitted_reference_import(destinations: list[Path], import_dir: Path | None) -> None:
    """Remove only paths reserved by this request, never a prior import."""

    from spectra_sherpa.app.lib.registered_reference_storage import remove_registered_reference_sidecar

    for destination in destinations:
        remove_registered_reference_sidecar(destination)
        destination.unlink(missing_ok=True)
    if import_dir is not None:
        try:
            import_dir.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Uncommitted registered-reference import directory is not empty")


@router.post(
    "/{experiment_id}/import-registered-reference",
    response_model=ReferenceDatasetImportResponse,
    status_code=201,
    dependencies=[Depends(demo_guard("registered_reference_import"))],
)
async def import_registered_reference_endpoint(
    experiment_id: int,
    projection_id: str | None = Form(None),
    package_id: str | None = Form(None),
    files: list[UploadFile] = File(..., alias="file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReferenceDatasetImportResponse:
    """Admit exact user-acquired references without enabling general trial upload."""

    from uuid import uuid4

    from spectra_sherpa.app.contracts.demo_policy import issue_trial_reference_grant
    from spectra_sherpa.app.lib.reference_artifacts import (
        ReferenceArtifactRegistryError,
        load_reference_artifact_registry,
    )
    from spectra_sherpa.app.lib.reference_dataset_packages import (
        load_reference_dataset_package_registry,
        package_import_projection,
    )
    from spectra_sherpa.app.lib.reference_materialization import (
        ReferenceMaterializationError,
        materialize_reference_projection,
    )
    from spectra_sherpa.app.lib.registered_reference_storage import write_registered_reference_sidecar
    from spectra_sherpa.app.services.audit import audit_emitter

    experiment = await _require_experiment(session, experiment_id, current_user.id)
    if bool(projection_id) == bool(package_id):
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "registered_reference_authority_invalid",
                "message": "Select exactly one registered reference projection or package.",
            },
        )
    try:
        registry = load_reference_artifact_registry()
        if package_id is not None:
            package_registry = load_reference_dataset_package_registry(artifact_registry=registry)
            package = package_import_projection(package_id, registry=package_registry)
            projections = [registry.projection(view["projection_id"]).as_dict() for view in package["views"]]
            view_ids_by_projection = {str(view["projection_id"]): str(view["view_id"]) for view in package["views"]}
            artifact_ids = {projection["artifact_id"] for projection in projections}
            if artifact_ids != set(package["artifact_ids"]):
                raise ReferenceArtifactRegistryError("registered reference package artifact set is incomplete")
            dataset_key = package_id
            initial_view_ids = set(package["initial_view_ids"])
            assembly_mode = str(package["assembly_mode"])
            if assembly_mode == "single_view":
                # A target-free single-view package is catalog structure, not
                # a distinct managed execution authority. Grant the exact
                # projection already admitted by the hosted allowlist.
                dataset_key = str(projections[0]["projection_id"])
        else:
            assert projection_id is not None
            projections = [registry.projection(projection_id).as_dict()]
            artifact_ids = {str(projections[0]["artifact_id"])}
            dataset_key = projection_id
            # A one-view registered reference has one unambiguous scientific
            # default. Returning its file id makes My Dataset open and plot the
            # qualified projection immediately instead of inheriting an older
            # dataset's plot selection.
            initial_view_ids = {str(projection_id)}
            view_ids_by_projection = {}
            assembly_mode = "single_projection"
        artifacts = {artifact_id: registry.artifact(artifact_id).as_dict() for artifact_id in artifact_ids}
    except ReferenceArtifactRegistryError as exc:
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=404,
            detail={"code": "registered_reference_unknown", "message": str(exc)},
        ) from exc
    if len(files) != len(artifacts):
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail={
                "code": "registered_reference_file_count_invalid",
                "message": f"registered reference import requires exactly {len(artifacts)} provider file(s)",
            },
        )

    raw_dir = experiment_dir(experiment_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destinations: list[Path] = []
    import_dir: Path | None = None
    persisted_files: list[ExperimentFile] = []
    initial_file_ids: list[int] = []
    phase = "upload_verification"
    try:
        with tempfile.TemporaryDirectory(prefix="spectra-reference-upload-") as temporary:
            staged_by_artifact: dict[str, Path] = {}
            maximum_size = max(int(artifact["expected_size_bytes"]) for artifact in artifacts.values())
            for index, upload in enumerate(files):
                staged = Path(temporary) / f"selected-reference-{index}"
                observed_size, observed_sha256 = await _stage_registered_reference_upload(
                    upload,
                    staged,
                    maximum_size_bytes=maximum_size,
                )
                matches = [
                    artifact_id
                    for artifact_id, artifact in artifacts.items()
                    if int(artifact["expected_size_bytes"]) == observed_size
                    and hmac.compare_digest(str(artifact["sha256"]), observed_sha256)
                ]
                if len(matches) != 1 or matches[0] in staged_by_artifact:
                    raise RegisteredReferenceUploadMismatch(
                        "selected file does not match one unused registered package artifact"
                    )
                staged_by_artifact[matches[0]] = staged
            if set(staged_by_artifact) != set(artifacts):
                raise RegisteredReferenceUploadMismatch(
                    "selected files do not reproduce the complete registered package"
                )
            reserved_dir = raw_dir / uuid4().hex
            reserved_dir.mkdir()
            import_dir = reserved_dir
            phase = "projection_materialization"
            materialized_views = []
            for projection in projections:
                view_id = view_ids_by_projection.get(str(projection["projection_id"]), str(projection["projection_id"]))
                member_suffix = Path(str(projection["member_path"])).suffix.lower()
                destination = (
                    Path(temporary) / f"view-{len(materialized_views)}{member_suffix}"
                    if app_config.site_profile == "pro"
                    else import_dir / f"{view_id}{member_suffix}"
                )
                # Register cleanup custody before the materializer touches
                # the destination; a refusing native reader may have written
                # a partial member before it discovers the mismatch.
                destinations.append(destination)
                materialized = await asyncio.to_thread(
                    materialize_reference_projection,
                    staged_by_artifact[str(projection["artifact_id"])],
                    str(projection["projection_id"]),
                    registry=registry,
                    persist_member_to=destination,
                )
                materialized_views.append((projection, view_id, member_suffix, destination, materialized))
            materialized_views = await _retain_pro_reference_views(
                session, current_user.id, experiment.project_id, import_dir, materialized_views, destinations
            )
        phase = "sidecar_retention"
        for _, _, _, destination, materialized in materialized_views:
            write_registered_reference_sidecar(destination, materialized.portable_reference)
        phase = "grant_persistence"
        reused_existing = False
        async with session.begin_nested() as import_savepoint:
            for _, view_id, member_suffix, destination, _ in materialized_views:
                persisted = await add_experiment_file(
                    session=session,
                    experiment_id=experiment_id,
                    stage="raw",
                    file_path=destination.relative_to(experiment_dir(experiment_id)).as_posix(),
                    file_size_bytes=destination.stat().st_size,
                    file_type=member_suffix.lstrip(".") or None,
                    flush_only=True,
                )
                persisted_files.append(persisted)
                if view_id in initial_view_ids:
                    initial_file_ids.append(int(persisted.id))
            if assembly_mode == "heterogeneous_views":
                grants = [
                    await issue_trial_reference_grant(
                        session=session,
                        user_id=current_user.id,
                        project_id=experiment.project_id,
                        experiment_id=experiment_id,
                        dataset_key=str(projection["projection_id"]),
                        stage="raw",
                        file_id=int(persisted.id),
                        asset_id=str(projection["projection_id"]),
                    )
                    for persisted, projection in zip(persisted_files, projections, strict=True)
                ]
            else:
                grants = [
                    await issue_trial_reference_grant(
                        session=session,
                        user_id=current_user.id,
                        project_id=experiment.project_id,
                        experiment_id=experiment_id,
                        dataset_key=dataset_key,
                        stage="raw",
                        file_id=int(persisted_files[0].id) if len(persisted_files) == 1 else None,
                        asset_id=str(projections[0]["projection_id"]) if len(projections) == 1 else None,
                    )
                ]
            authoritative_experiment_ids = {int(getattr(grant, "experiment_id", experiment_id)) for grant in grants}
            if len(authoritative_experiment_ids) != 1:
                raise RuntimeError("registered package views resolve to different durable datasets")
            authoritative_experiment_id = authoritative_experiment_ids.pop()
            authoritative_file_ids = {
                int(grant.file_id)
                for grant in grants
                if grant is not None and getattr(grant, "file_id", None) is not None
            }
            reused_existing = authoritative_experiment_id != experiment_id or bool(
                authoritative_file_ids
                and authoritative_file_ids != {int(persisted.id) for persisted in persisted_files}
            )
            if reused_existing:
                # Remove both the duplicate ExperimentFile and its queued
                # creation audit event without expiring unrelated request
                # state in the outer transaction.
                await import_savepoint.rollback()
        if reused_existing:
            # The exact reference already exists under this trial user's
            # durable custody.  Discard the duplicate materialized member;
            # the response directs the UI to the original Experiment instead
            # of weakening the one-grant boundary or retaining two copies.
            _remove_uncommitted_reference_import(destinations, import_dir)
            existing_query = select(ExperimentFile).where(
                ExperimentFile.experiment_id == authoritative_experiment_id,
                ExperimentFile.stage == "raw",
            )
            if authoritative_file_ids:
                existing_query = existing_query.where(ExperimentFile.id.in_(authoritative_file_ids))
            existing_files = list((await session.scalars(existing_query.order_by(ExperimentFile.id))).all())
            if not existing_files:
                raise RuntimeError("reused registered-reference grant has no retained source files")
            reused_initial_ids = [
                int(existing.id) for existing in existing_files if Path(existing.file_path).stem in initial_view_ids
            ]
            return ReferenceDatasetImportResponse(
                imported=0,
                files=[_experiment_file_out(existing) for existing in existing_files],
                experiment_id=authoritative_experiment_id,
                reused_existing=True,
                initial_file_ids=reused_initial_ids,
            )
        for persisted, (projection, view_id, _, _, materialized) in zip(
            persisted_files, materialized_views, strict=True
        ):
            artifact = artifacts[str(projection["artifact_id"])]
            audit_emitter.emit(
                session=session,
                action="registered_reference.imported",
                target_type="ExperimentFile",
                target_id=persisted.id,
                after={
                    "artifact_id": artifact["artifact_id"],
                    "artifact_size_bytes": artifact["expected_size_bytes"],
                    "artifact_sha256": artifact["sha256"],
                    "dataset_key": dataset_key,
                    "member_sha256": materialized.portable_reference["member_sha256"],
                    "projection_id": projection["projection_id"],
                    "scientific_sha256": projection["scientific_sha256"],
                    "view_id": view_id,
                    "selected_upload_retained": False,
                },
            )
        await session.commit()
    except (ReferenceMaterializationError, RegisteredReferenceUploadMismatch) as exc:
        await session.rollback()
        _remove_uncommitted_reference_import(destinations, import_dir)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "registered_reference_mismatch",
                "message": (
                    "This file does not match the registered reference file. "
                    "Download it again using the supplied provider link. No data from the refused file was retained."
                ),
            },
        ) from exc
    except ValueError as exc:
        await session.rollback()
        _remove_uncommitted_reference_import(destinations, import_dir)
        logger.warning("Registered-reference import refused during %s (ValueError)", phase)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "registered_reference_retention_failed",
                "message": (
                    "The exact reference file was verified, but its project record could not be retained. "
                    "Retry or contact the operator; the selected file was not added."
                ),
            },
        ) from exc
    except BaseException:
        await session.rollback()
        _remove_uncommitted_reference_import(destinations, import_dir)
        raise

    # A post-commit refresh failure must never delete committed scientific bytes.
    for persisted in persisted_files:
        await session.refresh(persisted)
    return ReferenceDatasetImportResponse(
        imported=len(persisted_files),
        files=[_experiment_file_out(persisted) for persisted in persisted_files],
        experiment_id=experiment_id,
        initial_file_ids=initial_file_ids,
    )


def _is_demo_server_reference_dataset(source: str | None, name: str | None) -> bool:
    if source == "builtin":
        return name == _BUILTIN_LAVENDER_NAME
    if source == "synthetic":
        from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

        return name in SYNTHETIC_REFERENCE_CATALOG
    if source == "sklearn":
        from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG

        return name in SKLEARN_CATALOG
    return False


def _enforce_reference_import_policy(payload: ReferenceDatasetImportRequest) -> None:
    if app_config.site_profile == "pro":
        # Only server-local catalog sources; provider acquisition remains a
        # separate authority. Registered uploads have their own exact-byte route.
        if all(_is_demo_server_reference_dataset(ds.source, ds.name) for ds in payload.datasets):
            return
        raise HTTPException(
            403,
            detail={
                "code": "reference_provider_unavailable",
                "message": "Use a server-local catalog reference or upload the exact registered provider file.",
            },
        )
    if app_config.site_profile != "demo":
        return
    from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

    if "reference_data_import" not in get_demo_policy().disabled_capabilities:
        return
    if all(_is_demo_server_reference_dataset(ds.source, ds.name) for ds in payload.datasets):
        return
    raise HTTPException(status_code=403, detail=_REFERENCE_IMPORT_DISABLED_DETAIL)


def _enforce_reference_import_batch(payload: ReferenceDatasetImportRequest) -> None:
    lavender = [
        dataset
        for dataset in payload.datasets
        if dataset.source == "builtin" and dataset.name == _BUILTIN_LAVENDER_NAME
    ]
    if lavender and len(payload.datasets) != 1:
        raise HTTPException(
            status_code=400,
            detail="Lavender is a defined scientific collection and must be added to its own My Dataset.",
        )
    if app_config.site_profile in {"demo", "pro"} and len(payload.datasets) != 1:
        raise HTTPException(
            status_code=400,
            detail="Add one server-issued reference at a time so its scientific custody remains explicit.",
        )


async def _enforce_reference_import_target(
    session: AsyncSession,
    experiment_id: int,
    payload: ReferenceDatasetImportRequest,
) -> None:
    imports_lavender = any(
        dataset.source == "builtin" and dataset.name == _BUILTIN_LAVENDER_NAME for dataset in payload.datasets
    )
    if not imports_lavender:
        return
    existing_file_id = await session.scalar(
        select(ExperimentFile.id).where(ExperimentFile.experiment_id == experiment_id).limit(1)
    )
    if existing_file_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Lavender is a defined scientific collection and must be added to an empty My Dataset.",
        )
    if collection_definition_path(experiment_id).exists():
        raise HTTPException(
            status_code=409,
            detail="Lavender cannot replace an existing collection definition. Add it to a new My Dataset.",
        )


@router.post(
    "/{experiment_id}/import-reference",
    response_model=ReferenceDatasetImportResponse,
    status_code=201,
    dependencies=[Depends(demo_guard("registered_reference_import"))],
)
async def import_reference_datasets_endpoint(
    experiment_id: int,
    payload: ReferenceDatasetImportRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReferenceDatasetImportResponse:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    _enforce_reference_import_batch(payload)
    await _enforce_reference_import_target(session, experiment_id, payload)
    _enforce_reference_import_policy(payload)

    all_files: list[ExperimentFile] = []
    exp_dir = experiment_dir(experiment_id)
    definition_preexisted = collection_definition_path(experiment_id).exists()
    existing_paths = set(
        (
            await session.scalars(select(ExperimentFile.file_path).where(ExperimentFile.experiment_id == experiment_id))
        ).all()
    )

    prepared_sidecars_before: dict[Path, bytes | None] = {}

    def _cleanup_orphan_files() -> None:
        """Restore scientific interpretation and remove uncommitted new files."""
        for sidecar, previous in prepared_sidecars_before.items():
            if previous is None:
                sidecar.unlink(missing_ok=True)
            else:
                sidecar.write_bytes(previous)
        for f in all_files:
            path = exp_dir / f.file_path
            if f.file_path not in existing_paths and path.exists():
                path.unlink()
        if not definition_preexisted:
            remove_collection_definition(experiment_id)

    try:
        reused_existing = False
        authoritative_experiment_id = experiment_id
        authoritative_file_ids: list[int] = []
        async with session.begin_nested() as import_savepoint:
            for ds in payload.datasets:
                files = await import_reference_dataset(session, experiment_id, ds.source, ds.name)
                prepared_payload = dict(ds.overrides or {})
                if ds.source == "sklearn":
                    # The server owns the catalog file and its structural
                    # interpretation.  Persist that canonical feature-table
                    # contract in every profile instead of depending on
                    # browser-local preview state to identify the response
                    # column.  The local OSS path uses the same materialized
                    # CSV as hosted profiles; omitting this sidecar locally
                    # drops the embedded class labels before My Dataset
                    # analysis-readiness inspection.
                    prepared_payload.update(
                        {
                            "data_role": "X_features",
                            "target_column": "target",
                            "target_type": "categorical",
                        }
                    )
                prepared = PreparedDataOverrides.from_mapping(prepared_payload)
                if not prepared.is_empty():
                    for file_record in files:
                        from spectra_sherpa.app.services.prepared_data import sidecar_path

                        path = str(exp_dir / file_record.file_path)
                        sidecar = sidecar_path(file_path=path, source=None, name=None)
                        if sidecar not in prepared_sidecars_before:
                            prepared_sidecars_before[sidecar] = sidecar.read_bytes() if sidecar.exists() else None
                        save_prepared_data_overrides(prepared, file_path=path)
                all_files.extend(files)
            if app_config.site_profile == "demo":
                from spectra_sherpa.app.contracts.demo_policy import issue_trial_reference_grant

                dataset = payload.datasets[0]
                is_lavender = dataset.source == "builtin" and dataset.name == _BUILTIN_LAVENDER_NAME
                grant = await issue_trial_reference_grant(
                    session=session,
                    user_id=current_user.id,
                    project_id=experiment.project_id,
                    experiment_id=experiment_id,
                    dataset_key=_BUILTIN_LAVENDER_TRIAL_DATASET_KEY if is_lavender else None,
                    reference_source=None if is_lavender else dataset.source,
                    reference_name=None if is_lavender else dataset.name,
                    stage="raw" if is_lavender else all_files[0].stage,
                    file_id=None if is_lavender else int(all_files[0].id),
                    asset_id="spectrum" if is_lavender else None,
                )
                authoritative_experiment_id = int(getattr(grant, "experiment_id", experiment_id))
                grant_file_id = getattr(grant, "file_id", None)
                authoritative_file_ids = [int(grant_file_id)] if grant_file_id is not None else []
                reused_existing = authoritative_experiment_id != experiment_id or bool(
                    authoritative_file_ids
                    and authoritative_file_ids != [int(file_record.id) for file_record in all_files]
                )
                if reused_existing:
                    await import_savepoint.rollback()
            if app_config.site_profile == "pro":
                from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker

                checker = get_hot_storage_checker()
                if checker is None:
                    raise HTTPException(503, "Storage accounting is unavailable")
                # New rows have been flushed; account them exactly once under the
                # grant lock before committing the imported scientific bytes.
                await checker(
                    session=session, user_id=current_user.id, project_id=experiment.project_id, incoming_bytes=0
                )
        if reused_existing:
            _cleanup_orphan_files()
            existing_query = select(ExperimentFile).where(ExperimentFile.experiment_id == authoritative_experiment_id)
            if authoritative_file_ids:
                existing_query = existing_query.where(ExperimentFile.id.in_(authoritative_file_ids))
            existing_files = list((await session.scalars(existing_query.order_by(ExperimentFile.id))).all())
            if not existing_files:
                raise RuntimeError("reused reference grant has no retained source files")
            return ReferenceDatasetImportResponse(
                imported=0,
                files=[_experiment_file_out(existing) for existing in existing_files],
                experiment_id=authoritative_experiment_id,
                reused_existing=True,
                initial_file_ids=authoritative_file_ids,
            )
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
        experiment_id=experiment_id,
        initial_file_ids=[int(file_record.id) for file_record in all_files] if len(all_files) == 1 else [],
    )


@router.get("/{experiment_id}/files", response_model=list[ExperimentFileOut])
async def list_experiment_files_endpoint(
    experiment_id: int,
    stage: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentFileOut]:
    if stage and stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    experiment = await _require_experiment(session, experiment_id, current_user.id, "read")
    if app_config.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        selected_stage = stage or await preferred_experiment_stage(session, experiment_id) or "raw"
        await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=experiment.project_id,
            experiment_id=experiment_id,
            stage=selected_stage,
            file_id=None,
            asset_id=None,
        )
        stage = selected_stage
    files = await list_experiment_files(session, experiment_id, stage=stage)
    if app_config.site_profile == "demo":
        return [ExperimentFileOut.model_validate(file) for file in files]
    return [_experiment_file_out(file) for file in files]


@router.get(
    "/{experiment_id}/files/{file_id}/scientific-assets",
    response_model=ExperimentFileAssetsOut,
    dependencies=[Depends(demo_guard("raw_data_export"))],
)
async def inspect_experiment_file_assets_endpoint(
    experiment_id: int,
    file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentFileAssetsOut:
    """Inspect every typed asset without silently selecting one of them."""

    await _require_experiment(session, experiment_id, current_user.id, "read")
    experiment_file = await get_experiment_file(session, experiment_id, file_id)
    if experiment_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
    from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar
    from spectra_sherpa.io import ingest

    source_path = experiment_dir(experiment_id) / experiment_file.file_path
    registered_reference = read_registered_reference_sidecar(source_path)
    if registered_reference is not None:
        # The sidecar is the reviewed scientific projection authority. Do not
        # expose unrelated MATLAB variables from the provider container as if
        # they were admissible alternatives. Generic uploads have no sidecar
        # and continue through the full native multi-asset inventory below.
        try:
            materialized = await asyncio.to_thread(
                materialize_reference_member,
                source_path,
                str(registered_reference["projection_id"]),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Registered scientific projection could not be reproduced: {exc}",
            ) from exc
        dataset = materialized.dataset
        role = str(dataset.data_role)
        feature_role = "spectral_variable" if role == "X_spectra" else "feature"
        return ExperimentFileAssetsOut(
            format_id=str(dataset.source_identity.source_format),
            variant=str(dataset.source_identity.storage_version or "registered-reference"),
            parser_id=str(registered_reference["native_reader_contract"]),
            parser_version="1",
            source_sha256=str(registered_reference["member_sha256"]),
            assets=[
                ScientificAssetOut(
                    asset_id=str(registered_reference["projection_id"]),
                    title=dataset.title,
                    shape=list(dataset.shape),
                    dimension_roles=["sample", feature_role],
                    data_role=role,
                    x_title=_optional_text(dataset.feature_axis.title),
                    x_units=_optional_text(dataset.feature_axis.units),
                    data_quantity=_optional_text(dataset.domain.data_quantity),
                    value_units=_optional_text(dataset.units),
                    warnings=[],
                )
            ],
        )

    try:
        result = await asyncio.to_thread(ingest, source_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not inspect scientific assets: {exc}") from exc

    member = result.source_members[0]
    return ExperimentFileAssetsOut(
        format_id=result.format_id,
        variant=result.variant,
        parser_id=result.parser_id,
        parser_version=result.parser_version,
        source_sha256=member.sha256,
        assets=[
            ScientificAssetOut(
                asset_id=asset.asset_id,
                title=asset.dataset.title,
                shape=list(asset.dataset.shape),
                dimension_roles=list(asset.dimension_roles),
                data_role=asset.dataset.data_role,
                x_title=_optional_text(asset.dataset.feature_axis.title),
                x_units=_optional_text(asset.dataset.feature_axis.units),
                data_quantity=_optional_text(asset.dataset.domain.data_quantity),
                value_units=_optional_text(asset.dataset.units),
                warnings=scientific_asset_warnings(result.warnings, asset.warnings),
            )
            for asset in result.assets
        ],
    )


@router.delete(
    "/{experiment_id}/files/{file_id}",
    dependencies=[Depends(demo_guard("data_upload"))],
)
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
    try:
        if file_path.exists():
            file_path.unlink()
        from spectra_sherpa.app.lib.registered_reference_storage import (
            remove_registered_reference_sidecar,
        )

        remove_registered_reference_sidecar(file_path)
    except OSError as exc:
        logger.warning(
            "Audited delete of ExperimentFile id=%s succeeded but "
            "filesystem cleanup of %s failed: %s. File is now an "
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
